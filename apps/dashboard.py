#!/usr/bin/env python3
"""Control Dashboard - Unified SPA (Port 5004)
• Sidebar + swipe/back navigation
• First-run welcome wizard (4 steps)
• Settings panel with "Restart Setup" button
• All hardware calls active (no demo gates)
"""
from flask import Flask, jsonify, request
import subprocess
import re
import logging
import requests as req
from settings_store import load_settings, save_settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# ── Input validators ──────────────────────────────────────────────────────────
_RESOLUTION_RE = re.compile(r'^\d{3,4}x\d{3,4}$')
_ALLOWED_RESOLUTIONS = {'1024x600', '1280x720', '1920x1080'}
_STATION_URLS = {s['url'] for s in [
    {"url": "http://direct.franceinter.fr/live/franceinter-midfi.mp3"},
    {"url": "http://stream.nrj.fr/nrj.m3u8"},
    {"url": "http://stream.skyrock.fr/skyrock.m3u8"},
    {"url": "http://stream.europe1.fr/europe1.m3u8"},
    {"url": "http://direct.fip.fr/live/fip-midfi.mp3"},
    {"url": "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service"},
    {"url": "http://media-ice.musicradio.com/JazzFMMP3"},
]}

def _valid_timezone(tz: str) -> bool:
    try:
        result = subprocess.run(
            ['timedatectl', 'list-timezones'],
            capture_output=True, text=True, timeout=5
        )
        return tz in result.stdout.splitlines()
    except Exception:
        # fallback: basic format check
        return bool(re.match(r'^[A-Za-z]+(/[A-Za-z_]+){0,2}$', tz))

def _valid_ssid(ssid: str) -> bool:
    return isinstance(ssid, str) and 1 <= len(ssid) <= 32

def _valid_password(pw: str) -> bool:
    return isinstance(pw, str) and len(pw) <= 63

def _safe_vol(raw) -> int:
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return 70

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

# ── System helpers ────────────────────────────────────────────────────────────
def sys_temp():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return f"{int(f.read()) // 1000}°C"
    except Exception:
        return "N/A"

def sys_uptime():
    try:
        return subprocess.check_output(['uptime', '-p'], timeout=3).decode().strip()
    except Exception:
        return "N/A"

def sys_mem():
    try:
        parts = subprocess.check_output(['free', '-h'], timeout=3).decode().split('\n')[1].split()
        return f"{parts[2]} / {parts[1]}" if len(parts) > 2 else '--'
    except Exception:
        return "N/A"

def sys_disk():
    try:
        return subprocess.check_output(['df', '-h', '/'], timeout=3).decode().split('\n')[1].split()[4]
    except Exception:
        return "N/A"

def sys_ip():
    try:
        out = subprocess.check_output(['hostname', '-I'], timeout=3).decode().strip()
        return out.split()[0] if out else 'Unknown'
    except Exception:
        return 'Unknown'

