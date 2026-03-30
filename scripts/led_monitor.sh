#!/bin/bash
###############################################################################
# Orange Pi LED Monitor
# Green (pwr):    solid = power on (always)
# Red (status):   heartbeat = idle/normal
#                 fast blink = CPU throttling (at max freq under load)
#                 solid on   = critical temp (>80°C)
#                 off        = error/dead
#
# LEDs:
#   /sys/class/leds/orangepi:green:pwr
#   /sys/class/leds/orangepi:red:status
###############################################################################

PWR_LED="/sys/class/leds/orangepi:green:pwr"
STATUS_LED="/sys/class/leds/orangepi:red:status"
TEMP_CRIT=80000   # millidegrees - critical
TEMP_WARN=70000   # millidegrees - warning
FREQ_FILE="/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq"
MAX_FILE="/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq"
TEMP_FILE="/sys/class/thermal/thermal_zone0/temp"

set_trigger() {
  local led=$1 trigger=$2
  echo "$trigger" > "$led/trigger" 2>/dev/null
}

set_brightness() {
  local led=$1 val=$2
  echo "$val" > "$led/brightness" 2>/dev/null
}

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
  echo "$delay_on"  > "$led/delay_on"  2>/dev/null
  echo "$delay_off" > "$led/delay_off" 2>/dev/null
}

# Power LED: always solid green
set_trigger "$PWR_LED" "none"
set_brightness "$PWR_LED" 1

echo "[led] LED monitor started"

while true; do
  TEMP=$(cat "$TEMP_FILE" 2>/dev/null || echo 0)
  CUR_FREQ=$(cat "$FREQ_FILE" 2>/dev/null || echo 0)
  MAX_FREQ=$(cat "$MAX_FILE" 2>/dev/null || echo 1)

  # Detect throttling: at max freq for 2 checks in a row
  if [ "$CUR_FREQ" -ge "$MAX_FREQ" ]; then
    THROTTLE=1
  else
    THROTTLE=0
  fi

  if [ "$TEMP" -ge "$TEMP_CRIT" ]; then
    # Critical temp: solid red
    set_solid "$STATUS_LED" 1
  elif [ "$TEMP" -ge "$TEMP_WARN" ] || [ "$THROTTLE" -eq 1 ]; then
    # Throttling or warm: fast blink (200ms on/200ms off)
    set_blink "$STATUS_LED" 200 200
  else
    # Normal: heartbeat
    set_heartbeat "$STATUS_LED"
  fi

  sleep 3
done
