#!/bin/bash
###############################################################################
# Orange Pi Control Center — Armbian Installer & Operations Menu
#
# Run directly:  sudo bash armbian_orangepi_installer.sh
# Armbian-config integration:
#   sudo mkdir -p /usr/lib/armbian-config/userpatches
#   sudo cp armbian_orangepi_installer.sh \
#     /usr/lib/armbian-config/userpatches/orangepi_control_center.sh
#   # Appears under: armbian-config → Software → Softy → User scripts
#
# What this script manages:
#   install      System packages (Python, Chromium, mpv, nmcli, amixer, etc.)
#   venv         Create/update isolated Python venv at /opt/orangepi/venv
#   deploy       Copy project files from source tree to /opt/orangepi
#   services     Enable & start all systemd services
#   timezone     Auto-detect timezone + location via GeoIP and apply
#   wifi         Connect to WiFi via nmcli (interactive)
#   rtlsdr       RTL-SDR / DAB+ driver setup (optional)
#   ha           Install Home Assistant Core (optional)
#   weewx        Install WeeWX weather station software (optional)
#   netdata      Install Netdata real-time monitor (optional)
#   wizard       Reset first-run welcome wizard
#   logs         Tail live logs from all services
#   status       Show service status summary
#   update       git pull + redeploy from local clone
#   quit         Exit
###############################################################################

set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────
DEST="/opt/orangepi"
VENV="$DEST/venv"
LOG_DIR="/var/log/orangepi"
INSTALLER_LOG="$LOG_DIR/installer.log"
SETTINGS="$DEST/config/user_settings.json"
TITLE="Orange Pi Control Center"

# ── Board detection ───────────────────────────────────────────────────────────
BOARD="generic"
_MODEL=""
if [ -f /proc/device-tree/model ]; then
    _MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
elif [ -f /etc/armbian-release ]; then
    # shellcheck disable=SC1091
    _MODEL="$(. /etc/armbian-release 2>/dev/null; echo "${BOARD_NAME:-}")"
fi
_MODEL_L="${_MODEL,,}"
if   echo "$_MODEL_L" | grep -qE "orange.?pi";    then BOARD="orangepi"
elif echo "$_MODEL_L" | grep -qE "raspberry.?pi"; then BOARD="raspberry"
elif echo "$_MODEL_L" | grep -qE "odroid";        then BOARD="odroid"
elif [ "$(uname -m)" = "x86_64" ];                then BOARD="intel"
fi
echo "[installer] Detected board: $BOARD  (${_MODEL:-unknown})"

# Default source: directory containing this script, or CWD
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DEFAULT="$(dirname "$SCRIPT_DIR")"   # parent of scripts/

# ── Guards ────────────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Run as root:  sudo bash $0" >&2
    exit 1
fi

# ── Logging ───────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
exec > >(tee -a "$INSTALLER_LOG") 2>&1
echo ""
echo "═══════════════════════════════════════════════════════"
echo " $TITLE — Installer started $(date)"
echo "═══════════════════════════════════════════════════════"

# ── Ensure whiptail ───────────────────────────────────────────────────────────
if ! command -v whiptail &>/dev/null; then
    echo "[installer] Installing whiptail..."
    apt-get update -qq && apt-get install -y --no-install-recommends whiptail
fi

# ── Helper: run with progress spinner ────────────────────────────────────────
run_task() {
    local label="$1"
    shift
    echo "[installer] $label..."
    "$@"
    echo "[installer] $label — done."
}

# ── Helper: show info box ─────────────────────────────────────────────────────
info() { whiptail --title "$TITLE" --msgbox "$1" 10 68; }
ask()  { whiptail --title "$TITLE" --yesno "$1" 10 68; }

