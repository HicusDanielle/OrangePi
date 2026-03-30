"""Simple JSON-backed settings store shared across Flask apps."""
import json
import os
import threading
from typing import Any, Dict


_LOCK = threading.Lock()
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _config_dir() -> str:
    """Locate the config directory whether running in-repo (apps/) or deployed (/opt/weather_station)."""
    candidates = [
        os.path.join(_BASE_DIR, "config"),            # deployed alongside apps
        os.path.join(_BASE_DIR, "..", "config"),      # in-repo relative to apps/
    ]
    for path in candidates:
        if os.path.isdir(path):
            return os.path.abspath(path)
    # fallback to first candidate
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
        merged = {**DEFAULTS, **data}
        return merged


def save_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Persist allowed keys and return the saved settings."""
    _ensure_file()
    with _LOCK:
        current = load_settings()
        for key in DEFAULTS:
            if key in updates:
                current[key] = updates[key]
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        try:
            os.chmod(_SETTINGS_PATH, 0o600)
        except OSError:
            pass
        return current


def toggle_first_run_done() -> Dict[str, Any]:
    """Mark the welcome wizard as completed."""
    return save_settings({"first_run": False})
