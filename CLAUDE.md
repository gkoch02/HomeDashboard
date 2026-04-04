# CLAUDE.md — Dashboard-v4

## Project Overview

Python eInk dashboard for Raspberry Pi. Displays a weekly calendar (Google Calendar), weather (OpenWeatherMap), upcoming birthdays, and a daily quote. Renders to a Waveshare eInk display or PNG preview. No web framework — pure CLI application.

## Quick Commands

```bash
make setup          # Create venv, install deps, copy config template
make test           # Run pytest
make dry            # Preview with dummy data → output/latest.png
make previews       # Generate all theme preview PNGs → output/theme_*.png
make check          # Validate config/config.yaml
make version        # Print current version (e.g. main.py 4.1.3)
make deploy         # Rsync to Pi (configurable: PI_USER, PI_HOST, PI_DIR)
make install        # Install systemd timer on remote Pi (via ssh/scp)
make pi-install     # Full Pi setup: apt deps, venv, Waveshare library (run ON Pi)
make pi-enable      # Install systemd units and enable timer (run ON Pi)
make pi-status      # Show timer status and recent logs (run ON Pi)
make pi-logs        # Tail output/dashboard.log (run ON Pi)
make configure      # Run deploy/configure.sh interactive setup
flake8 src/ tests/ --max-line-length=100   # Lint
```

## Tech Stack

- **Python 3.9+** — no async, no web framework
- **Pillow** — image rendering (PIL)
- **google-api-python-client / google-auth** — Google Calendar & Contacts APIs
- **requests** — OpenWeatherMap API + ICS feed fetching
- **icalendar** — ICS feed parsing (used when `google.ical_url` is configured)
- **PyYAML** — config parsing
- **pytest** — testing (with unittest.mock)
- **flake8** — linting (max line length: 100)

## Repository Structure

```
src/
├── main.py                    # Thin CLI entry point: parses args, loads config, runs DashboardApp
├── app.py                     # DashboardApp — top-level orchestrator (quiet hours, fetch, render, output)
├── cli.py                     # CLI argument parser (build_parser / parse_args)
├── data_pipeline.py           # DataPipeline — concurrent fetching, caching, circuit breaking per source
├── services/
│   ├── run_policy.py          # resolve_tz, should_skip_refresh, should_force_full_refresh
│   ├── theme.py               # resolve_theme_name (schedule → random → concrete), resolve_theme
│   └── output.py              # OutputService — publish image to display or PNG; write last_success.txt
├── services_run_policy.py     # Re-export shim for services/run_policy.py (backward compat)
├── services_theme_service.py  # Re-export shim for services/theme.py (backward compat)
├── services_output_service.py # Re-export shim for services/output.py (backward compat)
├── _version.py                # Single source of truth: __version__ = "4.1.3"
├── config.py                  # YAML → typed dataclasses; validate_config()
├── dummy_data.py              # Realistic dummy data for --dummy / dev previews
├── filters.py                 # Event filtering (calendar, keyword, all-day)
├── data/models.py             # Pure dataclasses: CalendarEvent, WeatherData, AirQualityData,
│                              #   Birthday, HostData, DashboardData, StalenessLevel
├── display/
│   ├── driver.py              # DisplayDriver ABC → DryRunDisplay, WaveshareDisplay; image_changed()
│   └── refresh_tracker.py     # Partial vs full refresh state machine
├── fetchers/
│   ├── calendar.py            # Google Calendar API + ICS feed + incremental sync + birthdays
│   ├── weather.py             # OpenWeatherMap (current + forecast + alerts)
│   ├── purpleair.py           # PurpleAir sensor → PM1 / PM2.5 / PM10 / AQI + ambient readings
│   ├── host.py                # System metrics via /proc: uptime, load, RAM, disk, CPU temp, IP
│   ├── cache.py               # Multi-source JSON cache with per-source TTL
│   ├── circuit_breaker.py     # Per-source circuit breaker
│   └── quota_tracker.py       # Daily API call counter
└── render/
    ├── canvas.py              # Top-level render orchestrator (dispatches to components by theme)
    ├── theme.py               # Theme system (ComponentRegion, ThemeLayout, ThemeStyle); AVAILABLE_THEMES
    ├── random_theme.py        # Daily/hourly random theme selection + persistence
    ├── layout.py              # Default layout constants
    ├── fonts.py               # Font loader (@lru_cache)
    ├── icons.py               # OWM icon code → Weather Icons glyph
    ├── moon.py                # Moon phase calculator
    ├── primitives.py          # Shared draw utilities (truncation, wrapping, colors, fmt_time,
    │                          #   events_for_day, deg_to_compass)
    ├── themes/                # themes: default, terminal, minimalist, old_fashioned, today,
    │                          #   fantasy, moonphase, moonphase_invert, qotd, qotd_invert,
    │                          #   weather, fuzzyclock, fuzzyclock_invert, diags, air_quality
    └── components/            # One file per UI region: header, week_view, weather_panel,
                               #   weather_full, birthday_bar, today_view, info_panel, qotd_panel,
                               #   fuzzyclock_panel, diags_panel, air_quality_panel,
                               #   moonphase_panel

config/
├── config.example.yaml        # Template (copy to config.yaml)
└── quotes.json                # Bundled daily quotes

docs/
├── setup.md                   # Google Calendar, ICS feed, birthdays, Pi hardware setup
├── themes.md                  # All themes, random rotation, schedule, custom themes
├── configuration.md           # Full config.yaml reference
├── development.md             # Makefile, CLI, project structure, dependencies
├── faq.md                     # Frequently asked questions (quiet hours, troubleshooting, etc.)
└── upgrading-from-v3.md       # Migration guide from v3

tests/                         # test files, extensive mocking
fonts/                         # Bundled TTF fonts
deploy/                        # Systemd service + timer + configure.sh + logrotate
output/                        # Generated PNGs + cache files (git-ignored except latest.png)
credentials/                   # Google service account JSON (git-ignored)
requirements.txt               # Core Python dependencies
requirements-pi.txt            # Raspberry Pi-specific deps (gpiozero, lgpio, Waveshare EPD)
```

