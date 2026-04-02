# Home Dashboard

Home Dashboard is a low-maintenance eInk wall display for family logistics: calendar,
weather, birthdays, and other glanceable daily context on a Raspberry Pi with a Waveshare
display. It's designed to be calm, readable, and reliable for unattended use, with quiet
hours, caching, graceful fallback behavior, and a handful of well-designed themes. Advanced
customization is available, but the default setup is optimized to get something useful on
the wall fast.

![Default theme preview](output/theme_default.png)

---

## Choose Your Path

- **First install on a Raspberry Pi:** start with [Quick Start](#quick-start), then finish
  [Google Calendar Setup](docs/setup.md#google-calendar-setup) if you use calendar/birthdays.
- **Want calendar without a GCP project?** Use [ICS Feed (No GCP Required)](docs/setup.md#ics-feed-no-gcp-required)
  — just paste one URL from Google Calendar settings, no credentials file needed.
- **Upgrading from an older release:** go to [Upgrading from v3](docs/upgrading-from-v3.md).
- **Local dev / preview only:** jump to [Development](docs/development.md) and run `make setup`
  + `make dry` (no hardware required).

## Documentation

- [Setup Guide](docs/setup.md) — Google Calendar, ICS feed, birthdays, Raspberry Pi setup, hardware
- [Themes](docs/themes.md) — all 16 built-in themes, random rotation, schedule, creating your own
- [Configuration Reference](docs/configuration.md) — full config.yaml, cache tuning, filtering, circuit breaker
- [Development](docs/development.md) — Makefile targets, CLI flags, project structure, dependencies
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
