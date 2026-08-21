import json
import logging
import os
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

log = logging.getLogger("watchlist.notifier")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Track which items have already had their alert sent, so we only notify once.
_sent_alerts = set()
_lock = threading.Lock()

# Live countdown messages: item_id -> {message_id, end_ts, last_edit_ts}
_live_messages = {}

# Guard so the notifier thread is only started once.
_THREAD_STARTED = threading.Event()


def _config():
    from . import settings_store
    s = settings_store.get_settings()
    return {
        "token": s.get("telegram_bot_token", "").strip(),
        "chat_id": s.get("telegram_chat_id", "").strip(),
        "enabled": bool(s.get("telegram_enabled", False)),
        "poll_seconds": int(s.get("telegram_poll_seconds", 30) or 30),
        "edit_seconds": int(s.get("telegram_edit_seconds", 30) or 30),
        "topic": os.environ.get("TELEGRAM_TOPIC", "").strip(),
    }


def config_enabled():
    c = _config()
    return bool(c["enabled"] and c["token"] and c["chat_id"])


def send_test():
    c = _config()
    if not (c["token"] and c["chat_id"]):
        return False
    return _send_message("<b>Goodwill Watchlist</b>\n\U00002705 Test notification sent from your settings page.") is not None


def _send_message(message, parse_mode="HTML"):
    """Send a message. Returns the message id on success, else None."""
    c = _config()
    url = TELEGRAM_API.format(token=c["token"], method="sendMessage")
    payload = {
        "chat_id": c["chat_id"],
        "text": message,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if c["topic"]:
        payload["message_thread_id"] = c["topic"]
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                log.warning("Telegram API error: %s", body.get("description"))
                return None
            result = body.get("result") or {}
            return result.get("message_id")
    except Exception as e:  # network / HTTP errors
        log.warning("Telegram send failed: %s", e)
        return None


def _edit_message(message_id, message, parse_mode="HTML"):
    """Edit an existing message's text. Returns True on success."""
    c = _config()
    url = TELEGRAM_API.format(token=c["token"], method="editMessageText")
    payload = {
        "chat_id": c["chat_id"],
        "message_id": message_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                log.warning("Telegram edit error: %s", body.get("description"))
                return False
            return True
    except Exception as e:
        log.warning("Telegram edit failed: %s", e)
        return False


def _mark_sent(item_id):
    with _lock:
        _sent_alerts.add(item_id)


def already_sent(item_id):
    with _lock:
        return item_id in _sent_alerts


def _fmt_countdown(seconds_left):
    sec = max(0, int(seconds_left))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def _load_watchlist():
    data_dir = os.environ.get(
        "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
    )
    path = os.path.join(data_dir, "watchlist.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _build_msg(label, seconds_left, end, url):
    msg = (f"\U000023F0 <b>Ending soon:</b> {label}\n"
           f"\U000023F1 {_fmt_countdown(seconds_left)} remaining\n"
           f"Ends {end.astimezone().strftime('%Y-%m-%d %H:%M')}")
    if url:
        msg += f"\n\U0001F517 <a href=\"{url}\">Open listing</a>"
    return msg


def _register_live(item_id, message_id, end_ts):
    with _lock:
        _live_messages[item_id] = {
            "message_id": message_id,
            "end_ts": end_ts,
            "last_edit_ts": 0.0,
        }


def _unregister_live(item_id):
    with _lock:
        _live_messages.pop(item_id, None)


def _check_once():
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    for item in _load_watchlist():
        try:
            end = datetime.fromisoformat(item["endsAtIso"])
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        seconds_left = (end - now).total_seconds()
        minutes_left = seconds_left / 60
        threshold = int(item.get("alertMinutes", 10) or 10)

        item_id = str(item.get("id", ""))
        # Alert when within threshold, still in the future.
        if 0 < seconds_left and minutes_left <= threshold:
            if not already_sent(item_id):
                label = item.get("label") or (f"Item {item_id}" if item_id else "An item")
                url = item.get("url")
                msg = _build_msg(label, seconds_left, end, url)
                message_id = _send_message(msg)
                if message_id is not None:
                    _mark_sent(item_id)
                    _register_live(item_id, message_id, end.timestamp())
                    log.info("Alert sent for item %s (%s)", item_id, label)
        # If it has ended, mark as sent so we don't alert again on an ended item
        # that briefly sits within a threshold due to timezone edge cases.
        elif seconds_left <= 0:
            _mark_sent(item_id)
            _unregister_live(item_id)


def _update_live_messages():
    """Edit existing Telegram messages to keep the countdown fresh."""
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()

    with _lock:
        snapshot = dict(_live_messages)

    done = []
    for item_id, meta in snapshot.items():
        remaining = meta["end_ts"] - now_ts
        if remaining <= 0:
            done.append(item_id)
            continue

        # Only edit if there is something meaningful to update; avoid hammering
        # the API every poll. Edit no more than once every N seconds.
        min_gap = _edit_gap_seconds(remaining)
        elapsed = now_ts - meta["last_edit_ts"]
        if elapsed < min_gap:
            continue

        # Build the item's label/url from the watchlist (cheap enough).
        label = item_id
        url = None
        for item in _load_watchlist():
            if str(item.get("id", "")) == item_id:
                label = item.get("label") or (f"Item {item_id}" if item_id else item_id)
                url = item.get("url")
                try:
                    end = datetime.fromisoformat(item["endsAtIso"])
                except (KeyError, ValueError):
                    end = now
                break
        else:
            # Item no longer in watchlist; stop updating.
            done.append(item_id)
            continue

        msg = _build_msg(label, remaining, end, url)
        if _edit_message(meta["message_id"], msg):
            with _lock:
                _live_messages[item_id]["last_edit_ts"] = now_ts
        else:
            # Editing failed (message deleted/revoked?). Stop updating.
            done.append(item_id)

    for item_id in done:
        _unregister_live(item_id)


def _edit_gap_seconds(remaining):
    # Users configure a base interval; speed it up in the final minutes.
    base = max(5, _config()["edit_seconds"])
    if remaining > 120 and base <= 30:
        return base
    if remaining > 30:
        return max(5, base // 2)
    return max(5, base // 6)


def _run():
    while True:
        try:
            if config_enabled():
                _check_once()
                _update_live_messages()
        except Exception as e:
            log.warning("notifier loop error: %s", e)
        time.sleep(_config()["poll_seconds"])


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start():
    # Run the notifier in only one process (important under gunicorn with
    # multiple workers). Claim a lock file that records the owning PID, and
    # reclaim it if the previous owner is no longer alive (handles hard kills).
    from . import settings_store
    lock_path = os.path.join(settings_store.DATA_DIR, "notifier.lock")
    my_pid = os.getpid()

    fd = None
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            old_pid = int(content) if content.isdigit() else -1
            if old_pid == my_pid or _pid_alive(old_pid):
                log.info("Notifier already active (pid %s); skipping.", old_pid)
                return
            log.info("Reclaiming stale notifier lock (pid %s gone).", old_pid)
            os.remove(lock_path)
        except ValueError:
            os.remove(lock_path)

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        fileobj = os.fdopen(fd, "w")
        fileobj.write(str(my_pid))
        fileobj.flush()
    except OSError:
        log.info("Could not acquire notifier lock; another process owns it.")
        return

    thread = threading.Thread(target=_run, name="telegram-notifier", daemon=True)
    thread.start()
    log.info("Notifier thread started (pid %s).", my_pid)

    def _monitor():
        thread.join()
        try:
            fileobj.close()
            os.remove(lock_path)
        except OSError:
            pass
    threading.Thread(target=_monitor, name="notifier-lock-monitor", daemon=True).start()
