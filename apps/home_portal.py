#!/usr/bin/env python3
"""Home Portal - Kiosk entry point (Port 5002)
Immediately redirects to the unified Dashboard on port 5004.
Also handles first-boot welcome and settings API for backward compatibility.
"""
from flask import Flask, redirect, jsonify, request
from settings_store import load_settings, save_settings

app = Flask(__name__)


@app.route('/')
def home():
    # Dashboard is the single unified interface
    return redirect('http://localhost:5004', code=302)


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        return jsonify(load_settings())
    data = request.json or {}
    return jsonify(save_settings(data))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)
