#!/usr/bin/env python3
"""Device Configuration app (Port 5001)
Board-agnostic: Orange Pi, Raspberry Pi, Odroid, Intel Stick
Redirects / to unified dashboard. Keeps /api/* routes active.
"""
import os
import logging
from flask import Flask, redirect, request, jsonify
import subprocess
import requests
from settings_store import load_settings, save_settings, valid_timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

_ALLOWED_RESOLUTIONS = {'1024x600', '1280x720', '1920x1080'}

# ── Board-agnostic helpers ────────────────────────────────────────────────────

def _display_output() -> str:
    """Return the currently connected xrandr output name, e.g. HDMI-1, DSI-1, VGA-1."""
    # Fastest: check file written by start_display.sh
    try:
        val = open('/run/orangepi_display_output').read().strip()
        if val:
            return val
    except OSError:
        pass
    # Probe live
    try:
        out = subprocess.check_output(
            ['xrandr', '--query'], timeout=3,
            env={**os.environ, 'DISPLAY': ':0'}
        ).decode()
        for line in out.splitlines():
            if ' connected' in line:
                return line.split()[0]
    except Exception:
        pass
    return 'HDMI-1'


def _audio_control() -> str:
    """Return the first usable amixer simple control name."""
    # Honour env var set by hw_detect.sh if available
    env_ctl = os.environ.get('HW_AUDIO_CTL', '')
    if env_ctl:
        return env_ctl
    for ctl in ('Master', 'PCM', 'Speaker', 'Headphone', 'Digital'):
        try:
            r = subprocess.run(
                ['amixer', 'sget', ctl],
                capture_output=True, timeout=2
            )
            if r.returncode == 0:
                return ctl
        except Exception:
            pass
    return 'Master'


def _valid_ssid(ssid: str) -> bool:
    return isinstance(ssid, str) and 1 <= len(ssid) <= 32

def _valid_password(pw: str) -> bool:
    return isinstance(pw, str) and len(pw) <= 63

# ── Board identity ────────────────────────────────────────────────────────────

def _board_info() -> dict:
    model = 'Unknown'
    for path in ('/proc/device-tree/model',
                 '/sys/firmware/devicetree/base/model'):
        try:
            model = open(path, 'rb').read().rstrip(b'\x00').decode(errors='replace')
            break
        except OSError:
            pass
    arch = subprocess.check_output(['uname', '-m'], timeout=2).decode().strip()
    return {'model': model, 'arch': arch}


app = Flask(__name__)


@app.route('/')
def index():
    return redirect('http://localhost:5004', 302)


@app.route('/api/mode')
def api_mode():
    s = load_settings()
    return jsonify({'hardware_control': True, 'timezone': s.get('timezone', 'UTC')})


@app.route('/api/hw/info')
def hw_info():
    """Hardware identity — used by the dashboard to show board name."""
    info = _board_info()
    info['audio_ctl'] = _audio_control()
    info['display_output'] = _display_output()
    return jsonify(info)


@app.route('/api/wifi/connect', methods=['POST'])
def wifi_connect():
    data = request.json or {}
    ssid = data.get('ssid', '')
    password = data.get('password', '')
    if not _valid_ssid(ssid):
        return jsonify({'message': 'Invalid SSID'}), 400
    if not _valid_password(password):
        return jsonify({'message': 'Invalid password'}), 400
    try:
        result = subprocess.run(
            ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid],
            input=f'{password}\n',
            timeout=25, capture_output=True, text=True
        )
        msg = result.stdout.strip() or f'Connecting to {ssid}...'
        return jsonify({'message': msg})
    except subprocess.TimeoutExpired:
        return jsonify({'message': 'Timeout — check SSID/password'}), 504
    except Exception:
        log.exception('wifi_connect failed ssid=%s', ssid)
        return jsonify({'message': 'Connection error'}), 500


@app.route('/api/wifi/scan')
def wifi_scan():
    try:
        out = subprocess.check_output(
            ['nmcli', '-t', '-f', 'SSID', 'device', 'wifi', 'list'],
            timeout=12, text=True
        )
        seen = {}
        networks = []
        for line in out.splitlines():
            ssid = line.strip()
            if ssid and ssid != '--' and ssid not in seen:
                seen[ssid] = True
                networks.append(ssid)
        return jsonify({'networks': networks[:15]})
    except Exception:
        log.exception('wifi_scan failed')
        return jsonify({'networks': [], 'message': 'Scan failed'}), 500