## Architecture Patterns

### Per-source independence
Fetchers, caching, circuit breaking, and staleness are all per-source (calendar, weather, birthdays, air_quality). A weather API failure doesn't block calendar rendering. PurpleAir is fully optional — when `purpleair.api_key` and `purpleair.sensor_id` are absent, the source is silently skipped.

### Theme system
Three-layer design: **ComponentRegion** (bounding box) → **ThemeLayout** (canvas + regions + draw order) → **ThemeStyle** (colors, fonts, spacing). Components receive region + style and draw only within bounds. Themes are frozen dataclasses.

Two rotation cadences are available: `theme: random_daily` (alias: `random`) picks once per day after midnight and persists to `output/random_theme_state.json`; `theme: random_hourly` picks once per hour and persists to `output/random_theme_hourly_state.json`. Both use the same `random_theme.include` / `random_theme.exclude` lists. The concrete theme name is resolved in `services_theme_service.py` before `load_theme()` is called — `load_theme()` itself never receives a pseudo-theme name.

`theme_schedule` is a higher-priority override: `resolve_theme_name()` checks the schedule entries (sorted by HH:MM) before consulting `cfg.theme` or the random pool. The active entry is the last one whose time ≤ current local time. When no entry matches, control falls through to `cfg.theme` / random as normal. CLI `--theme` always wins over the schedule.

### Data flow
`main.py` (thin): parse args → load config → validate config → `DashboardApp.run()`.

`DashboardApp.run()`: resolve timezone → check quiet hours → check morning startup (auto-force-full-refresh) → load data (dummy or `DataPipeline.fetch()`) → filter events → resolve theme name → load theme → render → `OutputService.publish()` → write `last_success.txt`.

`DataPipeline.fetch()`: check cache freshness per source → check circuit breaker → launch concurrent fetches via `ThreadPoolExecutor` → resolve results (cache fallback on failure) → fetch host data synchronously → return `DashboardData`.

### Rendering
Components are pure functions: `draw_*(draw, data, region, style) -> None`. No global state. Same input produces the same PNG.

## Key Conventions

- **Dataclass-first**: pure data models with no I/O in `src/data/models.py`
- **Config mirrors YAML**: dataclass hierarchy in `config.py` matches YAML structure; all fields optional with defaults
- **Max line length**: 100 characters
- **Testing**: heavy use of `unittest.mock.patch`; fixtures for temp dirs and dummy data; every public render function has dedicated smoke tests plus logic unit tests
- **Thread safety**: cache operations use `threading.Lock()`
- **Graceful degradation**: fetch failure → load cached → use stale data → staleness indicator in header
- **Error boundaries**: credential loading failures, malformed API responses, and cache write errors are caught and logged without crashing the app
- **API timeout**: `ThreadPoolExecutor` in `DataPipeline` enforces a 120-second upper bound per source via `future.result(timeout=120)`

