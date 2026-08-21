import json
import os
import threading

DATA_DIR = os.environ.get(
    "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

_lock = threading.Lock()

DEFAULTS = {
    "telegram_enabled": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "telegram_poll_seconds": 30,
    "telegram_edit_seconds": 30,
}


def _env_defaults():
    return {
        "telegram_enabled": os.environ.get("TELEGRAM_ENABLED", "").strip().lower()
        in ("1", "true", "yes", "on"),
        "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
        "telegram_poll_seconds": int(
            os.environ.get("TELEGRAM_POLL_SECONDS", "30") or 30
        ),
        "telegram_edit_seconds": int(
            os.environ.get("TELEGRAM_EDIT_SECONDS", "30") or 30
        ),
    }


def _load_file():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_file(data):
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


def get_settings():
    """Merge env defaults with any UI-saved overrides (UI wins)."""
    base = dict(DEFAULTS)
    base.update(_env_defaults())
    with _lock:
        saved = _load_file()
    merged = dict(base)
    merged.update({k: v for k, v in saved.items() if k in DEFAULTS})
    return merged


def update_settings(patch):
    """Persist UI settings overrides. Returns the merged settings."""
    with _lock:
        saved = _load_file()
        saved.update({k: v for k, v in patch.items() if k in DEFAULTS})
        _save_file(saved)
    return get_settings()
