#!/bin/bash
###############################################################################
# hw_detect.sh — Hardware detection library
# Source this file; do NOT execute it directly.
#
# After sourcing, the following variables are set:
#   HW_BOARD      = orangepi | raspberry | odroid | intel | generic
#   HW_ARCH       = arm64 | armhf | x86_64
#   HW_CPU_CORES  = number of CPU cores
#   HW_RAM_MB     = total RAM in MB
#   HW_DISPLAY    = hdmi | dsi | vga | unknown
#   HW_CHROMIUM   = chromium binary name (chromium / chromium-browser / google-chrome)
#   HW_AUDIO_CTL  = amixer control name (Master / PCM / Speaker / Headphone)
#   HW_LED_PWR    = sysfs path to power LED (or "none")
#   HW_LED_STATUS = sysfs path to status LED (or "none")
#   HW_TEMP_FILE  = sysfs thermal zone file
#   HW_GPU_FLAGS  = Chromium GPU flags appropriate for this board
#   HW_XORG_DRIVER= modesetting | fbdev
###############################################################################

HW_BOARD="generic"
HW_ARCH="$(uname -m)"
HW_CPU_CORES="$(nproc 2>/dev/null || echo 1)"
HW_RAM_MB="$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 512)"
HW_DISPLAY="hdmi"
HW_LED_PWR="none"
HW_LED_STATUS="none"
HW_TEMP_FILE="/sys/class/thermal/thermal_zone0/temp"
HW_XORG_DRIVER="modesetting"

# ── Board detection ────────────────────────────────────────────────────────────
_MODEL=""
if [ -f /proc/device-tree/model ]; then
    _MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
elif [ -f /sys/firmware/devicetree/base/model ]; then
    _MODEL="$(tr -d '\0' < /sys/firmware/devicetree/base/model 2>/dev/null)"
elif [ -f /etc/armbian-release ]; then
    _MODEL="$(. /etc/armbian-release 2>/dev/null; echo "${BOARD_NAME:-}")"
fi
_MODEL_LOWER="${_MODEL,,}"

if echo "$_MODEL_LOWER" | grep -qE "orange.?pi"; then
    HW_BOARD="orangepi"
elif echo "$_MODEL_LOWER" | grep -qE "raspberry.?pi|raspberrypi"; then
    HW_BOARD="raspberry"
elif echo "$_MODEL_LOWER" | grep -qE "odroid"; then
    HW_BOARD="odroid"
elif [ "$HW_ARCH" = "x86_64" ]; then
    # Intel Compute Stick / NUC / generic x86
    HW_BOARD="intel"
    HW_XORG_DRIVER="modesetting"
fi

# ── LED paths ──────────────────────────────────────────────────────────────────
_find_led() {
    # Try exact name first, then pattern
    local exact="$1" pattern="$2"
    if [ -d "/sys/class/leds/$exact" ]; then
        echo "/sys/class/leds/$exact"
    else
        find /sys/class/leds -maxdepth 1 -name "$pattern" 2>/dev/null | head -1
    fi
}

case "$HW_BOARD" in
    orangepi)
        HW_LED_PWR="$(_find_led 'orangepi:green:pwr'   'orangepi:green:*')"
        HW_LED_STATUS="$(_find_led 'orangepi:red:status' 'orangepi:red:*')"
        ;;
    raspberry)
        # RPi: green activity LED, red power LED
        HW_LED_STATUS="$(_find_led 'ACT'  'led0')"
        HW_LED_PWR="$(_find_led 'PWR'   'led1')"
        # RPi 4: led0=green(act), led1=red(pwr)
        [ -z "$HW_LED_STATUS" ] && HW_LED_STATUS="$(_find_led 'led0' 'ACT')"
        [ -z "$HW_LED_PWR" ]    && HW_LED_PWR="$(_find_led 'led1' 'PWR')"
        ;;
    odroid)
        HW_LED_STATUS="$(_find_led 'blue:heartbeat' 'blue:*')"
        HW_LED_PWR="$(_find_led 'red:microSD'      'red:*')"
        ;;
    *)
        # Intel / generic — try to find any LED; silently skip if none
        HW_LED_STATUS="$(find /sys/class/leds -maxdepth 1 -name '*:status*' 2>/dev/null | head -1)"
        HW_LED_PWR="$(find /sys/class/leds -maxdepth 1 -name '*:power*' 2>/dev/null | head -1)"
        ;;
