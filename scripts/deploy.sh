#!/bin/bash
###############################################################################
# deploy.sh — Push project to Orange Pi over SSH
#
# Usage:
#   bash scripts/deploy.sh                      # default: 192.168.1.93 root
#   bash scripts/deploy.sh 192.168.1.50 root
#   bash scripts/deploy.sh 192.168.1.50 orangepi
#
# SSH key: ~/.ssh/orangepi_key  (override with ORANGEPI_SSH_KEY env var)
#
# Loads optional .env from project root for HOST/USER overrides:
#   ORANGEPI_HOST=192.168.1.93
#   ORANGEPI_USER=root
#   ORANGEPI_SSH_KEY=~/.ssh/orangepi_key
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Load .env if present (never committed) ────────────────────────────────────
if [ -f "$PROJECT_DIR/.env" ]; then
    # shellcheck disable=SC1091
    set -a; source "$PROJECT_DIR/.env"; set +a
fi

# ── Config (args override env which overrides defaults) ───────────────────────
HOST="${1:-${ORANGEPI_HOST:-192.168.1.93}}"
USER="${2:-${ORANGEPI_USER:-root}}"
KEY="${ORANGEPI_SSH_KEY:-$HOME/.ssh/orangepi_key}"
DEST="/opt/orangepi"

# ── SSH helpers ───────────────────────────────────────────────────────────────
SSH_OPTS="-i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes"
SSH="ssh $SSH_OPTS"
SCP="scp $SSH_OPTS"
RSYNC="rsync -az --delete -e \"ssh $SSH_OPTS\""

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Orange Pi Control Center — Deploy Script    ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Target : $USER@$HOST"
echo "║  Dest   : $DEST"
echo "║  Key    : $KEY"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Verify SSH key exists ─────────────────────────────────────────────────────
if [ ! -f "$KEY" ]; then
    echo "ERROR: SSH key not found: $KEY"
    echo ""
    echo "  Generate one:   ssh-keygen -t ed25519 -f ~/.ssh/orangepi_key"
    echo "  Copy to device: ssh-copy-id -i ~/.ssh/orangepi_key.pub $USER@$HOST"
    exit 1
fi

# ── Test connectivity ─────────────────────────────────────────────────────────
echo "Testing connection to $USER@$HOST ..."
if ! $SSH "$USER@$HOST" "echo OK" &>/dev/null; then
    echo "ERROR: Cannot reach $USER@$HOST"
    echo "  Check: device is on, SSH is running, key is authorized."
    exit 1
fi
echo "Connection OK."
echo ""

# ── Create remote directory structure ────────────────────────────────────────
echo "Creating remote directories..."
$SSH "$USER@$HOST" "
    mkdir -p $DEST/apps $DEST/scripts $DEST/config
    mkdir -p /var/log/orangepi
    mkdir -p /etc/X11/xorg.conf.d
    mkdir -p /etc/udev/rules.d
    mkdir -p /etc/systemd/system
"

# ── Deploy: apps ─────────────────────────────────────────────────────────────
echo "Deploying apps..."
for f in home_portal.py web_app.py device_config.py internet_radio.py dashboard.py settings_store.py; do
    $SCP "$PROJECT_DIR/apps/$f" "$USER@$HOST:$DEST/apps/$f"
done
echo "  ✓ apps"

# ── Deploy: scripts ───────────────────────────────────────────────────────────
echo "Deploying scripts..."
for f in start_all.sh start_display.sh led_monitor.sh rtlsdr_setup.sh armbian_orangepi_installer.sh; do
    $SCP "$PROJECT_DIR/scripts/$f" "$USER@$HOST:$DEST/scripts/$f"
done
$SSH "$USER@$HOST" "chmod +x $DEST/scripts/*.sh"
echo "  ✓ scripts"

# ── Deploy: systemd services ──────────────────────────────────────────────────
echo "Deploying services..."
for f in weather-station.service x-display.service led-monitor.service; do
    $SCP "$PROJECT_DIR/services/$f" "$USER@$HOST:/etc/systemd/system/$f"
done
echo "  ✓ services"

# ── Deploy: Xorg config ───────────────────────────────────────────────────────
echo "Deploying Xorg config..."
$SCP "$PROJECT_DIR/config/99-modesetting.conf" \
    "$USER@$HOST:/etc/X11/xorg.conf.d/99-modesetting.conf"
# Remove stale fbdev config
$SSH "$USER@$HOST" "rm -f /etc/X11/xorg.conf.d/99-fbdev.conf"
echo "  ✓ xorg config"

# ── Deploy: udev touchscreen rules ───────────────────────────────────────────
echo "Deploying udev rules..."
$SCP "$PROJECT_DIR/config/99-touchscreen.rules" \
    "$USER@$HOST:/etc/udev/rules.d/99-touchscreen.rules"
$SSH "$USER@$HOST" "udevadm control --reload-rules && udevadm trigger"
echo "  ✓ udev rules"

# ── Deploy: user_settings.json — only seed if not present on device ───────────
echo "Checking user_settings.json..."
if ! $SSH "$USER@$HOST" "test -f $DEST/config/user_settings.json"; then
    $SCP "$PROJECT_DIR/config/user_settings.json.example" \
        "$USER@$HOST:$DEST/config/user_settings.json"
    echo "  ✓ user_settings.json seeded (first deploy)"
else
    echo "  ↷ user_settings.json already exists — kept (no overwrite)"
fi

# ── Systemd: reload, enable, restart ─────────────────────────────────────────
echo "Reloading systemd..."
$SSH "$USER@$HOST" "
    systemctl daemon-reload
    systemctl enable weather-station.service x-display.service led-monitor.service 2>/dev/null || true
    systemctl restart weather-station.service || true
    systemctl restart x-display.service       || true
    systemctl restart led-monitor.service     || true
"
echo "  ✓ services enabled and restarted"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Deploy complete!                            ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Dashboard (main): http://$HOST:5004"
echo "║  Weather API:      http://$HOST:5000"
echo "║  Device Config:    http://$HOST:5001"
echo "║  Home Portal:      http://$HOST:5002"
echo "║  Internet Radio:   http://$HOST:5003"
echo "╠══════════════════════════════════════════════╣"
echo "║  Logs:  ssh $USER@$HOST 'tail -f /var/log/orangepi/dashboard.log'"
echo "║  Rerun: bash scripts/deploy.sh $HOST $USER"
echo "╚══════════════════════════════════════════════╝"
echo ""
