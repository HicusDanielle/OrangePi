#!/bin/bash
###############################################################################
# start_all.sh — Launch all Orange Pi Flask applications
# Deployed to: /opt/orangepi/scripts/start_all.sh
# Called by:   weather-station.service
###############################################################################
set -uo pipefail

APP_DIR="/opt/orangepi/apps"
LOG_DIR="/var/log/orangepi"
VENV="/opt/orangepi/venv/bin/python3"
PYTHON="${VENV:-python3}"

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
    local name=$1 port=$2 file=$3 log=$4
    wait_port_free "$port"
    echo "[start_all] Starting ${name} (port ${port})..."
    "$PYTHON" "$file" >> "$LOG_DIR/${log}" 2>&1 &
    echo $! > "/run/orangepi/${name}.pid"
}

start_app "portal"  5002 home_portal.py    portal.log
start_app "weather" 5000 web_app.py        weather.log
start_app "config"  5001 device_config.py  config.log
start_app "radio"   5003 internet_radio.py radio.log
start_app "dash"    5004 dashboard.py      dashboard.log

echo "[start_all] All apps launched. PIDs in /run/orangepi_*.pid"

# Keep service alive; systemd monitors this process
wait
