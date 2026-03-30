#!/bin/bash
###############################################################################
# led_monitor.sh — Board-agnostic LED status daemon
#
# Supports: Orange Pi, Raspberry Pi, Odroid, Intel (no LEDs = silent no-op)
#
# Status LED behaviour:
#   heartbeat  = normal / idle
#   fast blink = CPU throttling or warm (>70°C)
#   solid on   = critical temperature (>80°C)
###############################################################################
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Source hardware detection ─────────────────────────────────────────────────
# Silence xrandr probe (X may not be up yet); we only need LED paths here
_OLD_DISPLAY="${DISPLAY:-}"
unset DISPLAY
# shellcheck source=hw_detect.sh
source "$SCRIPT_DIR/hw_detect.sh" 2>/dev/null || true
[ -n "$_OLD_DISPLAY" ] && export DISPLAY="$_OLD_DISPLAY"

PWR_LED="$HW_LED_PWR"
STATUS_LED="$HW_LED_STATUS"
TEMP_CRIT=80000     # millidegrees
TEMP_WARN=70000     # millidegrees
TEMP_FILE="${HW_TEMP_FILE:-/sys/class/thermal/thermal_zone0/temp}"
FREQ_FILE="/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq"
MAX_FILE="/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq"
THROTTLE_COUNT=0

# ── Graceful exit ─────────────────────────────────────────────────────────────
cleanup() {
    echo "[led] Shutdown — resetting LEDs"
    [ "$PWR_LED"    != "none" ] && set_heartbeat "$PWR_LED"    2>/dev/null || true
    [ "$STATUS_LED" != "none" ] && set_heartbeat "$STATUS_LED" 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# ── Helpers ───────────────────────────────────────────────────────────────────
led_write()     { local f=$1 v=$2; [ -w "$f" ] && echo "$v" > "$f"; }
set_trigger()   { led_write "$1/trigger"    "$2"; }
set_brightness(){ led_write "$1/brightness" "$2"; }
set_heartbeat() { set_trigger "$1" "heartbeat"; }
set_solid()     { set_trigger "$1" "none"; set_brightness "$1" "$2"; }
set_blink() {
    set_trigger "$1" "timer"
    led_write "$1/delay_on"  "$2"
    led_write "$1/delay_off" "$3"
}

# ── No LEDs available (Intel Stick, generic x86) ──────────────────────────────
if [ "$PWR_LED" = "none" ] && [ "$STATUS_LED" = "none" ]; then
    echo "[led] No LED sysfs paths found for board '$HW_BOARD' — running in temp-log-only mode"
    while true; do
        TEMP=$(cat "$TEMP_FILE" 2>/dev/null || echo 0)
        TEMP_C=$((TEMP / 1000))
        if [ "$TEMP_C" -ge 80 ]; then
            echo "[led] CRITICAL temp: ${TEMP_C}°C"
        elif [ "$TEMP_C" -ge 70 ]; then
            echo "[led] WARNING temp: ${TEMP_C}°C"
        fi
        sleep 10
    done
fi

# ── Power LED: always solid ───────────────────────────────────────────────────
[ "$PWR_LED" != "none" ] && set_solid "$PWR_LED" 1
echo "[led] LED monitor started — board: $HW_BOARD  pwr=$PWR_LED  status=$STATUS_LED"

# ── Main loop ─────────────────────────────────────────────────────────────────
while true; do
    TEMP=$(cat "$TEMP_FILE" 2>/dev/null || echo 0)
    CUR_FREQ=$(cat "$FREQ_FILE" 2>/dev/null || echo 0)
    MAX_FREQ=$(cat "$MAX_FILE"  2>/dev/null || echo 1)

    # Require 2 consecutive samples at max freq to avoid flapping
    if [ "$CUR_FREQ" -ge "$MAX_FREQ" ]; then
        THROTTLE_COUNT=$((THROTTLE_COUNT + 1))
    else
        THROTTLE_COUNT=0
    fi
    THROTTLED=$([ "$THROTTLE_COUNT" -ge 2 ] && echo 1 || echo 0)

    if [ "$STATUS_LED" != "none" ]; then
        if [ "$TEMP" -ge "$TEMP_CRIT" ]; then
            set_solid "$STATUS_LED" 1
        elif [ "$TEMP" -ge "$TEMP_WARN" ] || [ "$THROTTLED" -eq 1 ]; then
            set_blink "$STATUS_LED" 200 200
        else
            set_heartbeat "$STATUS_LED"
        fi
    fi

    sleep 3
done
