# Home Dashboard

Home Dashboard is a low-maintenance eInk wall display for family logistics: calendar,
weather, birthdays, and other glanceable daily context on a Raspberry Pi with a Waveshare
display. It's designed to be calm, readable, and reliable for unattended use, with quiet
hours, caching, graceful fallback behavior, and a handful of well-designed themes. Advanced
customization is available, but the default setup is optimized to get something useful on
the wall fast.

- Weekly calendar view — works via ICS feed (no GCP account needed) or Google Calendar API
- Current weather, forecast, and optional air quality (OpenWeatherMap + PurpleAir)
- Upcoming birthdays from Google Contacts, a flat file, or a calendar feed
- Daily quote from a bundled library
- 20 built-in themes with random daily/hourly rotation and a schedule override
- Graceful degradation: stale-cache fallback, circuit breakers, staleness indicators
- Optional web UI — health dashboard, safe config editor, recent events, integration diagnostics, and one-click refresh from any browser on your network

![Default theme preview](output/theme_default.png)

---

## Choose Your Path

- **First install on a Raspberry Pi:** start with [Quick Start](#quick-start).
- **Setting up calendar (recommended for most):** use [ICS Feed (No GCP Required)](docs/setup.md#ics-feed-no-gcp-required)
  — paste one URL from Google Calendar settings, no credentials file or GCP project needed.
- **Need contacts-based birthdays or incremental sync?** Follow [Google Calendar Setup](docs/setup.md#google-calendar-setup)
  to configure a service account instead.
- **Upgrading from an older release:** go to [Upgrading from v3](docs/upgrading-from-v3.md).
- **Want a browser-based status page and config editor?** See [Web UI](docs/web-ui.md) — install in four steps with `make web-enable`.
- **Local dev / preview only:** jump to [Development](docs/development.md) and run `make setup`
  + `make dry` (no hardware required).

## Documentation

- [Setup Guide](docs/setup.md) — Google Calendar, ICS feed, birthdays, Raspberry Pi setup, hardware
- [Web UI](docs/web-ui.md) — browser-based status page, config editor, manual refresh, authentication
- [Themes](docs/themes.md) — all 20 built-in themes, random rotation, schedule, creating your own
- [Configuration Reference](docs/configuration.md) — full config.yaml, cache tuning, filtering, circuit breaker
- [Development](docs/development.md) — Makefile targets, CLI flags, project structure, dependencies
- [Architecture](docs/architecture.md) — data flow, module layers, key design decisions
- [Contributing](CONTRIBUTING.md) — local setup, code style, how to add themes/fetchers, PR checklist
- [FAQ](docs/faq.md) — quiet hours, troubleshooting, common questions
- [Upgrading from v3](docs/upgrading-from-v3.md) — migration paths and what's new

---

## Quick Start

SSH into your Pi, then run these commands from the project directory:

```bash
git clone https://github.com/gkoch02/Dashboard-v4.git ~/home-dashboard
cd ~/home-dashboard
make pi-install    # apt deps, SPI, Python venv, Waveshare drivers — all in one
make configure     # interactive prompts fill in your API keys and settings
make dry           # render a preview with dummy data — no hardware needed
make pi-enable     # install and start the systemd refresh timer
make pi-status     # confirm the timer is active and healthy
```

That's it. The dashboard starts refreshing every 5 minutes automatically.

> **Note:** `make pi-install` enables SPI via `raspi-config`. If SPI was not previously
> enabled on your Pi, reboot once before running on real hardware (`sudo reboot`).
> `make configure` and `make dry` work fine before the reboot.
>
> **Next:** if you use Google Calendar or Google Contacts birthdays, complete
> [Google Calendar Setup](docs/setup.md#google-calendar-setup) before your first live run.

---

## make configure

`make configure` is an interactive wizard that writes your settings directly into
`config/config.yaml`. Run it after `make pi-install`.

```
Display model [epd7in5_V2]:
OpenWeatherMap API key:
Latitude:
Longitude:
Units (imperial/metric) [imperial]:
Google Calendar ID:
Timezone [America/New_York]:
PurpleAir API key (optional, press Enter to skip):
PurpleAir sensor ID (optional, press Enter to skip):
```

Existing values are shown as defaults — it is safe to re-run at any time to change a
setting. The wizard ends by running `make check` to validate your configuration.

**Google service account JSON** cannot be fetched automatically — it requires a
one-time browser download from Google Cloud Console. The wizard guides you through
placing it at `credentials/service_account.json` and links to the
[Google Calendar Setup](docs/setup.md#google-calendar-setup) instructions.

---

For supported display models and hardware recommendations, see the
[Setup Guide](docs/setup.md#supported-displays).

---

## Prerequisites

- **Hardware**: Raspberry Pi 3, 4, or 5 with a [supported Waveshare eInk display](docs/setup.md#supported-displays)
- **Software**: Raspberry Pi OS (Bookworm or later), Python 3.9+
- **Network**: Internet connection for API calls (weather, calendar)
- **Accounts**: Free [OpenWeatherMap API key](https://openweathermap.org/api) for weather; Google Calendar (ICS feed or service account) for events

---

## First-Run Checklist

After completing [Quick Start](#quick-start), verify everything is working:

1. `make check` -- validates your config file (API keys, paths, coordinates)
2. `make dry` -- renders a preview with dummy data to `output/latest.png`
3. Open `output/latest.png` on your computer to confirm the layout looks right
4. `make pi-enable` -- installs and starts the systemd refresh timer
5. `make pi-status` -- confirms the timer is active and shows recent logs

If anything looks wrong, see [Troubleshooting](#troubleshooting) below.

---

## Reliability

The dashboard is designed to run unattended for months. When things go wrong,
it degrades gracefully instead of showing a blank screen:

- **Cached data**: If an API call fails, the last successful response is used.
  A small `!` badge appears on stale panels so you know the data isn't fresh.
- **Staleness levels**: Data progresses through Fresh -> Aging -> Stale -> Expired
  based on age relative to the configured TTL. Expired data (older than 4x TTL)
  is discarded entirely.
- **Circuit breaker**: After 3 consecutive failures for a source (configurable),
  the dashboard stops attempting that API call for a cooldown period (default 30
  minutes), then probes once to see if it has recovered.
- **Independent sources**: A weather API outage doesn't affect calendar display.
  Each data source fetches, caches, and fails independently.

---

## Web UI

The optional web interface runs on the Pi and is accessible from any browser on your network at `http://<pi-hostname>:8080`.

| Page | What it does |
|---|---|
| **Status** (`/`) | System health, active/effective theme, live image preview, source diagnostics, integration readiness, recent events, system metrics, log tail |
| **Config** (`/config`) | Edit `config.yaml` in the browser with Basic/Advanced modes, change summary, backup restore, and review-before-save |
| **Refresh Now** | Triggers an immediate dashboard run without SSH |

Install in four steps:

```bash
venv/bin/pip install -r requirements-web.txt   # install Flask + Waitress
cp config/web.example.yaml config/web.yaml     # create web config
venv/bin/python -m src.web.auth --set-password # set a login password
# also set web.secret_key in config/web.yaml for CSRF/session integrity
make web-enable                                 # install + start systemd service
```

See [Web UI](docs/web-ui.md) for full setup details, current feature set, SSH tunnel access, and security notes.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Blank/white display | SPI not enabled, or display cable loose | Run `sudo raspi-config` -> Interface Options -> SPI -> Enable, then `sudo reboot` |
| Display shows old data | API fetch failing, using stale cache | Run `make pi-logs` to check for errors; verify API keys with `make check` |
| Calendar events missing | Service account not shared, or wrong calendar ID | Verify `calendar_id` in config; ensure the service account email has read access to your calendar |
| Weather showing wrong location | Coordinates still set to defaults | Check `weather.latitude` and `weather.longitude` in `config/config.yaml` |
| `make dry` works but display stays blank | Hardware issue or wrong display model | Verify `display.model` in config matches your Waveshare model |
| Timer not running | systemd units not installed | Run `make pi-enable` and check `make pi-status` |
| Web UI not loading | Service not installed or wrong port | Run `make web-enable`, then `make web-status` to check for errors |

For logs, run `make pi-logs` to tail the dashboard log, or check
`output/dashboard.log` directly. See also the [FAQ](docs/faq.md).
