
#!/usr/bin/env python3
"""Device Configuration app (Port 5001)
Redirects to unified dashboard. Keeps /api/* routes active (no demo gates).
"""
import re
import logging
from flask import Flask, redirect, request, jsonify
import subprocess
import requests
from settings_store import load_settings, save_settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

_ALLOWED_RESOLUTIONS = {'1024x600', '1280x720', '1920x1080'}


def _valid_timezone(tz: str) -> bool:
    try:
        result = subprocess.run(
            ['timedatectl', 'list-timezones'],
            capture_output=True, text=True, timeout=5
        )
        return tz in result.stdout.splitlines()
    except Exception:
        return bool(re.match(r'^[A-Za-z]+(/[A-Za-z_]+){0,2}$', tz))


def _valid_ssid(ssid: str) -> bool:
    return isinstance(ssid, str) and 1 <= len(ssid) <= 32


def _valid_password(pw: str) -> bool:
    return isinstance(pw, str) and len(pw) <= 63


app = Flask(__name__)


@app.route('/')
def index():
    return redirect('http://localhost:5004', 302)


@app.route('/api/mode')
def api_mode():
    s = load_settings()
    return jsonify({'hardware_control': True, 'timezone': s.get('timezone', 'UTC')})


@app.route('/api/wifi/connect', methods=['POST'])
def wifi_connect():
    data = request.json or {}
    ssid = data.get('ssid', '')
    password = data.get('password', '')
    if not _valid_ssid(ssid):
        return jsonify({'message': 'Invalid SSID'})
    if not _valid_password(password):
        return jsonify({'message': 'Invalid password'})
    try:
        result = subprocess.run(
            ['nmcli', '--ask', 'device', 'wifi', 'connect', ssid],
            input=f'{password}\n',
            timeout=20, capture_output=True, text=True
        )
        msg = result.stdout.strip() or f'Connecting to {ssid}...'
        return jsonify({'message': msg})
    except subprocess.TimeoutExpired:
        return jsonify({'message': 'Timeout — check SSID/password'})
    except Exception:
        log.exception('wifi_connect failed for ssid=%s', ssid)
        return jsonify({'message': 'Connection error'})


@app.route('/api/wifi/scan')
def wifi_scan():
    try:
        out = subprocess.check_output(
            ['nmcli', '-t', '-f', 'SSID,SIGNAL', 'device', 'wifi', 'list'],
            timeout=10, text=True
        )
        networks = []
        for line in out.splitlines():
            parts = line.split(':')
            ssid = parts[0].strip()
            if ssid and ssid != '--':
                networks.append(ssid)
        return jsonify({'networks': networks[:12]})
    except Exception:
        log.exception('wifi_scan failed')
        return jsonify({'networks': [], 'message': 'Scan failed'})


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
    try:
        subprocess.run(['amixer', 'set', 'Master', f'{vol}%'], capture_output=True, timeout=3)
        return jsonify({'ok': True, 'volume': vol})
    except Exception:
        log.exception('set_volume failed')
        return jsonify({'ok': False, 'message': 'Volume error'})


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
        return jsonify({'message': 'Invalid resolution'})
    try:
        w, h = res.split('x')
        subprocess.run(
            ['xrandr', '--output', 'HDMI-1', '--mode', f'{w}x{h}'],
            capture_output=True, timeout=5
        )
        return jsonify({'message': f'Resolution set to {res}'})
    except Exception:
        log.exception('set_resolution failed res=%s', res)
        return jsonify({'message': 'Display error'})


@app.route('/api/display/brightness', methods=['POST'])
def set_brightness():
    try:
        val = max(10, min(100, int((request.json or {}).get('brightness', 80))))
    except (TypeError, ValueError):
        val = 80
    level = round(val / 100, 2)
    try:
        subprocess.run(
            ['xrandr', '--output', 'HDMI-1', '--brightness', str(level)],
            capture_output=True, timeout=5
        )
        return jsonify({'ok': True})
    except Exception:
        log.exception('set_brightness failed')
        return jsonify({'ok': False, 'message': 'Display error'})


@app.route('/api/system/timezone', methods=['POST'])
def set_timezone():
    tz = (request.json or {}).get('timezone', '')
    if not _valid_timezone(tz):
        return jsonify({'message': 'Invalid timezone'})
    try:
        subprocess.run(['timedatectl', 'set-timezone', tz], check=True, timeout=5)
        save_settings({'timezone': tz})
        return jsonify({'message': f'Timezone set to {tz}'})
    except Exception:
        log.exception('set_timezone failed tz=%s', tz)
        return jsonify({'message': 'Timezone error'})


@app.route('/api/system/auto-timezone', methods=['POST'])
def auto_timezone():
    try:
        j = requests.get('https://ip-api.com/json', timeout=5).json()
        tz = j.get('timezone', 'UTC')
        lat = j.get('lat')
        lon = j.get('lon')
        if not _valid_timezone(tz):
            return jsonify({'message': 'Auto-detect returned invalid timezone'})
        save_settings({'timezone': tz, 'latitude': lat, 'longitude': lon})
        subprocess.run(['timedatectl', 'set-timezone', tz], timeout=5)
        return jsonify({'timezone': tz, 'message': f'Timezone set to {tz}'})
    except Exception:
        log.exception('auto_timezone failed')
        return jsonify({'message': 'Auto-detect failed'})


@app.route('/api/system/reboot', methods=['POST'])
def reboot():
    log.info('reboot requested by %s', request.remote_addr)
    subprocess.Popen(['shutdown', '-r', 'now'])
    return jsonify({'ok': True})


@app.route('/api/system/shutdown', methods=['POST'])
def shutdown():
    log.info('shutdown requested by %s', request.remote_addr)
    subprocess.Popen(['shutdown', '-h', 'now'])
    return jsonify({'ok': True})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
