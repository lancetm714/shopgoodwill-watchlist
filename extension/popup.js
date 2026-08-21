const urlInput = document.getElementById("url");
const msgEl = document.getElementById("msg");
const saveBtn = document.getElementById("save");

function setMsg(t, cls) {
  msgEl.textContent = t;
  msgEl.className = "msg" + (cls ? " " + cls : "");
}

chrome.runtime.sendMessage({ type: "GET_SETTINGS" }, (resp) => {
  if (chrome.runtime.lastError) return;
  if (resp && resp.dashboardUrl) urlInput.value = resp.dashboardUrl;
});

saveBtn.addEventListener("click", () => {
  const v = urlInput.value.trim();
  if (!v) { setMsg("Enter the dashboard URL.", "err"); return; }
  chrome.runtime.sendMessage({ type: "SET_DASHBOARD_URL", dashboardUrl: v }, (resp) => {
    if (chrome.runtime.lastError) { setMsg(chrome.runtime.lastError.message, "err"); return; }
    setMsg("Saved. Dashboard URL: " + v, "ok");
  });
});
