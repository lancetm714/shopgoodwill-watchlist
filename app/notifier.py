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

# Tiers of reminders for each item, in the order they fire as time runs out:
#   alert  -> first heads-up when the item enters its configured alert window
#             (and becomes the live countdown message).
#   nudge  -> final-minutes "bid now" push, sent once when very little time is left.
#   ended  -> distinct notification that the auction has now passed its end time.
# Persisted to disk so restarts don't re-fire or silently miss a tier.
_REMINDER_TIERS = ("alert", "nudge", "ended")

# item_id -> set of tier keys already sent.
_sent_tiers = {}
_lock = threading.Lock()

_SENT_FILE = os.path.join(
    os.environ.get(
        "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
    ),
    "sent_alerts.json",
)


def _load_sent():
    result = {}
    try:
        with open(_SENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return result
    # Backwards-compatible: an old list of sent item ids => "alert" tier already done.
    if isinstance(data, list):
        for item_id in data:
            result[str(item_id)] = {"alert"}
        return result
    if isinstance(data, dict):
        for item_id, value in data.items():
            if isinstance(value, list):
                result[str(item_id)] = set(value)
            else:
                result[str(item_id)] = {"alert"}
        return result
    return result


def _save_sent():
    data_dir = os.path.dirname(_SENT_FILE)
    try:
        os.makedirs(data_dir, exist_ok=True)
        tmp = _SENT_FILE + ".tmp"
        with _lock:
            snapshot = {k: sorted(v) for k, v in _sent_tiers.items()}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f)
        os.replace(tmp, _SENT_FILE)
    except OSError:
        log.warning("Could not persist sent alerts to %s", _SENT_FILE)


_sent_tiers = _load_sent()

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


def _mark_tier(item_id, tier):
    if tier not in _REMINDER_TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    with _lock:
        _sent_tiers.setdefault(str(item_id), set()).add(tier)
    _save_sent()


def tier_sent(item_id, tier):
    with _lock:
        return tier in _sent_tiers.get(str(item_id), set())


def _mark_sent(item_id):
    # Backwards-compatible helper: marking "sent" means the first alert fired.
    _mark_tier(item_id, "alert")


def already_sent(item_id):
    return tier_sent(item_id, "alert")


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


def _item_label(item):
    item_id = str(item.get("id", ""))
    return item.get("label") or (f"Item {item_id}" if item_id else "An item")


def _fmt_end_pt(end):
    return end.astimezone().strftime("%Y-%m-%d %H:%M")


def _build_nudge_msg(label, seconds_left, end, url):
    msg = (f"\U0001F534 <b>Bid now:</b> {label}\n"
           f"\U000023F1 {_fmt_countdown(seconds_left)} before the auction ends\n"
           f"Ends {_fmt_end_pt(end)}")
    if url:
        msg += f"\n\U0001F517 <a href=\"{url}\">Open listing</a>"
    return msg


def _build_ended_msg(label, end, url):
    msg = (f"\U00002753 <b>Auction ended:</b> {label}\n"
           f"Ended at {_fmt_end_pt(end)}")
    if url:
        msg += f"\n\U0001F517 <a href=\"{url}\">Open listing</a>"
    return msg


def _check_once():
    now = datetime.now(timezone.utc)
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
        label = _item_label(item)
        url = item.get("url")
        end_ts = end.timestamp()

        # Tier "ended": the auction has passed its end time.
        if seconds_left <= 0:
            _unregister_live(item_id)
            if not tier_sent(item_id, "ended"):
                _send_message(_build_ended_msg(label, end, url))
                _mark_tier(item_id, "ended")
                log.info("Ended notice sent for item %s (%s)", item_id, label)
            continue

        # Tier "nudge": final-minutes "bid now" push.
        if not tier_sent(item_id, "nudge") and seconds_left <= _nudge_seconds():
            _send_message(_build_nudge_msg(label, seconds_left, end, url))
            _mark_tier(item_id, "nudge")
            log.info("Nudge sent for item %s (%s)", item_id, label)

        # Tier "alert": first heads-up within the configured window, which also
        # becomes the live countdown message.
        if minutes_left <= threshold and not tier_sent(item_id, "alert"):
            msg = _build_msg(label, seconds_left, end, url)
            message_id = _send_message(msg)
            if message_id is not None:
                _mark_tier(item_id, "alert")
                _register_live(item_id, message_id, end_ts)
                log.info("Alert sent for item %s (%s)", item_id, label)