# ── Helper: write/update a JSON key in user_settings.json ────────────────────
json_set() {
    local key="$1" val="$2"
    python3 - "$key" "$val" <<'PY'
import sys, json, pathlib
key, val = sys.argv[1], sys.argv[2]
p = pathlib.Path("$SETTINGS")
p.parent.mkdir(parents=True, exist_ok=True)
data = {}
if p.exists():
    try: data = json.loads(p.read_text())
    except Exception: pass
# coerce type
try: data[key] = json.loads(val)
except Exception: data[key] = val
p.write_text(json.dumps(data, indent=2))
PY
}

# ── Helper: get value from JSON settings ─────────────────────────────────────
json_get() {
    local key="$1" default="${2:-}"
    python3 - "$key" "$default" <<'PY'
import sys, json, pathlib
key, default = sys.argv[1], sys.argv[2]
p = pathlib.Path("$SETTINGS")
if not p.exists(): print(default); sys.exit(0)
try: print(json.loads(p.read_text()).get(key, default))
except Exception: print(default)
PY
}

# ─────────────────────────────────────────────────────────────────────────────
# ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

do_install() {
    whiptail --title "$TITLE" --infobox "Installing system packages for board: $BOARD\nThis may take a few minutes." 8 56
    apt-get update -qq

    # Core packages common to all boards
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python3 python3-pip python3-venv python3-dev \
        python3-flask python3-requests \
        xorg xinit xserver-xorg-input-libinput \
        x11-xserver-utils xdpyinfo unclutter \
        mpv alsa-utils \
        network-manager \
        curl wget jq \
        usbutils rsync git \
        onboard \
        vainfo libva-dev \
        2>/dev/null || true

    # Chromium — package name varies by distro/board
    for _pkg in chromium chromium-browser; do
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$_pkg" 2>/dev/null && break || true
    done

    # RTL-SDR — best-effort, not fatal
    DEBIAN_FRONTEND=noninteractive apt-get install -y rtl-sdr dablin sox 2>/dev/null || true

    # Board-specific extras
    case "$BOARD" in
        orangepi)
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                libv4l-dev v4l-utils \
                libvdpau-va-gl1 2>/dev/null || true
            ;;
        raspberry)
            # raspi-config helper, VC libraries
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                raspi-config libraspberrypi-bin \
                libv4l-dev v4l-utils 2>/dev/null || true
            ;;
        odroid)
            # Odroid utility package
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                odroid-utility 2>/dev/null || true
            ;;
        intel)
            # Intel video/audio firmware
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                intel-microcode firmware-misc-nonfree \
                va-driver-all \
                i965-va-driver intel-media-va-driver 2>/dev/null || true
            ;;
    esac

    info "System packages installed for board: $BOARD"
}

do_venv() {
    echo "[installer] Creating Python venv at $VENV ..."
    mkdir -p "$DEST"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip --quiet
    "$VENV/bin/pip" install flask requests --quiet
    echo "[installer] Venv ready: $VENV"
    info "Python virtual environment created at $VENV\nFlask and requests installed."
}

