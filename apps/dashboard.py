#!/usr/bin/env python3
"""Control Dashboard — Unified SPA (Port 5004)
• Sidebar + swipe/back navigation with smooth transitions
• First-run welcome wizard (4 steps)
• Settings panel with Restart Setup button
• Dynamic timezone list from timedatectl
• 10-minute weather cache (avoids hammering Open-Meteo)
• All hardware calls active (no demo gates)
"""
import subprocess
import logging
import time
import threading
import requests as req
from flask import Flask, jsonify, request
from settings_store import (
    load_settings, save_settings, get_timezones, valid_timezone
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Station list (single source of truth) ────────────────────────────────────
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
_ALLOWED_RESOLUTIONS = {'1024x600', '1280x720', '1920x1080'}

# ── Validators ────────────────────────────────────────────────────────────────
def _valid_ssid(ssid: str) -> bool:
    return isinstance(ssid, str) and 1 <= len(ssid) <= 32

def _valid_password(pw: str) -> bool:
    return isinstance(pw, str) and len(pw) <= 63

def _safe_vol(raw) -> int:
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return 70

# ── Weather cache (10-minute TTL) ─────────────────────────────────────────────
_WX_CACHE: dict = {}
_WX_LOCK = threading.Lock()
_WX_TTL = 600  # seconds

WMO_ICONS = {
    0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️',
    45: '🌫️', 48: '🌫️',
    51: '🌦️', 53: '🌦️', 55: '🌧️',
    61: '🌧️', 63: '🌧️', 65: '🌧️',
    71: '❄️', 73: '❄️', 75: '❄️',
    77: '🌨️',
    80: '🌦️', 81: '🌧️', 82: '🌧️',
    85: '🌨️', 86: '🌨️',
    95: '⛈️', 96: '⛈️', 99: '⛈️',
}

def weather_data(lat: float, lon: float) -> dict:
    cache_key = f'{round(lat,2)},{round(lon,2)}'
    with _WX_LOCK:
        cached = _WX_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached['ts']) < _WX_TTL:
            return cached['data']
    try:
        url = (
            f'https://api.open-meteo.com/v1/forecast'
            f'?latitude={lat}&longitude={lon}'
            f'&current=temperature_2m,relative_humidity_2m,pressure_msl,'
            f'wind_speed_10m,weathercode,apparent_temperature'
        )
        r = req.get(url, timeout=8)
        r.raise_for_status()
        d = r.json()['current']
        code = d.get('weathercode', 0)
        data = {
            'temp':      f"{d['temperature_2m']}°C",
            'feels':     f"{d.get('apparent_temperature', '--')}°C",
            'humidity':  f"{d['relative_humidity_2m']}%",
            'pressure':  f"{int(d['pressure_msl'])} hPa",
            'wind':      f"{d['wind_speed_10m']} m/s",
            'icon':      WMO_ICONS.get(code, '🌡️'),
            'ok':        True,
        }
    except Exception:
        log.exception('weather_data fetch failed lat=%s lon=%s', lat, lon)
        data = {
            'temp': '--', 'feels': '--', 'humidity': '--',
            'pressure': '--', 'wind': '--', 'icon': '🌡️', 'ok': False,
        }
    with _WX_LOCK:
        _WX_CACHE[cache_key] = {'ts': time.monotonic(), 'data': data}
    return data

# ── System helpers ────────────────────────────────────────────────────────────
def sys_temp() -> str:
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return f"{int(f.read()) // 1000}°C"
    except Exception:
        return 'N/A'

def sys_uptime() -> str:
    try:
        return subprocess.check_output(['uptime', '-p'], timeout=3).decode().strip()
    except Exception:
        return 'N/A'

def sys_mem() -> str:
    try:
        lines = subprocess.check_output(['free', '-h'], timeout=3).decode().split('\n')
        parts = lines[1].split()
        return f"{parts[2]} / {parts[1]}" if len(parts) > 2 else '--'
    except Exception:
        return 'N/A'

def sys_disk() -> str:
    try:
        return subprocess.check_output(['df', '-h', '/'], timeout=3).decode().split('\n')[1].split()[4]
    except Exception:
        return 'N/A'

