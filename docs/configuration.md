← [README](../README.md)

# Configuration Reference

- [Full config reference](#full-config-reference)
- [Cache and staleness](#cache-and-staleness)
- [Fetch intervals](#fetch-intervals)
- [Event filtering](#event-filtering)
- [Circuit breaker](#circuit-breaker)
- [Conditional display refresh](#conditional-display-refresh)
- [Incremental calendar sync](#incremental-calendar-sync)

---

## Full config reference

All fields are optional. Missing fields use defaults shown below.

```yaml
display:
  model: "epd7in5_V2"             # Waveshare model name
  # width: 800                    # override auto-derived width
  # height: 480                   # override auto-derived height
  enable_partial_refresh: false    # use partial eInk refresh (faster, lower quality)
  max_partials_before_full: 6     # partial refreshes before forcing a full one
  week_days: 7                    # number of days in the week view
  show_weather: true
  show_birthdays: true
  show_info_panel: true

google:
  service_account_path: "credentials/service_account.json"
  calendar_id: "primary"
  additional_calendars: []
  # contacts_email: "you@yourdomain.com"  # required for birthdays.source: "contacts"
  daily_quota_warning: 500         # log warning when daily API calls exceed this

  # ICS feed alternative — when set, service_account_path is ignored for events.
  # Get the URL: Google Calendar → Settings → [calendar] → "Secret address in iCal format"
  # ical_url: "https://calendar.google.com/calendar/ical/.../.../basic.ics"
  # additional_ical_urls: []

weather:
  api_key: ""
  latitude: 0.0
  longitude: 0.0
  units: "imperial"                # "imperial", "metric", or "standard"

purpleair:                         # optional — adds AQI card to the weather theme
  api_key: ""                      # get a free key at develop.purpleair.com
  sensor_id: 0                     # find at map.purpleair.com (click sensor → URL)

birthdays:
  source: "file"                   # "file", "calendar", or "contacts"
  file_path: "config/birthdays.json"
  calendar_keyword: "Birthday"
  lookahead_days: 30

schedule:
  quiet_hours_start: 23            # hour (0-23)
  quiet_hours_end: 6               # hour (0-23)

timezone: "local"                  # IANA name or "local"
title: "Home Dashboard"            # text shown in the header bar
theme: "default"                   # default | terminal | minimalist | old_fashioned | today | fantasy | moonphase | moonphase_invert | qotd | qotd_invert | weather | air_quality | fuzzyclock | fuzzyclock_invert | diags | random_daily | random_hourly

random_theme:                      # only used when theme: random_daily or random_hourly
  include: []                      # allowlist (empty = all themes eligible)
  exclude: []                      # denylist (e.g. ["fantasy", "qotd"])

# theme_schedule:                  # time-of-day theme switching (checked before random/config.theme)
#   - time: "06:00"                # HH:MM, 24-hour; active theme = last entry whose time <= now
#     theme: "default"
#   - time: "22:00"
#     theme: "fuzzyclock_invert"

cache:
  weather_ttl_minutes: 60          # data older than 4x TTL is discarded
  events_ttl_minutes: 120
  birthdays_ttl_minutes: 1440
  air_quality_ttl_minutes: 30
  weather_fetch_interval: 30       # skip API call if cache is younger
  events_fetch_interval: 120
  birthdays_fetch_interval: 1440
  air_quality_fetch_interval: 15
  max_failures: 3                  # circuit breaker: failures before tripping
  cooldown_minutes: 30             # circuit breaker: wait before probing
  quote_refresh: daily             # daily | twice_daily | hourly

filters:
  exclude_calendars: []            # case-insensitive substring match
  exclude_keywords: []             # case-insensitive match against event summary
  exclude_all_day: false

output:
  dry_run_dir: "output"

logging:
  level: "INFO"
```

---

## Cache and staleness

Cached data progresses through four levels based on age relative to its TTL:

| Level | Age vs TTL | Behaviour |
|---|---|---|
| **FRESH** | <= TTL | Normal display |
| **AGING** | 1--2x TTL | Normal display |
| **STALE** | 2--4x TTL | Header shows "! Stale" indicator |
| **EXPIRED** | > 4x TTL | Data discarded, not displayed |

---

## Fetch intervals

Each data source has an independent fetch interval. When cached data is younger than the
interval, the API call is skipped entirely. This reduces API quota usage significantly.

| Source | Default interval | Default TTL |
|---|---|---|
| Weather | 30 min | 60 min |
| Calendar events | 120 min | 120 min |
| Birthdays | 1440 min (24h) | 1440 min |
| Air quality (PurpleAir) | 15 min | 30 min |

---

## Event filtering

```yaml
filters:
  exclude_calendars: ["US Holidays", "Spam Calendar"]
  exclude_keywords: ["OOO", "Focus Time", "Block"]
  exclude_all_day: false
```

Filters use case-insensitive substring matching. Filtered events remain in cache for
incremental sync correctness -- they are only hidden at render time.

---

## Circuit breaker

After 3 consecutive failures (configurable), a source is "tripped" and goes straight to
cache on subsequent runs. After the cooldown period, a single probe request is sent. If it
succeeds, normal fetching resumes.
Use `--ignore-breakers` to bypass OPEN breaker state for one run (useful for manual recovery checks).

---

## Conditional display refresh

The dashboard computes a SHA-256 hash of each rendered image and compares it to the
previous render. When nothing has changed (common overnight or on quiet days), the eInk
refresh is skipped entirely. This extends display lifespan and saves power.
`--force-full-refresh` bypasses this check.

---

## Incremental calendar sync

After the first full sync, subsequent fetches download only changed events using Google
Calendar sync tokens. This dramatically reduces API quota usage. Sync state is persisted
to `output/calendar_sync_state.json`.

This applies to the **service account path only**. When using `ical_url`, the full feed
is re-fetched on every calendar refresh (no sync tokens — ICS has no equivalent mechanism).
See [ICS Feed](setup.md#ics-feed-no-gcp-required) for the trade-offs.
