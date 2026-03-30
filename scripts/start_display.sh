#!/bin/bash
###############################################################################
# start_display.sh — Start Xorg and Chromium kiosk
# Board-agnostic: Orange Pi, Raspberry Pi, Odroid, Intel Stick
# Deployed to: /opt/orangepi/scripts/start_display.sh
# Called by:   x-display.service
###############################################################################
set -uo pipefail

SCRIPT_DIR="/opt/orangepi/scripts"
LOG_DIR="/var/log/orangepi"
mkdir -p "$LOG_DIR"

# ── Environment ───────────────────────────────────────────────────────────────
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/0
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export XCURSOR_SIZE=24

# ── Hardware detection ────────────────────────────────────────────────────────
# shellcheck source=hw_detect.sh
source "$SCRIPT_DIR/hw_detect.sh" 2>/dev/null || {
    # Fallback defaults if hw_detect.sh missing
    HW_BOARD="generic"
    HW_CHROMIUM="chromium"
    HW_GPU_FLAGS="--disable-gpu --disable-software-rasterizer"
}
echo "[display] Board: $HW_BOARD  Chromium: $HW_CHROMIUM"

# ── 1. Wait for Flask dashboard to be ready ───────────────────────────────────
echo "[display] Waiting for dashboard (port 5004)..."
for i in $(seq 1 30); do
    if ss -tlnp | grep -q ':5004 '; then
        echo "[display] Dashboard ready (${i}s)."
        break
    fi
    sleep 1
done

# ── 2. Kill stale X session ───────────────────────────────────────────────────
pkill -f "Xorg :0" 2>/dev/null || true
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0 2>/dev/null || true
sleep 1

# ── 3. Raspberry Pi: use startx / dispmanx path if no Xorg ───────────────────
# RPi with KMS (vc4-kms-v3d) works fine with Xorg modesetting.
# RPi with legacy firmware driver (vc4-fkms) needs fbturbo — handled by Xorg conf.
# No special case needed; modesetting works on all RPi 3/4/5 with current kernel.

# ── 4. Start Xorg ─────────────────────────────────────────────────────────────
echo "[display] Starting Xorg..."
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
    echo "[display] ERROR: Xorg failed within 45s — see $LOG_DIR/xorg.log"
    exit 1
fi

# ── 5. Detect connected output and set resolution ─────────────────────────────
sleep 1
echo "[display] Probing display outputs..."
CONNECTED_OUTPUT=$(DISPLAY=:0 xrandr --query 2>/dev/null \
    | awk '/ connected/ {print $1; exit}')
CONNECTED_OUTPUT="${CONNECTED_OUTPUT:-HDMI-1}"
echo "[display] Output: $CONNECTED_OUTPUT"

DISPLAY=:0 xrandr --output "$CONNECTED_OUTPUT" --mode 1024x600 --rate 59.80 2>/dev/null \
    || DISPLAY=:0 xrandr --output "$CONNECTED_OUTPUT" --preferred 2>/dev/null \
    || DISPLAY=:0 xrandr --output "$CONNECTED_OUTPUT" --auto 2>/dev/null \
    || true

# Save detected output for use by device_config.py
echo "$CONNECTED_OUTPUT" > /run/orangepi_display_output

# ── 6. Desktop housekeeping ───────────────────────────────────────────────────
DISPLAY=:0 xsetroot -solid black 2>/dev/null || true
DISPLAY=:0 xset s off    2>/dev/null || true
DISPLAY=:0 xset -dpms    2>/dev/null || true
DISPLAY=:0 xset s noblank 2>/dev/null || true
DISPLAY=:0 unclutter -idle 0 -root 2>/dev/null &

# ── 7. Board-specific RAM cap for Chromium ────────────────────────────────────
# Limit renderer memory relative to board RAM
if [ "${HW_RAM_MB:-512}" -le 512 ]; then
    RAM_FLAG="--renderer-process-limit=1 --max-old-space-size=128"
elif [ "${HW_RAM_MB:-512}" -le 1024 ]; then
    RAM_FLAG="--renderer-process-limit=2 --max-old-space-size=256"
else
    RAM_FLAG="--max-old-space-size=512"
fi

# ── 8. Launch Chromium kiosk (auto-restart on crash) ─────────────────────────
launch_chromium() {
    # shellcheck disable=SC2086
    DISPLAY=:0 "$HW_CHROMIUM" \
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
        $HW_GPU_FLAGS \
        --disable-dev-shm-usage \
        --no-first-run \
        --disable-background-networking \
        --disable-sync \
        --disable-extensions \
        --metrics-recording-only \
        --safebrowsing-disable-auto-update \
        --memory-pressure-off \
        $RAM_FLAG \
        --app=http://localhost:5004 \
        >> "$LOG_DIR/chromium.log" 2>&1
}

echo "[display] Launching $HW_CHROMIUM kiosk → http://localhost:5004"
while true; do
    launch_chromium
    EXIT=$?
    kill -0 $XORG_PID 2>/dev/null || break
    echo "[display] Chromium exited (code $EXIT), restarting in 3s..."
    sleep 3
done

wait $XORG_PID
