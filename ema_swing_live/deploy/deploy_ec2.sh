#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ema-swing-live}"
SERVICE_NAME="${SERVICE_NAME:-ema-swing-live}"
DEPLOY_BRANCH="${1:-${DEPLOY_BRANCH:-main}}"

cd "$APP_DIR"

echo "Deploying branch: $DEPLOY_BRANCH"
git fetch --prune origin "$DEPLOY_BRANCH"

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$DEPLOY_BRANCH" ]; then
  if git show-ref --verify --quiet "refs/heads/$DEPLOY_BRANCH"; then
    git checkout "$DEPLOY_BRANCH"
  else
    git checkout -b "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
  fi
fi

git pull --ff-only origin "$DEPLOY_BRANCH"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ema_swing_live/requirements.txt
python -m compileall -q ema_swing_live backtesting/etf_backtester
python -c "from ema_swing_live.app import create_app; app = create_app(); print('Flask app import OK:', len(app.url_map._rules), 'routes')"

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active --quiet "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager -l
