# Frequently Asked Questions

## General

### What happens during quiet hours?

During quiet hours (default 23:00 - 06:00, configurable via `schedule.quiet_hours_start`
and `schedule.quiet_hours_end`), the dashboard exits immediately without refreshing
the display or making API calls. The display retains whatever was last rendered.

The first run after quiet hours end automatically triggers a full eInk refresh
to ensure a clean image.

Quiet hours are bypassed when using `--dry-run`.

### How do I manually refresh the display?

The easiest way is the **Refresh Now** button on the [Web UI](web-ui.md) status page —
no SSH required.

From the command line, run the dashboard service directly:

```bash
sudo systemctl start dashboard.service
```

Or run the Python command:

```bash
cd ~/home-dashboard
venv/bin/python -m src.main --config config/config.yaml
```

Add `--force-full-refresh` to force a full eInk refresh and bypass fetch intervals.

If you use `display.provider: inky`, normal non-fuzzyclock themes are also limited to
one hardware update per hour because the Inky Impression does not support partial refresh.
`fuzzyclock` and `fuzzyclock_invert` bypass that hourly limit.

### How long is stale data kept?

Data progresses through four staleness levels based on age relative to the
configured TTL for each source:

| Level | Age | Behavior |
|-------|-----|----------|
| **Fresh** | < 1x TTL | Normal display |
| **Aging** | 1-2x TTL | Normal display |
| **Stale** | 2-4x TTL | Shown with `!` badge on the panel |
| **Expired** | > 4x TTL | Discarded; panel shows "Unavailable" |

Default TTLs: weather 60 min, calendar 120 min, birthdays 1440 min (24h),
air quality 30 min. All configurable in `config.yaml` under `cache:`.

### Where are the log files?

- **Dashboard log**: `output/dashboard.log` (or wherever `output.dry_run_dir` points)
- **Systemd journal**: `journalctl -u dashboard.service` (if using systemd)
- **Quick tail**: `make pi-logs` from the project directory

## Calendar

### ICS feed vs Google Calendar API -- which should I use?

**ICS feed** (recommended for most users): Simpler setup, no GCP project needed.
Paste the "Secret address in iCal format" URL from Google Calendar settings into
`google.ical_url` in your config. Trade-off: no incremental sync (full feed is
re-downloaded each time) and no contacts-based birthdays.

**Google Calendar API**: Required if you need incremental sync (faster for large
calendars), contacts-based birthday fetching, or domain-wide delegation. Requires
a GCP project and service account JSON.

### Why are my calendar events not showing up?

1. **ICS feed**: Verify the URL is the "Secret address in iCal format" (not the
   public URL). Test it by opening the URL in a browser -- you should see raw
   calendar data.
2. **Google API**: Ensure you shared your calendar with the service account email
   address (it looks like `name@project-id.iam.gserviceaccount.com`).
3. Check `make pi-logs` for error messages.
4. Run `make check` to validate your configuration.

## Weather

### How do I find my coordinates?

Search for your city at [latlong.net](https://www.latlong.net/) or use Google Maps
(right-click any location to copy coordinates). Set `weather.latitude` and
`weather.longitude` in `config/config.yaml`.

### How do I get an OpenWeatherMap API key?

1. Sign up at [openweathermap.org](https://openweathermap.org/api)
2. Go to "API keys" in your account
3. Copy the key and paste it into `weather.api_key` in config

The free tier allows 1,000 calls/day -- more than enough for the default
30-minute fetch interval.

## Themes

### How do I add a new theme?

1. Create `src/render/themes/my_theme.py` with a factory function returning a `Theme`
2. Register it in `_THEME_REGISTRY` in `src/render/theme.py`
3. That's it -- `AVAILABLE_THEMES` is derived automatically from the registry

See [Themes documentation](themes.md) and existing themes for examples.

### How does random theme rotation work?

- `theme: random_daily` picks a theme once per day (after midnight) and persists
  the choice in `state/random_theme_state.json`.
- `theme: random_hourly` picks once per hour and persists in
  `state/random_theme_hourly_state.json`.
- Delete the state file to force a new pick immediately.
- Use `random_theme.include` and `random_theme.exclude` in config to control
  which themes are in the rotation pool.
- `countdown`, `photo`, `message`, and `diags` are excluded from the random
  pool by default — they all need manual input and aren't useful as random picks.

### How do I configure the countdown theme?

Add entries under `countdown.events` in `config.yaml` and set `theme: countdown`:

```yaml
theme: countdown
countdown:
  events:
    - name: "Paris Trip"
      date: "2026-06-04"
    - name: "Anniversary"
      date: "2026-08-12"
```

Up to five upcoming entries are shown. Past dates are dropped silently. One
event renders as a hero numeral; multiple events stack as a list. See
[Themes → countdown](themes.md#countdown).

### What data does the astronomy theme need?

The `astronomy` theme works best with `weather.latitude` / `weather.longitude`
set in `config.yaml` — those enable the civil/nautical/astronomical twilight
times, day-length delta, and the dark-sky window. Without coordinates, the
theme falls back to OWM-reported sunrise/sunset (from `fetch_weather()`) and
hides the twilight section.

Moon phase, next full/new moon, and the next meteor shower are computed from
pure math and always work.

### What is `theme_rules`?

`theme_rules` picks a theme based on live context — weather, time-of-day,
season, or weekday. Rules fire *before* `theme_schedule` so they can override
the time-of-day schedule when, for example, a storm alert arrives.

```yaml
theme_rules:
  - when: { weather_alert_present: true }
    theme: "message"
  - when: { weather: ["rain", "snow", "thunderstorm"] }
    theme: "weather"
  - when: { daypart: "night", weather: "clear" }
    theme: "moonphase"
```

First match wins. See [Themes → Context-aware theme rules](themes.md#context-aware-theme-rules)
for the full condition reference.

### How do I force a full eInk refresh?

```bash
venv/bin/python -m src.main --config config/config.yaml --force-full-refresh
```

Or wait for the automatic full refresh that happens after
`max_partials_before_full` partial refreshes (default: 6).

That partial-refresh setting applies to Waveshare only. Inky Impression panels always do
full refreshes, and the dashboard instead limits non-fuzzyclock hardware writes to once
per hour.

## Display

### The display shows ghosting or artifacts

eInk displays accumulate artifacts over partial refreshes. The dashboard
automatically performs a full refresh after a configurable number of partial
refreshes (`display.max_partials_before_full`, default 6). You can also force
one with `--force-full-refresh`.

For `display.provider: inky`, the panel does not support partial refresh at all.
The dashboard therefore treats Inky differently: non-fuzzyclock themes are
limited to one hardware update per hour, while `fuzzyclock` and
`fuzzyclock_invert` continue updating normally.

### Which displays are supported?

See `display.provider` and `display.model` options in the
[Configuration Reference](configuration.md)
or the [Setup Guide](setup.md#supported-displays).