def sys_ip() -> str:
    try:
        out = subprocess.check_output(['hostname', '-I'], timeout=3).decode().strip()
        return out.split()[0] if out else 'Unknown'
    except Exception:
        return 'Unknown'

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=1024, height=600, initial-scale=1.0, user-scalable=no">
  <title>Orange Pi — Control Center</title>
  <style>
    *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
    html, body {
      width:1024px; height:600px; overflow:hidden;
      font-family:'Segoe UI',system-ui,Arial,sans-serif;
      background:radial-gradient(135% 120% at 15% 10%,#0e1628 0%,#080e1c 50%,#030810 100%);
      color:#e2e8f0; font-size:13px;
    }

    /* ── Layout ── */
    .shell { display:flex; width:1024px; height:600px; }

    /* ── Sidebar ── */
    .sidebar {
      width:185px; flex-shrink:0;
      background:linear-gradient(180deg,rgba(15,23,42,0.95),rgba(8,14,28,0.97));
      border-right:1px solid rgba(255,255,255,0.07);
      display:flex; flex-direction:column;
      padding:12px 9px 10px; gap:3px;
    }
    .sidebar-logo {
      text-align:center; font-size:14px; font-weight:700;
      padding:9px 8px; margin-bottom:6px;
      background:linear-gradient(135deg,rgba(34,197,94,0.15),rgba(16,185,129,0.08));
      border:1px solid rgba(34,197,94,0.25);
      border-radius:10px; letter-spacing:.3px; color:#4ade80;
    }
    .sidebar-logo small {
      display:block; font-size:10px; font-weight:400;
      color:#64748b; margin-top:1px; letter-spacing:.4px;
    }
    .nav-btn {
      display:flex; align-items:center; gap:8px;
      padding:9px 11px; border-radius:8px;
      background:transparent; border:1px solid transparent;
      color:#94a3b8; cursor:pointer; font-size:12.5px;
      transition:background .15s, color .15s, border-color .15s;
      user-select:none; width:100%; text-align:left;
    }
    .nav-btn:hover  { background:rgba(255,255,255,0.07); color:#e2e8f0; }
    .nav-btn.active { background:rgba(34,197,94,0.13); border-color:rgba(34,197,94,0.35); color:#4ade80; }
    .nav-btn .ico   { font-size:15px; width:18px; text-align:center; flex-shrink:0; }
    .nav-sep        { height:1px; background:rgba(255,255,255,0.06); margin:4px 0; }
    .sidebar-spacer { flex:1; }
    .hw-pill {
      text-align:center; padding:6px 8px; border-radius:8px; font-size:10.5px;
      background:rgba(34,197,94,0.1); border:1px solid rgba(34,197,94,0.3); color:#4ade80;
    }

    /* ── Main area ── */
    .main { flex:1; display:flex; flex-direction:column; overflow:hidden; min-width:0; }

    /* ── Topbar ── */
    .topbar {
      height:48px; flex-shrink:0;
      display:flex; align-items:center; justify-content:space-between;
      padding:0 18px;
      background:rgba(0,0,0,0.18);
      border-bottom:1px solid rgba(255,255,255,0.06);
    }
    .topbar-left   { display:flex; align-items:center; gap:10px; }
    .topbar h2     { font-size:15px; font-weight:600; color:#f1f5f9; }
    .topbar-right  { display:flex; align-items:center; gap:8px; }
    .clock         { font-size:13px; color:#64748b; font-variant-numeric:tabular-nums; letter-spacing:.5px; }
    .topbar-icon-btn {
      display:flex; align-items:center; justify-content:center;
      width:30px; height:30px; border-radius:7px;
      background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1);
      color:#94a3b8; cursor:pointer; font-size:14px;
      transition:background .15s, color .15s;
    }
    .topbar-icon-btn:hover { background:rgba(255,255,255,0.14); color:#e2e8f0; }
    .topbar-icon-btn.btn-red-ico { border-color:rgba(239,68,68,0.3); }
    .topbar-icon-btn.btn-red-ico:hover { background:rgba(239,68,68,0.2); color:#f87171; border-color:rgba(239,68,68,0.5); }
    .topbar-icon-btn.spinning { animation:spin .7s linear infinite; pointer-events:none; }
    .back-btn {
      display:none; align-items:center; gap:5px;
      padding:5px 11px; border-radius:7px;
      background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.11);
      color:#94a3b8; cursor:pointer; font-size:12px;
    }
    .back-btn.visible { display:flex; }

    /* ── Panels ── */
    .panels { flex:1; position:relative; overflow:hidden; }
    .panel {
      position:absolute; inset:0;
      padding:16px 18px; overflow-y:auto;
      opacity:0; pointer-events:none;
      transform:translateX(32px);
      transition:opacity .2s ease, transform .2s ease;
    }
    .panel.active          { opacity:1; pointer-events:all; transform:none; }
    .panel.slide-out-left  { opacity:0; transform:translateX(-32px); transition:opacity .2s ease, transform .2s ease; }

    /* ── Widgets ── */
    .grid { display:grid; gap:11px; }
    .g2   { grid-template-columns:1fr 1fr; }
    .g3   { grid-template-columns:1fr 1fr 1fr; }
    .g4   { grid-template-columns:repeat(4,1fr); }
    .widget {
      background:linear-gradient(150deg,rgba(255,255,255,0.065),rgba(255,255,255,0.025));
      border:1px solid rgba(255,255,255,0.09); border-radius:13px; padding:15px;
    }
    .widget + .widget { margin-top:0; }
    .wlabel {
      font-size:11px; color:#64748b; font-weight:500;
      text-transform:uppercase; letter-spacing:.5px; margin-bottom:9px;
    }
    .big-val  { font-size:28px; font-weight:700; line-height:1; margin-bottom:3px; }
    .sub-val  { font-size:11.5px; color:#94a3b8; }
    .row2     { display:flex; justify-content:space-between; margin-top:5px; font-size:11.5px; color:#94a3b8; }

    /* ── Weather panel ── */
    .wx-hero   { display:flex; align-items:center; gap:18px; margin-bottom:12px; }
    .wx-icon   { font-size:64px; line-height:1; }
    .wx-temp   { font-size:52px; font-weight:700; line-height:1; }
    .wx-sub    { font-size:12px; color:#94a3b8; margin-top:4px; }
    .wx-grid   { display:grid; grid-template-columns:1fr 1fr; gap:9px; }
    .wx-stat   { background:rgba(255,255,255,0.05); border-radius:9px; padding:11px; }
    .wx-lbl    { font-size:10.5px; color:#64748b; margin-bottom:3px; }
    .wx-val    { font-size:20px; font-weight:600; }

    /* ── Radio ── */
    .radio-bar {
      background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.08);
      border-radius:12px; padding:14px 16px; margin-bottom:12px;
      display:flex; align-items:center; gap:14px;
    }
    .radio-ico { font-size:34px; }
    .np-info   { flex:1; }
    .np-name   { font-size:15px; font-weight:600; margin-bottom:2px; }
    .np-stat   { font-size:11.5px; color:#94a3b8; }
    .stations-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
    .scard {
      background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.08);
      border-radius:9px; padding:12px 8px; text-align:center;
      cursor:pointer; transition:background .15s, transform .12s; font-size:12px;
    }
    .scard:hover   { background:rgba(255,255,255,0.12); transform:translateY(-2px); }
    .scard.playing { background:rgba(34,197,94,0.16); border-color:rgba(34,197,94,0.4); color:#4ade80; }
    .vol-row { display:flex; align-items:center; gap:11px; margin-top:11px; }
    .vol-row label  { font-size:11.5px; color:#94a3b8; width:50px; flex-shrink:0; }
    .vol-row input  { flex:1; accent-color:#22c55e; cursor:pointer; }
    .vol-row span   { font-size:11.5px; color:#cbd5e1; width:34px; text-align:right; }

    /* ── Config tabs ── */
    .ctabs { display:flex; gap:6px; margin-bottom:12px; flex-wrap:wrap; }
    .ctab {
      padding:6px 13px; border-radius:8px; border:1px solid rgba(255,255,255,0.1);
      background:rgba(255,255,255,0.06); color:#94a3b8;
      cursor:pointer; font-size:12px; transition:all .15s;
    }
    .ctab:hover  { background:rgba(255,255,255,0.11); color:#e2e8f0; }
    .ctab.active { background:rgba(34,197,94,0.15); border-color:rgba(34,197,94,0.4); color:#4ade80; }
    .ctab-panel  { display:none; }
    .ctab-panel.active { display:block; }

    /* ── Form fields ── */
    .field { margin-bottom:10px; }
    .field label { font-size:11.5px; color:#94a3b8; display:block; margin-bottom:4px; }
    .field input, .field select, .field textarea {
      width:100%; padding:8px 11px; border-radius:8px;
      border:1px solid rgba(255,255,255,0.12);
      background:rgba(255,255,255,0.06); color:#e2e8f0; font-size:12.5px;
    }
    .field input:focus, .field select:focus { outline:none; border-color:rgba(34,197,94,0.45); }
    .field-row { display:flex; gap:8px; }
    .field-row .field { flex:1; }

    /* ── System grid ── */
    .sys-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .sys-item { background:rgba(255,255,255,0.05); border-radius:10px; padding:12px; }
    .sys-lbl  { font-size:10.5px; color:#64748b; margin-bottom:4px; }
    .sys-val  { font-size:18px; font-weight:600; }

    /* ── Buttons ── */
    .btn {
      display:inline-flex; align-items:center; gap:5px;
      padding:8px 14px; border-radius:8px; font-size:12.5px;
      border:1px solid rgba(255,255,255,0.12);
      background:rgba(255,255,255,0.08); color:#e2e8f0;
      cursor:pointer; transition:background .15s;
    }
    .btn:hover     { background:rgba(255,255,255,0.15); }
    .btn-green     { background:rgba(34,197,94,0.18); border-color:rgba(34,197,94,0.4); color:#4ade80; }
    .btn-green:hover { background:rgba(34,197,94,0.28); }
    .btn-red       { background:rgba(239,68,68,0.18); border-color:rgba(239,68,68,0.4); color:#f87171; }
    .btn-red:hover { background:rgba(239,68,68,0.28); }
    .btn-sm        { padding:6px 11px; font-size:12px; }
    .btn-row       { display:flex; gap:7px; flex-wrap:wrap; margin-top:9px; }
    .msg           { font-size:11.5px; color:#94a3b8; margin-top:6px; min-height:16px; }

    /* ── Settings toggles ── */
    .setting-row {
      display:flex; align-items:center; justify-content:space-between;
      padding:11px 14px; border-radius:9px;
      background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07);
      margin-bottom:8px; cursor:pointer;
    }
    .setting-row:hover { background:rgba(255,255,255,0.08); }
    .sr-label { font-size:12.5px; color:#e2e8f0; }
    .sr-sub   { font-size:11px; color:#64748b; margin-top:1px; }
    .toggle {
      position:relative; width:42px; height:22px;
      background:rgba(255,255,255,0.1); border-radius:11px;
      cursor:pointer; transition:background .2s; flex-shrink:0;
    }
    .toggle.on { background:#22c55e; }
    .toggle-knob {
      position:absolute; top:3px; left:3px;
      width:16px; height:16px; border-radius:50%;
      background:#fff; transition:transform .2s;
    }
    .toggle.on .toggle-knob { transform:translateX(20px); }

    /* ── Wizard overlay ── */
    #wizard-overlay {
      position:fixed; inset:0; z-index:100;
      background:rgba(3,8,20,0.93);
      display:none; align-items:center; justify-content:center;
      backdrop-filter:blur(6px);
    }
    #wizard-overlay.open { display:flex; }
    .wizard-box {
      width:780px;
      background:linear-gradient(160deg,rgba(255,255,255,0.08),rgba(255,255,255,0.03));
      border:1px solid rgba(255,255,255,0.13); border-radius:18px;
      padding:26px 28px; box-shadow:0 24px 60px rgba(0,0,0,0.55);
    }
    .wiz-hdr h2  { font-size:20px; font-weight:700; margin-bottom:3px; }
    .wiz-hdr p   { font-size:11.5px; color:#94a3b8; }
    .wiz-steps   { display:flex; align-items:center; gap:8px; margin:16px 0; }
    .wiz-bubble  {
      width:28px; height:28px; border-radius:50%;
      display:flex; align-items:center; justify-content:center;
      font-size:12.5px; font-weight:600;
      background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); color:#64748b;
      transition:all .2s;
    }
    .wiz-bubble.done   { background:#22c55e; border-color:#22c55e; color:#0f172a; }
    .wiz-bubble.active { background:rgba(34,197,94,0.18); border-color:#22c55e; color:#4ade80; box-shadow:0 0 10px rgba(34,197,94,0.35); }
    .wiz-line { flex:1; height:1px; background:rgba(255,255,255,0.08); }
    .wiz-body {
      background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.07);
      border-radius:12px; padding:18px; min-height:180px;
    }
    .wiz-body label  { font-size:11.5px; color:#94a3b8; display:block; margin-bottom:5px; }
    .wiz-body input, .wiz-body select {
      width:100%; padding:9px 12px; border-radius:8px;
      border:1px solid rgba(255,255,255,0.12);
      background:rgba(255,255,255,0.06); color:#e2e8f0; font-size:12.5px;
      margin-bottom:10px;
    }
    .wiz-row2 { display:grid; grid-template-columns:1fr 1fr; gap:11px; }
    .wiz-toggle {
      display:flex; align-items:center; justify-content:space-between;
      padding:10px 13px; border-radius:9px;
      background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07);
      margin-bottom:8px; cursor:pointer;
    }
    .wiz-toggle:hover { background:rgba(255,255,255,0.08); }
    .pill {
      padding:3px 10px; border-radius:999px; font-size:11px; font-weight:600;
      background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:#64748b;
      transition:all .2s;
    }
    .pill.on { background:rgba(34,197,94,0.16); border-color:rgba(34,197,94,0.4); color:#4ade80; }
    .wiz-nav { display:flex; justify-content:space-between; align-items:center; margin-top:16px; }

    /* ── Toast ── */
    #toast {
      position:fixed; bottom:16px; left:50%; transform:translateX(-50%);
      background:rgba(34,197,94,0.92); color:#0f172a;
      padding:8px 18px; border-radius:9px; font-size:12.5px; font-weight:600;
      opacity:0; transition:opacity .25s; pointer-events:none; z-index:999;
      white-space:nowrap;
    }
    #toast.show { opacity:1; }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width:4px; }
    ::-webkit-scrollbar-track { background:transparent; }
    ::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.12); border-radius:4px; }

    /* ── Spinner ── */
    .spin { display:inline-block; width:12px; height:12px; border:2px solid rgba(255,255,255,0.2); border-top-color:#4ade80; border-radius:50%; animation:spin .6s linear infinite; }
    @keyframes spin { to { transform:rotate(360deg); } }

    /* ── Status badges ── */
    .badge-ok  { color:#4ade80; }
    .badge-err { color:#f87171; }
  </style>
</head>
<body>

<!-- ── Wizard Overlay ──────────────────────────────────────────────────────── -->
<div id="wizard-overlay">
  <div class="wizard-box">
    <div class="wiz-hdr">
      <h2 id="wiz-title">Welcome to Orange Pi Control Center</h2>
      <p id="wiz-desc">Let's set up your device. This takes about a minute.</p>
    </div>
    <div class="wiz-steps">
      <div class="wiz-bubble active" id="wb1">1</div>
      <div class="wiz-line"></div>
      <div class="wiz-bubble" id="wb2">2</div>
      <div class="wiz-line"></div>
      <div class="wiz-bubble" id="wb3">3</div>
      <div class="wiz-line"></div>
      <div class="wiz-bubble" id="wb4">4</div>
    </div>

    <!-- Step 1: Language -->
    <div class="wiz-body" id="ws1">
      <label>Display Language</label>
      <select id="wiz-lang">
        <option value="en">🇬🇧 English</option>
        <option value="fr">🇫🇷 Français</option>
        <option value="es">🇪🇸 Español</option>
        <option value="de">🇩🇪 Deutsch</option>
        <option value="ar">🇸🇦 العربية</option>
      </select>
    </div>

    <!-- Step 2: Location -->
    <div class="wiz-body" id="ws2" style="display:none">
      <label>Your Location (for accurate weather)</label>
      <div class="wiz-row2">
        <div><label>Latitude</label><input id="wiz-lat" type="number" step="0.0001" placeholder="51.5074"></div>
        <div><label>Longitude</label><input id="wiz-lon" type="number" step="0.0001" placeholder="-0.1278"></div>
      </div>
      <div class="wiz-toggle" onclick="wizGeolocate()">
        <div>
          <div style="font-size:12.5px;color:#e2e8f0">📍 Auto-detect location</div>
          <div style="font-size:11px;color:#64748b">Uses browser GPS or server GeoIP fallback</div>
        </div>
        <div class="pill" id="geo-pill">Tap to detect</div>
      </div>
    </div>

    <!-- Step 3: Timezone -->
    <div class="wiz-body" id="ws3" style="display:none">
      <label>Timezone</label>
      <select id="wiz-tz"></select>
      <div class="wiz-toggle" onclick="wizAutoTz()">
        <div>
          <div style="font-size:12.5px;color:#e2e8f0">🌐 Auto-detect & apply timezone</div>
          <div style="font-size:11px;color:#64748b">Uses GeoIP — applies immediately</div>
        </div>
        <div class="pill" id="tz-pill">Tap to detect</div>
      </div>
    </div>

    <!-- Step 4: Features -->
    <div class="wiz-body" id="ws4" style="display:none">
      <div class="wiz-toggle" onclick="wizToggle('weewx')">
        <div><div style="font-size:12.5px;color:#e2e8f0">🌧️ WeeWX Weather Station</div></div>
        <div class="pill" id="pill-weewx">Hidden</div>
      </div>
      <div class="wiz-toggle" onclick="wizToggle('netdata')">
        <div><div style="font-size:12.5px;color:#e2e8f0">📈 Netdata System Monitor</div></div>
        <div class="pill" id="pill-netdata">Hidden</div>
      </div>
      <div class="wiz-toggle" onclick="wizToggle('ha')">
        <div><div style="font-size:12.5px;color:#e2e8f0">🏠 Home Assistant</div></div>
        <div class="pill" id="pill-ha">Hidden</div>
      </div>
    </div>

    <div class="wiz-nav">
      <button class="btn" id="wiz-prev" onclick="wizPrev()" disabled>← Back</button>
      <div style="display:flex;gap:8px">
        <button class="btn" onclick="wizSkip()">Skip setup</button>
        <button class="btn btn-green" id="wiz-next" onclick="wizNext()">Next →</button>
      </div>
    </div>
  </div>
</div>

<!-- ── Main shell ──────────────────────────────────────────────────────────── -->
<div class="shell">
  <nav class="sidebar">
    <div class="sidebar-logo">
      🍊 Orange Pi
      <small>CONTROL CENTER</small>
    </div>
    <button class="nav-btn active" data-panel="dash"     onclick="nav('dash',this)">    <span class="ico">📊</span>Dashboard</button>
    <button class="nav-btn"        data-panel="weather"  onclick="nav('weather',this)"> <span class="ico">🌤️</span>Weather</button>
    <button class="nav-btn"        data-panel="radio"    onclick="nav('radio',this)">   <span class="ico">📻</span>Radio</button>
    <div class="nav-sep"></div>
    <button class="nav-btn"        data-panel="config"   onclick="nav('config',this)">  <span class="ico">⚙️</span>Device Config</button>
    <button class="nav-btn"        data-panel="system"   onclick="nav('system',this)">  <span class="ico">💻</span>System</button>
    <button class="nav-btn"        data-panel="settings" onclick="nav('settings',this)"><span class="ico">🔧</span>Settings</button>
    <div class="sidebar-spacer"></div>
    <div class="hw-pill">⚡ Hardware Active</div>
  </nav>

  <div class="main">
    <div class="topbar">
      <div class="topbar-left">
        <button class="back-btn" id="back-btn" onclick="goBack()">← Back</button>
        <h2 id="panel-title">📊 Dashboard</h2>
      </div>
      <div class="topbar-right">
        <button class="topbar-icon-btn" id="refresh-btn" onclick="refreshCurrentPanel()" title="Refresh">🔄</button>
        <span class="clock" id="clock">--:--:--</span>
        <button class="topbar-icon-btn btn-red-ico" onclick="topbarShutdown()" title="Shutdown / Reboot">⏻</button>
      </div>
    </div>

    <div class="panels" id="panels"
         ontouchstart="swipeStart(event)" ontouchend="swipeEnd(event)">

      <!-- ── Dashboard ── -->
      <div class="panel active" id="panel-dash">
        <div class="grid g3">
          <div class="widget">
            <div class="wlabel">Weather</div>
            <div style="font-size:44px;text-align:center;margin:2px 0 4px" id="d-icon">🌡️</div>
            <div class="big-val" id="d-temp">--</div>
            <div class="row2"><span id="d-hum">Hum --</span><span id="d-wind">Wind --</span></div>
          </div>
          <div class="widget">
            <div class="wlabel">System</div>
            <div class="big-val" style="font-size:22px;margin-bottom:5px" id="d-cpu">--</div>
            <div class="sub-val" id="d-mem">RAM --</div>
            <div class="sub-val" style="margin-top:3px" id="d-uptime">Up --</div>
          </div>
          <div class="widget">
            <div class="wlabel">Radio</div>
            <div style="font-size:28px;margin-bottom:6px">📻</div>
            <div class="sub-val" style="font-size:12.5px;color:#e2e8f0" id="d-radio">Stopped</div>
            <div class="btn-row" style="margin-top:8px">
              <button class="btn btn-green btn-sm" onclick="quickPlay()">▶ Play</button>
              <button class="btn btn-red btn-sm"   onclick="radioStop()">■</button>
            </div>
          </div>
        </div>
        <div class="grid g2" style="margin-top:10px">
          <div class="widget">
            <div class="wlabel">Quick Access</div>
            <div class="btn-row" style="margin-top:2px">
              <button class="btn btn-sm" onclick="nav('weather',null)">🌤️ Weather</button>
              <button class="btn btn-sm" onclick="nav('radio',null)">📻 Radio</button>
              <button class="btn btn-sm" onclick="nav('config',null)">⚙️ Config</button>
            </div>
          </div>
          <div class="widget">
            <div class="wlabel">Network</div>
            <div style="font-size:17px;font-weight:600;margin-bottom:4px" id="d-ip">--</div>
            <div class="sub-val" id="d-disk">Disk --</div>
          </div>
        </div>
      </div>

      <!-- ── Weather ── -->
      <div class="panel" id="panel-weather">
        <div class="wx-hero">
          <div class="wx-icon" id="w-icon">🌡️</div>
          <div>
            <div class="wx-temp" id="w-temp">--</div>
            <div class="wx-sub" id="w-feels">Feels like --</div>
            <div class="wx-sub" style="margin-top:3px" id="w-loc">--</div>
          </div>
        </div>
        <div class="wx-grid">
          <div class="wx-stat"><div class="wx-lbl">Humidity</div><div class="wx-val" id="w-hum">--</div></div>
          <div class="wx-stat"><div class="wx-lbl">Pressure</div><div class="wx-val" id="w-pres">--</div></div>
          <div class="wx-stat"><div class="wx-lbl">Wind Speed</div><div class="wx-val" id="w-wind">--</div></div>
          <div class="wx-stat"><div class="wx-lbl">Last Update</div><div class="wx-val" style="font-size:14px" id="w-updated">--</div></div>
        </div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn" onclick="loadWeather(true)">🔄 Refresh</button>
        </div>
        <div class="msg" id="wx-msg"></div>
      </div>

      <!-- ── Radio ── -->
      <div class="panel" id="panel-radio">
        <div class="radio-bar">
          <div class="radio-ico">📻</div>
          <div class="np-info">
            <div class="np-name" id="r-name">Not playing</div>
            <div class="np-stat" id="r-status">Select a station below</div>
          </div>
          <div style="display:flex;gap:7px">
            <button class="btn btn-green" onclick="radioPlay()">▶ Play</button>
            <button class="btn btn-red"   onclick="radioStop()">■ Stop</button>
          </div>
        </div>
        <div class="vol-row">
          <label>Volume</label>
          <input type="range" min="0" max="100" value="70" id="vol-slider"
                 oninput="setVolume(this.value)">
          <span id="vol-val">70%</span>
        </div>
        <div class="stations-grid" id="stations-grid" style="margin-top:12px"></div>
      </div>

      <!-- ── Device Config ── -->
      <div class="panel" id="panel-config">
        <div class="ctabs">
          <button class="ctab active" onclick="ctab('net',this)">📡 Network</button>
          <button class="ctab"        onclick="ctab('audio',this)">🔊 Audio</button>
          <button class="ctab"        onclick="ctab('display',this)">🖥️ Display</button>
          <button class="ctab"        onclick="ctab('power',this)">🔧 System</button>
        </div>

        <!-- Network -->
        <div class="ctab-panel active" id="ct-net">
          <div class="widget">
            <div class="wlabel">WiFi Connection</div>
            <div class="field-row">
              <div class="field"><label>Network (SSID)</label><input id="ssid" type="text" placeholder="Network name" autocomplete="off" maxlength="32"></div>
              <div class="field"><label>Password</label><input id="wifi-pass" type="password" placeholder="Password" maxlength="63"></div>
            </div>
            <div class="btn-row">
              <button class="btn btn-green" onclick="connectWifi()">Connect</button>
              <button class="btn" onclick="scanWifi()">🔍 Scan</button>
            </div>
            <div id="scan-results" style="margin-top:8px;display:none">
              <div class="wlabel" style="margin-bottom:6px">Available Networks</div>
              <div id="scan-list" style="display:flex;flex-wrap:wrap;gap:6px"></div>
            </div>
            <div class="msg" id="net-msg"></div>
          </div>
          <div class="widget" style="margin-top:10px">
            <div class="wlabel">IP Address</div>
            <div style="font-size:20px;font-weight:600;margin-bottom:6px" id="ip-val">--</div>
            <button class="btn btn-sm" onclick="refreshIP()">🔄 Refresh</button>
          </div>
        </div>

        <!-- Audio -->
        <div class="ctab-panel" id="ct-audio">
          <div class="widget">
            <div class="wlabel">Volume Control</div>
            <div class="vol-row" style="margin:8px 0 12px">
              <label>Master</label>
              <input type="range" min="0" max="100" value="70" id="cfg-vol"
                     oninput="cfgVolume(this.value)">
              <span id="cfg-vol-val">70%</span>
            </div>
            <div class="btn-row">
              <button class="btn" onclick="testAudio()">🔊 Test Tone</button>
              <button class="btn btn-red" onclick="muteAudio()">🔇 Mute</button>
            </div>
            <div class="msg" id="audio-msg"></div>
          </div>
        </div>

        <!-- Display -->
        <div class="ctab-panel" id="ct-display">
          <div class="widget">
            <div class="wlabel">Resolution</div>
            <div class="field">
              <label>Screen Resolution</label>
              <select id="resolution">
                <option value="1024x600">1024×600 (Default — 7" panel)</option>
                <option value="1280x720">1280×720 (HD)</option>
                <option value="1920x1080">1920×1080 (Full HD)</option>
              </select>
            </div>
            <div class="btn-row"><button class="btn btn-green" onclick="applyRes()">Apply</button></div>
            <div class="msg" id="disp-msg"></div>
          </div>
          <div class="widget" style="margin-top:10px">
            <div class="wlabel">Brightness</div>
            <div class="vol-row" style="margin-top:6px">
              <label>Level</label>
              <input type="range" min="10" max="100" value="80" id="bright-slider"
                     oninput="setBright(this.value)">
              <span id="bright-val">80%</span>
            </div>
          </div>
        </div>

        <!-- System config / Timezone / Power -->
        <div class="ctab-panel" id="ct-power">
          <div class="widget">
            <div class="wlabel">Timezone</div>
            <div class="field">
              <label>Select Timezone</label>
              <select id="tz-select"></select>
            </div>
            <div class="btn-row">
              <button class="btn btn-green" onclick="setTimezone()">Save</button>
              <button class="btn" onclick="autoTimezone()">🌐 Auto-detect</button>
            </div>
            <div class="msg" id="tz-msg"></div>
          </div>
          <div class="widget" style="margin-top:10px">
            <div class="wlabel">Power</div>
            <div class="btn-row">
              <button class="btn btn-red" onclick="confirmAction('reboot')">🔄 Reboot</button>
              <button class="btn btn-red" onclick="confirmAction('shutdown')">⏻ Shutdown</button>
            </div>
          </div>
        </div>
      </div>

      <!-- ── System ── -->
      <div class="panel" id="panel-system">
        <div class="sys-grid">
          <div class="sys-item"><div class="sys-lbl">CPU Temperature</div><div class="sys-val" id="s-cpu">--</div></div>
          <div class="sys-item"><div class="sys-lbl">Memory Used</div><div class="sys-val" style="font-size:15px" id="s-mem">--</div></div>
          <div class="sys-item"><div class="sys-lbl">Disk Used</div><div class="sys-val" id="s-disk">--</div></div>
          <div class="sys-item"><div class="sys-lbl">Uptime</div><div class="sys-val" style="font-size:14px" id="s-uptime">--</div></div>
          <div class="sys-item"><div class="sys-lbl">IP Address</div><div class="sys-val" style="font-size:15px" id="s-ip">--</div></div>
          <div class="sys-item"><div class="sys-lbl">Hostname</div><div class="sys-val" style="font-size:15px" id="s-host">--</div></div>
        </div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn" onclick="loadSystem()">🔄 Refresh</button>
        </div>
      </div>

      <!-- ── Settings ── -->
      <div class="panel" id="panel-settings">
        <div class="widget" style="margin-bottom:10px">
          <div class="wlabel">Location & Language</div>
          <div class="field-row" style="margin-top:6px">
            <div class="field"><label>Latitude</label><input id="set-lat" type="number" step="0.0001" placeholder="51.5074"></div>
            <div class="field"><label>Longitude</label><input id="set-lon" type="number" step="0.0001" placeholder="-0.1278"></div>
            <div class="field">
              <label>Language</label>
              <select id="set-lang">
                <option value="en">🇬🇧 English</option>
                <option value="fr">🇫🇷 Français</option>
                <option value="es">🇪🇸 Español</option>
                <option value="de">🇩🇪 Deutsch</option>
                <option value="ar">🇸🇦 العربية</option>
              </select>
            </div>
          </div>
          <div class="btn-row">
            <button class="btn btn-green" onclick="saveLocationLang()">💾 Save</button>
            <button class="btn" onclick="geoIPSettings()">🌐 Auto-detect</button>
          </div>
          <div class="msg" id="loc-msg"></div>
        </div>
        <div class="widget" style="margin-bottom:10px">
          <div class="wlabel">Optional Integrations</div>
          <div class="setting-row" onclick="toggleFlag('show_weewx')">
            <div><div class="sr-label">WeeWX Weather Station</div><div class="sr-sub">Local HTML weather reports on port 8080</div></div>
            <div class="toggle" id="sw-weewx"><div class="toggle-knob"></div></div>
          </div>
          <div class="setting-row" onclick="toggleFlag('show_netdata')">
            <div><div class="sr-label">Netdata Monitor</div><div class="sr-sub">Real-time system graphs on port 19999</div></div>
            <div class="toggle" id="sw-netdata"><div class="toggle-knob"></div></div>
          </div>
          <div class="setting-row" onclick="toggleFlag('show_ha')">
            <div><div class="sr-label">Home Assistant</div><div class="sr-sub">Smart home dashboard on port 8123</div></div>
            <div class="toggle" id="sw-ha"><div class="toggle-knob"></div></div>
          </div>
        </div>
        <div class="widget">
          <div class="wlabel">Setup</div>
          <p style="font-size:11.5px;color:#94a3b8;margin-bottom:10px">Re-run the welcome wizard to reconfigure language, location, timezone, and integrations.</p>
          <button class="btn btn-green" onclick="openWizard()">↩ Restart Setup Wizard</button>
        </div>
      </div>

    </div><!-- /panels -->
  </div><!-- /main -->
</div><!-- /shell -->

<div id="toast"></div>

<script>
/* ── Constants ──────────────────────────────────────────────────────────────── */
const STATIONS = """ + str(STATIONS).replace("'", '"') + r""";
const PANELS   = ['dash','weather','radio','config','system','settings'];
const TITLES   = {
  dash:'📊 Dashboard', weather:'🌤️ Weather', radio:'📻 Internet Radio',
  config:'⚙️ Device Config', system:'💻 System', settings:'🔧 Settings'
};

/* ── State ───────────────────────────────────────────────────────────────────── */
let currentStation = 0;
let radioPlaying   = false;
let navHistory     = ['dash'];
let CFG            = {};
let wizStep        = 1;
let wizData        = {show_weewx:false, show_netdata:false, show_ha:false};

/* ── Helpers ─────────────────────────────────────────────────────────────────── */
function api(path, opts) {
  return fetch(path, opts).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });
}

function post(path, body) {
  return api(path, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
}

function setTextSafe(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setMsg(id, val, ok) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = val;
  el.style.color = ok === false ? '#f87171' : '#94a3b8';
}

let toastTimer;
function toast(msg, color) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.background = color || 'rgba(34,197,94,0.92)';
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

/* ── Clock ───────────────────────────────────────────────────────────────────── */
function tick() {
  setTextSafe('clock', new Date().toLocaleTimeString('en-GB', {hour12:false}));
}
tick(); setInterval(tick, 1000);

/* ── Navigation ──────────────────────────────────────────────────────────────── */
function nav(id, btn) {
  const prev = navHistory[navHistory.length - 1];
  if (prev === id) return;

  const oldEl = document.getElementById('panel-' + prev);
  oldEl.classList.remove('active');
  oldEl.classList.add('slide-out-left');
  setTimeout(() => oldEl.classList.remove('slide-out-left'), 220);

  const newEl = document.getElementById('panel-' + id);
  newEl.style.transform = 'translateX(32px)';
  newEl.classList.add('active');
  requestAnimationFrame(() => requestAnimationFrame(() => { newEl.style.transform = ''; }));

  setTextSafe('panel-title', TITLES[id]);
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  const target = btn || document.querySelector(`[data-panel="${id}"]`);
  if (target) target.classList.add('active');

  navHistory.push(id);
  document.getElementById('back-btn').classList.toggle('visible', navHistory.length > 1);

  // Lazy-load data on panel entry
  if (id === 'weather')  loadWeather();
  if (id === 'system')   loadSystem();
  if (id === 'config')   { refreshIP(); populateTzSelect('tz-select'); }
  if (id === 'dash')     loadDash();
  if (id === 'settings') loadCFG();
}

function goBack() {
  if (navHistory.length <= 1) return;
  navHistory.pop();
  const prev = navHistory.pop();
  nav(prev || 'dash', null);
}

/* ── Swipe navigation ────────────────────────────────────────────────────────── */
let swX = 0, swY = 0;
function swipeStart(e) { swX = e.changedTouches[0].clientX; swY = e.changedTouches[0].clientY; }
function swipeEnd(e) {
  const dx = e.changedTouches[0].clientX - swX;
  const dy = e.changedTouches[0].clientY - swY;
  if (Math.abs(dx) < Math.abs(dy) || Math.abs(dx) < 55) return;
  if (dx > 0) {
    goBack();
  } else {
    const cur = navHistory[navHistory.length - 1];
    const idx = PANELS.indexOf(cur);
    if (idx < PANELS.length - 1) nav(PANELS[idx + 1], null);
  }
}

/* ── Settings (CFG mirror) ───────────────────────────────────────────────────── */
function loadCFG() {
  api('/api/settings').then(s => {
    CFG = s;
    const setVal = (id, v) => { const e = document.getElementById(id); if (e && v !== undefined) e.value = v; };
    setVal('set-lat',  s.latitude);
    setVal('set-lon',  s.longitude);
    setVal('set-lang', s.language);
    setSwitch('sw-weewx',   s.show_weewx);
    setSwitch('sw-netdata', s.show_netdata);
    setSwitch('sw-ha',      s.show_ha);
    if (s.first_run) openWizard();
  }).catch(() => {});
}

function setSwitch(id, on) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('on', !!on);
}

function toggleFlag(key) {
  CFG[key] = !CFG[key];
  const map = {show_weewx:'sw-weewx', show_netdata:'sw-netdata', show_ha:'sw-ha'};
  setSwitch(map[key], CFG[key]);
  post('/api/settings/save', {[key]: CFG[key]}).catch(() => {});
}

function saveLocationLang() {
  const lat  = parseFloat(document.getElementById('set-lat').value);
  const lon  = parseFloat(document.getElementById('set-lon').value);
  const lang = document.getElementById('set-lang').value;
  if (isNaN(lat) || isNaN(lon)) { setMsg('loc-msg', 'Enter valid coordinates', false); return; }
  setMsg('loc-msg', 'Saving...');
  post('/api/settings/save', {latitude:lat, longitude:lon, language:lang})
    .then(() => { setMsg('loc-msg', 'Saved.'); toast('Settings saved'); })
    .catch(() => setMsg('loc-msg', 'Save failed', false));
}

function geoIPSettings() {
  setMsg('loc-msg', 'Detecting location...');
  post('/api/system/auto-timezone')
    .then(d => { setMsg('loc-msg', d.message || 'Done'); loadCFG(); })
    .catch(() => setMsg('loc-msg', 'Detection failed', false));
}

/* ── Timezone helpers ────────────────────────────────────────────────────────── */
let _tzLoaded = false;
let _tzList   = [];

function populateTzSelect(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  if (_tzLoaded) { _applyTzOptions(sel); return; }
  api('/api/timezones').then(data => {
    _tzList   = data.timezones || [];
    _tzLoaded = true;
    document.querySelectorAll('.tz-select-target').forEach(_applyTzOptions);
    _applyTzOptions(sel);
  }).catch(() => {
    // Fallback: common zones
    _tzList = ['UTC','Europe/London','Europe/Paris','Europe/Berlin','Europe/Madrid',
      'America/New_York','America/Chicago','America/Los_Angeles','America/Sao_Paulo',
      'Asia/Dubai','Asia/Kolkata','Asia/Shanghai','Asia/Tokyo','Australia/Sydney',
      'Africa/Cairo','Africa/Algiers'];
    _tzLoaded = true;
    _applyTzOptions(sel);
  });
}

function _applyTzOptions(sel) {
  const cur = sel.value || (CFG && CFG.timezone) || 'UTC';
  sel.innerHTML = _tzList.map(tz =>
    `<option value="${tz}"${tz===cur?' selected':''}>${tz}</option>`
  ).join('');
}

/* ── Weather ─────────────────────────────────────────────────────────────────── */
function loadWeather(force) {
  setMsg('wx-msg', force ? 'Refreshing...' : '');
  return api('/api/weather' + (force ? '?force=1' : '')).then(d => {
    setTextSafe('w-icon',    d.icon);
    setTextSafe('w-temp',    d.temp);
    setTextSafe('w-feels',   `Feels like ${d.feels || '--'}`);
    setTextSafe('w-hum',     d.humidity);
    setTextSafe('w-pres',    d.pressure);
    setTextSafe('w-wind',    d.wind);
    setTextSafe('w-loc',     `${d.lat}°N  ${d.lon}°E`);
    setTextSafe('w-updated', new Date().toLocaleTimeString('en-GB', {hour12:false}));
    setTextSafe('d-icon',    d.icon);
    setTextSafe('d-temp',    d.temp);
    setTextSafe('d-hum',     `Hum ${d.humidity}`);
    setTextSafe('d-wind',    `Wind ${d.wind}`);
    setMsg('wx-msg', d.ok ? '' : 'Using cached / unavailable data');
  }).catch(() => setMsg('wx-msg', 'Weather unavailable', false));
}

/* ── System info ─────────────────────────────────────────────────────────────── */
function loadSystem() {
  return api('/api/system').then(d => {
    setTextSafe('s-cpu',    d.temp);
    setTextSafe('s-mem',    d.memory);
    setTextSafe('s-disk',   d.disk);
    setTextSafe('s-uptime', d.uptime);
    setTextSafe('s-ip',     d.ip);
    setTextSafe('s-host',   d.hostname || '--');
    // Keep dashboard widgets in sync too
    setTextSafe('d-cpu',    d.temp);
    setTextSafe('d-mem',    `RAM ${d.memory}`);
    setTextSafe('d-uptime', `Up ${d.uptime}`);
    setTextSafe('d-ip',     d.ip);
    setTextSafe('d-disk',   `Disk ${d.disk}`);
  }).catch(() => {});
}

function loadDash() {
  return Promise.all([loadSystem(), loadWeather()]);
}

/* ── Radio ───────────────────────────────────────────────────────────────────── */
function buildStations() {
  document.getElementById('stations-grid').innerHTML = STATIONS.map((s, i) =>
    `<div class="scard" id="sc-${i}" onclick="selectStation(${i})">${s.name}</div>`
  ).join('');
}

function selectStation(i) {
  currentStation = i;
  radioPlay();
}

function radioPlay() {
  const s = STATIONS[currentStation];
  setTextSafe('r-name',   s.name);
  setTextSafe('r-status', 'Connecting...');
  document.querySelectorAll('.scard').forEach(c => c.classList.remove('playing'));
  const sc = document.getElementById('sc-' + currentStation);
  if (sc) sc.classList.add('playing');
  post('/api/radio/play', {url: s.url, name: s.name}).then(d => {
    setTextSafe('r-status', d.message || 'Playing');
    setTextSafe('d-radio',  s.name);
    radioPlaying = true;
    toast('▶ ' + s.name);
  }).catch(() => {
    setTextSafe('r-status', 'Connection failed');
    toast('Radio error', 'rgba(239,68,68,0.9)');
  });
}

function radioStop() {
  post('/api/radio/stop').then(() => {
    setTextSafe('r-status', 'Stopped');
    setTextSafe('d-radio',  'Stopped');
    radioPlaying = false;
    document.querySelectorAll('.scard').forEach(c => c.classList.remove('playing'));
    toast('■ Stopped', 'rgba(239,68,68,0.9)');
  }).catch(() => {});
}

function quickPlay() { radioPlay(); nav('radio', null); }

function setVolume(v) {
  setTextSafe('vol-val', v + '%');
  post('/api/audio/volume', {volume: parseInt(v)}).catch(() => {});
}

/* ── Config tabs ─────────────────────────────────────────────────────────────── */
function ctab(id, btn) {
  document.querySelectorAll('.ctab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.ctab').forEach(b => b.classList.remove('active'));
  document.getElementById('ct-' + id).classList.add('active');
  btn.classList.add('active');
}

/* ── WiFi ────────────────────────────────────────────────────────────────────── */
function connectWifi() {
  const ssid = document.getElementById('ssid').value.trim();
  const pass = document.getElementById('wifi-pass').value;
  if (!ssid) { setMsg('net-msg', 'Enter a network name', false); return; }
  setMsg('net-msg', 'Connecting — this may take up to 20 seconds...');
  post('/api/wifi/connect', {ssid, password: pass})
    .then(d => { setMsg('net-msg', d.message); toast(d.message); refreshIP(); })
    .catch(() => setMsg('net-msg', 'Connection failed', false));
}

function scanWifi() {
  setMsg('net-msg', 'Scanning...');
  document.getElementById('scan-results').style.display = 'none';
  api('/api/wifi/scan').then(d => {
    setMsg('net-msg', '');
    const list = document.getElementById('scan-list');
    if (d.networks && d.networks.length) {
      list.innerHTML = d.networks.map(n =>
        `<button class="btn btn-sm" onclick="document.getElementById('ssid').value='${n.replace(/'/g, "\\'")}'">${n}</button>`
      ).join('');
      document.getElementById('scan-results').style.display = 'block';
    } else {
      setMsg('net-msg', d.message || 'No networks found');
    }
  }).catch(() => setMsg('net-msg', 'Scan failed', false));
}

function refreshIP() {
  api('/api/system/ip').then(d => setTextSafe('ip-val', d.ip || '--')).catch(() => {});
}

/* ── Audio ───────────────────────────────────────────────────────────────────── */
function cfgVolume(v) {
  setTextSafe('cfg-vol-val', v + '%');
  post('/api/audio/volume', {volume: parseInt(v)}).catch(() => {});
}

function testAudio() {
  setMsg('audio-msg', 'Playing 440 Hz test tone...');
  post('/api/audio/test')
    .then(d => setMsg('audio-msg', d.message || 'Done'))
    .catch(() => setMsg('audio-msg', 'Audio test failed', false));
}

function muteAudio() {
  post('/api/audio/volume', {volume: 0}).then(() => {
    document.getElementById('cfg-vol').value = 0;
    setTextSafe('cfg-vol-val', '0%');
    setMsg('audio-msg', 'Muted');
    toast('🔇 Muted', 'rgba(239,68,68,0.9)');
  }).catch(() => {});
}

/* ── Display ─────────────────────────────────────────────────────────────────── */
function applyRes() {
  const res = document.getElementById('resolution').value;
  post('/api/display/resolution', {resolution: res})
    .then(d => { setMsg('disp-msg', d.message); toast(d.message); })
    .catch(() => setMsg('disp-msg', 'Failed to change resolution', false));
}

function setBright(v) {
  setTextSafe('bright-val', v + '%');
  post('/api/display/brightness', {brightness: parseInt(v)}).catch(() => {});
}

/* ── Timezone ────────────────────────────────────────────────────────────────── */
function setTimezone() {
  const tz = document.getElementById('tz-select').value;
  if (!tz) return;
  setMsg('tz-msg', 'Applying...');
  post('/api/system/timezone', {timezone: tz})
    .then(d => { setMsg('tz-msg', d.message); toast(d.message); })
    .catch(() => setMsg('tz-msg', 'Failed to set timezone', false));
}

function autoTimezone() {
  setMsg('tz-msg', 'Detecting...');
  post('/api/system/auto-timezone').then(d => {
    if (d.timezone) {
      const sel = document.getElementById('tz-select');
      if (sel && [...sel.options].some(o => o.value === d.timezone)) sel.value = d.timezone;
    }
    setMsg('tz-msg', d.message); toast(d.message);
  }).catch(() => setMsg('tz-msg', 'Detection failed', false));
}

/* ── Power ───────────────────────────────────────────────────────────────────── */
function confirmAction(action) {
  const labels = {reboot: 'Reboot the Orange Pi?', shutdown: 'Shutdown the Orange Pi?'};
  if (!confirm(labels[action])) return;
  if (action === 'reboot') {
    post('/api/system/reboot').then(() => toast('🔄 Rebooting...', 'rgba(239,68,68,0.9)'));
  } else {
    post('/api/system/shutdown').then(() => toast('⏻ Shutting down...', 'rgba(239,68,68,0.9)'));
  }
}

/* ── Wizard ──────────────────────────────────────────────────────────────────── */
const WIZ_TITLES = ['Language', 'Location', 'Timezone', 'Integrations'];
const WIZ_DESCS  = [
  'Choose your display language.',
  'Set your location for accurate local weather.',
  'Select your timezone — applied immediately to the system.',
  'Enable optional integrations (can be changed later in Settings).',
];

function openWizard() {
  wizStep = 1;
  wizData = {show_weewx: false, show_netdata: false, show_ha: false};
  updateWizPills();
  renderWizStep(1);
  populateTzSelect('wiz-tz');
  document.getElementById('wizard-overlay').classList.add('open');
}

function renderWizStep(n) {
  for (let i = 1; i <= 4; i++) {
    document.getElementById('ws' + i).style.display = i === n ? 'block' : 'none';
    const b = document.getElementById('wb' + i);
    b.className = 'wiz-bubble' + (i < n ? ' done' : i === n ? ' active' : '');
  }
  setTextSafe('wiz-title', WIZ_TITLES[n - 1]);
  setTextSafe('wiz-desc',  WIZ_DESCS[n - 1]);
  const prev = document.getElementById('wiz-prev');
  prev.disabled = n === 1;
  prev.style.opacity = n === 1 ? '.4' : '1';
  document.getElementById('wiz-next').textContent = n === 4 ? 'Finish ✓' : 'Next →';
}

function wizNext() { if (wizStep === 4) { wizFinish(); return; } wizStep++; renderWizStep(wizStep); }
function wizPrev()  { if (wizStep > 1) { wizStep--; renderWizStep(wizStep); } }

function wizSkip() {
  post('/api/wizard/skip').catch(() => {});
  document.getElementById('wizard-overlay').classList.remove('open');
}

function wizGeolocate() {
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      pos => {
        document.getElementById('wiz-lat').value = pos.coords.latitude.toFixed(4);
        document.getElementById('wiz-lon').value = pos.coords.longitude.toFixed(4);
        const p = document.getElementById('geo-pill');
        p.textContent = '✓ GPS'; p.classList.add('on');
      },
      () => wizServerGeoIP()
    );
  } else { wizServerGeoIP(); }
}

function wizServerGeoIP() {
  api('/api/system/geoip').then(d => {
    if (d.latitude)  document.getElementById('wiz-lat').value = d.latitude.toFixed(4);
    if (d.longitude) document.getElementById('wiz-lon').value = d.longitude.toFixed(4);
    const p = document.getElementById('geo-pill');
    p.textContent = '✓ GeoIP'; p.classList.add('on');
  }).catch(() => {});
}

function wizAutoTz() {
  const p = document.getElementById('tz-pill');
  p.textContent = 'Detecting...';
  post('/api/system/auto-timezone').then(d => {
    if (d.timezone) {
      const sel = document.getElementById('wiz-tz');
      if (sel && [...sel.options].some(o => o.value === d.timezone)) sel.value = d.timezone;
    }
    p.textContent = d.timezone ? `✓ ${d.timezone}` : 'Done';
    p.classList.add('on');
  }).catch(() => { p.textContent = 'Failed'; });
}

function wizToggle(key) {
  const kmap = {weewx:'show_weewx', netdata:'show_netdata', ha:'show_ha'};
  const k = kmap[key];
  wizData[k] = !wizData[k];
  updateWizPills();
}

function updateWizPills() {
  const fields = [
    ['weewx',   'show_weewx',   'Enabled', 'Hidden'],
    ['netdata', 'show_netdata', 'Enabled', 'Hidden'],
    ['ha',      'show_ha',      'Enabled', 'Hidden'],
  ];
  fields.forEach(([key, prop, yes, no]) => {
    const el = document.getElementById('pill-' + key);
    if (!el) return;
    const on = !!wizData[prop];
    el.textContent = on ? yes : no;
    el.classList.toggle('on', on);
  });
}

function wizFinish() {
  const body = {
    language:     document.getElementById('wiz-lang').value || 'en',
    latitude:     parseFloat(document.getElementById('wiz-lat').value) || 51.5074,
    longitude:    parseFloat(document.getElementById('wiz-lon').value) || -0.1278,
    timezone:     document.getElementById('wiz-tz').value || 'UTC',
    show_weewx:   !!wizData.show_weewx,
    show_netdata: !!wizData.show_netdata,
    show_ha:      !!wizData.show_ha,
    first_run:    false,
  };
  post('/api/wizard/finish', body).then(() => {
    document.getElementById('wizard-overlay').classList.remove('open');
    toast('✓ Setup complete!'); loadDash(); loadCFG();
  }).catch(() => toast('Save failed', 'rgba(239,68,68,0.9)'));
}

/* ── Topbar refresh ──────────────────────────────────────────────────────────── */
function refreshCurrentPanel() {
  const cur = navHistory[navHistory.length - 1];
  const btn = document.getElementById('refresh-btn');
  btn.classList.add('spinning');
  const done = () => setTimeout(() => btn.classList.remove('spinning'), 400);
  const p = {
    dash:     () => loadDash().finally(done),
    weather:  () => loadWeather(true).finally(done),
    system:   () => loadSystem().finally(done),
    config:   () => { refreshIP(); done(); },
    settings: () => { loadCFG(); done(); },
    radio:    () => done(),
  };
  (p[cur] || done)();
}

/* ── Topbar shutdown dialog ──────────────────────────────────────────────────── */
function topbarShutdown() {
  // Inline non-blocking dialog — avoids browser confirm() blocking the UI
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:200;display:flex;align-items:center;justify-content:center;background:rgba(3,8,20,0.82);backdrop-filter:blur(4px)';
  overlay.innerHTML = `
    <div style="background:linear-gradient(150deg,rgba(30,41,59,0.98),rgba(15,23,42,0.98));border:1px solid rgba(255,255,255,0.13);border-radius:14px;padding:24px 28px;min-width:300px;text-align:center">
      <div style="font-size:32px;margin-bottom:10px">⏻</div>
      <div style="font-size:15px;font-weight:600;margin-bottom:5px;color:#f1f5f9">Power Options</div>
      <div style="font-size:12px;color:#94a3b8;margin-bottom:20px">Choose an action for the Orange Pi</div>
      <div style="display:flex;gap:10px;justify-content:center">
        <button id="_sd_reboot"   class="btn btn-red" style="flex:1">🔄 Reboot</button>
        <button id="_sd_shutdown" class="btn btn-red" style="flex:1">⏻ Shutdown</button>
        <button id="_sd_cancel"   class="btn"         style="flex:1">✕ Cancel</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  document.getElementById('_sd_cancel').onclick   = () => overlay.remove();
  document.getElementById('_sd_reboot').onclick   = () => {
    overlay.remove();
    post('/api/system/reboot').then(() => toast('🔄 Rebooting...', 'rgba(239,68,68,0.9)'));
  };
  document.getElementById('_sd_shutdown').onclick = () => {
    overlay.remove();
    post('/api/system/shutdown').then(() => toast('⏻ Shutting down...', 'rgba(239,68,68,0.9)'));
  };
  overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };
}

/* ── Auto-refresh: active panel only ────────────────────────────────────────── */
setInterval(() => {
  const cur = navHistory[navHistory.length - 1];
  if (cur === 'dash')    loadDash();
  if (cur === 'weather') loadWeather();
  if (cur === 'system')  loadSystem();
}, 30000);

/* ── Boot ────────────────────────────────────────────────────────────────────── */
buildStations();
loadCFG();
loadDash();
</script>
</body>
</html>"""


# ── API routes ────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return HTML


@app.route('/api/settings')
def api_settings():
    return jsonify(load_settings())


@app.route('/api/settings/save', methods=['POST'])
def api_settings_save():
    data = request.json or {}
    return jsonify(save_settings(data))


@app.route('/api/timezones')
def api_timezones():
    """Return the full IANA timezone list for the UI selects."""
    tzs = get_timezones()
    return jsonify({'timezones': tzs})


@app.route('/api/wizard/finish', methods=['POST'])
def api_wizard_finish():
    data = request.json or {}
    data['first_run'] = False
    tz = data.get('timezone', 'UTC')
    if not valid_timezone(tz):
        data['timezone'] = 'UTC'
        tz = 'UTC'
    saved = save_settings(data)
    try:
        subprocess.run(['timedatectl', 'set-timezone', tz], timeout=5)
    except Exception:
        pass
    return jsonify(saved)


@app.route('/api/wizard/skip', methods=['POST'])
def api_wizard_skip():
    return jsonify(save_settings({'first_run': False}))


@app.route('/api/weather')
def api_weather():
    force = request.args.get('force', '0') == '1'
    if force:
        # Invalidate cache for this location
        s = load_settings()
        lat = float(s.get('latitude', 51.5074))
        lon = float(s.get('longitude', -0.1278))
        cache_key = f'{round(lat,2)},{round(lon,2)}'
        with _WX_LOCK:
            _WX_CACHE.pop(cache_key, None)
    s = load_settings()
    lat = float(s.get('latitude', 51.5074))
    lon = float(s.get('longitude', -0.1278))
    d = weather_data(lat, lon)
    d['lat'] = round(lat, 4)
    d['lon'] = round(lon, 4)
    return jsonify(d)


@app.route('/api/system')
def api_system():
    try:
        hostname = subprocess.check_output(['hostname'], timeout=3).decode().strip()
    except Exception:
        hostname = 'orangepi'
    return jsonify({
        'temp':     sys_temp(),
        'memory':   sys_mem(),
        'uptime':   sys_uptime(),
        'disk':     sys_disk(),
        'ip':       sys_ip(),
        'hostname': hostname,
    })


@app.route('/api/system/ip')
def api_ip():
    return jsonify({'ip': sys_ip()})


@app.route('/api/system/geoip')
def api_geoip():
    try:
        j = req.get('https://ip-api.com/json', timeout=6).json()
        return jsonify({'latitude': j.get('lat'), 'longitude': j.get('lon'), 'timezone': j.get('timezone')})
    except Exception:
        log.warning('GeoIP lookup failed')
        return jsonify({'error': 'geoip_failed'}), 503


@app.route('/api/system/timezone', methods=['POST'])
def api_set_timezone():
    tz = (request.json or {}).get('timezone', '')
    if not valid_timezone(tz):
        return jsonify({'message': 'Invalid timezone'}), 400
    try:
        subprocess.run(['timedatectl', 'set-timezone', tz], check=True, timeout=5)
        save_settings({'timezone': tz})
        return jsonify({'message': f'Timezone set to {tz}'})
    except Exception:
        log.exception('set_timezone failed tz=%s', tz)
        return jsonify({'message': 'Failed to set timezone'}), 500


@app.route('/api/system/auto-timezone', methods=['POST'])
def api_auto_timezone():
    try:
        j = req.get('https://ip-api.com/json', timeout=6).json()
        tz  = j.get('timezone', 'UTC')
        lat = j.get('lat')
        lon = j.get('lon')
        if not valid_timezone(tz):
            tz = 'UTC'
        save_settings({'timezone': tz, 'latitude': lat, 'longitude': lon})
        subprocess.run(['timedatectl', 'set-timezone', tz], timeout=5)
        return jsonify({'timezone': tz, 'message': f'Timezone set to {tz}'})
    except Exception:
        log.exception('auto_timezone failed')
        return jsonify({'message': 'Auto-detect failed'}), 500


@app.route('/api/system/reboot', methods=['POST'])
def api_reboot():
    log.warning('Reboot requested from %s', request.remote_addr)
    subprocess.Popen(['shutdown', '-r', 'now'])
    return jsonify({'ok': True})


@app.route('/api/system/shutdown', methods=['POST'])
def api_shutdown():
    log.warning('Shutdown requested from %s', request.remote_addr)
    subprocess.Popen(['shutdown', '-h', 'now'])
    return jsonify({'ok': True})


@app.route('/api/radio/play', methods=['POST'])
def api_radio_play():
    data = request.json or {}
    url  = data.get('url', '')
    name = data.get('name', 'Station')
    if url not in _ALLOWED_URLS:
        return jsonify({'ok': False, 'message': 'Unknown station'}), 400
    subprocess.run(['pkill', '-f', 'mpv'], stderr=subprocess.DEVNULL)
    subprocess.Popen(
        ['mpv', '--no-video', '--quiet', '--volume=70', url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return jsonify({'ok': True, 'message': f'Playing {name}'})


@app.route('/api/radio/stop', methods=['POST'])
def api_radio_stop():
    subprocess.run(['pkill', '-f', 'mpv'], stderr=subprocess.DEVNULL)
    return jsonify({'ok': True, 'message': 'Stopped'})


@app.route('/api/audio/volume', methods=['POST'])
def api_volume():
    vol = _safe_vol((request.json or {}).get('volume', 70))
    try:
        subprocess.run(['amixer', 'set', 'Master', f'{vol}%'], capture_output=True, timeout=3)
        return jsonify({'ok': True, 'volume': vol})
    except Exception:
        log.exception('amixer failed')
        return jsonify({'ok': False, 'message': 'Volume control failed'}), 500


@app.route('/api/audio/test', methods=['POST'])
def api_audio_test():
    subprocess.Popen(
        ['speaker-test', '-t', 'sine', '-f', '440', '-l', '1'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return jsonify({'ok': True, 'message': 'Playing 440 Hz test tone'})


@app.route('/api/display/resolution', methods=['POST'])
def api_resolution():
    res = (request.json or {}).get('resolution', '')
    if res not in _ALLOWED_RESOLUTIONS:
        return jsonify({'message': 'Invalid resolution'}), 400
    w, h = res.split('x')
    try:
        # Probe the actual connected output name first
        out = subprocess.check_output(['xrandr', '--query'], timeout=3, env={'DISPLAY': ':0'}).decode()
        output = next((l.split()[0] for l in out.splitlines() if ' connected' in l), 'HDMI-1')
        subprocess.run(['xrandr', '--output', output, '--mode', f'{w}x{h}'], capture_output=True, timeout=5,
                       env={'DISPLAY': ':0'})
        return jsonify({'message': f'Resolution set to {res}'})
    except Exception:
        log.exception('xrandr failed')
        return jsonify({'message': 'Display change failed'}), 500


@app.route('/api/display/brightness', methods=['POST'])
def api_brightness():
    try:
        val = max(10, min(100, int((request.json or {}).get('brightness', 80))))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': 'Invalid value'}), 400
    level = round(val / 100, 2)
    try:
        out = subprocess.check_output(['xrandr', '--query'], timeout=3, env={'DISPLAY': ':0'}).decode()
        output = next((l.split()[0] for l in out.splitlines() if ' connected' in l), 'HDMI-1')
        subprocess.run(['xrandr', '--output', output, '--brightness', str(level)],
                       capture_output=True, timeout=5, env={'DISPLAY': ':0'})
        return jsonify({'ok': True})
    except Exception:
        log.exception('xrandr brightness failed')
        return jsonify({'ok': False, 'message': 'Brightness change failed'}), 500


@app.route('/api/wifi/connect', methods=['POST'])
def api_wifi_connect():
    data     = request.json or {}
    ssid     = data.get('ssid', '')
    password = data.get('password', '')
    if not _valid_ssid(ssid):
        return jsonify({'message': 'Invalid SSID (1–32 characters)'}), 400
    if not _valid_password(password):
        return jsonify({'message': 'Password too long (max 63 characters)'}), 400
    try:
        subprocess.run(
            ['nmcli', '--ask', 'device', 'wifi', 'connect', ssid],
            input=f'{password}\n', capture_output=True, text=True, timeout=25
        )
        return jsonify({'message': f'Connecting to {ssid}'})
    except subprocess.TimeoutExpired:
        return jsonify({'message': 'Connection timed out — check SSID / password'}), 504
    except Exception:
        log.exception('WiFi connect failed ssid=%s', ssid)
        return jsonify({'message': 'Connection failed'}), 500


@app.route('/api/wifi/scan')
def api_wifi_scan():
    try:
        out = subprocess.check_output(
            ['nmcli', '-t', '-f', 'SSID', 'device', 'wifi', 'list'],
            timeout=12
        ).decode()
        networks = list(dict.fromkeys(  # deduplicate, preserve order
            l.strip() for l in out.splitlines() if l.strip() and l.strip() != '--'
        ))
        return jsonify({'networks': networks[:15]})
    except Exception:
        log.exception('WiFi scan failed')
        return jsonify({'message': 'Scan failed', 'networks': []}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5004, debug=False)
