#!/bin/bash
###############################################################################
# start_display.sh — Start Flask apps, Xorg, and Chromium kiosk
# Deployed to: /opt/orangepi/scripts/start_display.sh
# Called by:   x-display.service
###############################################################################
set -euo pipefail

APP_DIR="/opt/orangepi/apps"
SCRIPT_DIR="/opt/orangepi/scripts"
LOG_DIR="/var/log/orangepi"

mkdir -p "$LOG_DIR"

# ── 1. Start Flask apps ───────────────────────────────────────────────────────
echo "[display] Starting Flask apps..."
bash "$SCRIPT_DIR/start_all.sh" &

echo "[display] Waiting for Flask apps to bind..."
sleep 4

# ── 2. Environment ────────────────────────────────────────────────────────────
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/0
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

# ── 3. Start Xorg ─────────────────────────────────────────────────────────────
echo "[display] Starting Xorg (DRM/KMS modesetting)..."
/usr/lib/xorg/Xorg :0 vt1 -logfile "$LOG_DIR/xorg.log" -nolisten tcp &
XORG_PID=$!

echo "[display] Waiting for X to be ready..."
for i in $(seq 1 30); do
    [ -e /tmp/.X0-lock ] && break
    sleep 1
done

if [ ! -e /tmp/.X0-lock ]; then
    echo "[display] ERROR: Xorg did not start within 30s"
    exit 1
fi

# ── 4. Set resolution via xrandr ──────────────────────────────────────────────
sleep 1
echo "[display] Setting display mode 1024x600..."
DISPLAY=:0 xrandr --output HDMI-1 --mode 1024x600 --rate 59.80 2>/dev/null \
    || DISPLAY=:0 xrandr --output HDMI-1 --preferred 2>/dev/null \
    || DISPLAY=:0 xrandr --output HDMI-1 --auto 2>/dev/null \
    || true

# Hide mouse cursor (requires unclutter)
DISPLAY=:0 unclutter -idle 0 -root &>/dev/null &

# ── 5. Launch Chromium kiosk ──────────────────────────────────────────────────
echo "[display] Launching Chromium kiosk → http://localhost:5004"
DISPLAY=:0 chromium \
    --kiosk \
    --no-sandbox \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --disable-translate \
    --disable-features=TranslateUI \
    --noerrdialogs \
    --window-size=1024,600 \
    --window-position=0,0 \
    --start-fullscreen \
    --touch-events=enabled \
    --enable-touch-drag-drop \
    --overscroll-history-navigation=0 \
    --disable-pinch \
    --disable-gpu \
    --disable-software-rasterizer \
    --disable-dev-shm-usage \
    --no-first-run \
    --disable-background-networking \
    --disable-sync \
    --metrics-recording-only \
    --safebrowsing-disable-auto-update \
    --app=http://localhost:5004 \
    > "$LOG_DIR/chromium.log" 2>&1 &

wait $XORG_PID
