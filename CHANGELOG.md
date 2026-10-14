# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-10-14

First tagged release.

### Added

- **Dashboard** — add watched items with a live, auto-sorted countdown; browser
  notification and spoken alert when an item is about to end.
- **Browser extension** (Chrome / Edge / Firefox) — one-click "Add to Watchlist"
  on ShopGoodwill listing pages, with the end time read from the page and
  confirmed before saving.
- **Personalized extension download** — the Settings page serves an extension
  zip pre-configured to the dashboard's address (no manual URL setup).
- **Telegram notifications** — tiered, escalating pushes: a first heads-up, a
  final-minutes "bid now" nudge, and an "auction ended" notice. The countdown is
  refreshed in the message as it ticks down.
- **Settings page** — configure the Telegram bot token, chat ID, poll interval,
  and countdown refresh interval in the UI (stored in `data/settings.json`).
- **DST-safe Pacific time** — end times are interpreted as Pacific Time with
  correct daylight-saving handling.
- **Docker support** — single-container deployment with a persisted `data/`
  volume.
- **GHCR image** — multi-arch (`linux/amd64`, `linux/arm64`) image published to
  `ghcr.io/lancetm714/shopgoodwill-watchlist`, with a `docker-compose.ghcr.yml`
  for NAS / server deploys.
- **CI** — GitHub Actions workflow builds and pushes the image on push to `main`
  and on `v*` tags.

### Fixed

- Notifier now starts reliably after container restarts.
- Sent-reminder state is persisted to disk, so reminders survive restarts
  without duplicating or being missed.
- End times are stored as exact UTC, fixing a timezone offset bug.
- Notifier activity is logged so it is visible in `docker logs`.

[Unreleased]: https://github.com/lancetm714/shopgoodwill-watchlist/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/lancetm714/shopgoodwill-watchlist/releases/tag/v1.1.0
