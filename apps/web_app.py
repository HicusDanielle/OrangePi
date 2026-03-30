#!/usr/bin/env python3
"""Weather Station + System info app (Port 5000)
Board-agnostic thermal probing: Orange Pi, Raspberry Pi, Odroid, Intel Stick.
"""
import glob
import logging
from flask import Flask, redirect, jsonify
import subprocess
import requests
from settings_store import load_settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)


def _coords():
    s = load_settings()
    return float(s.get('latitude', 51.5074)), float(s.get('longitude', -0.1278))


def _read_temp() -> str:
    """Read CPU temperature from the first readable thermal zone."""
    for path in sorted(glob.glob('/sys/class/thermal/thermal_zone*/temp')):
        try:
            val = int(open(path).read().strip())
            # Ignore bogus/stub sensors that always read 0 or negative
            if val > 1000:
                return f"{val // 1000}°C"
        except (OSError, ValueError):
            pass
    return 'N/A'


@app.route('/')
def index():
    return redirect('http://localhost:5004', 302)


@app.route('/api/weather')
def weather():
    lat, lon = _coords()
    try:
        url = (
            f'https://api.open-meteo.com/v1/forecast'
            f'?latitude={lat}&longitude={lon}'
            f'&current=temperature_2m,relative_humidity_2m,pressure_msl,'
            f'wind_speed_10m,weathercode,apparent_temperature'
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        d = r.json()['current']
        code = d.get('weathercode', 0)
        icons = {
            0:'☀️', 1:'🌤️', 2:'⛅', 3:'☁️',
            45:'🌫️', 48:'🌫️',
            51:'🌦️', 53:'🌦️', 55:'🌧️',
            61:'🌧️', 63:'🌧️', 65:'🌧️',
            71:'❄️', 73:'❄️', 75:'❄️', 77:'🌨️',
            80:'🌦️', 81:'🌧️', 82:'🌧️',
            85:'🌨️', 86:'🌨️',
            95:'⛈️', 96:'⛈️', 99:'⛈️',
        }
        return jsonify({
            'temp':       f"{d['temperature_2m']}°C",
            'feels_like': f"{d.get('apparent_temperature', '--')}°C",
            'humidity':   f"{d['relative_humidity_2m']}%",
            'pressure':   f"{int(d['pressure_msl'])} hPa",
            'wind':       f"{d['wind_speed_10m']} m/s",
            'icon':       icons.get(code, '🌡️'),
        })
    except Exception:
        log.exception('weather fetch failed')
        return jsonify({
            'error': 'Unavailable',
            'temp': '--', 'humidity': '--', 'pressure': '--',
            'wind': '--', 'icon': '🌡️',
        })


@app.route('/api/system')
def system():
    try:
        uptime   = subprocess.check_output(['uptime', '-p'], timeout=3).decode().strip()
        mem_rows = subprocess.check_output(['free', '-h'], timeout=3).decode().split('\n')
        mem_cols = mem_rows[1].split() if len(mem_rows) > 1 else []
        mem      = f"{mem_cols[2]} / {mem_cols[1]}" if len(mem_cols) > 2 else '--'
        disk     = subprocess.check_output(['df', '-h', '/'], timeout=3).decode().split('\n')[1].split()[4]
        return jsonify({
            'temp':   _read_temp(),
            'memory': mem,
            'uptime': uptime,
            'disk':   disk,
        })
    except Exception:
        log.exception('system info failed')
        return jsonify({'temp': 'N/A', 'memory': 'N/A', 'uptime': 'N/A', 'disk': 'N/A'})


@app.route('/api/dab/play', methods=['POST'])
def dab_play():
    subprocess.run(['pkill', '-f', 'mpv'], stderr=subprocess.DEVNULL)
    return jsonify({'ok': True, 'message': 'DAB+ play triggered'})


@app.route('/api/dab/stop', methods=['POST'])
def dab_stop():
    subprocess.run(['pkill', '-f', 'mpv'], stderr=subprocess.DEVNULL)
    return jsonify({'ok': True, 'message': 'Stopped'})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