## CLI Flags

```
--dry-run              Save PNG instead of writing to eInk hardware
--dummy                Use built-in dummy data (no API keys needed)
--config PATH          Custom config file path
--date YYYY-MM-DD      Override today's date for dry-run previews (requires --dry-run)
--theme THEME          Override theme from config (choices: all AVAILABLE_THEMES)
--force-full-refresh   Force full eInk refresh and bypass fetch intervals
--ignore-breakers      Ignore OPEN circuit breakers for this run
--check-config         Validate config and exit
--version              Print version and exit (e.g. "main.py 4.1.3")
```

## Adding New Features

**New component**: Create `src/render/components/my_component.py` → implement `draw_my_component(draw, data, region, style)` → add `ComponentRegion` to themes → register in `canvas.py` draw dispatch → add to theme `draw_order`.

**New theme**: Create `src/render/themes/my_theme.py` → implement `my_theme() -> Theme` factory → register in `load_theme()` in `theme.py` → add name to `AVAILABLE_THEMES`. New themes are automatically included in the random rotation pool (both daily and hourly). To exclude a theme from the pool (e.g. utility or diagnostic views), add its name to `_EXCLUDED_FROM_POOL` in `src/render/random_theme.py`.

**New fetcher**: Create `src/fetchers/my_fetcher.py` → use `cache.py` and `circuit_breaker.py` → integrate into `DataPipeline` in `data_pipeline.py` → extend `DashboardData` if needed → add ser/deser branch to `cache.py` `save_source()`/`load_cached_source()`. See `purpleair.py` as a reference implementation.

**New config option**: Add field to relevant dataclass in `config.py` → add to `config.example.yaml` → use in `DashboardApp`, `DataPipeline`, or components.

## Fonts

### Bundled fonts (`fonts/`)

| File | Accessor(s) in `fonts.py` | Used by |
|---|---|---|
| `PlusJakartaSans-*.ttf` | `regular`, `medium`, `semibold`, `bold` | Default font for all themes |
| `weathericons-regular.ttf` | `weather_icon` | Weather condition icons + moon phase glyphs (all themes) |
| `ShareTechMono-Regular.ttf` | `cyber_mono` | `terminal` — event body text; `diags` — all data rows |
| `Maratype.otf` | `maratype` | `terminal` — dashboard title, day column headers, quote body |
| `UESC Display.otf` | `uesc_display` | `terminal` — month band, section labels, quote attribution |
| `Synthetic Genesis.otf` | `synthetic_genesis` | `terminal` — large today date numeral |
| `DMSans.ttf` | `dm_regular/medium/semibold/bold` | `minimalist`, `weather`, `fuzzyclock`, `diags` (section labels) |
| `PlayfairDisplay-*.ttf` | `playfair_regular/medium/semibold/bold` | `old_fashioned`, `qotd`, `moonphase` |
| `Cinzel.ttf` | `cinzel_regular/semibold/bold/black` | `fantasy`, `old_fashioned` section labels, `moonphase` |
| `SpaceGrotesk-Regular.ttf` | `sg_regular` | `air_quality` |
| `SpaceGrotesk-Medium.ttf` | `sg_medium` | `air_quality` |
| `SpaceGrotesk-Bold.ttf` | `sg_bold` | `air_quality` |
| `NuCore.otf` / `NuCore Condensed.otf` | *(unused — available for new themes)* | — |

### `ThemeStyle` font fields

`ThemeStyle` exposes font callables of the form `(size: int) -> FreeTypeFont`. All fields
default to `None` and fall back gracefully so adding a new field never breaks existing themes.

| Field | Fallback | Controls |
|---|---|---|
| `font_regular` | Plus Jakarta Sans Regular | General body text |
| `font_medium` | Plus Jakarta Sans Medium | Mid-weight body text |
| `font_semibold` | Plus Jakarta Sans SemiBold | Emphasis text, event titles |
| `font_bold` | Plus Jakarta Sans Bold | Default for unlisted elements |
| `font_title` | `font_bold` | Dashboard title (header) + day column headers |
| `font_section_label` | `font_bold` (or weight set by `label_font_weight`) | WEATHER / BIRTHDAYS / QUOTE OF THE DAY labels |
| `font_date_number` | `font_bold` | Large today date numeral (bottom-right of week view) |
| `font_month_title` | `font_bold` | Large month name band above the date numeral |
| `font_quote` | `font_regular` | Quote body text in the info panel |
| `font_quote_author` | `font_regular` | Quote attribution line (`— Author`) |

