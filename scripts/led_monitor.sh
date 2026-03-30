#!/bin/bash
###############################################################################
# Orange Pi LED Monitor — status indicator daemon
#
# Green (pwr):    solid = power on (always)
# Red (status):   heartbeat  = normal / idle
#                 fast blink = CPU throttling or warm (>70°C)
#                 solid on   = critical temperature (>80°C)
#
# LED sysfs paths for Orange Pi PC2:
#   /sys/class/leds/orangepi:green:pwr
#   /sys/class/leds/orangepi:red:status
###############################################################################
set -uo pipefail

PWR_LED="/sys/class/leds/orangepi:green:pwr"
STATUS_LED="/sys/class/leds/orangepi:red:status"
TEMP_CRIT=80000     # millidegrees
TEMP_WARN=70000     # millidegrees
FREQ_FILE="/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq"
MAX_FILE="/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq"
TEMP_FILE="/sys/class/thermal/thermal_zone0/temp"

THROTTLE_COUNT=0    # consecutive samples at max freq

# ── Graceful exit on SIGTERM / SIGINT ────────────────────────────────────────
cleanup() {
    echo "[led] Shutting down — resetting LEDs to heartbeat"
    set_heartbeat "$PWR_LED" 2>/dev/null || true
    set_heartbeat "$STATUS_LED" 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# ── Helpers ───────────────────────────────────────────────────────────────────
led_write() {
    local file=$1 val=$2
    [ -w "$file" ] && echo "$val" > "$file"
}

set_trigger()   { led_write "$1/trigger" "$2"; }
set_brightness(){ led_write "$1/brightness" "$2"; }

set_heartbeat() {
    local led=$1
    set_trigger "$led" "heartbeat"
}

set_solid() {
    local led=$1 val=$2
    set_trigger "$led" "none"
    set_brightness "$led" "$val"
}

set_blink() {
    local led=$1 delay_on=$2 delay_off=$3
    set_trigger "$led" "timer"
    led_write "$led/delay_on"  "$delay_on"
    led_write "$led/delay_off" "$delay_off"
}

# ── Verify LED paths exist ────────────────────────────────────────────────────
if [ ! -d "$PWR_LED" ] || [ ! -d "$STATUS_LED" ]; then
    echo "[led] WARN: LED sysfs paths not found — LED monitor inactive"
    # Stay alive so systemd doesn't restart in a crash loop
    while true; do sleep 60; done
fi

# ── Power LED: always solid green ────────────────────────────────────────────
set_solid "$PWR_LED" 1
echo "[led] LED monitor started"

# ── Main loop ─────────────────────────────────────────────────────────────────
while true; do
    TEMP=$(cat "$TEMP_FILE" 2>/dev/null || echo 0)
    CUR_FREQ=$(cat "$FREQ_FILE" 2>/dev/null || echo 0)
    MAX_FREQ=$(cat "$MAX_FILE" 2>/dev/null || echo 1)

    # Throttle: require 2 consecutive samples at max freq to avoid flapping
    if [ "$CUR_FREQ" -ge "$MAX_FREQ" ]; then
        THROTTLE_COUNT=$((THROTTLE_COUNT + 1))
    else
        THROTTLE_COUNT=0
    fi
    THROTTLED=$( [ "$THROTTLE_COUNT" -ge 2 ] && echo 1 || echo 0 )

    if [ "$TEMP" -ge "$TEMP_CRIT" ]; then
        # Critical temperature — solid red
        set_solid "$STATUS_LED" 1
    elif [ "$TEMP" -ge "$TEMP_WARN" ] || [ "$THROTTLED" -eq 1 ]; then
        # Warm or throttling — fast blink (200 ms on / 200 ms off)
        set_blink "$STATUS_LED" 200 200
    else
        # Normal — slow heartbeat
        set_heartbeat "$STATUS_LED"
    fi

    sleep 3
done
