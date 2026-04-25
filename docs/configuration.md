← [README](../README.md)

# Configuration Reference

- [Full config reference](#full-config-reference)
- [Theme selection priority](#theme-selection-priority)
- [Cache and staleness](#cache-and-staleness)
- [Fetch intervals](#fetch-intervals)
- [Event filtering](#event-filtering)
- [Circuit breaker](#circuit-breaker)
- [Conditional display refresh](#conditional-display-refresh)
- [Incremental calendar sync](#incremental-calendar-sync)

---

## Full config reference

Most fields have sensible defaults. The example below shows every supported key with its default value; copy only the ones you need to change. A few fields are conditionally required (notably `weather.api_key`, `weather.latitude`/`longitude`, and either `google.service_account_path` or `google.ical_url`).

```yaml
display:
  provider: "waveshare"           # "waveshare" | "inky"
  model: "epd7in5_V2"             # provider-specific model name
  # width: 800                    # override auto-derived width
  # height: 480                   # override auto-derived height
  enable_partial_refresh: false    # Waveshare only; ignored/not supported on Inky
  max_partials_before_full: 20    # partial refreshes before forcing a full one
  week_days: 7                    # number of days in the week view
  show_weather: true
  show_birthdays: true
  show_info_panel: true
  # quantization_mode: "threshold" # Waveshare 1-bit path: threshold | floyd_steinberg | ordered

google:
  service_account_path: "credentials/service_account.json"
  calendar_id: "primary"
  additional_calendars: []
  # contacts_email: "you@yourdomain.com"  # required for birthdays.source: "contacts"
                                          # — the user whose Google Contacts the
                                          # service account reads via the People API
                                          # (requires domain-wide delegation; see
                                          # setup.md → Birthday Configuration)
  daily_quota_warning: 500         # log warning when daily API calls exceed this

  # ICS feed alternative — when set, service_account_path is ignored for events.
  # Get the URL: Google Calendar → Settings → [calendar] → "Secret address in iCal format"
  # ical_url: "https://calendar.google.com/calendar/ical/.../.../basic.ics"
  # additional_ical_urls: []        # optional extra ICS URLs; events are merged
                                    # with `ical_url`. Per-feed failure is non-fatal:
                                    # any feed that returns an HTTP error is logged
                                    # as a warning and skipped while the others render.

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
theme: "default"                   # see themes.md for the full catalog;
                                   # use one of the 25 built-in theme names,
                                   # or `random_daily` / `random_hourly` for rotation

# photo:                           # only used when theme: photo (see setup.md → Photo theme)
#   path: "/home/pi/wallpaper.jpg" # JPEG or PNG; converted to greyscale and dithered
                                   # (Floyd-Steinberg on Waveshare; Spectra-6 palette mapping on Inky)

# countdown:                       # only used when theme: countdown (see themes.md → countdown)
#   events:                        # up to 5 upcoming entries; past ones dropped silently
#     - name: "Paris Trip"
#       date: "2026-06-04"
#     - name: "Anniversary"
#       date: "2026-08-12"

random_theme:                      # only used when theme: random_daily or random_hourly
  include: []                      # allowlist (empty = all themes eligible)
  exclude: []                      # denylist (e.g. ["fantasy", "qotd"])

# theme_schedule:                  # time-of-day theme switching (checked before config.theme)
#   - time: "06:00"                # HH:MM, 24-hour; active theme = last entry whose time <= now
#     theme: "default"
#   - time: "22:00"
#     theme: "fuzzyclock_invert"

# theme_rules:                     # context-aware rules; evaluated BEFORE theme_schedule
#   - when: { weather_alert_present: true }
#     theme: "message"
#   - when: { calendar: "birthday_today" }
#     theme: "today"
#   - when: { calendar: ["empty", "done"] }
#     theme: "qotd"
#   - when: { weather: ["rain", "snow", "thunderstorm"] }
#     theme: "weather"
#   - when: { daypart: "night", weather: "clear" }
#     theme: "moonphase"
#   # See themes.md → Context-aware theme rules for the full condition reference.

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

## Theme selection priority

The concrete theme used for each render is resolved in this order (highest wins):

1. `--theme` CLI override
2. `theme_rules` — first matching context rule (weather / daypart / season / weekday / calendar). See [Context-aware theme rules](themes.md#context-aware-theme-rules).
3. `theme_schedule` — latest HH:MM entry whose time ≤ now.
4. `theme` — the static config value (may be `random`, `random_daily`, `random_hourly`).

Rules that reference weather or calendar data silently skip on first boot (no cached data), so the resolver falls through cleanly. If any rule can resolve to `monthly`, the calendar event window is pre-sized for the month grid so the view has complete data when the rule fires.

---

## Quantization mode

The `display.quantization_mode` field controls how the greyscale rendering canvas is
converted to the 1-bit output required by Waveshare displays. All built-in themes render
in strict black/white so the choice only affects output when:

- A display model with a non-default resolution is configured (the LANCZOS resize produces
  intermediate grey pixels that must be quantized), or
- A custom theme opts into greyscale rendering by setting `canvas_mode = "L"` in its
  `ThemeLayout` (see [Creating your own theme](themes.md#creating-your-own-theme)).

| Mode | Algorithm | When to use |
|---|---|---|
| `threshold` | Simple split at 128 — pixels > 128 → white, ≤ 128 → black. No dithering. | **Default.** Preserves the strict black/white look of all built-in themes. |
| `floyd_steinberg` | Error-diffusion dithering (Pillow built-in). | Smoothest apparent grey for scaled or greyscale-rendered content. Note: the previous resize path used this algorithm implicitly — set this mode to restore that exact behavior for non-default display sizes. |
| `ordered` | 4×4 Bayer threshold matrix (pure Python, no numpy). | Regular dot-matrix pattern; useful for structured gradients or a halftone aesthetic. |

```yaml
display:
  quantization_mode: "threshold"   # threshold | floyd_steinberg | ordered
```

For `display.provider: inky`, the final output is mapped to the Inky Impression's
limited color palette instead of being quantized to 1-bit.

---

## Display providers and models

```yaml
display:
  provider: "waveshare"
  model: "epd7in5_V2"
```

Supported providers:

- `waveshare` — Waveshare e-Paper HATs via the `waveshare_epd` Python package
- `inky` — Pimoroni Inky Impression panels via the `inky` Python package

Supported models:

- `waveshare`: `epd7in5`, `epd7in5_V2`, `epd7in5_V3`, `epd7in5b_V2`, `epd7in5_HD`, `epd9in7`, `epd13in3k`
- `inky`: `impression_7_3_2025`

Width and height are derived automatically from the selected provider/model unless
overridden explicitly.

---

## Cache and staleness

Cached data progresses through four levels based on age relative to its TTL:

| Level | Age vs TTL | Behaviour |
|---|---|---|
| **Fresh** | ≤ 1× TTL | Normal display |
| **Aging** | 1–2× TTL | Normal display |
| **Stale** | 2–4× TTL | Panel shows a `!` staleness badge |
| **Expired** | > 4× TTL | Data discarded; panel shows "Unavailable" |

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

When `display.provider: inky` is selected, there is an additional time-based limit because
the Inky Impression panel does not support partial refresh:

- Non-fuzzyclock themes are limited to one hardware update per hour.
- `fuzzyclock` and `fuzzyclock_invert` bypass that hourly limit and can refresh at the
  normal timer cadence.
- `--force-full-refresh` bypasses the hourly limit.

The Inky throttle state is persisted in `state/inky_refresh_state.json`.

---

## Incremental calendar sync

After the first full sync, subsequent fetches download only changed events using Google
Calendar sync tokens. This dramatically reduces API quota usage. Sync state is persisted
to `state/calendar_sync_state.json`.

This applies to the **service account path only**. When using `ical_url`, the full feed
is re-fetched on every calendar refresh (no sync tokens — ICS has no equivalent mechanism).
See [ICS Feed](setup.md#ics-feed-no-gcp-required) for the trade-offs.
