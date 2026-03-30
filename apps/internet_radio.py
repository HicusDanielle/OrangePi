#!/usr/bin/env python3
"""Internet Radio streaming app (Port 5003)
Redirects to unified dashboard. Keeps /api/* routes for backward compatibility.
"""
import logging
from flask import Flask, redirect, request, jsonify
import subprocess

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)

STATIONS = [
    {"name": "France Inter", "url": "http://direct.franceinter.fr/live/franceinter-midfi.mp3"},
    {"name": "NRJ",          "url": "http://stream.nrj.fr/nrj.m3u8"},
    {"name": "Skyrock",      "url": "http://stream.skyrock.fr/skyrock.m3u8"},
    {"name": "Europe 1",     "url": "http://stream.europe1.fr/europe1.m3u8"},
    {"name": "FIP",          "url": "http://direct.fip.fr/live/fip-midfi.mp3"},
    {"name": "BBC World",    "url": "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service"},
    {"name": "Jazz FM",      "url": "http://media-ice.musicradio.com/JazzFMMP3"},
]

_ALLOWED_URLS = {s['url'] for s in STATIONS}


@app.route('/')
def index():
    return redirect('http://localhost:5004', 302)


@app.route('/api/stations')
def api_stations():
    return jsonify(STATIONS)


@app.route('/api/play', methods=['POST'])
def play():
    url = (request.json or {}).get('url', '')
    if url not in _ALLOWED_URLS:
        log.warning('play: rejected URL from %s', request.remote_addr)
        return jsonify({'ok': False, 'message': 'Invalid station'})
    subprocess.run(['pkill', '-f', 'mpv'], stderr=subprocess.DEVNULL)
    subprocess.Popen(
        ['mpv', '--no-video', '--quiet', '--volume=70', url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return jsonify({'ok': True, 'message': 'Playing'})


@app.route('/api/stop', methods=['POST'])
def stop():
    subprocess.run(['pkill', '-f', 'mpv'], stderr=subprocess.DEVNULL)
    return jsonify({'ok': True, 'message': 'Stopped'})


@app.route('/api/volume', methods=['POST'])
def volume():
    try:
        vol = max(0, min(100, int((request.json or {}).get('volume', 70))))
    except (TypeError, ValueError):
        vol = 70
    subprocess.run(['amixer', 'set', 'Master', f'{vol}%'], capture_output=True)
    return jsonify({'ok': True, 'volume': vol})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)
