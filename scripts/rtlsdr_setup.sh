#!/bin/bash
###############################################################################
# RTL-SDR / DAB+ Auto-Install & Configure Script
# Supports: RTL2832U-based dongles (Realtek 0bda:2832, 0bda:2838, 0bda:2833)
#
# What this does:
#   1. Install rtl-sdr tools, librtlsdr, dablin (DAB+ decoder)
#   2. Blacklist dvb_usb_rtl28xxu (conflicts with rtlsdr driver)
#   3. Install udev rules for RTL2832U dongles (non-root access)
#   4. Load rtl2832_sdr kernel module
#   5. Test dongle if plugged in
###############################################################################

set -euo pipefail

LOG="/tmp/rtlsdr_setup.log"
exec > >(tee -a "$LOG") 2>&1

echo "[rtlsdr] === RTL-SDR / DAB+ Setup ==="
echo "[rtlsdr] Date: $(date)"

#------------------------------------------------------------------------------
# 1. Install packages
#------------------------------------------------------------------------------
echo "[rtlsdr] Installing packages..."
apt-get update -qq
apt-get install -y \
  rtl-sdr \
  librtlsdr0 \
  librtlsdr-dev \
  dablin \
  sox \
  wget \
  usbutils

echo "[rtlsdr] Packages installed."

#------------------------------------------------------------------------------
# 2. Blacklist conflicting DVB driver
#    dvb_usb_rtl28xxu grabs the dongle before rtlsdr can use it
#------------------------------------------------------------------------------
BLACKLIST_FILE="/etc/modprobe.d/rtlsdr-blacklist.conf"
echo "[rtlsdr] Writing blacklist: $BLACKLIST_FILE"
cat > "$BLACKLIST_FILE" << 'EOF'
# RTL-SDR: prevent DVB driver from claiming RTL2832U devices
blacklist dvb_usb_rtl28xxu
blacklist dvb_usb_v2
blacklist rtl_2830
blacklist rtl_2832
EOF
echo "[rtlsdr] Blacklist written."

#------------------------------------------------------------------------------
# 3. udev rules — allow non-root access to RTL2832U dongles
#------------------------------------------------------------------------------
UDEV_RULES="/etc/udev/rules.d/20-rtlsdr.rules"
echo "[rtlsdr] Writing udev rules: $UDEV_RULES"
cat > "$UDEV_RULES" << 'EOF'
# RTL-SDR / RTL2832U USB dongles — non-root access
# Realtek RTL2832U (generic)
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", GROUP="plugdev", MODE="0664", SYMLINK+="rtlsdr%n", TAG+="uaccess"
# Realtek RTL2838 (common cheap dongle variant)
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", GROUP="plugdev", MODE="0664", SYMLINK+="rtlsdr%n", TAG+="uaccess"
# Realtek RTL2833 (some dongles)
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2833", GROUP="plugdev", MODE="0664", SYMLINK+="rtlsdr%n", TAG+="uaccess"
# Realtek RTL2832P (DVB-T+DAB+FM variety)
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2837", GROUP="plugdev", MODE="0664", SYMLINK+="rtlsdr%n", TAG+="uaccess"
# ezcap EzTV668 / EzCAP USB2.0 DVB-T+DAB
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2836", GROUP="plugdev", MODE="0664", SYMLINK+="rtlsdr%n", TAG+="uaccess"
# Terratec Cinergy T Stick
SUBSYSTEM=="usb", ATTRS{idVendor}=="0ccd", ATTRS{idProduct}=="00d3", GROUP="plugdev", MODE="0664", SYMLINK+="rtlsdr%n", TAG+="uaccess"
# Terratec Cinergy T Stick+
SUBSYSTEM=="usb", ATTRS{idVendor}=="0ccd", ATTRS{idProduct}=="00b7", GROUP="plugdev", MODE="0664", SYMLINK+="rtlsdr%n", TAG+="uaccess"
# Generic DVB-T OEM (many common $10 dongles)
SUBSYSTEM=="usb", ATTRS{idVendor}=="1f4d", ATTRS{idProduct}=="b803", GROUP="plugdev", MODE="0664", SYMLINK+="rtlsdr%n", TAG+="uaccess"
# Nooelec RTL-SDR
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", GROUP="plugdev", MODE="0664", TAG+="uaccess"
EOF
echo "[rtlsdr] udev rules written."

# Reload udev
udevadm control --reload-rules
udevadm trigger
echo "[rtlsdr] udev rules reloaded."

#------------------------------------------------------------------------------
# 4. Ensure plugdev group exists and root is in it
#------------------------------------------------------------------------------
getent group plugdev > /dev/null 2>&1 || groupadd plugdev
usermod -aG plugdev root 2>/dev/null || true
echo "[rtlsdr] plugdev group configured."