esac
[ -z "$HW_LED_PWR" ]    && HW_LED_PWR="none"
[ -z "$HW_LED_STATUS" ] && HW_LED_STATUS="none"

# ── Thermal zone ───────────────────────────────────────────────────────────────
# Use the first readable zone; on RPi zone0 is SoC, on Intel it may be CPU pkg
for _zone in /sys/class/thermal/thermal_zone{0,1,2,3}/temp; do
    if [ -r "$_zone" ]; then
        HW_TEMP_FILE="$_zone"
        break
    fi
done

# ── Audio control name ─────────────────────────────────────────────────────────
HW_AUDIO_CTL="Master"
if amixer scontrols 2>/dev/null | grep -q "'PCM'"; then
    HW_AUDIO_CTL="PCM"
elif amixer scontrols 2>/dev/null | grep -q "'Speaker'"; then
    HW_AUDIO_CTL="Speaker"
elif amixer scontrols 2>/dev/null | grep -q "'Headphone'"; then
    HW_AUDIO_CTL="Headphone"
fi
# Export for device_config.py to read via env
export HW_AUDIO_CTL

# ── Chromium binary ────────────────────────────────────────────────────────────
HW_CHROMIUM="chromium"
for _bin in chromium chromium-browser google-chrome-stable google-chrome; do
    if command -v "$_bin" &>/dev/null; then
        HW_CHROMIUM="$_bin"
        break
    fi
done

# ── Chromium GPU flags per board ───────────────────────────────────────────────
# Check if VAAPI is available (hardware video decode)
_VAAPI_FLAGS=""
if vainfo 2>/dev/null | grep -q "VA-API"; then
    _VAAPI_FLAGS="--enable-accelerated-video-decode --use-gl=egl --enable-features=VaapiVideoDecoder"
fi

case "$HW_BOARD" in
    intel)
        # Intel GPU: enable hardware acceleration + VAAPI
        HW_GPU_FLAGS="--enable-gpu-rasterization --enable-zero-copy $_VAAPI_FLAGS"
        ;;
    raspberry)
        # RPi 4/5 has V3D GPU; RPi 3 uses software render
        if grep -q "Raspberry Pi 4\|Raspberry Pi 5" /proc/device-tree/model 2>/dev/null; then
            HW_GPU_FLAGS="--enable-gpu-rasterization --enable-zero-copy $_VAAPI_FLAGS"
        else
            HW_GPU_FLAGS="--disable-gpu --disable-software-rasterizer"
        fi
        ;;
    orangepi)
        # Orange Pi: try V4L2 decode if available
        if [ -e /dev/video0 ] && command -v v4l2-ctl &>/dev/null; then
            HW_GPU_FLAGS="--disable-gpu-sandbox --enable-accelerated-video-decode --use-gl=egl"
        else
            HW_GPU_FLAGS="--disable-gpu --disable-software-rasterizer"
        fi
        ;;
    *)
        # Generic ARM / Odroid — no GPU
        HW_GPU_FLAGS="--disable-gpu --disable-software-rasterizer"
        ;;
esac

# ── Display connection type ────────────────────────────────────────────────────
# Detect display connector type from sysfs (works before X starts)
if ls /sys/class/drm/card*/card*-HDMI-*/status 2>/dev/null | xargs grep -l "^connected" &>/dev/null; then
    HW_DISPLAY="hdmi"
elif ls /sys/class/drm/card*/card*-DSI-*/status 2>/dev/null | xargs grep -l "^connected" &>/dev/null; then
    HW_DISPLAY="dsi"
elif ls /sys/class/drm/card*/card*-VGA-*/status 2>/dev/null | xargs grep -l "^connected" &>/dev/null; then
    HW_DISPLAY="vga"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo "[hw_detect] Board:    $HW_BOARD ($_MODEL)"
echo "[hw_detect] Arch:     $HW_ARCH  Cores: $HW_CPU_CORES  RAM: ${HW_RAM_MB}MB"
echo "[hw_detect] LED pwr:  $HW_LED_PWR"
echo "[hw_detect] LED stat: $HW_LED_STATUS"
echo "[hw_detect] Temp:     $HW_TEMP_FILE"
echo "[hw_detect] Chromium: $HW_CHROMIUM"
echo "[hw_detect] Audio:    $HW_AUDIO_CTL"
