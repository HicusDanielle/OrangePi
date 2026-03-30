#!/bin/bash
###############################################################################
# start_all.sh — Launch all Orange Pi Flask applications
# Deployed to: /opt/orangepi/scripts/start_all.sh
# Called by:   weather-station.service
###############################################################################
set -uo pipefail

APP_DIR="/opt/orangepi/apps"
LOG_DIR="/var/log/orangepi"
PY_BIN="/opt/orangepi/venv/bin/python3"
PYTHON="${PY_BIN:-python3}"
GUNICORN_BIN="/opt/orangepi/venv/bin/gunicorn"
[ -x "$GUNICORN_BIN" ] || GUNICORN_BIN="gunicorn"

mkdir -p "$LOG_DIR"
cd "$APP_DIR"

# ── Kill any stale instances ──────────────────────────────────────────────────
for app in home_portal web_app device_config internet_radio dashboard; do
    pkill -f "python3 ${app}.py" 2>/dev/null || true
done
sleep 1

# ── Wait for a port to be free ────────────────────────────────────────────────
wait_port_free() {
    local port=$1
    for i in $(seq 1 10); do
        if ! ss -tlnp | grep -q ":${port} "; then return 0; fi
        sleep 0.5
    done
    echo "[start_all] WARN: port ${port} still busy after 5s"
}

# ── Start apps ────────────────────────────────────────────────────────────────
start_app() {
    local name=$1 port=$2 module=$3 log=$4
    wait_port_free "$port"
    echo "[start_all] Starting ${name} (port ${port}) via gunicorn..."
    "$GUNICORN_BIN" -w 2 -b 127.0.0.1:"${port}" \
        --access-logfile "$LOG_DIR/${log%.log}.access.log" \
        --error-logfile "$LOG_DIR/${log}" \
        --capture-output --timeout 30 \
        "${module}:app" &
    echo $! > "/run/orangepi/${name}.pid"
}

start_app "portal"  5002 home_portal    portal.log
start_app "weather" 5000 web_app        weather.log
start_app "config"  5001 device_config  config.log
start_app "radio"   5003 internet_radio radio.log
start_app "dash"    5004 dashboard      dashboard.log

echo "[start_all] All apps launched. PIDs in /run/orangepi_*.pid"

# Keep service alive; systemd monitors this process
wait
