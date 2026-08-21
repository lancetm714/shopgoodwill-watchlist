const tokenInput = document.getElementById("set-token");
const chatInput = document.getElementById("set-chat");
const pollInput = document.getElementById("set-poll");
const editInput = document.getElementById("set-edit");
const enabledInput = document.getElementById("set-enabled");
const saveBtn = document.getElementById("save");
const testBtn = document.getElementById("test");
const msgEl = document.getElementById("msg");
const statusEl = document.getElementById("notify-status");

function setMsg(t, cls) {
  msgEl.textContent = t;
  msgEl.className = "msg" + (cls ? " " + cls : "");
}

function setStatus(html) {
  statusEl.innerHTML = html;
}

async function load() {
  try {
    const res = await fetch("/api/settings");
    const d = await res.json();
    if (d.telegram_bot_token_set) {
      tokenInput.placeholder = "Saved token " + d.telegram_bot_token_masked + " (leave blank to keep)";
    }
    chatInput.value = d.telegram_chat_id || "";
    pollInput.value = d.telegram_poll_seconds || 30;
    editInput.value = d.telegram_edit_seconds || 30;
    enabledInput.checked = !!d.telegram_enabled;
    setStatus(d.telegram_enabled
      ? '<span class="dot on"></span><span><b>Notifications are on.</b> Polling every ' + (d.telegram_poll_seconds || 30) + 's, countdown refresh every ' + (d.telegram_edit_seconds || 30) + 's.</span>'
      : '<span class="dot off"></span><span><b>Notifications are off.</b> Enable and save to turn them on.</span>');
  } catch (e) {
    setStatus("Could not load settings.");
  }
}

function payloadForSave() {
  return {
    telegram_bot_token: tokenInput.value.trim() || "KEEP",
    telegram_chat_id: chatInput.value.trim() || "KEEP",
    telegram_poll_seconds: Number(pollInput.value) || 30,
    telegram_edit_seconds: Number(editInput.value) || 30,
    telegram_enabled: enabledInput.checked,
  };
}

saveBtn.addEventListener("click", async () => {
  setMsg("Saving…");
  try {
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payloadForSave()),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || "Failed to save");
    setMsg("Settings saved.", "ok");
    await load();
  } catch (e) {
    setMsg(e.message, "error");
  }
});

testBtn.addEventListener("click", async () => {
  setMsg("Sending test notification…");
  try {
    const res = await fetch("/api/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payloadForSave()),
    });
    const d = await res.json();
    if (d.ok) setMsg("Test notification sent. Check your Telegram!", "ok");
    else setMsg("Could not send. Check your token and chat ID, and that they're correct.", "error");
    await load();
  } catch (e) {
    setMsg(e.message, "error");
  }
});

load();
