# 9 EMA Swing Live

Live-only web dashboard for the existing ETF 9 EMA swing daily strategy.

What it does:

- Runs the existing `backtesting.etf_backtester.live.signal_runner` workflow.
- Shows live actions, holdings, cash/equity, and all ETF signals in a mobile-friendly UI.
- Provides app login for remote EC2/mobile access.
- Stores ICICI Breeze credentials locally and tests login/data access with a quote request.
- Supports manually approved ICICI Breeze single-leg GTT order placement with dry-run preview.

## Local Run

From the repo root:

```powershell
pip install -r ema_swing_live\requirements.txt
$env:EMA_SWING_APP_USERNAME="admin"
$env:EMA_SWING_APP_PASSWORD="change-me"
$env:EMA_SWING_SECRET_KEY="change-me-too"
python -m ema_swing_live.app
```

Open `http://127.0.0.1:8080`.

## EC2 Deployment

On an Ubuntu EC2 instance:

```bash
sudo mkdir -p /opt/ema-swing-live
sudo chown "$USER":"$USER" /opt/ema-swing-live
cd /opt/ema-swing-live
python3 -m venv .venv
. .venv/bin/activate
pip install -r ema_swing_live/requirements.txt
cp ema_swing_live/.env.example .env
```

Edit `.env` and set strong values for:

- `EMA_SWING_APP_PASSWORD`
- `EMA_SWING_SECRET_KEY`
- `EMA_SWING_LIVE_INSTANCE_DIR`

Install the service and nginx reverse proxy:

```bash
sudo cp ema_swing_live/deploy/ema-swing-live.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ema-swing-live

sudo cp ema_swing_live/deploy/nginx.conf /etc/nginx/sites-available/ema-swing-live
sudo ln -s /etc/nginx/sites-available/ema-swing-live /etc/nginx/sites-enabled/ema-swing-live
sudo nginx -t
sudo systemctl reload nginx
```

Open port 80 in the EC2 security group. For real internet use, add a domain and HTTPS with Certbot before saving broker credentials.

### Continuous Deployment

This repo includes a GitHub Actions workflow at `.github/workflows/deploy-ema-swing-live.yml`. On pushes to `main` that touch `ema_swing_live`, `backtesting/etf_backtester`, or the workflow itself, GitHub SSHes into EC2 and runs:

```bash
bash ./ema_swing_live/deploy/deploy_ec2.sh main
```

The EC2 deploy script fetches the branch, runs `git pull --ff-only`, installs `ema_swing_live/requirements.txt`, compiles the app/backtester modules, imports the Flask app, and restarts `ema-swing-live`.

Add these GitHub repository secrets:

- `EC2_HOST`: public DNS or IP of the EC2 instance
- `EC2_USER`: SSH user, for example `ubuntu`
- `EC2_SSH_PRIVATE_KEY`: private key matching a public key in `~/.ssh/authorized_keys` on EC2

Optional secrets:

- `EC2_PORT`: defaults to `22`
- `EC2_APP_DIR`: defaults to `/opt/ema-swing-live`
- `EC2_SERVICE_NAME`: defaults to `ema-swing-live`

One-time EC2 setup:

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv nginx

sudo mkdir -p /opt/ema-swing-live
sudo chown "$USER":"$USER" /opt/ema-swing-live
git clone <your-github-repo-url> /opt/ema-swing-live
cd /opt/ema-swing-live

cp ema_swing_live/.env.example .env
nano .env

sudo cp ema_swing_live/deploy/ema-swing-live.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ema-swing-live
```

Allow the deploy user to restart only this service without an interactive sudo password:

```bash
SYSTEMCTL_PATH="$(command -v systemctl)"
echo "$USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH restart ema-swing-live, $SYSTEMCTL_PATH is-active ema-swing-live, $SYSTEMCTL_PATH status ema-swing-live" | sudo tee /etc/sudoers.d/ema-swing-live-deploy
sudo chmod 440 /etc/sudoers.d/ema-swing-live-deploy
sudo visudo -cf /etc/sudoers.d/ema-swing-live-deploy
```

Keep `.env`, Breeze tokens, and app instance files on EC2 only. Do not add broker/API secrets to GitHub Actions secrets unless they are needed by the workflow itself; this deploy flow does not need them.

## ICICI Breeze Login Test

In the dashboard:

1. Enter your Breeze API key.
2. Click `Open Login`.
3. Complete ICICI Direct login and copy the `API_Session`/session key shown after login.
4. Enter API key, secret key, session token, and an ICICI Breeze ETF short code from the Security Master, for example `GOLDEX` for `NSE:GOLDBEES`.
5. Click `Save & Test`.

ICICI says the Breeze session key is generated from `https://api.icicidirect.com/apiuser/login?api_key=...` and is valid for the trading session, usually expiring within 24 hours or by midnight. The app uses the official `breeze-connect` SDK pattern: initialize `BreezeConnect(api_key=...)`, call `generate_session(api_secret=..., session_token=...)`, then request quotes.

References:

- ICICI Direct session key guide: https://www.icicidirect.com/ilearn/stocks/articles/how-to-generate-session-key-and-install-sdk-for-breeze-api
- ICICI Direct Breeze API page: https://www.icicidirect.com/futures-and-options/api/breeze
- Breeze API reference: https://api.icicidirect.com/breezeapi/documents/index.html

## ICICI GTT Order Test

The dashboard has an `ICICI GTT Order` panel for single-leg GTT payload checks. Keep `Dry run` checked for NSE ETF/cash symbols; this builds and displays the Breeze payload without sending it.

For strategy actions, run signals, select one action, then click `Use Selected Action` to copy symbol, side, quantity, and signal price into the GTT form. `NSE:GOLDBEES` is resolved through the ICICI alias file to `GOLDEX`; direct Breeze stock codes like `GOLDEX` also work.

On May 10, 2026, ICICI Breeze rejected a real `NSE` cash GTT request with `Exchange-code should be 'nfo'.` The app therefore blocks real NSE ETF/cash GTT placement through this API path and leaves dry-run enabled for payload validation. Place cash/ETF GTT orders manually in ICICI Direct unless ICICI enables this Breeze API segment for your account.

## ICICI Limit Order Test

Use the `ICICI Limit Order` panel for regular Breeze `OrderPlacement` orders. The Breeze docs list `POST /breezeapi/api/v1/order` for `NSE` cash with `order_type=limit`; the installed Breeze SDK also accepts `mtf` as a product type. Market orders are not permitted. Keep `Dry run` checked first to inspect the payload, then uncheck it only when you intentionally want to place the order.

On holidays or outside market hours, ICICI may reject a regular day order depending on exchange/session rules. Use a very small quantity and a safe limit price when testing real placement. MTF acceptance also depends on account eligibility, stock eligibility, and available margin.

## Data Provider

The dashboard provider selector controls `ETF_DATA_PROVIDER` for live runs:

- `auto`: existing Dhan then Yahoo behavior
- `dhan`: Dhan live quotes with Yahoo fallback
- `icici`: ICICI Breeze historical/quote data with Yahoo fallback
- `yahoo`: Yahoo only

Order placement is manual by design: the app never sends broker orders from the signal run automatically.