do_deploy() {
    local src
    src=$(whiptail --title "$TITLE" \
        --inputbox "Path to project root (folder containing apps/, scripts/, config/):" \
        10 70 "$SOURCE_DEFAULT" 3>&1 1>&2 2>&3) || return 0

    if [ ! -d "$src/apps" ]; then
        info "ERROR: $src/apps not found.\nMake sure you point to the project root."
        return 1
    fi

    echo "[installer] Deploying from $src → $DEST"
    mkdir -p "$DEST" "$LOG_DIR"

    # Apps
    rsync -av --delete \
        "$src/apps/" "$DEST/apps/" \
        --exclude "__pycache__" --exclude "*.pyc" --exclude "*.pyo"

    # Scripts (no delete — device may have generated scripts)
    rsync -av \
        "$src/scripts/" "$DEST/scripts/" \
        --exclude "__pycache__"
    chmod +x "$DEST"/scripts/*.sh 2>/dev/null || true

    # Services
    rsync -av "$src/services/" /etc/systemd/system/ \
        --include "*.service" --exclude "*"

    # Config (Xorg, udev)
    [ -f "$src/config/99-modesetting.conf" ] && \
        rsync -av "$src/config/99-modesetting.conf" /etc/X11/xorg.conf.d/
    [ -f "$src/config/99-touchscreen.rules" ] && \
        rsync -av "$src/config/99-touchscreen.rules" /etc/udev/rules.d/
    [ -f "$src/config/99-kiosk-leds.rules" ] && \
        rsync -av "$src/config/99-kiosk-leds.rules" /etc/udev/rules.d/
    udevadm control --reload-rules && udevadm trigger

    # user_settings.json: deploy example only if no real file exists
    mkdir -p "$DEST/config"
    if [ ! -f "$SETTINGS" ]; then
        if [ -f "$src/config/user_settings.json.example" ]; then
            cp "$src/config/user_settings.json.example" "$SETTINGS"
        elif [ -f "$src/config/user_settings.json" ]; then
            cp "$src/config/user_settings.json" "$SETTINGS"
        fi
    fi

    # Remove legacy fbdev config
    rm -f /etc/X11/xorg.conf.d/99-fbdev.conf

    systemctl daemon-reload
    info "Deploy complete!\nFiles are in $DEST\nRun 'Enable & start services' next."
}

do_services() {
    # ── 1. Create kiosk user ──────────────────────────────────────────────────
    echo "[installer] Setting up kiosk user..."
    if ! id kiosk &>/dev/null; then
        useradd -r -m -d /home/kiosk -s /bin/bash \
            -c "Orange Pi kiosk user" kiosk
        echo "[installer] User 'kiosk' created"
    else
        echo "[installer] User 'kiosk' already exists"
    fi
    # Add kiosk to required hardware groups
    for grp in video audio input netdev tty dialout plugdev; do
        getent group "$grp" &>/dev/null && usermod -aG "$grp" kiosk
    done

    # ── 2. Sudoers: only specific privileged commands, no password ────────────
    cat > /etc/sudoers.d/kiosk-orangepi << 'SUDOERS'
# Orange Pi kiosk — minimal privilege escalation
# NOPASSWD for shutdown/reboot (called by Flask dashboard)
kiosk ALL=(root) NOPASSWD: /sbin/shutdown
kiosk ALL=(root) NOPASSWD: /usr/bin/timedatectl set-timezone *
kiosk ALL=(root) NOPASSWD: /usr/bin/nmcli device wifi connect *
kiosk ALL=(root) NOPASSWD: /usr/bin/nmcli device wifi list
SUDOERS
    chmod 440 /etc/sudoers.d/kiosk-orangepi
    echo "[installer] Sudoers configured for kiosk"

    # ── 3. Fix file ownership ─────────────────────────────────────────────────
    chown -R kiosk:kiosk /opt/orangepi 2>/dev/null || true
    chown -R kiosk:kiosk /var/log/orangepi 2>/dev/null || true
    # PID files in /run
    mkdir -p /run/orangepi
    chown kiosk:kiosk /run/orangepi

    # ── 4. XDG_RUNTIME_DIR for kiosk ─────────────────────────────────────────
    KIOSK_UID=$(id -u kiosk)
    mkdir -p "/run/user/${KIOSK_UID}"
    chown kiosk:kiosk "/run/user/${KIOSK_UID}"
    chmod 700 "/run/user/${KIOSK_UID}"
    # Patch the service file with the real UID
    sed -i "s|XDG_RUNTIME_DIR=/run/user/[0-9]*|XDG_RUNTIME_DIR=/run/user/${KIOSK_UID}|" \
        /etc/systemd/system/x-display.service 2>/dev/null || true
    echo "[installer] XDG_RUNTIME_DIR set to /run/user/${KIOSK_UID}"

    # ── 5. Autologin: kiosk on tty1 ──────────────────────────────────────────
    echo "[installer] Configuring autologin for kiosk on tty1..."
    mkdir -p /etc/systemd/system/getty@tty1.service.d
    cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << AUTOLOGIN
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin kiosk --noclear %I \$TERM
Type=idle
AUTOLOGIN
    echo "[installer] Autologin configured — kiosk user logs in to tty1 automatically"

    # ── 6. Onboard virtual keyboard autostart ────────────────────────────────
    if command -v onboard &>/dev/null; then
        mkdir -p /home/kiosk/.config/autostart
        cat > /home/kiosk/.config/autostart/onboard-kiosk.desktop << 'ONBOARD'
[Desktop Entry]
Type=Application
Name=Onboard Keyboard
Exec=onboard --size=800x220 --layout=Phone --xid
NoDisplay=true
X-GNOME-Autostart-enabled=true
ONBOARD
        chown -R kiosk:kiosk /home/kiosk/.config
        echo "[installer] Onboard keyboard autostart configured"
    fi

    # ── 7. Enable and start services ─────────────────────────────────────────
    systemctl daemon-reload
    echo "[installer] Enabling and starting services..."
    local services=("weather-station.service" "x-display.service" "led-monitor.service")
    for svc in "${services[@]}"; do
        if systemctl list-unit-files "$svc" &>/dev/null; then
            systemctl enable "$svc" 2>/dev/null || true
            systemctl restart "$svc" 2>/dev/null || true
            echo "[installer] $svc → enabled+started"
        else
            echo "[installer] $svc not found — skipping"
        fi
    done
    local status=""
    for svc in "${services[@]}"; do
        state=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
        status+="  $svc : $state\n"
    done
    info "Services status:\n\n$status\nApps run as: kiosk (UID ${KIOSK_UID})\nSSH access: root only"
}

do_timezone() {
    whiptail --title "$TITLE" --infobox "Detecting location via GeoIP..." 6 40
    local json tz lat lon city country
    if json=$(curl -s --max-time 8 "http://ip-api.com/json"); then
        tz=$(echo "$json"    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('timezone','UTC'))")
        lat=$(echo "$json"   | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('lat',''))")
        lon=$(echo "$json"   | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('lon',''))")
        city=$(echo "$json"  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('city',''))")
        country=$(echo "$json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('country',''))")
    else
        tz="UTC"; lat=""; lon=""; city="Unknown"; country=""
    fi

    # Apply timezone
    timedatectl set-timezone "$tz" || true

    # Persist to user_settings.json
    mkdir -p "$(dirname "$SETTINGS")"
    python3 - "$tz" "$lat" "$lon" <<'PY'
import sys, json, pathlib
tz, lat, lon = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path("$SETTINGS")
data = {}
if p.exists():
    try: data = json.loads(p.read_text())
    except Exception: pass
data["timezone"] = tz
data["hardware_control"] = True
data["first_run"] = data.get("first_run", False)
if lat:
    try: data["latitude"] = float(lat)
    except Exception: pass
if lon:
    try: data["longitude"] = float(lon)
    except Exception: pass
p.write_text(json.dumps(data, indent=2))
PY

    info "Timezone: $tz\nLocation: $city, $country\nLat: $lat  Lon: $lon\n\nApplied to system and saved to config."
}

do_wifi() {
    local ssid pass
    ssid=$(whiptail --title "$TITLE" --inputbox "WiFi SSID:" 8 50 "" 3>&1 1>&2 2>&3) || return 0
    [ -z "$ssid" ] && return 0
    pass=$(whiptail --title "$TITLE" --passwordbox "WiFi Password:" 8 50 "" 3>&1 1>&2 2>&3) || return 0

    whiptail --title "$TITLE" --infobox "Connecting to '$ssid'..." 6 40
    if nmcli device wifi connect "$ssid" password "$pass" 2>&1; then
        info "Connected to '$ssid' successfully."
    else
        info "Connection to '$ssid' failed.\nCheck SSID and password, then retry."
    fi
}

do_rtlsdr() {
    ask "Install RTL-SDR / DAB+ drivers?\n\nThis installs rtl-sdr, librtlsdr, dablin and configures udev rules." || return 0
    bash "$SCRIPT_DIR/rtlsdr_setup.sh"
    info "RTL-SDR setup complete.\nPlug in your dongle and run: rtl_test -t"
}

do_ha() {
    ask "Install Home Assistant Core?\n\nCreates user 'hass', installs Python venv under /home/hass/ha\nThis can take 10-20 minutes." || return 0
    whiptail --title "$TITLE" --infobox "Installing Home Assistant Core...\nPlease wait (10-20 min)." 8 50
    id hass &>/dev/null 2>&1 || useradd -rm -G dialout -s /bin/bash hass
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python3-venv python3-dev libffi-dev libssl-dev autoconf libjpeg-dev libopenjp2-7
    sudo -u hass bash -c '
        python3 -m venv ~/ha
        source ~/ha/bin/activate
        pip install --upgrade pip --quiet
        pip install homeassistant --quiet
        cat > ~/start_ha.sh << "EOF"
#!/bin/bash
source ~/ha/bin/activate
hass --open-ui
EOF
        chmod +x ~/start_ha.sh
    '
    info "Home Assistant Core installed.\n\nStart with:\n  sudo -u hass /home/hass/start_ha.sh\n\nWeb UI: http://$(hostname -I | awk '{print $1}'):8123"
}

do_weewx() {
    ask "Install WeeWX weather station software?" || return 0
    whiptail --title "$TITLE" --infobox "Installing WeeWX..." 6 40
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y weewx
    systemctl enable weewx 2>/dev/null || true
    systemctl start weewx  2>/dev/null || true
    info "WeeWX installed and started.\n\nDefault web reports: http://localhost:8080/weewx/\n\nConfigure at: /etc/weewx/weewx.conf"
}

do_netdata() {
    ask "Install Netdata real-time system monitor?" || return 0
    whiptail --title "$TITLE" --infobox "Installing Netdata (one-line installer)..." 6 50
    bash <(curl -Ss https://my-netdata.io/kickstart.sh) --disable-telemetry --dont-wait || true
    info "Netdata installed.\n\nLive dashboard: http://$(hostname -I | awk '{print $1}'):19999"
}

do_wizard_reset() {
    ask "Reset welcome wizard?\n\nThe setup wizard will reappear on next browser launch." || return 0
    python3 - <<PY
import json, pathlib
p = pathlib.Path("$SETTINGS")
data = {}
if p.exists():
    try: data = json.loads(p.read_text())
    except Exception: pass
data["first_run"] = True
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(data, indent=2))
print("[installer] first_run set to true")
PY
    info "Welcome wizard reset.\n\nRefresh the browser to start the setup wizard."
}

do_logs() {
    local choice
    choice=$(whiptail --title "$TITLE — Live Logs" --menu "Select log to tail (Ctrl+C to stop):" 16 70 8 \
        dashboard  "Dashboard (port 5004)" \
        weather    "Weather Station (port 5000)" \
        radio      "Internet Radio (port 5003)" \
        config     "Device Config (port 5001)" \
        portal     "Home Portal (port 5002)" \
        xorg       "Xorg display server" \
        chromium   "Chromium kiosk" \
        installer  "Installer log" \
        3>&1 1>&2 2>&3) || return 0

    local log_file=""
    case "$choice" in
        dashboard)  log_file="$LOG_DIR/dashboard.log" ;;
        weather)    log_file="$LOG_DIR/weather.log" ;;
        radio)      log_file="$LOG_DIR/radio.log" ;;
        config)     log_file="$LOG_DIR/config.log" ;;
        portal)     log_file="$LOG_DIR/portal.log" ;;
        xorg)       log_file="$LOG_DIR/xorg.log" ;;
        chromium)   log_file="$LOG_DIR/chromium.log" ;;
        installer)  log_file="$INSTALLER_LOG" ;;
    esac

    if [ -f "$log_file" ]; then
        clear
        echo "=== Tailing $log_file (Ctrl+C to return) ==="
        tail -f "$log_file"
    else
        info "Log file not found: $log_file\nService may not have started yet."
    fi
}

do_status() {
    local status_text=""
    local services=("weather-station" "x-display" "led-monitor")
    for svc in "${services[@]}"; do
        local state active
        state=$(systemctl is-active  "${svc}.service" 2>/dev/null || echo "not-found")
        active=$(systemctl is-enabled "${svc}.service" 2>/dev/null || echo "disabled")
        status_text+="  ${svc}: $state ($active)\n"
    done

    # Check Flask ports
    status_text+="\nPorts:\n"
    for port in 5000 5001 5002 5003 5004; do
        if ss -tlnp 2>/dev/null | grep -q ":$port "; then
            status_text+="  :$port → LISTENING\n"
        else
            status_text+="  :$port → not bound\n"
        fi
    done

    local ip; ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    status_text+="\nDevice IP: ${ip:-unknown}"
    status_text+="\nDashboard: http://${ip:-localhost}:5004"

    whiptail --title "$TITLE — Status" --msgbox "$status_text" 22 68
}

do_update() {
    local src
    src=$(whiptail --title "$TITLE" \
        --inputbox "Path to local git clone (project root):" \
        10 70 "$SOURCE_DEFAULT" 3>&1 1>&2 2>&3) || return 0

    if [ -d "$src/.git" ]; then
        whiptail --title "$TITLE" --infobox "Running git pull in $src ..." 6 50
        git -C "$src" pull --ff-only || true
    fi

    do_deploy_from "$src"
    systemctl restart weather-station.service x-display.service 2>/dev/null || true
    info "Update complete. Services restarted."
}

# Thin wrapper used by do_update to avoid the inputbox again
do_deploy_from() {
    local src="$1"
    mkdir -p "$DEST" "$LOG_DIR"
    rsync -av --delete \
        "$src/apps/"    "$DEST/apps/"    \
        --exclude "__pycache__" --exclude "*.pyc"
    rsync -av "$src/scripts/" "$DEST/scripts/" --exclude "__pycache__"
    chmod +x "$DEST"/scripts/*.sh 2>/dev/null || true
    rsync -av "$src/services/" /etc/systemd/system/ --include "*.service" --exclude "*"
    [ -f "$src/config/99-modesetting.conf" ] && \
        rsync -av "$src/config/99-modesetting.conf" /etc/X11/xorg.conf.d/
    systemctl daemon-reload
}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN MENU LOOP
# ─────────────────────────────────────────────────────────────────────────────
while true; do
    CHOICE=$(whiptail --title "$TITLE" --menu \
        "Select an action  (installer log: $INSTALLER_LOG)" \
        24 72 15 \
        install   "1. Install system packages" \
        venv      "2. Create/update Python venv" \
        deploy    "3. Deploy project files → /opt/orangepi" \
        services  "4. Enable & start services" \
        timezone  "5. Auto-detect timezone & location" \
        wifi      "6. Connect to WiFi" \
        rtlsdr    "7. RTL-SDR / DAB+ driver setup" \
        ha        "8. Install Home Assistant Core (optional)" \
        weewx     "9. Install WeeWX weather station (optional)" \
        netdata   "10. Install Netdata monitor (optional)" \
        wizard    "11. Reset welcome wizard" \
        logs      "12. View live logs" \
        status    "13. Show service & port status" \
        update    "14. git pull + redeploy" \
        quit      "Exit" \
        3>&1 1>&2 2>&3) || exit 0

    case "$CHOICE" in
        install)  do_install  ;;
        venv)     do_venv     ;;
        deploy)   do_deploy   ;;
        services) do_services ;;
        timezone) do_timezone ;;
        wifi)     do_wifi     ;;
        rtlsdr)   do_rtlsdr  ;;
        ha)       do_ha       ;;
        weewx)    do_weewx    ;;
        netdata)  do_netdata  ;;
        wizard)   do_wizard_reset ;;
        logs)     do_logs     ;;
        status)   do_status   ;;
        update)   do_update   ;;
        quit)     echo "[installer] Exiting."; exit 0 ;;
    esac
done