## Gotchas

- Incremental sync tokens persist in `calendar_sync_state.json`; delete to force full resync
- Quiet hours (default 23:00–06:00): app exits immediately during this window (dry-run bypasses this)
- Morning startup: first run within 30 minutes after `quiet_hours_end` automatically forces a full refresh, regardless of `--force-full-refresh`
- eInk partial refreshes degrade quality; full refresh forced after `max_partials_before_full` partials
- Default canvas: 800×480; scaled via LANCZOS to match display resolution
- Image hash comparison (`last_image_hash.txt`) skips eInk writes when content unchanged
- Health marker written to `output/last_success.txt` on every successful run (ISO timestamp)
- Daily random theme state persists in `output/random_theme_state.json`; delete it to force a new pick mid-day
- Hourly random theme state persists in `output/random_theme_hourly_state.json`; delete it to force a new pick mid-hour
- `terminal` theme: the month band font (`font_month_title`) starts at 33px and scales down to fit longer names (e.g. FEBRUARY, SEPTEMBER) within the combined date cell width
- Deploy paths (`PI_USER`, `PI_HOST`, `PI_DIR`) default to `pi`, `dashboard`, `/home/pi/home-dashboard`; override with `make deploy PI_USER=myuser PI_HOST=mypi.local`
- `make install` (remote deploy) uses `__INSTALL_DIR__` and `__USER__` placeholders in `dashboard.service` — these are substituted via `sed` during install, so no manual editing is needed for standard setups
- Service account credentials are cached for the process lifetime; tokens auto-refresh via google-auth (safe for the hourly cron use case)
- Weather forecast parsing skips malformed OWM slots (missing `"main"` key or empty `"weather"` array) rather than crashing
- `fuzzyclock` theme: time phrases snap to the nearest 5-minute bucket; the default systemd timer runs every 5 minutes; the image-hash check prevents eInk refreshes when the phrase hasn't changed
- `fuzzyclock` component uses `style.font_bold` / `style.font_medium` for the phrase / date — font-agnostic so the theme can be re-skinned by swapping the style callables
- `qotd_invert` and `fuzzyclock_invert` are inverted-color variants of their base themes; they are included in the random rotation pool by default
- Theme preview PNGs (`output/theme_*.png`) are git-ignored by `.gitignore` (`output/*.png`) but tracked as exceptions; use `git add -f output/theme_<name>.png` when adding a new one
- PurpleAir data surfaces in two themes: `weather` shows a compact AQI card + PM detail strip alongside weather data; `air_quality` devotes the full canvas to environmental health data (AQI hero + scale bar, PM1/PM2.5/PM10 row, ambient sensor cards, weather strip)
- `_pm25_to_aqi()` in `purpleair.py` implements the EPA AQI piecewise linear formula with standard breakpoints; PM2.5 is truncated (not rounded) to one decimal before lookup, and AQI is applied to the 60-minute PM2.5 average (`pm2.5_60minute`) for a smoother, less noisy reading — the result is stored on `AirQualityData.aqi` at fetch time; `AirQualityData` also carries `pm1` (PM1.0) and `pm10` (PM10) for display in the `weather` theme detail strip
- When `purpleair.api_key` or `purpleair.sensor_id` is `0`/`""`, the source is skipped silently (no circuit breaker entry, no cache miss); validation emits warnings only when one is set without the other
- `AirQualityData` includes optional `temperature` (°F), `humidity` (%), and `pressure` (hPa) fields from PurpleAir ambient readings; these appear in the `diags` panel; old cache entries missing these fields deserialize safely as `None`
- `HostData` is fetched synchronously (after concurrent API fetches complete) using only Python stdlib and `/proc`; fields that are unavailable (e.g. CPU temp on non-Pi) return `None` and are silently omitted in the `diags` panel
- `diags` theme is permanently excluded from the random rotation pool via `_EXCLUDED_FROM_POOL` in `random_theme.py`; use `theme: diags` directly instead. `air_quality` is included in the pool and will appear in normal random rotation.
- `air_quality` theme uses `draw_air_quality_full()` in `air_quality_panel.py`, which receives the full `DashboardData` object (same pattern as `diags_panel`); the component dispatches via the `air_quality_full` region on `ThemeLayout`
- `retry_fetch()` in `data_pipeline.py` retries only likely transient failures and does not retry likely permanent config/data errors (`RuntimeError`, `ValueError`, `TypeError`, `KeyError`)
- `gpiozero` pin factory is set to `lgpio` for Pi hardware runtime (required for modern Pi OS)
- Supported Waveshare display models: `epd7in5` (640×384), `epd7in5_V2` (800×480, default), `epd7in5_V3` (800×480), `epd7in5b_V2` (800×480), `epd7in5_HD` (880×528), `epd9in7` (1200×825), `epd13in3k` (1600×1200). Model is set via `display.model` in config; canvas renders at 800×480 and scales to the target resolution via LANCZOS.
- **ICS feed**: when `google.ical_url` is set, `fetch_events()` dispatches to `_fetch_from_ical()` instead of the Google API path — `service_account_path` is ignored for event fetching; the Google API path (including incremental sync) is completely bypassed
- ICS feeds have no sync token mechanism — the full feed is always re-downloaded and re-parsed on every calendar fetch; at the default 2-hour `events_fetch_interval` this is negligible
- `_fetch_from_ical()` uses `requests.get(..., timeout=30)` and the `icalendar` library; HTTP errors or parse errors are caught, logged as warnings, and return `[]` (graceful degradation)
- ICS calendar name is taken from the `X-WR-CALNAME` property of the VCALENDAR component; falls back to the URL hostname if absent
- ICS tz-aware `DTSTART` datetimes are converted to naive local wall-clock time (same pattern as `_parse_event()` in the Google API path) so rendering code sees identical `CalendarEvent` objects regardless of source
- `validate_config()` skips the service-account-file-missing warning and the `calendar_id == "primary"` warning when `ical_url` is set; emits a `ConfigError` if the URL doesn't start with `http://` or `https://`; emits a `ConfigWarning` if both `ical_url` and a real `service_account.json` are present (informational only — `ical_url` wins)
- `theme_schedule` priority chain: CLI `--theme` > `theme_schedule` entries > `cfg.theme` / random. `_resolve_scheduled_theme()` sorts entries by HH:MM string and returns the last one whose time ≤ current local time; returns `None` when no entry has fired yet (e.g. all entries start after midnight and it's 3 AM), at which point normal `cfg.theme` / `random_daily` / `random_hourly` logic applies. `validate_config()` validates each entry's time format and theme name.
- `WeatherData.location_name` is populated from `current["name"]` in the OWM `/weather` response (always present when the API returns successfully); it is `None` when absent or empty. Old cache entries without this field deserialize safely as `None` via `.get()`.
- Per-panel staleness glyphs: `draw_staleness_glyph()` in `primitives.py` draws a 12×14px inverted `!` badge in the bottom-right corner of a component region. `weather_panel.py` and `birthday_bar.py` accept an optional `staleness: StalenessLevel | None` kwarg and call the helper when staleness is `STALE` or `EXPIRED`; `canvas.py` passes `data.source_staleness.get("weather"/"birthdays")`. `info_panel` has no live data source and therefore no staleness glyph.
- `cache.quote_refresh` controls how often the displayed quote rotates: `daily` (default), `twice_daily`, or `hourly`. Quote selection uses a stable date/time-bucket hash — the same bucket always maps to the same quote (repeats are possible). With 144 bundled quotes: daily ≈ 144-day cycle, twice_daily ≈ 72-day cycle, hourly ≈ 6-day cycle. The hash input is `(title, date, bucket_index)` so the same slot is stable across restarts.
- `moonphase` theme is a full-canvas display using the `moonphase_full` region on `ThemeLayout`; `draw_moonphase()` in `moonphase_panel.py` receives the full `DashboardData` object (same pattern as `diags_panel` and `air_quality_panel`). Moon phase data is purely computational via `moon.py` — no API needed.
- `moon_illumination(d)` in `moon.py` returns 0.0–100.0 using a cosine approximation from the phase age; used by the `moonphase` theme's illumination display.
- `moonphase` and `moonphase_invert` are both included in the random rotation pool by default. `moonphase_invert` shares the same overlay function (`_draw_moonphase_overlay`) from `moonphase.py` — it adapts to fg/bg colors automatically.
- `moonphase_panel.py` has its own `_quote_for_panel()` function with a `"moonphase-"` key prefix so its quote selection is independent from `info_panel`'s quote (they won't show the same quote on the same day).
