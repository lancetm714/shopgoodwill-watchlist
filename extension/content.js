// Content script: runs on shopgoodwill.com/item/* pages.
// Adds a floating "Add to Watchlist" button and reads the item's end time from
// the page content the user is already viewing. The user confirms in a dialog
// before anything is sent.

(function () {
  "use strict";

  console.log("[GoodwillWatchlist] content script loaded, url =", window.location.href);

  if (window.__gwwInjected) { console.log("[GoodwillWatchlist] already injected, skipping"); return; }
  if (window.top !== window.self) { console.log("[GoodwillWatchlist] in iframe, skipping"); return; }
  window.__gwwInjected = true;

  const itemId = readItemId();
  if (!itemId) {
    console.log("[GoodwillWatchlist] no item id in URL, skipping");
    return;
  }
  console.log("[GoodwillWatchlist] item id =", itemId);

  let detected = null;

  // ---- helpers -----------------------------------------------------------

  function readItemId() {
    const m = window.location.pathname.match(/\/(?:item|Item)\/(\d+)/);
    return m ? m[1] : null;
  }

  function readTitle() {
    const t = document.querySelector('h1');
    if (t && t.textContent.trim()) return t.textContent.trim();
    if (document.title) return document.title.replace(/\s*\|\s*ShopGoodwill\.com$/i, "").trim();
    return "Item " + itemId;
  }

  // Grab the text next to a known label (e.g. "Ending Date", "Ends On").
  function textAfterLabel(labels) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    const all = [];
    let node;
    const seen = new Set();
    while ((node = walker.nextNode())) {
      const t = node.textContent || "";
      for (const lbl of labels) {
        const idx = t.toUpperCase().indexOf(lbl.toUpperCase());
        if (idx !== -1) {
          const after = t.slice(idx + lbl.length).trim();
          // Also gather up to ~20 words after the label from the same text node,
          // in case the label and value share a line.
          const following = t.slice(idx + lbl.length, idx + lbl.length + 200).trim();
          const parentEl = node.parentElement;
          const parentText = (parentEl && parentEl.textContent || "").trim();
          const key = (after + "|" + parentText);
          if (seen.has(key)) continue;
          seen.add(key);
          all.push({ after, following, prev: parentText, parentEl });
        }
      }
    }
    return all.length ? all : null;
  }

  // Look for a date token like "8/20/2026" in a string.
  function findDateToken(str) {
    if (!str) return null;
    const re = /\d{1,2}\/\d{1,2}\/\d{2,4}/;
    const m = str.match(re);
    return m ? m[0] : null;
  }

  // Look for a time token like "2:30 PM", "14:30", or "06:10:00 PM" in a string.
  function findTimeToken(str) {
    if (!str) return null;
    const re = /\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\b/i;
    const m = str.match(re);
    return m ? m[0] : null;
  }

  // Convert a date token like "8/22/2026" plus a time token like "06:10:00 PM"
  // to a datetime-local value ("YYYY-MM-DDTHH:MM").
  function toLocalInputToken(dateToken, timeToken) {
    if (!dateToken) return null;
    let trimmed = dateToken.trim();
    const m = trimmed.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/i);
    if (!m) return null;
    let mo = +m[1], da = +m[2], yr = +m[3];
    if (yr < 100) yr += 2000;
    const pad = (n) => String(n).padStart(2, "0");

    let hour = 12, minute = 0;
    if (timeToken) {
      const tm = timeToken.trim().match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$/i);
      if (tm) {
        let hh = +tm[1], mm = +tm[2], ap = tm[4];
        let hour12 = hh % 12;
        if (/pm/i.test(ap)) hour12 += 12;
        hour = hour12;
        minute = mm;
      }
    }
    return `${yr}-${pad(mo)}-${pad(da)}T${pad(hour)}:${pad(minute)}`;
  }

  function detectFromCountdown() {
    // The listing shows a live countdown like "2d 14h 5m 39s". If we can find it
    // we can compute the end time relative to now. This is best-effort.
    const re = /(\d+)\s*d\s+(\d+)\s*h\s+(\d+)\s*m/g;
    const all = document.body.innerText || "";
    // Look in likely containers to avoid matching unrelated text.
    const candidates = [];
    for (const el of document.querySelectorAll('*')) {
      const t = (el.textContent || "").trim();
      if (t.length > 2 && t.length < 40 && /\d+\s*d?\s*\d*\s*h\s+\d+\s*m/.test(t)) {
        candidates.push(t);
      }
    }
    // Prefer the shortest match with a days count.
    candidates.sort((a, b) => a.length - b.length);
    return null; // conversion handled in popup against a known time is unreliable; rely on date labels instead
  }

  function detect() {
    // Find an "Ends On"-style label, then read the date and time from the same
    // parent container (they may be split across elements, but both sit in the
    // container that holds the label/value pair).
    const labelGroups = [
      ["Ends On", "Ending Date", "Ending Date (PT)", "Ending", "Ends", "End Time"],
      ["Time Left", "Time Remaining", "Remaining Time", "Auction Ends"],
    ];

    let date = null, time = null, hitDepth = Infinity;

    for (const labels of labelGroups) {
      const hits = textAfterLabel(labels);
      if (!hits) continue;
      for (const h of hits) {
        // Smallest container holding a date is most likely the exact value cell.
        // Walk up from the label's parent to find a container that has a date
        // and a time together; prefer the smallest.
        let el = h.parentEl;
        while (el && document.body.contains(el)) {
          const text = (el.textContent || "").trim();
          const d = findDateToken(text);
          const t = findTimeToken(text);
          if (d) {
            const depth = getDepth(el);
            if (depth < hitDepth) {
              hitDepth = depth;
              date = d;
              time = t;
            }
            break; // found the smallest container with a date; don't go higher
          }
          el = el.parentElement;
        }
        if (date) break;
      }
      if (date) break;
    }

    // Fallback: look for a date with an adjacent time anywhere on the page
    // near an end-related word.
    if (!date) {
      const lines = (document.body.innerText || "").split(/\n/);
      outer:
      for (const line of lines) {
        if (!/\b(end|closing|auction|remaining)\b/i.test(line)) continue;
        const d = findDateToken(line);
        const t = findTimeToken(line);
        if (d && t) { date = d; time = t; break outer; }
        if (d) { date = d; time = t; break outer; }
      }
    }

    const endValue = toLocalInputToken(date, time);
    return { endValue, title: readTitle(), url: window.location.href, id: itemId };
  }

  function getDepth(el) {
    let n = 0;
    while (el) { n++; el = el.parentElement; }
    return n;
  }

  // ---- UI ---------------------------------------------------------------

  function addStyles() {
    const style = document.createElement("style");
    style.textContent = `
      .gww-btn {
        position: fixed; right: 20px; bottom: 20px; z-index: 999999;
        background: #0b5cad; color: #fff; border: none; border-radius: 999px;
        padding: 12px 18px; font: 600 14px/1 system-ui, sans-serif;
        cursor: pointer; box-shadow: 0 4px 16px rgba(0,0,0,.25);
      }
      .gww-btn:hover { filter: brightness(1.08); }
      .gww-overlay {
        position: fixed; inset: 0; z-index: 1000000;
        background: rgba(20,24,28,.45); display: flex; align-items: center; justify-content: center;
      }
      .gww-dialog {
        background: #fff; color: #1f2328; border-radius: 12px; width: 420px; max-width: 92vw;
        padding: 18px; font: 14px/1.4 system-ui, sans-serif; box-shadow: 0 10px 40px rgba(0,0,0,.3);
        display: flex; flex-direction: column; gap: 10px;
      }
      .gww-dialog h3 { margin: 0; font-size: 16px; }
      .gww-dialog label { display: flex; flex-direction: column; gap: 5px; font-weight: 600; font-size: 12px; color: #6b7280; }
      .gww-dialog input[type=text], .gww-dialog input[type=datetime-local] {
        padding: 9px 11px; border: 1px solid #e3e6ea; border-radius: 8px; font-size: 14px; color: #1f2328;
      }
      .gww-dialog .row { display: flex; gap: 10px; }
      .gww-dialog .row label { flex: 1; }
      .gww-dialog .actions { display: flex; gap: 10px; justify-content: flex-end; }
      .gww-dialog button {
        padding: 9px 16px; border-radius: 8px; border: 1px solid #e3e6ea; background: #fff;
        font-weight: 600; cursor: pointer; font-size: 13px;
      }
      .gww-dialog .gww-primary { background: #0b5cad; border-color: #0b5cad; color: #fff; }
      .gww-dialog .gww-msg { font-size: 13px; min-height: 1.2em; color: #6b7280; }
      .gww-dialog .gww-error { color: #c0392b; }
      .gww-dialog .gww-ok { color: #237a3a; }
      .gww-dialog .gww-note { font-size: 12px; color: #9aa0a6; }
    `;
    document.head.appendChild(style);
  }

  function openDialog(info) {
    if (document.querySelector(".gww-overlay")) return;

    const overlay = document.createElement("div");
    overlay.className = "gww-overlay";
    overlay.innerHTML = `
      <div class="gww-dialog" role="dialog" aria-label="Add to Watchlist">
        <h3>Add to Watchlist</h3>
        <label>Label
          <input type="text" id="gww-label" value="">
        </label>
        <label>End time (if empty, enter the ending time shown on this page)
          <input type="datetime-local" id="gww-ends" value="">
        </label>
        <div class="row">
          <label>Alert (minutes left)
            <input type="number" id="gww-amin" value="10" min="1" max="1440">
          </label>
        </div>
        <p class="gww-note">End time is read from what's shown on this page. Confirm it's correct — auctions can be extended by the seller.</p>
        <p class="gww-msg" id="gww-msg"></p>
        <div class="actions">
          <button id="gww-cancel" type="button">Cancel</button>
          <button id="gww-submit" class="gww-primary" type="button">Add</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    document.getElementById("gww-label").value = info.title;
    if (info.endValue) {
      document.getElementById("gww-ends").value = info.endValue;
    }

    const msg = document.getElementById("gww-msg");
    function setMsg(t, cls) { msg.textContent = t; msg.className = "gww-msg" + (cls ? " " + cls : ""); }

    document.getElementById("gww-cancel").onclick = () => overlay.remove();
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

    document.getElementById("gww-submit").onclick = async () => {
      const ends = document.getElementById("gww-ends").value;
      if (!ends) { setMsg("Please enter the ending time shown on the page.", "gww-error"); return; }
      setMsg("Sending...");
      const payload = {
        url: info.url,
        label: document.getElementById("gww-label").value.trim(),
        endsAt: ends.replace("T", " "),
        alertMinutes: Number(document.getElementById("gww-amin").value) || 10,
      };
      try {
        const ok = await sendToBackground(payload);
        if (ok) { setMsg("Added to your watchlist.", "gww-ok"); setTimeout(() => overlay.remove(), 1100); }
        else setMsg("Could not reach your dashboard. Is it running at localhost:6518?", "gww-error");
      } catch (e) {
        setMsg("Error: " + e.message, "gww-error");
      }
    };
  }

  function sendToBackground(payload) {
    return new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage({ type: "ADD_ITEM", payload }, (resp) => {
          if (chrome.runtime.lastError) { reject(new Error(chrome.runtime.lastError.message)); return; }
          resolve(resp && resp.ok);
        });
      } catch (e) { reject(e); }
    });
  }

  function init() {
    addStyles();
    const btn = document.createElement("button");
    btn.className = "gww-btn";
    btn.textContent = "Add to Watchlist";
    btn.onclick = () => { detected = detect(); openDialog(detected); };
    if (!document.body) {
      console.log("[GoodwillWatchlist] body not ready, retrying in 300ms");
      setTimeout(init, 300);
      return;
    }
    document.body.appendChild(btn);
    console.log("[GoodwillWatchlist] button injected");

    // Re-detect when the page finishes loading detail data (Angular lazy render).
    let attempts = 0;
    const iv = setInterval(() => {
      detected = detect();
      attempts++;
      if (detected && detected.endValue) clearInterval(iv);
      if (attempts > 20) clearInterval(iv);
    }, 1500);
  }

  init();
})();
