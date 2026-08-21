// Background service worker (MV3).
// Receives "ADD_ITEM" messages from the content script and POSTs them to the
// local Goodwill Watchlist dashboard API. The dashboard URL is configurable and
// defaults to localhost:6518.

const DEFAULT_DASHBOARD = "http://localhost:6518";

async function getDashboardUrl() {
  const stored = await chrome.storage.local.get("dashboardUrl");
  let url = stored.dashboardUrl || DEFAULT_DASHBOARD;
  url = url.replace(/\/+$/, "");
  return url;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === "ADD_ITEM") {
    getDashboardUrl()
      .then((base) => fetch(base + "/api/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(message.payload),
      }))
      .then((res) => {
        if (!res.ok) return res.text().then((t) => { throw new Error(t || ("HTTP " + res.status)); });
        return res.json();
      })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true; // keep the messaging channel open for the async response
  }

  if (message && message.type === "GET_SETTINGS") {
    getDashboardUrl().then((url) => sendResponse({ dashboardUrl: url }));
    return true;
  }

  if (message && message.type === "SET_DASHBOARD_URL") {
    chrome.storage.local.set({ dashboardUrl: message.dashboardUrl }).then(() =>
      sendResponse({ ok: true })
    );
    return true;
  }
});
