#!/bin/bash
###############################################################################
# start_all.sh — Launch all Orange Pi Flask applications
# Deployed to: /opt/orangepi/scripts/start_all.sh
# Called by:   weather-station.service
###############################################################################
set -euo pipefail

APP_DIR="/opt/orangepi/apps"
LOG_DIR="/var/log/orangepi"

mkdir -p "$LOG_DIR"

cd "$APP_DIR"

# Kill any stale instances
pkill -f "python3 home_portal.py"   2>/dev/null || true
pkill -f "python3 web_app.py"       2>/dev/null || true
pkill -f "python3 device_config.py" 2>/dev/null || true
pkill -f "python3 internet_radio.py" 2>/dev/null || true
pkill -f "python3 dashboard.py"     2>/dev/null || true
sleep 1

echo "[start_all] Starting Home Portal     (port 5002)..."
python3 home_portal.py    > "$LOG_DIR/portal.log"   2>&1 &

echo "[start_all] Starting Weather Station (port 5000)..."
python3 web_app.py        > "$LOG_DIR/weather.log"  2>&1 &

echo "[start_all] Starting Device Config   (port 5001)..."
python3 device_config.py  > "$LOG_DIR/config.log"   2>&1 &

echo "[start_all] Starting Internet Radio  (port 5003)..."
python3 internet_radio.py > "$LOG_DIR/radio.log"    2>&1 &

echo "[start_all] Starting Dashboard       (port 5004)..."
python3 dashboard.py      > "$LOG_DIR/dashboard.log" 2>&1 &

echo "[start_all] All apps started. Logs in $LOG_DIR/"
wait
