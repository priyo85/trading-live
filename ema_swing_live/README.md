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

## ICICI Trading Workflow

The dashboard places regular ICICI Breeze limit orders directly from generated 9 EMA actions. Run signals, review the generated actions, choose `Cash` or `MTF`, adjust quantity/limit price if needed, then use `Preview` before `Place`.

The ICICI panel shows live session status. If it is not connected, generate a fresh Breeze session token with `Open Login`, paste it, then `Save & Test`.

Successful broker responses are recorded in the local broker order log, and the action can be booked into the strategy ledger automatically. Preview rows can be removed, and broker orders with an order ID can be cancelled from the dashboard. The broker order book can be refreshed from the dashboard.

For MTF buy actions, the UI defaults quantity from the configured MTF funded multiple, matching the live strategy MTF assumptions, while still allowing manual override before placing the order.

Strategy holdings and the booked order ledger are editable from the dashboard. Save manual edits before the next signal run so the strategy sees the updated state.

ICICI Breeze rejected real NSE cash/ETF GTT placement with `Exchange-code should be 'nfo'.` The app keeps GTT helpers on the backend for reference but the live ETF workflow uses regular `OrderPlacement` limit orders. MTF acceptance depends on account eligibility, stock eligibility, and available margin.

## Data Provider

The dashboard provider selector controls `ETF_DATA_PROVIDER` for live runs:

- `auto`: existing Dhan then Yahoo behavior
- `dhan`: Dhan live quotes with Yahoo fallback
- `icici`: ICICI Breeze historical/quote data with Yahoo fallback
- `yahoo`: Yahoo only

Order placement is manual by design: the app never sends broker orders from the signal run automatically.

## Local Storage

Each running instance keeps its own local state. Your laptop and EC2 do not share a live database connection.

By default the app creates a SQLite database at:

```text
ema_swing_live/instance/ema_swing_live.sqlite
```

Override it with:

```bash
EMA_SWING_LIVE_DB_PATH=/opt/ema-swing-live/instance/ema_swing_live.sqlite
```

The app still writes the existing JSON files for compatibility, but mirrors non-secret app documents into SQLite:

- live strategy state
- latest live report
- app settings
- live config
- broker order log
- broker portfolio/trade/order snapshots

Broker credentials are intentionally not mirrored into SQLite. Keep ICICI/Dhan credentials in `.env` or the instance credential JSON files on EC2/local only.

This means:

- local app can run strategy signals, holdings, ledger, config, and reports without EC2
- EC2 app can run broker fetches and ICICI order placement through its static IP
- broker snapshots are stored locally on whichever instance fetched them
- sync/gateway are explicit instead of relying on a shared internet-facing database

## Lightweight EC2 Broker Gateway

For the lowest EC2 footprint, run the full dashboard locally and keep EC2 as a small broker gateway only. ICICI Breeze calls can be proxied through EC2 because ICICI needs the static IP. Dhan profile, funds, holdings, trades, and signals can run locally; Dhan order placement can be routed through the gateway later by enabling the Dhan order flag once implemented.

On EC2 `.env`, set a long token and keep the broker credentials there:

```bash
EMA_SWING_BROKER_GATEWAY_TOKEN=<long-random-token>
EMA_SWING_SYNC_TOKEN=<same-token-if-you-also-use-sync>
ICICI_BREEZE_API_KEY=...
ICICI_BREEZE_API_SECRET=...
ICICI_BREEZE_SESSION_TOKEN=...
```

Do not set `EMA_SWING_BROKER_GATEWAY_URL` on EC2. Restart the EC2 service after editing `.env`:

```bash
sudo systemctl restart ema-swing-live
```

On your local PowerShell before starting the app:

```powershell
$env:EMA_SWING_BROKER_GATEWAY_URL="http://13.205.114.241"
$env:EMA_SWING_BROKER_GATEWAY_TOKEN="<same-long-random-token>"
python -m ema_swing_live.app
```

With this mode:

- local strategy screens, signal generation, holdings, ledger, logs, config, and Dhan info continue to work even if EC2 is down
- ICICI login/session, quote test, portfolio, trades, order book, order placement, cancel, and GTT helper calls go through EC2 when the gateway URL/token are configured
- if EC2 is down, only those ICICI broker calls fail; local strategy state remains usable

For internet use, put HTTPS in front of EC2 before sending broker credentials over the gateway. A temporary SSH tunnel is also safer than plain HTTP.

## Live Run Performance

`Run Signals` displays timing chips after each run so slow phases are visible. History should normally come from SQLite cache after the first warm-up run. CMP quote speed can be tuned with:

```powershell
$env:ETF_CMP_CACHE_TTL_SECONDS="60"
$env:ETF_QUOTE_FETCH_WORKERS="8"
$env:ETF_HISTORY_FETCH_WORKERS="8"
```

Dhan CMP uses the bulk LTP endpoint first. The slower holdings snapshot fallback is off by default; enable it only if you need holdings prices when marketfeed fails:

```powershell
$env:DHAN_LTP_HOLDINGS_FALLBACK="1"
```

## Local to EC2 Sync

Local and EC2 intentionally keep separate databases. To copy EC2 strategy state into your local app, configure a shared sync token.

On EC2 `.env`:

```bash
EMA_SWING_SYNC_TOKEN=<long-random-token>
```

On local PowerShell before starting the app:

```powershell
$env:EMA_SWING_REMOTE_URL="http://13.205.114.241"
$env:EMA_SWING_SYNC_TOKEN="<same-long-random-token>"
```

Then open the `Sync` tab locally and click `Pull EC2 Data`.

Sync copies only non-secret data:

- strategy config
- strategy holdings/trades/cash state
- latest signal report
- broker order log
- app settings

It does not copy ICICI/Dhan API credentials or session tokens.
