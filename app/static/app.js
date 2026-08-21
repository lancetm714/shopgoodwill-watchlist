const form = document.getElementById("item-form");
const msgEl = document.getElementById("form-msg");
const itemsEl = document.getElementById("items");
const emptyEl = document.getElementById("empty");
const countEl = document.getElementById("count");
const urlInput = document.getElementById("url");
const labelInput = document.getElementById("label");
const endsInput = document.getElementById("ends");
const alertMinInput = document.getElementById("alert-min");
const fillNowBtn = document.getElementById("fill-now");

let items = [];

function fmtPieces(sec) {
  sec = Math.max(0, sec);
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return { d, h, m, s };
}

function countdownText(sec) {
  const p = fmtPieces(sec);
  if (p.d > 0) return `${p.d}d ${p.h}h ${p.m}m ${p.s}s`;
  if (p.h > 0) return `${p.h}h ${p.m}m ${p.s}s`;
  if (p.m > 0) return `${p.m}m ${p.s}s`;
  return `${p.s}s`;
}

function localDateString(iso) {
  if (!iso) return "n/a";
  return new Date(iso).toLocaleString();
}

function statusOf(it) {
  const end = new Date(it.endsAtIso).getTime();
  const diff = end - Date.now();
  if (diff <= 0) return "ended";
  if (diff / 60000 <= (it.alertMinutes || 10)) return "ending_soon";
  return "active";
}

function card(it) {
  const end = new Date(it.endsAtIso).getTime();
  const sec = (end - Date.now()) / 1000;
  const status = statusOf(it);

  const badges = { active: "Active", ending_soon: "Ending soon", ended: "Ended" };
  const title = it.label || (it.id ? "Item " + it.id : "Untitled");
  const href = it.url ? `<a class="url" href="${it.url}" target="_blank" rel="noopener">${it.url}</a>` : "";

  return `
    <div class="item" data-id="${html(it.id)}">
      <div class="title">${html(title)}</div>
      ${it.url ? href : ""}
      <div class="countdown ${status}" data-end="${it.endsAtIso}">${countdownText(sec)}</div>
      <div class="meta">
        <span>Ends ${localDateString(it.endsAtIso)}</span>
        <span class="badge ${status}">${badges[status]}</span>
      </div>
      <div class="controls">
        <span class="sub">Alert at ${it.alertMinutes || 10}m</span>
        <span>
          <button class="edit-btn" data-action="edit" title="Edit">Edit</button>
          <button class="del-btn" data-action="delete" title="Remove">Remove</button>
        </span>
      </div>
    </div>
  `;
}

function html(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function render() {
  items.sort((a, b) => new Date(a.endsAtIso) - new Date(b.endsAtIso));
  itemsEl.innerHTML = items.map(card).join("");
  countEl.textContent = items.length ? `(${items.length})` : "";
  emptyEl.style.display = items.length ? "none" : "";
}

function tick() {
  for (const el of itemsEl.querySelectorAll(".countdown")) {
    const end = new Date(el.dataset.end).getTime();
    const sec = (end - Date.now()) / 1000;
    el.textContent = countdownText(sec);
    const status = sec <= 0 ? "ended" : (sec / 60000 <= (elStatusEndingSec(el)) ? "ending_soon" : "active");
    el.classList.remove("active", "ending_soon", "ended");
    el.classList.add(status);
  }
}

function elStatusEndingSec(el) {
  // Find the parent item's alert threshold.
  const cardEl = el.closest(".item");
  const sub = cardEl.querySelector(".sub");
  const m = sub && sub.textContent.match(/(\d+)m/);
  return m ? Number(m[1]) * 60 : 600;
}

let alerted = new Set();

async function load() {
  const res = await fetch("/api/items");
  const data = await res.json();
  items = data.items || [];
  render();
  checkAlerts(data.items || []);
}

function checkAlerts(list) {
  for (const it of list) {
    const end = new Date(it.endsAtIso).getTime();
    const diff = end - Date.now();
    const minutes = diff / 60000;
    if (minutes <= (it.alertMinutes || 10) && diff > 0 && !alerted.has(it.id)) {
      alerted.add(it.id);
      const title = it.label || "Item " + it.id;
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        new Notification("Ending soon: " + title, { body: `${countdownText(diff / 1000)} left` });
      }
      if (typeof window.speechSynthesis !== "undefined") {
        try { window.speechSynthesis.speak(new SpeechSynthesisUtterance("Ending soon: " + title)); } catch (e) {}
      }
    }
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msgEl.textContent = "";
  msgEl.className = "msg";
  const ends = endsInput.value;
  if (!ends) {
    setMsg("Please choose an end time.", "error");
    return;
  }
  const payload = {
    url: urlInput.value.trim(),
    label: labelInput.value.trim(),
    endsAt: ends.replace("T", " "),
    alertMinutes: Number(alertMinInput.value) || 10,
  };
  try {
    const res = await fetch("/api/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to add item");
    urlInput.value = "";
    labelInput.value = "";
    setMsg("Item added.", "ok");
    await load();
  } catch (err) {
    setMsg(err.message, "error");
  }
});

itemsEl.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const cardEl = btn.closest(".item");
  const id = cardEl.dataset.id;
  const action = btn.dataset.action;
  if (action === "delete") {
    await fetch("/api/items/" + encodeURIComponent(id), { method: "DELETE" });
    alerted.delete(id);
    await load();
  } else if (action === "edit") {
    const it = items.find((x) => x.id === id);
    if (!it) return;
    const label = prompt("Label (leave blank to keep):", it.label || "");
    if (label === null) return;
    const minutes = prompt("Alert threshold (minutes):", String(it.alertMinutes || 10));
    if (minutes === null) return;
    const body = {};
    if (label.trim()) body.label = label.trim();
    if (Number(minutes)) body.alertMinutes = Number(minutes);
    if (Object.keys(body).length) {
      await fetch("/api/items/" + encodeURIComponent(id), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      await load();
    }
  }
});

fillNowBtn.addEventListener("click", () => {
  const d = new Date(Date.now() + 24 * 3600 * 1000);
  d.setSeconds(0, 0);
  endsInput.value = toLocalInput(d);
});

function toLocalInput(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function setMsg(text, kind) {
  msgEl.textContent = text;
  msgEl.className = "msg " + kind;
}

async function loadNotifyStatus() {
  const el = document.getElementById("notify-status");
  if (!el) return;
  try {
    const res = await fetch("/api/notify");
    const d = await res.json();
    if (d.enabled) {
      el.innerHTML = '<span class="dot on"></span><span><b>Telegram notifications are on.</b> You\'ll get a push when an item is within its alert window (poll every ' + (d.pollSeconds || 30) + 's).</span>';
    } else {
      el.innerHTML = '<span class="dot off"></span><span><b>Telegram notifications are off.</b> Add <code>TELEGRAM_BOT_TOKEN</code> + <code>TELEGRAM_CHAT_ID</code> env vars and restart.</span>';
    }
  } catch (e) {
    el.textContent = "Could not load notification status.";
  }
}

if (typeof Notification !== "undefined" && Notification.permission === "default") {
  Notification.requestPermission();
}

load();
loadNotifyStatus();
setInterval(load, 30000);   // refresh end time data every 30s
tick();
setInterval(tick, 1000);    // tick the local countdown every second
