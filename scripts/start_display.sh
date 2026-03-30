#!/bin/bash
###############################################################################
# start_display.sh — Start Xorg and Chromium kiosk
# Deployed to: /opt/orangepi/scripts/start_display.sh
# Called by:   x-display.service
###############################################################################
set -uo pipefail

APP_DIR="/opt/orangepi/apps"
SCRIPT_DIR="/opt/orangepi/scripts"
LOG_DIR="/var/log/orangepi"

mkdir -p "$LOG_DIR"

# ── Environment ───────────────────────────────────────────────────────────────
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/0
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export XCURSOR_SIZE=24

# ── 1. Wait for Flask dashboard to be ready ───────────────────────────────────
echo "[display] Waiting for dashboard (port 5004)..."
for i in $(seq 1 30); do
    if ss -tlnp | grep -q ':5004 '; then
        echo "[display] Dashboard is up (${i}s)."
        break
    fi
    sleep 1
done

# ── 2. Kill stale X session ───────────────────────────────────────────────────
pkill -f "Xorg :0" 2>/dev/null || true
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0 2>/dev/null || true
sleep 1

# ── 3. Start Xorg ─────────────────────────────────────────────────────────────
echo "[display] Starting Xorg (DRM/KMS modesetting)..."
/usr/lib/xorg/Xorg :0 vt1 \
    -logfile "$LOG_DIR/xorg.log" \
    -nolisten tcp \
    -nolisten local \
    &
XORG_PID=$!

echo "[display] Waiting for X server (up to 45s)..."
for i in $(seq 1 45); do
    if [ -e /tmp/.X0-lock ] && DISPLAY=:0 xdpyinfo &>/dev/null; then
        echo "[display] X ready (${i}s)."
        break
    fi
    sleep 1
done

if ! [ -e /tmp/.X0-lock ]; then
    echo "[display] ERROR: Xorg failed to start within 45s. Check $LOG_DIR/xorg.log"
    exit 1
fi

# ── 4. Detect connected output and set resolution ─────────────────────────────
sleep 1
echo "[display] Probing connected display outputs..."
CONNECTED_OUTPUT=$(DISPLAY=:0 xrandr --query 2>/dev/null \
    | awk '/ connected/ {print $1; exit}')
CONNECTED_OUTPUT="${CONNECTED_OUTPUT:-HDMI-1}"
echo "[display] Using output: $CONNECTED_OUTPUT"

# Try exact mode, fall back to preferred, then auto
DISPLAY=:0 xrandr --output "$CONNECTED_OUTPUT" --mode 1024x600 --rate 59.80 2>/dev/null \
    || DISPLAY=:0 xrandr --output "$CONNECTED_OUTPUT" --preferred 2>/dev/null \
    || DISPLAY=:0 xrandr --output "$CONNECTED_OUTPUT" --auto 2>/dev/null \
    || true

# ── 5. Set desktop background (black) ─────────────────────────────────────────
DISPLAY=:0 xsetroot -solid black 2>/dev/null || true

# ── 6. Disable screen blanking / DPMS at X level ─────────────────────────────
DISPLAY=:0 xset s off 2>/dev/null || true
DISPLAY=:0 xset -dpms 2>/dev/null || true
DISPLAY=:0 xset s noblank 2>/dev/null || true

# ── 7. Hide mouse cursor ──────────────────────────────────────────────────────
DISPLAY=:0 unclutter -idle 0 -root 2>/dev/null &

# ── 8. Launch Chromium kiosk (auto-restart on crash) ─────────────────────────
launch_chromium() {
    DISPLAY=:0 chromium \
        --kiosk \
        --no-sandbox \
        --disable-infobars \
        --disable-session-crashed-bubble \
        --disable-restore-session-state \
        --disable-translate \
        --disable-features=TranslateUI,VizDisplayCompositor \
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
        --disable-extensions \
        --metrics-recording-only \
        --safebrowsing-disable-auto-update \
        --memory-pressure-off \
        --max-old-space-size=256 \
        --app=http://localhost:5004 \
        >> "$LOG_DIR/chromium.log" 2>&1
}

echo "[display] Launching Chromium kiosk → http://localhost:5004"
# Restart Chromium automatically if it exits (e.g. OOM crash)
while true; do
    launch_chromium
    EXIT=$?
    # Don't restart if X is gone or service is stopping
    kill -0 $XORG_PID 2>/dev/null || break
    echo "[display] Chromium exited (code $EXIT), restarting in 3s..."
    sleep 3
done

wait $XORG_PID