def weather_data(lat, lon):
    try:
        url = (
            f'https://api.open-meteo.com/v1/forecast'
            f'?latitude={lat}&longitude={lon}'
            f'&current=temperature_2m,relative_humidity_2m,pressure_msl,wind_speed_10m,weathercode'
        )
        r = req.get(url, timeout=6)
        d = r.json()['current']
        code = d.get('weathercode', 0)
        icons = {0:'☀️',1:'🌤️',2:'⛅',3:'☁️',45:'🌫️',48:'🌫️',
                 51:'🌦️',61:'🌧️',71:'❄️',80:'🌦️',95:'⛈️'}
        return {
            'temp': f"{d['temperature_2m']}°C",
            'humidity': f"{d['relative_humidity_2m']}%",
            'pressure': f"{int(d['pressure_msl'])} hPa",
            'wind': f"{d['wind_speed_10m']} m/s",
            'icon': icons.get(code, '🌡️'),
            'ok': True,
        }
    except Exception:
        return {'temp':'--','humidity':'--','pressure':'--','wind':'--','icon':'🌡️','ok':False}

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=1024, height=600, initial-scale=1.0, user-scalable=no">
  <title>Orange Pi Dashboard</title>
  <style>
    *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
    html, body {
      width:1024px; height:600px; overflow:hidden;
      font-family:'Segoe UI',Arial,sans-serif;
      background:radial-gradient(120% 120% at 20% 20%,#0f172a 0%,#0b1022 40%,#050814 100%);
      color:#e2e8f0;
    }

    /* ── Shell ── */
    .shell { display:flex; width:1024px; height:600px; }

    /* ── Sidebar ── */
    .sidebar {
      width:190px; flex-shrink:0;
      background:rgba(0,0,0,0.45);
      border-right:1px solid rgba(255,255,255,0.08);
      display:flex; flex-direction:column;
      padding:14px 10px; gap:5px;
    }
    .sidebar-logo {
      text-align:center; font-size:15px; font-weight:700;
      padding:10px; margin-bottom:8px;
      background:rgba(255,255,255,0.06);
      border:1px solid rgba(255,255,255,0.1);
      border-radius:10px; letter-spacing:.4px;
    }
    .nav-btn {
      display:flex; align-items:center; gap:9px;
      padding:10px 12px; border-radius:8px;
      background:rgba(255,255,255,0.05);
      border:1px solid transparent;
      color:#cbd5e1; cursor:pointer; font-size:13px;
      transition:all .18s; user-select:none;
    }
    .nav-btn:hover { background:rgba(255,255,255,0.11); color:#fff; }
    .nav-btn.active { background:rgba(34,197,94,0.18); border-color:#22c55e; color:#4ade80; }
    .nav-btn .ico { font-size:16px; width:20px; text-align:center; }
    .sidebar-spacer { flex:1; }
    .hw-pill {
      text-align:center; padding:7px 10px; border-radius:8px;
      font-size:11px; background:rgba(34,197,94,0.14);
      border:1px solid #22c55e; color:#4ade80;
    }

    /* ── Main ── */
    .main { flex:1; display:flex; flex-direction:column; overflow:hidden; }
    .topbar {
      height:52px; flex-shrink:0;
      display:flex; align-items:center; justify-content:space-between;
      padding:0 20px;
      background:rgba(0,0,0,0.22);
      border-bottom:1px solid rgba(255,255,255,0.07);
    }
    .topbar h2 { font-size:17px; font-weight:600; }
    .topbar-right { display:flex; align-items:center; gap:10px; }
    .clock { font-size:13px; color:#94a3b8; font-variant-numeric:tabular-nums; }
    .back-btn {
      display:none; align-items:center; gap:5px;
      padding:6px 12px; border-radius:8px;
      background:rgba(255,255,255,0.09);
      border:1px solid rgba(255,255,255,0.14);
      color:#cbd5e1; cursor:pointer; font-size:12px;
    }
    .back-btn.visible { display:flex; }

    /* ── Panels ── */
    .panels { flex:1; position:relative; overflow:hidden; }
    .panel {
      position:absolute; inset:0;
      padding:18px 20px; overflow-y:auto;
      opacity:0; pointer-events:none;
      transform:translateX(40px);
      transition:opacity .23s ease, transform .23s ease;
    }
    .panel.active { opacity:1; pointer-events:all; transform:translateX(0); }
    .panel.slide-left { transform:translateX(-40px); }

    /* ── Grid / Widgets ── */
    .grid { display:grid; gap:13px; }
    .g2 { grid-template-columns:1fr 1fr; }
    .g3 { grid-template-columns:1fr 1fr 1fr; }
    .widget {
      background:linear-gradient(145deg,rgba(255,255,255,0.07),rgba(255,255,255,0.03));
      border:1px solid rgba(255,255,255,0.1);
      border-radius:14px; padding:17px;
    }
    .widget h3 { font-size:12px; color:#94a3b8; font-weight:500; margin-bottom:10px; text-transform:uppercase; letter-spacing:.5px; }
    .big-val { font-size:30px; font-weight:700; line-height:1; margin-bottom:4px; }
    .sub-val { font-size:12px; color:#94a3b8; }
    .stat-row { display:flex; justify-content:space-between; margin-top:5px; font-size:12px; color:#94a3b8; }

    /* Weather panel */
    .w-main { display:flex; align-items:center; gap:20px; margin-bottom:14px; }
    .w-icon-big { font-size:68px; }
    .w-details { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:2px; }
    .w-stat { background:rgba(255,255,255,0.06); border-radius:10px; padding:12px; }
    .w-stat-lbl { font-size:11px; color:#94a3b8; margin-bottom:4px; }
    .w-stat-val { font-size:22px; font-weight:600; }

    /* Radio panel */
    .radio-player {
      background:rgba(0,0,0,0.28); border:1px solid rgba(255,255,255,0.09);
      border-radius:13px; padding:18px; margin-bottom:14px;
      display:flex; align-items:center; gap:14px;
    }
    .radio-icon { font-size:38px; }
    .now-playing { flex:1; }
    .np-name { font-size:16px; font-weight:600; margin-bottom:3px; }
    .np-status { font-size:12px; color:#94a3b8; }
    .stations-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:9px; }
    .scard {
      background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.09);
      border-radius:9px; padding:13px 8px; text-align:center;
      cursor:pointer; transition:all .18s; font-size:12px;
    }
    .scard:hover { background:rgba(255,255,255,0.13); transform:translateY(-2px); }
    .scard.playing { background:rgba(34,197,94,0.18); border-color:#22c55e; color:#4ade80; }
    .vol-row { display:flex; align-items:center; gap:12px; margin-top:12px; }
    .vol-row label { font-size:12px; color:#94a3b8; width:54px; }
    .vol-row input[type=range] { flex:1; accent-color:#22c55e; cursor:pointer; }
    .vol-row span { font-size:12px; color:#cbd5e1; width:34px; text-align:right; }

    /* Config */
    .config-tabs { display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; }
    .ctab {
      padding:7px 15px; border-radius:8px; border:1px solid rgba(255,255,255,0.13);
      background:rgba(255,255,255,0.07); color:#cbd5e1;
      cursor:pointer; font-size:12px; transition:all .18s;
    }
    .ctab.active { background:rgba(34,197,94,0.18); border-color:#22c55e; color:#4ade80; }
    .ctab-panel { display:none; }
    .ctab-panel.active { display:block; }
    .field { margin-bottom:12px; }
    .field label { font-size:12px; color:#94a3b8; display:block; margin-bottom:5px; }
    .field input, .field select {
      width:100%; padding:9px 12px; border-radius:8px;
      border:1px solid rgba(255,255,255,0.14);
      background:rgba(255,255,255,0.07); color:#e2e8f0; font-size:13px;
    }
    .field-row { display:flex; gap:8px; }
    .field-row .field { flex:1; }

    /* System */
    .sys-grid { display:grid; grid-template-columns:1fr 1fr; gap:11px; }
    .sys-item { background:rgba(255,255,255,0.06); border-radius:10px; padding:13px; }
    .sys-lbl { font-size:11px; color:#94a3b8; margin-bottom:5px; }
    .sys-val { font-size:19px; font-weight:600; }

    /* Buttons */
    .btn {
      display:inline-flex; align-items:center; gap:6px;
      padding:9px 15px; border-radius:9px; font-size:13px;
      border:1px solid rgba(255,255,255,0.14);
      background:rgba(255,255,255,0.09); color:#e2e8f0;
      cursor:pointer; transition:all .18s;
    }
    .btn:hover { background:rgba(255,255,255,0.17); }
    .btn-green { background:rgba(34,197,94,0.2); border-color:#22c55e; color:#4ade80; }
    .btn-green:hover { background:rgba(34,197,94,0.3); }
    .btn-red { background:rgba(239,68,68,0.2); border-color:#ef4444; color:#f87171; }
    .btn-red:hover { background:rgba(239,68,68,0.3); }
    .btn-row { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
    .msg { font-size:12px; color:#94a3b8; margin-top:7px; min-height:17px; }

    /* Settings panel */
    .setting-row {
      display:flex; align-items:center; justify-content:space-between;
      padding:13px 16px; border-radius:10px;
      background:rgba(255,255,255,0.05);
      border:1px solid rgba(255,255,255,0.08);
      margin-bottom:10px;
    }
    .setting-row-label { font-size:13px; color:#e2e8f0; }
    .setting-row-sub { font-size:11px; color:#64748b; margin-top:2px; }
    .toggle-switch {
      position:relative; width:44px; height:24px;
      background:rgba(255,255,255,0.12); border-radius:12px;
      cursor:pointer; transition:background .2s; flex-shrink:0;
    }
    .toggle-switch.on { background:#22c55e; }
    .toggle-knob {
      position:absolute; top:3px; left:3px;
      width:18px; height:18px; border-radius:50%;
      background:#fff; transition:transform .2s;
    }
    .toggle-switch.on .toggle-knob { transform:translateX(20px); }

    /* ── First-Run Wizard ── */
    #wizard-overlay {
      position:fixed; inset:0; z-index:100;
      background:rgba(5,8,20,0.92);
      display:flex; align-items:center; justify-content:center;
      backdrop-filter:blur(4px);
    }
    .wizard-box {
      width:820px;
      background:linear-gradient(160deg,rgba(255,255,255,0.09),rgba(255,255,255,0.03));
      border:1px solid rgba(255,255,255,0.14);
      border-radius:20px; padding:28px 30px;
      box-shadow:0 24px 60px rgba(0,0,0,0.5);
    }
    .wiz-header { margin-bottom:18px; }
    .wiz-header h2 { font-size:22px; font-weight:700; margin-bottom:4px; }
    .wiz-header p { font-size:12px; color:#94a3b8; }
    .wiz-steps { display:flex; align-items:center; gap:8px; margin-bottom:20px; }
    .wiz-bubble {
      width:30px; height:30px; border-radius:50%;
      display:flex; align-items:center; justify-content:center;
      font-size:13px; font-weight:600;
      background:rgba(255,255,255,0.08);
      border:1px solid rgba(255,255,255,0.18); color:#94a3b8;
      transition:all .2s;
    }
    .wiz-bubble.done { background:#22c55e; border-color:#22c55e; color:#0f172a; }
    .wiz-bubble.active { background:rgba(34,197,94,0.2); border-color:#22c55e; color:#4ade80; box-shadow:0 0 12px rgba(34,197,94,0.4); }
    .wiz-line { flex:1; height:1px; background:rgba(255,255,255,0.1); }
    .wiz-panel {
      background:rgba(0,0,0,0.28); border:1px solid rgba(255,255,255,0.07);
      border-radius:14px; padding:20px; min-height:200px;
    }
    .wiz-panel label { font-size:12px; color:#94a3b8; display:block; margin-bottom:6px; }
    .wiz-panel input, .wiz-panel select {
      width:100%; padding:10px 13px; border-radius:9px;
      border:1px solid rgba(255,255,255,0.14);
      background:rgba(255,255,255,0.07); color:#e2e8f0; font-size:13px;
      margin-bottom:12px;
    }
    .wiz-row2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .wiz-toggle {
      display:flex; align-items:center; justify-content:space-between;
      padding:12px 14px; border-radius:10px;
      background:rgba(255,255,255,0.05);
      border:1px solid rgba(255,255,255,0.08);
      margin-bottom:10px; cursor:pointer;
    }
    .wiz-toggle-lbl { font-size:13px; color:#e2e8f0; }
    .wiz-toggle-sub { font-size:11px; color:#64748b; margin-top:2px; }
    .pill {
      padding:4px 11px; border-radius:999px;
      font-size:11px; font-weight:600;
      background:rgba(255,255,255,0.08);
      border:1px solid rgba(255,255,255,0.12); color:#94a3b8;
      transition:all .2s;
    }
    .pill.on { background:rgba(34,197,94,0.18); border-color:#22c55e; color:#4ade80; }
    .wiz-nav { display:flex; justify-content:space-between; align-items:center; margin-top:18px; }

    /* Toast */
    #toast {
      position:fixed; bottom:18px; left:50%; transform:translateX(-50%);
      background:rgba(34,197,94,0.92); color:#0f172a;
      padding:9px 20px; border-radius:10px; font-size:13px; font-weight:600;
      opacity:0; transition:opacity .3s; pointer-events:none; z-index:999;
    }
    #toast.show { opacity:1; }

    /* Scrollbar */
    ::-webkit-scrollbar { width:4px; }
    ::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.14); border-radius:4px; }
  </style>
</head>
<body>

<!-- ── First-Run Wizard Overlay ───────────────────────────────────────────── -->
<div id="wizard-overlay" style="display:none">
  <div class="wizard-box">
    <div class="wiz-header">
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
    <div class="wiz-panel" id="ws1">
      <label>Display Language</label>
      <select id="wiz-lang">
        <option value="en">English</option>
        <option value="fr">Français</option>
        <option value="es">Español</option>
        <option value="de">Deutsch</option>
        <option value="ar">العربية</option>
      </select>
    </div>

    <!-- Step 2: Location -->
    <div class="wiz-panel" id="ws2" style="display:none">
      <label>Your Coordinates (for weather)</label>
      <div class="wiz-row2">
        <div><label>Latitude</label><input id="wiz-lat" type="number" step="0.0001" placeholder="51.5074"></div>
        <div><label>Longitude</label><input id="wiz-lon" type="number" step="0.0001" placeholder="-0.1278"></div>
      </div>
      <div class="wiz-toggle" onclick="wizGeolocate()">
        <div>
          <div class="wiz-toggle-lbl">Auto-detect location</div>
          <div class="wiz-toggle-sub">Uses browser GPS or server GeoIP fallback</div>
        </div>
        <div class="pill" id="geo-pill">Not requested</div>
      </div>
    </div>

    <!-- Step 3: Timezone -->
    <div class="wiz-panel" id="ws3" style="display:none">
      <label>Timezone</label>
      <select id="wiz-tz">
        <option value="UTC">UTC</option>
        <option value="Europe/London">Europe/London</option>
        <option value="Europe/Paris">Europe/Paris</option>
        <option value="Europe/Berlin">Europe/Berlin</option>
        <option value="America/New_York">America/New_York</option>
        <option value="America/Chicago">America/Chicago</option>
        <option value="America/Los_Angeles">America/Los_Angeles</option>
        <option value="Asia/Tokyo">Asia/Tokyo</option>
        <option value="Asia/Shanghai">Asia/Shanghai</option>
        <option value="Australia/Sydney">Australia/Sydney</option>
      </select>
      <div class="wiz-toggle" onclick="wizAutoTz()">
        <div>
          <div class="wiz-toggle-lbl">Auto-detect & apply timezone</div>
          <div class="wiz-toggle-sub">Uses GeoIP — applies immediately via timedatectl</div>
        </div>
        <div class="pill" id="tz-pill">Not applied</div>
      </div>
    </div>

    <!-- Step 4: Hardware & optional apps -->
    <div class="wiz-panel" id="ws4" style="display:none">
      <div class="wiz-toggle" onclick="wizToggle('hw')">
        <div>
          <div class="wiz-toggle-lbl">Hardware Control Mode</div>
          <div class="wiz-toggle-sub">Enables WiFi, audio, radio, display — leave ON for real device</div>
        </div>
        <div class="pill on" id="pill-hw">Enabled</div>
      </div>
      <div class="wiz-toggle" onclick="wizToggle('weewx')">
        <div><div class="wiz-toggle-lbl">Show WeeWX weather station</div></div>
        <div class="pill" id="pill-weewx">Hidden</div>
      </div>
      <div class="wiz-toggle" onclick="wizToggle('netdata')">
        <div><div class="wiz-toggle-lbl">Show Netdata system monitor</div></div>
        <div class="pill" id="pill-netdata">Hidden</div>
      </div>
      <div class="wiz-toggle" onclick="wizToggle('ha')">
        <div><div class="wiz-toggle-lbl">Show Home Assistant</div></div>
        <div class="pill" id="pill-ha">Hidden</div>
      </div>
    </div>

    <div class="wiz-nav">
      <button class="btn" id="wiz-prev" onclick="wizPrev()" style="opacity:.4;pointer-events:none">← Back</button>
      <div style="display:flex;gap:8px">
        <button class="btn" onclick="wizSkip()">Skip</button>
        <button class="btn btn-green" id="wiz-next" onclick="wizNext()">Next →</button>
      </div>
    </div>
  </div>
</div>

<!-- ── Main Shell ─────────────────────────────────────────────────────────── -->
<div class="shell">
  <div class="sidebar">
    <div class="sidebar-logo">🍊 Orange Pi</div>
    <button class="nav-btn active" data-panel="dash" onclick="nav('dash',this)">
      <span class="ico">📊</span>Dashboard
    </button>
    <button class="nav-btn" data-panel="weather" onclick="nav('weather',this)">
      <span class="ico">🌤️</span>Weather
    </button>
    <button class="nav-btn" data-panel="radio" onclick="nav('radio',this)">
      <span class="ico">📻</span>Radio
    </button>
    <button class="nav-btn" data-panel="config" onclick="nav('config',this)">
      <span class="ico">⚙️</span>Device Config
    </button>
    <button class="nav-btn" data-panel="system" onclick="nav('system',this)">
      <span class="ico">💻</span>System
    </button>
    <button class="nav-btn" data-panel="settings" onclick="nav('settings',this)">
      <span class="ico">🔧</span>Settings
    </button>
    <div class="sidebar-spacer"></div>
    <div class="hw-pill">⚡ Hardware Active</div>
  </div>

  <div class="main">
    <div class="topbar">
      <h2 id="panel-title">📊 Dashboard</h2>
      <div class="topbar-right">
        <div class="clock" id="clock">--:--:--</div>
        <button class="back-btn" id="back-btn" onclick="goBack()">← Back</button>
      </div>
    </div>

    <div class="panels" id="panels"
         ontouchstart="swipeStart(event)" ontouchend="swipeEnd(event)">

      <!-- Dashboard -->
      <div class="panel active" id="panel-dash">
        <div class="grid g3">
          <div class="widget">
            <h3>Weather</h3>
            <div style="font-size:46px;text-align:center;margin-bottom:6px" id="d-wicon">🌡️</div>
            <div class="big-val" id="d-temp">--°C</div>
            <div class="stat-row">
              <span id="d-hum">Hum --</span><span id="d-wind">Wind --</span>
            </div>
          </div>
          <div class="widget">
            <h3>System</h3>
            <div class="big-val" style="font-size:24px;margin-bottom:6px" id="d-cpu">--</div>
            <div class="sub-val" id="d-mem">RAM --</div>
            <div class="sub-val" style="margin-top:4px" id="d-uptime">Up --</div>
          </div>
          <div class="widget">
            <h3>Radio</h3>
            <div style="font-size:28px;margin-bottom:8px">📻</div>
            <div class="sub-val" style="font-size:13px;color:#e2e8f0" id="d-radio-name">Stopped</div>
            <div class="btn-row" style="margin-top:10px">
              <button class="btn btn-green" onclick="quickPlay()">▶</button>
              <button class="btn btn-red" onclick="radioStop()">■</button>
            </div>
          </div>
        </div>
        <div class="grid g2" style="margin-top:13px">
          <div class="widget">
            <h3>Quick Navigation</h3>
            <div class="btn-row">
              <button class="btn" onclick="nav('weather',null)">🌤️ Weather</button>
              <button class="btn" onclick="nav('radio',null)">📻 Radio</button>
              <button class="btn" onclick="nav('config',null)">⚙️ Config</button>
            </div>
          </div>
          <div class="widget">
            <h3>Network</h3>
            <div style="font-size:18px;font-weight:600;margin-bottom:6px" id="d-ip">--</div>
            <div class="sub-val" id="d-disk">Disk --</div>
          </div>
        </div>
      </div>

      <!-- Weather -->
      <div class="panel" id="panel-weather">
        <div class="w-main">
          <div class="w-icon-big" id="w-icon">🌡️</div>
          <div>
            <div style="font-size:52px;font-weight:700;line-height:1" id="w-temp">--</div>
            <div style="font-size:13px;color:#94a3b8;margin-top:4px" id="w-loc">Loading...</div>
          </div>
        </div>
        <div class="w-details">
          <div class="w-stat"><div class="w-stat-lbl">Humidity</div><div class="w-stat-val" id="w-hum">--</div></div>
          <div class="w-stat"><div class="w-stat-lbl">Pressure</div><div class="w-stat-val" id="w-pres">--</div></div>
          <div class="w-stat"><div class="w-stat-lbl">Wind Speed</div><div class="w-stat-val" id="w-wind">--</div></div>
          <div class="w-stat"><div class="w-stat-lbl">Updated</div><div class="w-stat-val" style="font-size:15px" id="w-updated">--</div></div>
        </div>
        <div class="btn-row" style="margin-top:14px">
          <button class="btn" onclick="loadWeather()">🔄 Refresh</button>
        </div>
      </div>

      <!-- Radio -->
      <div class="panel" id="panel-radio">
        <div class="radio-player">
          <div class="radio-icon">📻</div>
          <div class="now-playing">
            <div class="np-name" id="r-name">Not playing</div>
            <div class="np-status" id="r-status">Select a station below</div>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn btn-green" onclick="radioPlay()">▶ Play</button>
            <button class="btn btn-red" onclick="radioStop()">■ Stop</button>
          </div>
        </div>
        <div class="vol-row">
          <label>Volume</label>
          <input type="range" min="0" max="100" value="70" id="vol-slider" oninput="setVolume(this.value)">
          <span id="vol-val">70%</span>
        </div>
        <div class="stations-grid" id="stations-grid" style="margin-top:14px"></div>
      </div>

      <!-- Device Config -->
      <div class="panel" id="panel-config">
        <div class="config-tabs">
          <button class="ctab active" onclick="ctab('net',this)">📡 Network</button>
          <button class="ctab" onclick="ctab('audio',this)">🔊 Audio</button>
          <button class="ctab" onclick="ctab('display',this)">🖥️ Display</button>
          <button class="ctab" onclick="ctab('sysconf',this)">🔧 System</button>
        </div>
        <!-- Network -->
        <div class="ctab-panel active" id="ct-net">
          <div class="widget">
            <h3>WiFi</h3>
            <div class="field-row">
              <div class="field"><label>SSID</label><input id="ssid" type="text" placeholder="Network name"></div>
              <div class="field"><label>Password</label><input id="wifi-pass" type="password" placeholder="Password"></div>
            </div>
            <div class="btn-row">
              <button class="btn btn-green" onclick="connectWifi()">Connect</button>
              <button class="btn" onclick="scanWifi()">🔍 Scan</button>
            </div>
            <div class="msg" id="net-msg"></div>
          </div>
          <div class="widget" style="margin-top:11px">
            <h3>IP Address</h3>
            <div style="font-size:20px;font-weight:600;margin-bottom:8px" id="ip-val">--</div>
            <button class="btn" onclick="refreshIP()">🔄 Refresh</button>
          </div>
        </div>
        <!-- Audio -->
        <div class="ctab-panel" id="ct-audio">
          <div class="widget">
            <h3>Volume</h3>
            <div class="vol-row" style="margin-bottom:12px">
              <label>Master</label>
              <input type="range" min="0" max="100" value="70" id="cfg-vol" oninput="cfgVolume(this.value)">
              <span id="cfg-vol-val">70%</span>
            </div>
            <div class="btn-row">
              <button class="btn" onclick="testAudio()">🔊 Test</button>
              <button class="btn btn-red" onclick="muteAudio()">🔇 Mute</button>
            </div>
            <div class="msg" id="audio-msg"></div>
          </div>
        </div>
        <!-- Display -->
        <div class="ctab-panel" id="ct-display">
          <div class="widget">
            <h3>Resolution</h3>
            <div class="field">
              <label>Resolution</label>
              <select id="resolution">
                <option value="1024x600">1024×600 (Default)</option>
                <option value="1280x720">1280×720 (HD)</option>
                <option value="1920x1080">1920×1080 (Full HD)</option>
              </select>
            </div>
            <div class="btn-row"><button class="btn btn-green" onclick="applyRes()">Apply</button></div>
            <div class="msg" id="disp-msg"></div>
          </div>
          <div class="widget" style="margin-top:11px">
            <h3>Brightness</h3>
            <div class="vol-row">
              <label>Level</label>
              <input type="range" min="10" max="100" value="80" id="bright-slider" oninput="setBright(this.value)">
              <span id="bright-val">80%</span>
            </div>
          </div>
        </div>
        <!-- System config -->
        <div class="ctab-panel" id="ct-sysconf">
          <div class="widget">
            <h3>Timezone</h3>
            <div class="field">
              <label>Select Timezone</label>
              <select id="tz-select">
                <option value="UTC">UTC</option>
                <option value="Europe/London">Europe/London</option>
                <option value="Europe/Paris">Europe/Paris</option>
                <option value="Europe/Berlin">Europe/Berlin</option>
                <option value="America/New_York">America/New_York</option>
                <option value="America/Chicago">America/Chicago</option>
                <option value="America/Los_Angeles">America/Los_Angeles</option>
                <option value="Asia/Tokyo">Asia/Tokyo</option>
                <option value="Asia/Shanghai">Asia/Shanghai</option>
                <option value="Australia/Sydney">Australia/Sydney</option>
              </select>
            </div>
            <div class="btn-row">
              <button class="btn btn-green" onclick="setTimezone()">Save</button>
              <button class="btn" onclick="autoTimezone()">🌐 Auto-detect</button>
            </div>
            <div class="msg" id="tz-msg"></div>
          </div>
          <div class="widget" style="margin-top:11px">
            <h3>Power</h3>
            <div class="btn-row">
              <button class="btn btn-red" onclick="confirmReboot()">🔄 Reboot</button>
              <button class="btn btn-red" onclick="confirmShutdown()">⏻ Shutdown</button>
            </div>
          </div>
        </div>
      </div>

      <!-- System -->
      <div class="panel" id="panel-system">
        <div class="sys-grid">
          <div class="sys-item"><div class="sys-lbl">CPU Temperature</div><div class="sys-val" id="s-cpu">--</div></div>
          <div class="sys-item"><div class="sys-lbl">Memory</div><div class="sys-val" style="font-size:15px" id="s-mem">--</div></div>
          <div class="sys-item"><div class="sys-lbl">Disk Used</div><div class="sys-val" id="s-disk">--</div></div>
          <div class="sys-item"><div class="sys-lbl">Uptime</div><div class="sys-val" style="font-size:14px" id="s-uptime">--</div></div>
          <div class="sys-item"><div class="sys-lbl">IP Address</div><div class="sys-val" style="font-size:15px" id="s-ip">--</div></div>
          <div class="sys-item"><div class="sys-lbl">Hostname</div><div class="sys-val" style="font-size:15px" id="s-host">--</div></div>
        </div>
        <div class="btn-row" style="margin-top:14px">
          <button class="btn" onclick="loadSystem()">🔄 Refresh</button>
        </div>
      </div>

      <!-- Settings -->
      <div class="panel" id="panel-settings">
        <div class="widget" style="margin-bottom:13px">
          <h3>Location & Language</h3>
          <div class="field-row" style="margin-top:8px">
            <div class="field"><label>Latitude</label><input id="set-lat" type="number" step="0.0001"></div>
            <div class="field"><label>Longitude</label><input id="set-lon" type="number" step="0.0001"></div>
            <div class="field">
              <label>Language</label>
              <select id="set-lang">
                <option value="en">English</option>
                <option value="fr">Français</option>
                <option value="es">Español</option>
                <option value="de">Deutsch</option>
                <option value="ar">العربية</option>
              </select>
            </div>
          </div>
          <div class="btn-row">
            <button class="btn btn-green" onclick="saveLocationLang()">Save</button>
            <button class="btn" onclick="geoIPSettings()">🌐 Auto-detect</button>
          </div>
          <div class="msg" id="loc-msg"></div>
        </div>
        <div class="widget" style="margin-bottom:13px">
          <h3>Optional Apps</h3>
          <div class="setting-row" onclick="toggleAppFlag('show_weewx')">
            <div><div class="setting-row-label">WeeWX Weather Station</div><div class="setting-row-sub">Local HTML weather reports</div></div>
            <div class="toggle-switch" id="sw-weewx"><div class="toggle-knob"></div></div>
          </div>
          <div class="setting-row" onclick="toggleAppFlag('show_netdata')">
            <div><div class="setting-row-label">Netdata Monitor</div><div class="setting-row-sub">Real-time CPU/memory/disk graphs</div></div>
            <div class="toggle-switch" id="sw-netdata"><div class="toggle-knob"></div></div>
          </div>
          <div class="setting-row" onclick="toggleAppFlag('show_ha')">
            <div><div class="setting-row-label">Home Assistant</div><div class="setting-row-sub">Full smart-home dashboard</div></div>
            <div class="toggle-switch" id="sw-ha"><div class="toggle-knob"></div></div>
          </div>
        </div>
        <div class="widget">
          <h3>Setup Wizard</h3>
          <p style="font-size:12px;color:#94a3b8;margin-bottom:12px">Re-run the welcome wizard to reconfigure language, location, timezone, and hardware mode.</p>
          <button class="btn btn-green" onclick="openWizard()">↩ Restart Setup Wizard</button>
        </div>
      </div>

    </div><!-- /panels -->
  </div><!-- /main -->
</div><!-- /shell -->

<div id="toast"></div>

<script>
const STATIONS = """ + str(STATIONS).replace("'", '"') + r""";
let currentStation = 0;
let radioPlaying = false;
let navHistory = ['dash'];
const PANELS = ['dash','weather','radio','config','system','settings'];
const TITLES = {
  dash:'📊 Dashboard', weather:'🌤️ Weather', radio:'📻 Internet Radio',
  config:'⚙️ Device Config', system:'💻 System', settings:'🔧 Settings'
};

// ── Settings (in-memory mirror) ───────────────────────────────────────────────
let CFG = {};

function loadCFG() {
  fetch('/api/settings').then(r=>r.json()).then(s=>{
    CFG = s;
    // Populate settings panel fields
    if (document.getElementById('set-lat')) {
      document.getElementById('set-lat').value = s.latitude || '';
      document.getElementById('set-lon').value = s.longitude || '';
      document.getElementById('set-lang').value = s.language || 'en';
    }
    // Toggle switches
    updateSwitch('sw-weewx', s.show_weewx);
    updateSwitch('sw-netdata', s.show_netdata);
    updateSwitch('sw-ha', s.show_ha);
    // Timezone selector
    if (s.timezone) {
      const sel = document.getElementById('tz-select');
      if (sel && [...sel.options].some(o=>o.value===s.timezone)) sel.value = s.timezone;
    }
    // First-run check
    if (s.first_run) openWizard();
  });
}

function updateSwitch(id, on) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('on', !!on);
}

function toggleAppFlag(key) {
  CFG[key] = !CFG[key];
  const swMap = {show_weewx:'sw-weewx', show_netdata:'sw-netdata', show_ha:'sw-ha'};
  updateSwitch(swMap[key], CFG[key]);
  fetch('/api/settings/save', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({[key]: CFG[key]})
  });
}

function saveLocationLang() {
  const lat = parseFloat(document.getElementById('set-lat').value);
  const lon = parseFloat(document.getElementById('set-lon').value);
  const lang = document.getElementById('set-lang').value;
  fetch('/api/settings/save', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({latitude:lat, longitude:lon, language:lang})
  }).then(r=>r.json()).then(()=>{
    document.getElementById('loc-msg').textContent = 'Saved.';
    toast('Settings saved');
  });
}

function geoIPSettings() {
  document.getElementById('loc-msg').textContent = 'Detecting...';
  fetch('/api/system/auto-timezone', {method:'POST'}).then(r=>r.json()).then(d=>{
    document.getElementById('loc-msg').textContent = d.message || 'Done';
    loadCFG();
  });
}

// ── Navigation ────────────────────────────────────────────────────────────────
function nav(id, btn) {
  const prev = navHistory[navHistory.length - 1];
  if (prev === id) return;
  const oldEl = document.getElementById('panel-' + prev);
  oldEl.classList.remove('active');
  oldEl.classList.add('slide-left');
  setTimeout(() => oldEl.classList.remove('slide-left'), 260);

  const newEl = document.getElementById('panel-' + id);
  newEl.style.transform = 'translateX(40px)';
  newEl.classList.add('active');
  setTimeout(() => { newEl.style.transform = ''; }, 10);

  document.getElementById('panel-title').textContent = TITLES[id];
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  const target = btn || document.querySelector(`[data-panel="${id}"]`);
  if (target) target.classList.add('active');

  navHistory.push(id);
  document.getElementById('back-btn').classList.toggle('visible', navHistory.length > 1);

  if (id === 'weather') loadWeather();
  if (id === 'system') loadSystem();
  if (id === 'config') refreshIP();
  if (id === 'dash') loadDash();
  if (id === 'settings') loadCFG();
}

function goBack() {
  if (navHistory.length <= 1) return;
  navHistory.pop();
  const prev = navHistory[navHistory.length - 1];
  const oldEl = document.getElementById('panel-' + PANELS[PANELS.indexOf(prev) === -1 ? 0 : PANELS.indexOf(prev)]);
  // re-navigate to prev without pushing history again
  const cur = navHistory[navHistory.length - 1];
  navHistory.pop();
  nav(cur, null);
  document.getElementById('back-btn').classList.toggle('visible', navHistory.length > 1);
}

// ── Swipe ─────────────────────────────────────────────────────────────────────
let swX=0, swY=0;
function swipeStart(e){ swX=e.changedTouches[0].clientX; swY=e.changedTouches[0].clientY; }
function swipeEnd(e){
  const dx=e.changedTouches[0].clientX-swX, dy=e.changedTouches[0].clientY-swY;
  if (Math.abs(dx)<Math.abs(dy)||Math.abs(dx)<50) return;
  if (dx>0) { goBack(); }
  else {
    const cur=navHistory[navHistory.length-1], idx=PANELS.indexOf(cur);
    if (idx<PANELS.length-1) nav(PANELS[idx+1],null);
  }
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function tick(){
  document.getElementById('clock').textContent=new Date().toLocaleTimeString('en-GB',{hour12:false});
}
tick(); setInterval(tick,1000);

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg,color){
  const el=document.getElementById('toast');
  el.textContent=msg; el.style.background=color||'rgba(34,197,94,0.92)';
  el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),2500);
}

// ── Weather ───────────────────────────────────────────────────────────────────
function loadWeather(){
  fetch('/api/weather').then(r=>r.json()).then(d=>{
    document.getElementById('w-icon').textContent=d.icon;
    document.getElementById('w-temp').textContent=d.temp;
    document.getElementById('w-hum').textContent=d.humidity;
    document.getElementById('w-pres').textContent=d.pressure;
    document.getElementById('w-wind').textContent=d.wind;
    document.getElementById('w-loc').textContent=`Lat ${d.lat} · Lon ${d.lon}`;
    document.getElementById('w-updated').textContent=new Date().toLocaleTimeString('en-GB',{hour12:false});
    document.getElementById('d-wicon').textContent=d.icon;
    document.getElementById('d-temp').textContent=d.temp;
    document.getElementById('d-hum').textContent=`Hum ${d.humidity}`;
    document.getElementById('d-wind').textContent=`Wind ${d.wind}`;
  });
}

// ── System ────────────────────────────────────────────────────────────────────
function loadSystem(){
  fetch('/api/system').then(r=>r.json()).then(d=>{
    document.getElementById('s-cpu').textContent=d.temp;
    document.getElementById('s-mem').textContent=d.memory;
    document.getElementById('s-disk').textContent=d.disk;
    document.getElementById('s-uptime').textContent=d.uptime;
    document.getElementById('s-ip').textContent=d.ip;
    document.getElementById('s-host').textContent=d.hostname||'--';
  });
}

function loadDash(){
  fetch('/api/system').then(r=>r.json()).then(d=>{
    document.getElementById('d-cpu').textContent=d.temp;
    document.getElementById('d-mem').textContent=`RAM ${d.memory}`;
    document.getElementById('d-uptime').textContent=`Up ${d.uptime}`;
    document.getElementById('d-ip').textContent=d.ip;
    document.getElementById('d-disk').textContent=`Disk ${d.disk}`;
  });
  loadWeather();
}

// ── Radio ─────────────────────────────────────────────────────────────────────
function buildStations(){
  document.getElementById('stations-grid').innerHTML=
    STATIONS.map((s,i)=>`<div class="scard" id="sc-${i}" onclick="selectStation(${i})">${s.name}</div>`).join('');
}
function selectStation(i){
  currentStation=i;
  document.querySelectorAll('.scard').forEach(c=>c.classList.remove('playing'));
  document.getElementById('sc-'+i).classList.add('playing');
  radioPlay();
}
function radioPlay(){
  const s=STATIONS[currentStation];
  document.getElementById('r-name').textContent=s.name;
  document.getElementById('r-status').textContent='Connecting...';
  fetch('/api/radio/play',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({url:s.url,name:s.name})
  }).then(r=>r.json()).then(d=>{
    document.getElementById('r-status').textContent=d.message||'Playing';
    document.getElementById('d-radio-name').textContent=s.name;
    radioPlaying=true;
    document.querySelectorAll('.scard').forEach(c=>c.classList.remove('playing'));
    const el=document.getElementById('sc-'+currentStation);
    if(el) el.classList.add('playing');
    toast('▶ '+s.name);
  });
}
function radioStop(){
  fetch('/api/radio/stop',{method:'POST'}).then(r=>r.json()).then(()=>{
    document.getElementById('r-status').textContent='Stopped';
    document.getElementById('d-radio-name').textContent='Stopped';
    radioPlaying=false;
    document.querySelectorAll('.scard').forEach(c=>c.classList.remove('playing'));
    toast('■ Stopped','rgba(239,68,68,0.9)');
  });
}
function quickPlay(){ radioPlay(); nav('radio',null); }
function setVolume(v){
  document.getElementById('vol-val').textContent=v+'%';
  fetch('/api/audio/volume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({volume:parseInt(v)})});
}

// ── Config tabs ───────────────────────────────────────────────────────────────
function ctab(id,btn){
  document.querySelectorAll('.ctab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.ctab').forEach(b=>b.classList.remove('active'));
  document.getElementById('ct-'+id).classList.add('active');
  btn.classList.add('active');
}
function connectWifi(){
  const ssid=document.getElementById('ssid').value.trim();
  const pass=document.getElementById('wifi-pass').value;
  if(!ssid){document.getElementById('net-msg').textContent='Enter SSID';return;}
  document.getElementById('net-msg').textContent='Connecting...';
  fetch('/api/wifi/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid,password:pass})})
    .then(r=>r.json()).then(d=>{document.getElementById('net-msg').textContent=d.message;toast(d.message);});
}
function scanWifi(){
  document.getElementById('net-msg').textContent='Scanning...';
  fetch('/api/wifi/scan').then(r=>r.json()).then(d=>{
    document.getElementById('net-msg').textContent=d.networks&&d.networks.length?'Found: '+d.networks.join(', '):(d.message||'No networks found');
  });
}
function refreshIP(){
  fetch('/api/system/ip').then(r=>r.json()).then(d=>document.getElementById('ip-val').textContent=d.ip||'--');
}
function cfgVolume(v){
  document.getElementById('cfg-vol-val').textContent=v+'%';
  fetch('/api/audio/volume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({volume:parseInt(v)})});
}
function testAudio(){
  document.getElementById('audio-msg').textContent='Playing test tone...';
  fetch('/api/audio/test',{method:'POST'}).then(r=>r.json()).then(d=>{document.getElementById('audio-msg').textContent=d.message||'Done';});
}
function muteAudio(){
  fetch('/api/audio/volume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({volume:0})}).then(()=>{
    document.getElementById('cfg-vol').value=0;
    document.getElementById('cfg-vol-val').textContent='0%';
    document.getElementById('audio-msg').textContent='Muted';
    toast('🔇 Muted','rgba(239,68,68,0.9)');
  });
}
function applyRes(){
  const res=document.getElementById('resolution').value;
  fetch('/api/display/resolution',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resolution:res})})
    .then(r=>r.json()).then(d=>{document.getElementById('disp-msg').textContent=d.message;toast(d.message);});
}
function setBright(v){
  document.getElementById('bright-val').textContent=v+'%';
  fetch('/api/display/brightness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({brightness:parseInt(v)})});
}
function setTimezone(){
  const tz=document.getElementById('tz-select').value;
  fetch('/api/system/timezone',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({timezone:tz})})
    .then(r=>r.json()).then(d=>{document.getElementById('tz-msg').textContent=d.message;toast(d.message);});
}
function autoTimezone(){
  document.getElementById('tz-msg').textContent='Detecting...';
  fetch('/api/system/auto-timezone',{method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.timezone){const s=document.getElementById('tz-select');if([...s.options].some(o=>o.value===d.timezone))s.value=d.timezone;}
    document.getElementById('tz-msg').textContent=d.message;toast(d.message);
  });
}
function confirmReboot(){if(!confirm('Reboot the Orange Pi?'))return;fetch('/api/system/reboot',{method:'POST'});toast('🔄 Rebooting...','rgba(239,68,68,0.9)');}
function confirmShutdown(){if(!confirm('Shutdown the Orange Pi?'))return;fetch('/api/system/shutdown',{method:'POST'});toast('⏻ Shutting down...','rgba(239,68,68,0.9)');}

// ── First-Run Wizard ──────────────────────────────────────────────────────────
let wizStep = 1;
let wizData = { hardware_control:true, show_weewx:false, show_netdata:false, show_ha:false };

const WIZ_TITLES = ['Language','Location','Timezone','Hardware & Apps'];
const WIZ_DESCS  = [
  'Choose your display language.',
  'Set your coordinates for accurate weather.',
  'Select your timezone — applied immediately.',
  'Configure hardware mode and optional integrations.'
];

function openWizard(){
  wizStep=1;
  wizData={hardware_control:true, show_weewx:false, show_netdata:false, show_ha:false};
  updateWizPills();
  renderWizStep(1);
  document.getElementById('wizard-overlay').style.display='flex';
}

function renderWizStep(n){
  for(let i=1;i<=4;i++){
    document.getElementById('ws'+i).style.display = i===n?'block':'none';
    const b=document.getElementById('wb'+i);
    b.className='wiz-bubble'+(i<n?' done':i===n?' active':'');
  }
  document.getElementById('wiz-title').textContent=WIZ_TITLES[n-1];
  document.getElementById('wiz-desc').textContent=WIZ_DESCS[n-1];
  document.getElementById('wiz-prev').style.opacity=n===1?'.4':'1';
  document.getElementById('wiz-prev').style.pointerEvents=n===1?'none':'all';
  document.getElementById('wiz-next').textContent=n===4?'Finish ✓':'Next →';
}

function wizNext(){
  if(wizStep===4){ wizFinish(); return; }
  wizStep++; renderWizStep(wizStep);
}
function wizPrev(){ if(wizStep>1){ wizStep--; renderWizStep(wizStep); } }
function wizSkip(){
  fetch('/api/wizard/skip',{method:'POST'});
  document.getElementById('wizard-overlay').style.display='none';
}

function wizGeolocate(){
  if(navigator.geolocation){
    navigator.geolocation.getCurrentPosition(pos=>{
      document.getElementById('wiz-lat').value=pos.coords.latitude.toFixed(4);
      document.getElementById('wiz-lon').value=pos.coords.longitude.toFixed(4);
      document.getElementById('geo-pill').textContent='GPS set'; document.getElementById('geo-pill').classList.add('on');
    }, ()=>wizServerGeoIP());
  } else { wizServerGeoIP(); }
}

function wizServerGeoIP(){
  fetch('/api/system/geoip').then(r=>r.json()).then(d=>{
    if(d.latitude) document.getElementById('wiz-lat').value=d.latitude.toFixed(4);
    if(d.longitude) document.getElementById('wiz-lon').value=d.longitude.toFixed(4);
    document.getElementById('geo-pill').textContent='GeoIP set'; document.getElementById('geo-pill').classList.add('on');
  });
}

function wizAutoTz(){
  document.getElementById('tz-pill').textContent='Detecting...';
  fetch('/api/system/auto-timezone',{method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.timezone){const s=document.getElementById('wiz-tz');if([...s.options].some(o=>o.value===d.timezone))s.value=d.timezone;}
    document.getElementById('tz-pill').textContent=d.message?'Applied':'Done';
    document.getElementById('tz-pill').classList.add('on');
  });
}

function wizToggle(key){
  const map={hw:'hardware_control',weewx:'show_weewx',netdata:'show_netdata',ha:'show_ha'};
  const k=map[key]; wizData[k]=!wizData[k]; updateWizPills();
}
function updateWizPills(){
  const fields=[['hw','hardware_control','Enabled','Disabled'],['weewx','show_weewx','Shown','Hidden'],['netdata','show_netdata','Shown','Hidden'],['ha','show_ha','Shown','Hidden']];
  fields.forEach(([key,prop,yes,no])=>{
    const el=document.getElementById('pill-'+key);
    if(!el)return;
    const on=!!wizData[prop];
    el.textContent=on?yes:no;
    el.classList.toggle('on',on);
  });
}

function wizFinish(){
  const body={
    language: document.getElementById('wiz-lang').value||'en',
    latitude: parseFloat(document.getElementById('wiz-lat').value)||51.5074,
    longitude: parseFloat(document.getElementById('wiz-lon').value)||-0.1278,
    timezone: document.getElementById('wiz-tz').value||'UTC',
    hardware_control: !!wizData.hardware_control,
    show_weewx: !!wizData.show_weewx,
    show_netdata: !!wizData.show_netdata,
    show_ha: !!wizData.show_ha,
    first_run: false,
  };
  fetch('/api/wizard/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(()=>{
      document.getElementById('wizard-overlay').style.display='none';
      toast('Setup complete!'); loadDash(); loadCFG();
    });
}

// ── Boot ──────────────────────────────────────────────────────────────────────
buildStations();
loadCFG();
loadDash();
setInterval(loadDash,30000);
</script>
</body>
</html>"""


# ── API ───────────────────────────────────────────────────────────────────────
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


@app.route('/api/wizard/finish', methods=['POST'])
def api_wizard_finish():
    data = request.json or {}
    data['first_run'] = False
    tz = data.get('timezone', 'UTC')
    if not _valid_timezone(tz):
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
        'temp': sys_temp(),
        'memory': sys_mem(),
        'uptime': sys_uptime(),
        'disk': sys_disk(),
        'ip': sys_ip(),
        'hostname': hostname,
    })


@app.route('/api/system/ip')
def api_ip():
    return jsonify({'ip': sys_ip()})


@app.route('/api/system/geoip')
def api_geoip():
    try:
        j = req.get('https://ip-api.com/json', timeout=5).json()
        return jsonify({
            'latitude': j.get('lat'),
            'longitude': j.get('lon'),
            'timezone': j.get('timezone'),
        })
    except Exception:
        log.warning('GeoIP lookup failed')
        return jsonify({'error': 'geoip_failed'})


@app.route('/api/system/timezone', methods=['POST'])
def api_set_timezone():
    tz = (request.json or {}).get('timezone', 'UTC')
    if not _valid_timezone(tz):
        return jsonify({'message': 'Invalid timezone'}), 400
    try:
        subprocess.run(['timedatectl', 'set-timezone', tz], check=True, timeout=5)
        save_settings({'timezone': tz})
        return jsonify({'message': f'Timezone set to {tz}'})
    except Exception:
        log.exception('Failed to set timezone')
        return jsonify({'message': 'Failed to set timezone'}), 500


@app.route('/api/system/auto-timezone', methods=['POST'])
def api_auto_timezone():
    try:
        j = req.get('https://ip-api.com/json', timeout=5).json()
        tz = j.get('timezone', 'UTC')
        lat, lon = j.get('lat'), j.get('lon')
        if not _valid_timezone(tz):
            tz = 'UTC'
        save_settings({'timezone': tz, 'latitude': lat, 'longitude': lon})
        subprocess.run(['timedatectl', 'set-timezone', tz], timeout=5)
        return jsonify({'timezone': tz, 'message': f'Timezone set to {tz}'})
    except Exception:
        log.exception('Auto-timezone failed')
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
    url = data.get('url', '')
    name = data.get('name', 'Station')
    if url not in _STATION_URLS:
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
        subprocess.run(
            ['xrandr', '--output', 'HDMI-1', '--mode', f'{w}x{h}'],
            capture_output=True, timeout=5
        )
        return jsonify({'message': f'Resolution set to {res}'})
    except Exception:
        log.exception('xrandr failed')
        return jsonify({'message': 'Display change failed'}), 500


@app.route('/api/display/brightness', methods=['POST'])
def api_brightness():
    try:
        val = max(10, min(100, int((request.json or {}).get('brightness', 80))))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': 'Invalid brightness value'}), 400
    level = round(val / 100, 2)
    try:
        subprocess.run(
            ['xrandr', '--output', 'HDMI-1', '--brightness', str(level)],
            capture_output=True, timeout=5
        )
        return jsonify({'ok': True})
    except Exception:
        log.exception('xrandr brightness failed')
        return jsonify({'ok': False, 'message': 'Brightness change failed'}), 500


@app.route('/api/wifi/connect', methods=['POST'])
def api_wifi_connect():
    data = request.json or {}
    ssid = data.get('ssid', '')
    password = data.get('password', '')
    if not _valid_ssid(ssid):
        return jsonify({'message': 'Invalid SSID (1-32 characters)'}), 400
    if not _valid_password(password):
        return jsonify({'message': 'Password too long (max 63 characters)'}), 400
    try:
        # Pass credentials via stdin to avoid exposure in process list
        proc_input = f'{password}\n'
        subprocess.run(
            ['nmcli', '--ask', 'device', 'wifi', 'connect', ssid],
            input=proc_input, capture_output=True, text=True, timeout=20
        )
        return jsonify({'message': f'Connecting to {ssid}'})
    except subprocess.TimeoutExpired:
        return jsonify({'message': 'Connection timed out'}), 504
    except Exception:
        log.exception('WiFi connect failed for SSID: %s', ssid)
        return jsonify({'message': 'Connection failed'}), 500


@app.route('/api/wifi/scan')
def api_wifi_scan():
    try:
        out = subprocess.check_output(
            ['nmcli', '-t', '-f', 'SSID', 'device', 'wifi', 'list'],
            timeout=10
        ).decode()
        networks = [l.strip() for l in out.splitlines() if l.strip() and l.strip() != '--']
        return jsonify({'networks': networks[:12]})
    except Exception:
        log.exception('WiFi scan failed')
        return jsonify({'message': 'Scan failed', 'networks': []}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5004, debug=False)