@app.route('/api/system/ip')
def get_ip():
    try:
        out = subprocess.check_output(['hostname', '-I'], timeout=3).decode().strip()
        return jsonify({'ip': out.split()[0] if out else 'Unknown'})
    except Exception:
        return jsonify({'ip': 'Unknown'})


@app.route('/api/audio/volume', methods=['POST'])
def set_volume():
    try:
        vol = max(0, min(100, int((request.json or {}).get('volume', 70))))
    except (TypeError, ValueError):
        vol = 70
    ctl = _audio_control()
    try:
        subprocess.run(['amixer', 'set', ctl, f'{vol}%'], capture_output=True, timeout=3)
        return jsonify({'ok': True, 'volume': vol, 'control': ctl})
    except Exception:
        log.exception('set_volume failed ctl=%s', ctl)
        return jsonify({'ok': False, 'message': 'Volume error'}), 500


@app.route('/api/audio/test', methods=['POST'])
def test_audio():
    subprocess.Popen(
        ['speaker-test', '-t', 'sine', '-f', '440', '-l', '1'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return jsonify({'ok': True, 'message': 'Playing 440 Hz test tone'})


@app.route('/api/display/resolution', methods=['POST'])
def set_resolution():
    res = (request.json or {}).get('resolution', '')
    if res not in _ALLOWED_RESOLUTIONS:
        return jsonify({'message': 'Invalid resolution'}), 400
    w, h = res.split('x')
    output = _display_output()
    try:
        subprocess.run(
            ['xrandr', '--output', output, '--mode', f'{w}x{h}'],
            capture_output=True, timeout=5,
            env={**os.environ, 'DISPLAY': ':0'}
        )
        return jsonify({'message': f'Resolution set to {res} on {output}'})
    except Exception:
        log.exception('set_resolution failed res=%s output=%s', res, output)
        return jsonify({'message': 'Display error'}), 500


@app.route('/api/display/brightness', methods=['POST'])
def set_brightness():
    try:
        val = max(10, min(100, int((request.json or {}).get('brightness', 80))))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': 'Invalid value'}), 400
    level = round(val / 100, 2)
    output = _display_output()
    try:
        subprocess.run(
            ['xrandr', '--output', output, '--brightness', str(level)],
            capture_output=True, timeout=5,
            env={**os.environ, 'DISPLAY': ':0'}
        )
        return jsonify({'ok': True})
    except Exception:
        log.exception('set_brightness failed output=%s', output)
        return jsonify({'ok': False, 'message': 'Display error'}), 500


@app.route('/api/system/timezone', methods=['POST'])
def set_timezone():
    tz = (request.json or {}).get('timezone', '')
    if not valid_timezone(tz):
        return jsonify({'message': 'Invalid timezone'}), 400
    try:
        subprocess.run(['sudo', 'timedatectl', 'set-timezone', tz], check=True, timeout=5)
        save_settings({'timezone': tz})
        return jsonify({'message': f'Timezone set to {tz}'})
    except Exception:
        log.exception('set_timezone failed tz=%s', tz)
        return jsonify({'message': 'Timezone error'}), 500


@app.route('/api/system/auto-timezone', methods=['POST'])
def auto_timezone():
    try:
        j = requests.get('https://ip-api.com/json', timeout=6).json()
        tz  = j.get('timezone', 'UTC')
        lat = j.get('lat')
        lon = j.get('lon')
        if not valid_timezone(tz):
            return jsonify({'message': 'Auto-detect returned invalid timezone'}), 422
        save_settings({'timezone': tz, 'latitude': lat, 'longitude': lon})
        subprocess.run(['sudo', 'timedatectl', 'set-timezone', tz], timeout=5)
        return jsonify({'timezone': tz, 'message': f'Timezone set to {tz}'})
    except Exception:
        log.exception('auto_timezone failed')
        return jsonify({'message': 'Auto-detect failed'}), 500


@app.route('/api/system/reboot', methods=['POST'])
def reboot():
    log.warning('Reboot requested by %s', request.remote_addr)
    subprocess.Popen(['sudo', 'shutdown', '-r', 'now'])
    return jsonify({'ok': True})


@app.route('/api/system/shutdown', methods=['POST'])
def shutdown():
    log.warning('Shutdown requested by %s', request.remote_addr)
    subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
    return jsonify({'ok': True})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
