# Goodwill Watchlist — Local Dashboard + Browser Extension

A ToS-safe watchlist for ShopGoodwill.com auctions. Add items you're watching,
see a live countdown, and get alerted when an auction is about to end.

**Why "ToS-safe":** this tool does NOT scrape the site or use its internal API,
and it does NOT automate bidding. End times are entered by you (or captured from
the page you're already viewing, then confirmed by you). It only reads publicly
displayed data and never sends or places bids.

## Parts

| Part | Purpose |
|------|---------|
| `app/` | Flask web dashboard (list form, live countdown grid, alerts). Data stored in `data/watchlist.json`. |
| `extension/` | Chrome / Edge / Firefox extension. Adds a floating "Add to Watchlist" button on listing pages and sends the confirmed end time to your dashboard. |

## Dashboard

### Run locally
```
python -m pip install -r requirements.txt
python run.py
```
Open http://localhost:6518

### Run with Docker
```
docker compose up --build
```
Open http://localhost:6518

### Usage
1. Open a ShopGoodwill listing page and note its **ending time (Pacific Time)**.
2. In the dashboard, paste the listing URL (optional), a label, the end time,
   and an alert threshold (default 10 minutes).
3. The item shows a live countdown. When it crosses your threshold you get a
   browser notification plus a spoken alert.

End times without a timezone are interpreted as **Pacific Time** (the zone the
site displays). You may also paste a UTC timestamp if present.

## Browser extension

Adds a floating **"Add to Watchlist"** button on `shopgoodwill.com/item/*`
pages. Click it, confirm (or edit) the ending time shown on the page, and it's
added to your dashboard in one click.

### Install (unpacked)

**Chrome / Edge / Brave**
1. Open the extensions page (`chrome://extensions` or `edge://extensions`).
2. Enable **Developer mode** (top-right).
3. Click **Load unpacked** and select the `extension/` folder.

**Firefox**
1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on** and select `extension/manifest.json`.
   (Temporary add-ons load until Firefox closes; see below for a permanent
   signed/packaged option.)

### Configure the dashboard URL
Click the extension's toolbar icon, set the dashboard URL (default
`http://localhost:6518`), and save. Make sure the dashboard is running.

### Note on accuracy
ShopGoodwill allows sellers to extend auctions or use a "soft close" in the
final minutes. The end time is captured (and confirmed) at the moment you click
Add; if the seller extends the auction afterward, re-run the button to refresh.

## Phone push notifications (Telegram)

Get a push to your Android phone 10–15 minutes before an item ends. The backend
polls your watchlist and sends a Telegram message once per item (no spam).

### Setup
1. Create a bot with **@BotFather** on Telegram (send `/newbot`, pick a name).
   It gives you a **bot token** like `123456:ABC...`.
2. Get your **chat id**: message your bot once, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` — find `"chat":{"id":...}`.
3. Set the environment variables and start the app:

   **Local:**
   ```
   set TELEGRAM_ENABLED=1
   set TELEGRAM_BOT_TOKEN=<your token>
   set TELEGRAM_CHAT_ID=<your chat id>
   python run.py
   ```
   (Linux/macOS: use `export` instead of `set`.)

   **Docker:** copy `.env.example` to `.env`, fill it in, then
   `docker compose up --build` (compose reads `.env` automatically).

4. The dashboard shows a **Phone notification** status card confirming whether
   notifications are on/off.

### How it works
- Polls `data/watchlist.json` every `TELEGRAM_POLL_SECONDS` (default 30s).
- When an item falls within its `alertMinutes` threshold (default per-item 10m),
  it sends one Telegram message with the item name, time remaining, end time,
  and a link — then marks it sent so it won't repeat.
- The message's countdown is refreshed in place every `TELEGRAM_EDIT_SECONDS`
  (default 30s, speeding up in the final minutes), so the "time remaining" stays
  roughly current without reopening the dashboard.
- Alerts only use the end times **you entered**; it never contacts
  ShopGoodwill's site or API.

The poll interval and countdown-refresh interval are configurable from the
**Settings** page (http://localhost:6518/settings).

## Notes / limitations
- The extension reads the end time from the page content **you're already
  viewing** and always shows a confirmation dialog before sending. It does not
  silently extract data in the background.
- This is for personal, non-commercial tracking only, per ShopGoodwill's Terms
  of Use. Review the current Terms of Use before use.
