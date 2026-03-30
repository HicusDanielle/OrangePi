"""Simple JSON-backed settings store shared across Flask apps."""
import json
import os
import tempfile
import threading
from typing import Any, Dict


_LOCK = threading.Lock()
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Cached timezone list (populated on first validation call)
_TZ_CACHE: list = []
_TZ_LOCK = threading.Lock()


def _config_dir() -> str:
    candidates = [
        os.path.join(_BASE_DIR, "config"),
        os.path.join(_BASE_DIR, "..", "config"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return os.path.abspath(path)
    return os.path.abspath(candidates[0])


_SETTINGS_PATH = os.path.normpath(os.path.join(_config_dir(), "user_settings.json"))

DEFAULTS: Dict[str, Any] = {
    "language": "en",
    "latitude": 51.5074,
    "longitude": -0.1278,
    "timezone": "UTC",
    "hardware_control": True,
    "first_run": False,
    "show_weewx": False,
    "show_netdata": False,
    "show_ha": False,
    "apps": {
        "weewx": "http://localhost:8080/weewx/",
        "netdata": "http://localhost:19999",
        "ha": "http://localhost:8123",
    },
}


def _ensure_file() -> None:
    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    if not os.path.exists(_SETTINGS_PATH):
        save_settings(DEFAULTS)


def load_settings() -> Dict[str, Any]:
    """Return settings merged with defaults."""
    _ensure_file()
    with _LOCK:
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        return {**DEFAULTS, **data}


def save_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Persist allowed keys atomically and return the saved settings."""
    _ensure_file()
    with _LOCK:
        current = load_settings()
        for key in DEFAULTS:
            if key in updates:
                current[key] = updates[key]
        # Atomic write: write to temp file then rename
        dir_ = os.path.dirname(_SETTINGS_PATH)
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, _SETTINGS_PATH)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return current


def toggle_first_run_done() -> Dict[str, Any]:
    """Mark the welcome wizard as completed."""
    return save_settings({"first_run": False})


def get_timezones() -> list:
    """Return cached list of valid IANA timezones from timedatectl."""
    global _TZ_CACHE
    with _TZ_LOCK:
        if _TZ_CACHE:
            return _TZ_CACHE
        try:
            import subprocess
            result = subprocess.run(
                ['timedatectl', 'list-timezones'],
                capture_output=True, text=True, timeout=5
            )
            _TZ_CACHE = [tz for tz in result.stdout.splitlines() if tz.strip()]
        except Exception:
            _TZ_CACHE = []
        return _TZ_CACHE


def valid_timezone(tz: str) -> bool:
    """Return True if tz is a known IANA timezone."""
    import re
    tzlist = get_timezones()
    if tzlist:
        return tz in tzlist
    # Fallback format check when timedatectl unavailable
    return bool(re.match(r'^[A-Za-z]+(/[A-Za-z_\-+0-9]+){0,2}$', tz))