def _nudge_seconds():
    # Final-minutes nudge window. Configurable via env for power users.
    try:
        return float(os.environ.get("TELEGRAM_NUDGE_SECONDS", "120"))
    except (TypeError, ValueError):
        return 120.0


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


def _pid_alive(pid, start_marker=""):
    """Return True only if <pid> is alive AND is (or was started at) the same
    process that wrote the lock. A bare kill(pid, 0) unsafe inside a container,
    where gunicorn worker PIDs are low and get recycled: after a restart an old,
    dead PID can now belong to an unrelated live process, making the lock look
    permanently owned and silently disabling the notifier.

    start_marker is the process start time (from /proc) recorded in the lock; if
    provided and readable, we require the /proc start time to match so a recycled
    PID is not mistaken for the old owner.
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False  # no such process
    # PID is alive now. If we recorded its start time, verify it still matches.
    if start_marker:
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
                stat = f.read()
                # field 22 is the process start time (in clock ticks since boot);
                # it appears after the comm field, which may contain spaces/parens.
                # After stripping "pid (comm) " the start time is at index 19.
                close = stat.rfind(")")
                fields = stat[close + 2:].split()
                if len(fields) > 19 and fields[19] != start_marker:
                    return False  # PID reused by a different process
        except OSError:
            # /proc unavailable (e.g. non-Linux); fall back to liveness only.
            pass
    return True


def _own_start_marker():
    # Field 22 of /proc/self/stat is the start time of this process. Reused PIDs
    # have different start times, so this lets us tell a stale lock from a live one.
    try:
        with open("/proc/self/stat", "r", encoding="utf-8") as f:
            stat = f.read()
            close = stat.rfind(")")
            fields = stat[close + 2:].split()
            return fields[19] if len(fields) > 19 else ""
    except OSError:
        return ""


def start():
    # Run the notifier in only one process (important under gunicorn with
    # multiple workers). Claim a lock file that records the owning PID + start
    # time, and reclaim it if the previous owner stopped (handles hard kills and
    # recycled PIDs inside containers).
    from . import settings_store
    lock_path = os.path.join(settings_store.DATA_DIR, "notifier.lock")
    my_pid = os.getpid()
    my_marker = _own_start_marker()

    if os.path.exists(lock_path):
        old_marker = ""
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            parts = content.split()
            old_pid = int(parts[0]) if parts and parts[0].isdigit() else -1
            old_marker = parts[1] if len(parts) > 1 else ""
            if old_pid == my_pid:
                # Same PID as us: either we already started in this process, or
                # the PID was recycled from a previous run (common in containers,
                # where PIDs are allocated deterministically). Use the process
                # start time to tell the two apart.
                if old_marker and my_marker and old_marker != my_marker:
                    log.info("Reclaiming stale notifier lock (pid %s recycled).", old_pid)
                    os.remove(lock_path)
                else:
                    log.info("Notifier already active (pid %s); skipping.", old_pid)
                    return
            elif _pid_alive(old_pid, old_marker):
                log.info("Notifier already active (pid %s); skipping.", old_pid)
                return
            else:
                log.info("Reclaiming stale notifier lock (pid %s gone).", old_pid)
                os.remove(lock_path)
        except (ValueError, OSError):
            try:
                os.remove(lock_path)
            except OSError:
                pass

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        fileobj = os.fdopen(fd, "w")
        fileobj.write(f"{my_pid} {my_marker}")
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
