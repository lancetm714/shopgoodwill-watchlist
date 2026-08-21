import os
import json
import threading
import time
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, render_template

bp = Blueprint("main", __name__)


@bp.after_request
def add_cors_headers(resp):
    # The browser-extension POSTs to this local dashboard from its own origin,
    # so we allow cross-origin requests. This is a local, user-controlled app.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
WATCH_FILE = os.path.join(DATA_DIR, "watchlist.json")
os.makedirs(DATA_DIR, exist_ok=True)

_lock = threading.Lock()

PT_OFFSET = -7  # Pacific Time standard. Use fixed offset; see parse note below.


def _now_pt():
    # Return current time as a naive UTC-based "PT-ish" marker is fragile;
    # we store absolute UTC and let the client render PT. Keep server simple.
    return datetime.now(timezone.utc)


def _load_watchlist():
    if not os.path.exists(WATCH_FILE):
        return []
    try:
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_watchlist(items):
    tmp = WATCH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, WATCH_FILE)


def _parse_iso(value):
    # Accept YYYY-MM-DD, YYYY-MM-DD HH:MM, YYYY-MM-DD HH:MM:SS, with optional
    # timezone (Z or +/-HH:MM). If no timezone is given, interpret the value as
    # Pacific Time (PT), which is what shopgoodwill listing pages display.
    value = value.strip()
    if not value:
        return None

    has_tz = bool(re.search(r"[zZ]|[+-]\d{2}:?\d{2}$", value))
    cleaned = value.replace(" ", "T").rstrip("Zz")

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        cleaned += "T00:00:00"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", cleaned):
        cleaned += ":00"

    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None

    if dt.tzinfo is None:
        if not has_tz:
            pt = timezone(timedelta(hours=PT_OFFSET))
            dt = dt.replace(tzinfo=pt)
        else:
            dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _item_id_from_url(url):
    # Extract the numeric id from a shopgoodwill item URL like
    # https://shopgoodwill.com/item/123456789
    m = re.search(r"/(?:item|Item)/(\d+)", url)
    return m.group(1) if m else None


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/settings")
def settings_page():
    return render_template("settings.html")


@bp.route("/api/notify", methods=["GET"])
def notify_status():
    from . import notifier
    return jsonify({
        "enabled": notifier.config_enabled(),
        "provider": "telegram",
        "pollSeconds": notifier._config()["poll_seconds"],
        "configured": bool(notifier._config()["token"]) and bool(notifier._config()["chat_id"]),
    })


@bp.route("/api/settings", methods=["GET"])
def get_settings():
    from . import settings_store
    s = settings_store.get_settings()
    # Never send the bot token back to the client in full; send a masked version.
    token = s.get("telegram_bot_token", "")
    masked = (token[:6] + "..." + token[-4:]) if len(token) > 10 else ("set" if token else "")
    return jsonify({
        "telegram_enabled": bool(s.get("telegram_enabled", False)),
        "telegram_bot_token_masked": masked,
        "telegram_bot_token_set": bool(token),
        "telegram_chat_id": s.get("telegram_chat_id", ""),
        "telegram_poll_seconds": int(s.get("telegram_poll_seconds", 30) or 30),
        "telegram_edit_seconds": int(s.get("telegram_edit_seconds", 30) or 30),
    })


@bp.route("/api/settings", methods=["PUT"])
def update_settings():
    from . import settings_store
    data = request.get_json(silent=True) or {}

    patch = {}
    if "telegram_enabled" in data:
        patch["telegram_enabled"] = bool(data["telegram_enabled"])
    if "telegram_poll_seconds" in data:
        try:
            patch["telegram_poll_seconds"] = max(10, int(data["telegram_poll_seconds"]))
        except (TypeError, ValueError):
            pass
    if "telegram_edit_seconds" in data:
        try:
            patch["telegram_edit_seconds"] = max(5, int(data["telegram_edit_seconds"]))
        except (TypeError, ValueError):
            pass
    # Chat id and token are only written when a non-empty value is sent,
    # so an empty value does not wipe an existing one accidentally.
    if data.get("telegram_chat_id"):
        patch["telegram_chat_id"] = str(data["telegram_chat_id"]).strip()
    if data.get("telegram_bot_token") and data.get("telegram_bot_token") != "KEEP":
        patch["telegram_bot_token"] = str(data["telegram_bot_token"]).strip()

    updated = settings_store.update_settings(patch)
    return jsonify({"ok": True, "settings": updated})


