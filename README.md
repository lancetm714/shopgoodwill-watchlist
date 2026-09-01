# ShopGoodwill Watchlist

A ToS-safe watchlist for ShopGoodwill.com auctions: add items you're watching,
see a live countdown, and get a push to your phone when an auction is about to
end.

**Why "ToS-safe":** this tool does **not** scrape the site, use its internal
API, or automate bidding. End times are entered by you (or captured from the
page you're already viewing and confirmed by you). It only works with data you
provide, and it never places or interferes with bids.

---

## Features

- **Dashboard** — add items with a live, auto-sorted countdown; browser
  notification + spoken alert when one is about to end.
- **Browser extension** — one-click "Add to Watchlist" on any listing page, with
  the end time auto-filled and confirmed before saving.
- **Phone push (Telegram)** — get an alert 10–15 minutes before an item ends,
  with the countdown refreshed in the message as it ticks down.
- **Docker-ready** — runs in a single container; data and settings persist.

---

## Quick start

### Docker (recommended)

```bash
docker compose up --build
```

Open **http://localhost:6518**.

### Docker from GHCR (prebuilt image)

The image is published automatically to
`ghcr.io/lancetm714/shopgoodwill-watchlist` on every push to `main`.

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

Use this on a NAS or any Docker host without building from source. See
[Deploying on a NAS](#deploying-on-a-nas).

### Run locally (no Docker)

```bash
python -m pip install -r requirements.txt
python run.py
```

Open **http://localhost:6518**.

> The default port is `6518`. Override it with the `PORT` environment variable.

---

## Deploying on a NAS

The `docker-compose.ghcr.yml` pulls the prebuilt image from GHCR, so no source
code or build step is needed on the NAS.

1. Create a project folder, e.g. `/volume1/docker/shopgoodwill-watchlist`.
2. Inside it, place `docker-compose.ghcr.yml` and create an empty `data/` folder
   (Docker bind-mounts often fail if the target folder doesn't already exist).
3. In Synology **Container Manager → Project → Add**, point it at that folder,
   then start the project.
4. Open **http://<NAS-IP>:6518** and configure Telegram on the
   **Settings** page — the token, chat ID, and intervals are saved into
   `data/settings.json` on the NAS volume and persist across updates.

---

## Dashboard usage

1. Open a ShopGoodwill listing page and note its **ending time (Pacific Time)**.
2. In the dashboard, paste the listing URL (optional), a label, the end time,
   and an alert threshold (default 10 minutes).
3. The item appears as a card with a **live countdown**, sorted by soonest end.
4. When an item crosses your threshold, you get a **browser notification** and a
   **spoken alert**.

End times without a timezone are interpreted as **Pacific Time** (the zone the
site displays). You may also paste a UTC timestamp if present.

---

## Browser extension

Adds a floating **"Add to Watchlist"** button on `shopgoodwill.com/item/*`
pages. Click it, confirm (or edit) the ending time shown on the page, and it's
added to your dashboard in one click — no copy/paste.

### Install (unpacked)

**Chrome / Edge / Brave**

1. Open the extensions page (`chrome://extensions` or `edge://extensions`).
2. Turn on **Developer mode** (top-right).
3. Click **Load unpacked** and select the `extension/` folder from this repo.

**Firefox**

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on** and select `extension/manifest.json`.
   (Temporary add-ons unload when Firefox closes; for a permanent install you'd
   need a signed/packaged build.)

### Configure the dashboard URL

Click the extension's toolbar icon, set the dashboard URL (default
`http://localhost:6518`), and save. Make sure the dashboard is running on that
port first.

> If you change the dashboard's port, update this URL too.

### Accuracy note

ShopGoodwill allows sellers to extend auctions or use a "soft close" in the
final minutes. The end time is captured (and confirmed) at the moment you click
**Add**; if the seller extends the auction afterward, click the button again to
refresh.

---

## Phone push notifications (Telegram)

Get a push to your Android phone when an item is about to end. The backend polls
your watchlist and sends a Telegram message once per item (no spam), refreshing
the countdown in the message as it ticks down.

### 1. First-time: get your Token & Chat ID (one-time)

1. In Telegram, message **@BotFather** and send `/newbot`. Follow the prompts to
   name your bot — it returns a **bot token** like `123456789:AAbbCC...`.
2. Message your new bot **once** (any message).
3. Open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and find
   `"chat":{"id":...}` — that number is your **Chat ID**.
   (If the result is empty `[]`, message your bot first and refresh.)

### 2. Configure in the Settings page

1. Start the app and open the **Settings** page: **http://localhost:6518/settings**.
2. Paste your **bot token** and **chat ID**.
3. Adjust the **poll interval** (how often it checks, e.g. 30s) and the
   **countdown update** (how often the message refreshes).
4. Tick **Enable notifications**, then **Save**.
5. Click **Send test notification** — you should receive a push on your phone.

The dashboard also shows a **Phone notification** status card confirming
whether notifications are on and how often it polls.

### How it works

- Polls the watchlist every **poll interval** (default 30s).
- Alerts escalate in three steps so you don't miss an auction:
  1. **Ending soon** — when an item enters its alert window (default per-item
     10m), it sends a message with the item name, time remaining, end time, and a
     link, then keeps refreshing that message's countdown in place.
  2. **Bid now** — a final-minutes extra push (default: inside the last 2
     minutes) in case the first alert was missed.
  3. **Auction ended** — a distinct notice once the stored end time has passed,
     instead of silently dropping the item.
- Each step fires only once per item, and that state is persisted to disk so a
  restart won't re-send or skip a step.
- The live message's countdown is refreshed in place every **countdown update**
  seconds (faster in the final minutes).
- Alerts use only the end times **you entered**; it never contacts ShopGoodwill's
  site or API.

> Tokens and chat IDs are stored locally in `data/settings.json`, which is
> git-ignored and never committed.

---

## Configuration reference

All of the above can also be set via environment variables (useful for Docker
via a `.env` file). UI settings entered on the Settings page take precedence.

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Dashboard port | `6518` |
| `DATA_DIR` | Directory for `watchlist.json` / `settings.json` | `./data` |
| `TELEGRAM_ENABLED` | Enable the Telegram notifier (`1`/`true`) | `0` |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | — |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID | — |
| `TELEGRAM_POLL_SECONDS` | How often the backend checks | `30` |
| `TELEGRAM_EDIT_SECONDS` | How often the message countdown refreshes | `30` |
| `TELEGRAM_NUDGE_SECONDS` | Window (seconds before end) for the "bid now" push | `120` |

For Docker, copy `.env.example` to `.env`, fill in your values, then
`docker compose up --build` — compose reads `.env` automatically.

---

## Project structure

```
.
├── app/                  Flask backend
│   ├── templates/        Dashboard + Settings pages
│   ├── static/           Frontend JS/CSS
│   ├── routes.py         HTTP API
│   ├── notifier.py       Telegram poller + sender
│   └── settings_store.py Settings persistence
├── extension/            Chrome / Edge / Firefox extension
├── data/                 Runtime data (git-ignored; created on first run)
├── .github/workflows/    GHCR publish workflow (auto-push on main)
├── Dockerfile
├── docker-compose.yml
├── docker-compose.ghcr.yml
├── .env.example
└── requirements.txt
```

---

## Notes / limitations

- The extension reads the end time from the page content **you're already
  viewing** and always shows a confirmation dialog before sending. It does not
  silently extract data in the background.
- Alerts reflect the end time as of when you added the item; if the seller
  extends the auction, re-add (or edit) the item to refresh.
- This is for personal, non-commercial tracking only, per ShopGoodwill's Terms
  of Use. Review the current Terms of Use before use.
