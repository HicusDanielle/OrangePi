#!/bin/bash
###############################################################################
# update_remote.sh — Pull latest code from GitHub on the device and restart
# services over SSH. Uses the same host/user/key conventions as deploy.sh.
#
# Usage:
#   bash scripts/update_remote.sh                 # default host 192.168.1.93 root
#   bash scripts/update_remote.sh 192.168.1.50 root
#
# Env overrides (optional):
#   ORANGEPI_HOST, ORANGEPI_USER, ORANGEPI_SSH_KEY
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load optional .env from project root
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a; source "$PROJECT_DIR/.env"; set +a
fi

HOST="${1:-${ORANGEPI_HOST:-192.168.1.93}}"
USER="${2:-${ORANGEPI_USER:-root}}"
KEY="${ORANGEPI_SSH_KEY:-$HOME/.ssh/orangepi_key}"
DEST="/opt/orangepi"
REPO_URL="https://github.com/HicusDanielle/OrangePi"

SSH_OPTS="-i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes"
SSH="ssh $SSH_OPTS"

echo "[update] Target: $USER@$HOST  dest: $DEST"

if [ ! -f "$KEY" ]; then
  echo "[update] ERROR: SSH key not found: $KEY" >&2
  exit 1
fi

if ! $SSH "$USER@$HOST" "echo connected" >/dev/null 2>&1; then
  echo "[update] ERROR: cannot reach $USER@$HOST" >&2
  exit 1
fi

echo "[update] Ensuring repo present at $DEST ..."
$SSH "$USER@$HOST" "
  set -e
  if [ ! -d '$DEST/.git' ]; then
    rm -rf '$DEST'
    git clone '$REPO_URL' '$DEST'
  else
    cd '$DEST'
    git remote set-url origin '$REPO_URL'
    git reset --hard
    git clean -fd
    git pull --ff-only
  fi
  cd '$DEST'
  if [ -f requirements.txt ]; then
    pip3 install --upgrade pip >/dev/null 2>&1 || true
    pip3 install -r requirements.txt >/dev/null 2>&1 || true
  fi
  systemctl daemon-reload
  systemctl restart weather-station.service x-display.service led-monitor.service || true
"

echo "[update] Done. Services restarted on $HOST."