@bp.route("/api/settings/test", methods=["POST"])
def test_settings():
    from . import notifier, settings_store
    # Apply any pending settings first (so a just-entered token is used).
    data = request.get_json(silent=True) or {}
    patch = {}
    if data.get("telegram_chat_id"):
        patch["telegram_chat_id"] = str(data["telegram_chat_id"]).strip()
    if data.get("telegram_bot_token") and data.get("telegram_bot_token") != "KEEP":
        patch["telegram_bot_token"] = str(data["telegram_bot_token"]).strip()
    if "telegram_enabled" in data:
        patch["telegram_enabled"] = bool(data["telegram_enabled"])
    if "telegram_edit_seconds" in data:
        try:
            patch["telegram_edit_seconds"] = max(5, int(data["telegram_edit_seconds"]))
        except (TypeError, ValueError):
            pass
    if patch:
        settings_store.update_settings(patch)

    ok = notifier.send_test()
    return jsonify({"ok": ok})


@bp.route("/api/items", methods=["GET"])
def list_items():
    with _lock:
        items = _load_watchlist()
    now = _now_pt()
    for it in items:
        it["endsAtIso"] = it.get("endsAtIso")
        it["status"] = _status(it, now)
    return jsonify({"items": items, "serverNow": now.isoformat()})


@bp.route("/api/items", methods=["POST"])
def add_item():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    label = (data.get("label") or "").strip()
    ends_raw = (data.get("endsAt") or "").strip()
    alert_min = data.get("alertMinutes", 10)

    end_dt = _parse_iso(ends_raw)
    if end_dt is None:
        return jsonify({"error": "Could not parse the end time. Use e.g. 2026-08-22 14:30 (PT)."}), 400

    item_id = _item_id_from_url(url)
    rec = {
        "id": item_id if item_id else (label or url or str(int(time.time() * 1000))),
        "url": url if url else None,
        "label": label if label else (f"Item {item_id}" if item_id else "Untitled item"),
        "endsAtIso": end_dt.isoformat(),
        "alertMinutes": int(alert_min),
        "createdAt": _now_pt().isoformat(),
    }

    with _lock:
        items = _load_watchlist()
        # avoid duplicate by url or id
        items = [i for i in items if i.get("id") != rec["id"] or i.get("url") != rec["url"]]
        items.insert(0, rec)
        _save_watchlist(items)

    rec["status"] = _status(rec, _now_pt())
    return jsonify({"item": rec}), 201


@bp.route("/api/items/<item_id>", methods=["DELETE"])
def delete_item(item_id):
    with _lock:
        items = _load_watchlist()
        items = [i for i in items if i.get("id") != item_id]
        _save_watchlist(items)
    return jsonify({"ok": True})


@bp.route("/api/items/<item_id>", methods=["PUT"])
def update_item(item_id):
    data = request.get_json(silent=True) or {}
    with _lock:
        items = _load_watchlist()
        for it in items:
            if it.get("id") == item_id:
                if "endsAt" in data:
                    end_dt = _parse_iso((data.get("endsAt") or "").strip())
                    if end_dt is None:
                        return jsonify({"error": "Could not parse end time."}), 400
                    it["endsAtIso"] = end_dt.isoformat()
                if "alertMinutes" in data:
                    it["alertMinutes"] = int(data.get("alertMinutes", 10))
                if "label" in data and str(data.get("label", "")).strip():
                    it["label"] = str(data["label"]).strip()
                break
        _save_watchlist(items)
    return jsonify({"ok": True})


def _status(item, now):
    try:
        end = datetime.fromisoformat(item["endsAtIso"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return "invalid"
    seconds_left = (end - now).total_seconds()
    if seconds_left <= 0:
        return "ended"
    minutes_left = seconds_left / 60
    if minutes_left <= item.get("alertMinutes", 10):
        return "ending_soon"
    return "active"
