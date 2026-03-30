# Orange Pi Weather Station - Project Setup Guide

## Device Info

| Item | Value |
|------|-------|
| Device | Orange Pi PC2 |
| IP (LAN) | 192.168.1.93 |
| OS | Armbian Linux 6.12.74 |
| CPU | Allwinner H5 (quad-core ARM Cortex-A53) |
| RAM | 1 GB DDR3 |
| Storage | 15 GB eMMC |
| Display | 7" HDMI touchscreen 1024x600 (DWE HDMI) |
| Touchscreen | wch.cn USB2IIC_CTP_CONTROL (1a86:e5e3) on /dev/input/event5 |
| SSH Key | `C:\Users\think\.ssh\orangepi_key` |
| Browser | Chromium 146 (kiosk mode) |
| Bootloader | U-Boot flashed to SPI NOR flash (mtd0) |

---

## Project Structure

```
OrangePI/
├── apps/                        # Flask web applications
│   ├── home_portal.py           # Port 5002 - Landing page kiosk
│   ├── web_app.py               # Port 5000 - Weather + DAB+ Radio
│   ├── device_config.py         # Port 5001 - Device settings
│   ├── internet_radio.py        # Port 5003 - Internet radio
│   └── dashboard.py             # Port 5004 - Control dashboard
├── scripts/
│   ├── deploy.sh                # One-command deploy to device
│   ├── start_display.sh         # Start Flask + Xorg + Chromium kiosk
│   ├── start_all.sh             # Start Flask apps only
│   └── browser_launcher.sh      # Legacy browser launcher
├── services/
│   └── weather-station.service  # systemd: single service for everything
├── config/
│   ├── 99-modesetting.conf      # Xorg KMS/DRM modesetting 1024x600
│   ├── 99-touchscreen.rules     # udev rule for wch.cn touchscreen
│   └── xinitrc                  # X startup script (legacy)
└── docs/
    └── SETUP.md                 # This file
```

---

## Deploy

```bash
cd "C:/Users/think/Downloads/VS_COde_Project/OrangePI"
bash scripts/deploy.sh 192.168.1.93 root
```

### Install from the Pi via armbian-config (interactive)
1. Copy the installer to armbian-config user scripts:
   ```bash
   sudo cp /opt/weather_station/scripts/armbian_orangepi_installer.sh /usr/lib/armbian-config/userpatches/
   ```
2. Run `sudo armbian-config` → Softy → User provided scripts → `armbian_orangepi_installer.sh`.
3. Menu options let you install packages, deploy/refresh files, enable services, auto-detect timezone/locale, or reset the welcome wizard.

### Pull and install directly from Git (for armbian-config user menu)
To fetch the latest code from GitHub without a local copy:
```bash
sudo -i
cd /opt
rm -rf weather_station
git clone https://github.com/HicusDanielle/OrangePi weather_station
cd weather_station/scripts
./armbian_orangepi_installer.sh   # then choose deploy/services/timezone
```
Or add this one-liner as a user script entry in `/usr/lib/armbian-config/userpatches`:
```bash
#!/bin/bash
set -e
cd /opt
rm -rf weather_station
git clone https://github.com/HicusDanielle/OrangePi weather_station
cd weather_station/scripts
./armbian_orangepi_installer.sh
```

---

## Web Interfaces

| App | URL |
|-----|-----|
| Home Portal (kiosk default) | http://192.168.1.93:5002 |
| Weather Station | http://192.168.1.93:5000 |
| Device Config | http://192.168.1.93:5001 |
| Internet Radio | http://192.168.1.93:5003 |
| Dashboard | http://192.168.1.93:5004 |

---

## Boot Sequence

1. U-Boot loads from SPI NOR flash (mtd0) — faster, eMMC-independent
2. Kernel boots Armbian (~5s kernel, ~9s userspace = **~14s total**)
3. systemd starts `weather-station.service`
4. `start_display.sh` launches:
   - Flask apps (home_portal, web_app, device_config) on ports 5002/5000/5001
   - `Xorg :0` using modesetting driver (DRM/KMS → HDMI out)
   - `xrandr` sets 1024x600 @ 59.8Hz
   - Chromium in kiosk mode → `http://localhost:5002`
5. Touchscreen (event5) auto-detected by Xorg libinput

---

## SSH Commands

```bash
# Connect
ssh -i ~/.ssh/orangepi_key root@192.168.1.93

# Service management
systemctl status weather-station.service
systemctl restart weather-station.service

# Logs
journalctl -u weather-station.service -f
cat /tmp/chromium.log
cat /tmp/xorg.log
cat /tmp/weather.log

# Quick reboot
ssh -i ~/.ssh/orangepi_key root@192.168.1.93 'reboot'
```

---

## Boot Optimizations Applied

| Change | Saving |
|--------|--------|
| U-Boot flashed to SPI NOR | Faster boot, eMMC-independent |
| serial-getty@ttyS0 masked | ~17s saved |
| networkd-wait-online masked | ~4.5s saved |
| 7 services/timers disabled | ~5s saved |
| DTB overlays stripped (7 removed) | Faster kernel init |
| Display 1024x600 (was 1920x1080) | Less framebuffer RAM |
| **Total: 1m36s → 14s** | **6.8x faster** |

---

## Display Stack

- **Driver**: modesetting (KMS/DRM via sun4i-drm)
- **Xorg config**: `/etc/X11/xorg.conf.d/99-modesetting.conf`
- **Browser**: Chromium 146 (`--kiosk --no-sandbox --touch-events=enabled`)
- **Resolution**: 1024x600 @ 59.82Hz (native from EDID)

## Touchscreen

- **Device**: wch.cn USB2IIC_CTP_CONTROL
- **USB ID**: 1a86:e5e3
- **Input**: /dev/input/event5
- **Driver**: libinput (hid-multitouch kernel module)
- **udev rule**: `/etc/udev/rules.d/99-touchscreen.rules`
- **Calibration**: Identity matrix (1:1, no rotation needed)

---

## Customization

### Change Weather Location
Edit [apps/web_app.py](../apps/web_app.py) and [apps/dashboard.py](../apps/dashboard.py):
```python
LATITUDE = 51.5074
LONGITUDE = -0.1278
```

### Add Internet Radio Stations
Edit [apps/internet_radio.py](../apps/internet_radio.py):
```python
STATIONS = [
    {"name": "My Station", "url": "http://stream.example.com/radio.mp3"},
]
```

### Touchscreen Calibration (if inverted/offset)
SSH in and run:
```bash
# Test touch input
DISPLAY=:0 xinput test-xi2
# Adjust matrix: xinput set-prop "wch.cn USB2IIC_CTP_CONTROL" "Coordinate Transformation Matrix" ...
# Common fix for inverted Y: "1 0 0 0 -1 1 0 0 1"
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Black screen | `systemctl restart weather-station.service` |
| Chromium not starting | `cat /tmp/chromium.log` |
| Wrong resolution | `DISPLAY=:0 xrandr --output HDMI-1 --mode 1024x600` |
| Touchscreen not working | `udevadm trigger && DISPLAY=:0 xinput list` |
| Flask app down | `curl http://localhost:5002` — check `/tmp/portal.log` |
| SPI backup | `/root/spi_mtd0_backup.bin`, `/root/spi_mtd1_backup.bin` |