#------------------------------------------------------------------------------
# 5. Unload conflicting DVB modules if loaded
#------------------------------------------------------------------------------
echo "[rtlsdr] Unloading conflicting modules (if loaded)..."
for mod in dvb_usb_rtl28xxu dvb_usb_v2 rtl_2832 rtl_2830; do
  if lsmod | grep -q "^$mod "; then
    modprobe -r "$mod" 2>/dev/null && echo "[rtlsdr] Unloaded: $mod" || echo "[rtlsdr] Could not unload: $mod"
  fi
done

#------------------------------------------------------------------------------
# 6. Load rtlsdr module
#------------------------------------------------------------------------------
echo "[rtlsdr] Loading rtlsdr module..."
modprobe rtlsdr 2>/dev/null || modprobe rtl2832_sdr 2>/dev/null || echo "[rtlsdr] Note: rtlsdr module not loaded (will load on dongle plug-in)"

#------------------------------------------------------------------------------
# 7. Write DAB+ wrapper script
#    Usage: dab_play.sh <frequency_MHz> [ensemble_name]
#    Example: dab_play.sh 218.640   (BBC National DAB, UK block 12B)
#------------------------------------------------------------------------------
DAB_SCRIPT="/opt/weather_station/dab_play.sh"
echo "[rtlsdr] Writing DAB+ play script: $DAB_SCRIPT"
cat > "$DAB_SCRIPT" << 'DABEOF'
#!/bin/bash
# DAB+ Play using dablin + rtl_sdr
# Usage: dab_play.sh <frequency_MHz>
# Example: dab_play.sh 218.640

FREQ_MHZ="${1:-218.640}"
FREQ_HZ=$(echo "$FREQ_MHZ * 1000000" | bc | cut -d. -f1)

echo "[dab] Starting DAB+ on ${FREQ_MHZ} MHz (${FREQ_HZ} Hz)"

# Check dongle present
if ! rtl_test -t 2>/dev/null | grep -q "Found"; then
  echo "[dab] ERROR: No RTL-SDR dongle detected"
  exit 1
fi

# dablin: pipe from rtl_sdr
rtl_sdr -f "$FREQ_HZ" -s 2048000 -g 40 - 2>/dev/null | \
  dablin -d - -p 0 2>/dev/null
DABEOF
chmod +x "$DAB_SCRIPT"

#------------------------------------------------------------------------------
# 8. Write dongle detection/status script (used by Flask UI)
#------------------------------------------------------------------------------
DETECT_SCRIPT="/opt/weather_station/rtlsdr_detect.sh"
cat > "$DETECT_SCRIPT" << 'DETECTEOF'
#!/bin/bash
# Detect RTL-SDR dongle and output JSON status
# Called by Flask API for UI status display

FOUND=0
DEVICE=""
USB_ID=""

# Check for known RTL2832U USB IDs
while IFS= read -r line; do
  if echo "$line" | grep -qiE "0bda:(2832|2833|2836|2837|2838)|0ccd:(00b7|00d3)|1f4d:b803"; then
    FOUND=1
    USB_ID=$(echo "$line" | grep -oE "[0-9a-f]{4}:[0-9a-f]{4}")
    DEVICE=$(echo "$line" | sed 's/^.*: //')
    break
  fi
done < <(lsusb 2>/dev/null)

# Check if driver is loaded
DRIVER_LOADED=0
if lsmod 2>/dev/null | grep -q "rtl"; then
  DRIVER_LOADED=1
fi

# Check if DVB conflict module is active (bad)
DVB_CONFLICT=0
if lsmod 2>/dev/null | grep -q "dvb_usb_rtl28xxu"; then
  DVB_CONFLICT=1
fi

echo "{\"found\": $FOUND, \"usb_id\": \"$USB_ID\", \"device\": \"$DEVICE\", \"driver_loaded\": $DRIVER_LOADED, \"dvb_conflict\": $DVB_CONFLICT}"
DETECTEOF
chmod +x "$DETECT_SCRIPT"

#------------------------------------------------------------------------------
# 9. Test dongle if plugged in
#------------------------------------------------------------------------------
echo "[rtlsdr] Checking for connected dongle..."
if lsusb | grep -iE "0bda:(2832|2838|2833)"; then
  echo "[rtlsdr] Dongle detected! Running rtl_test..."
  timeout 5 rtl_test -t 2>&1 | head -20 || true
else
  echo "[rtlsdr] No dongle plugged in — skipping rtl_test."
  echo "[rtlsdr] Plug in RTL2832U dongle and re-run this script to test."
fi

echo ""
echo "[rtlsdr] === Setup Complete ==="
echo "[rtlsdr] Log: $LOG"
echo ""
echo "Quick test after plugging dongle:"
echo "  rtl_test -t"
echo "  rtl_power -f 200M:250M:100k -1 /tmp/scan.csv && cat /tmp/scan.csv"
echo ""
echo "DAB+ play (UK block 12B = 218.640 MHz):"
echo "  /opt/weather_station/dab_play.sh 218.640"
