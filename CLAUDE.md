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
make version        # Print current version (e.g. main.py 4.1.0)
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
- **requests** — OpenWeatherMap API
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
├── services_run_policy.py     # resolve_tz, should_skip_refresh, should_force_full_refresh
├── services_theme_service.py  # resolve_theme_name (random → concrete), resolve_theme
├── services_output_service.py # OutputService — publish image to display or PNG; write last_success.txt
├── _version.py                # Single source of truth: __version__ = "4.1.0"
├── config.py                  # YAML → typed dataclasses; validate_config()
├── dummy_data.py              # Realistic dummy data for --dummy / dev previews
├── filters.py                 # Event filtering (calendar, keyword, all-day)
├── data/models.py             # Pure dataclasses: CalendarEvent, WeatherData, AirQualityData,
│                              #   Birthday, HostData, DashboardData, StalenessLevel
├── display/
│   ├── driver.py              # DisplayDriver ABC → DryRunDisplay, WaveshareDisplay; image_changed()
│   └── refresh_tracker.py     # Partial vs full refresh state machine
├── fetchers/
│   ├── calendar.py            # Google Calendar API + incremental sync + birthdays
│   ├── weather.py             # OpenWeatherMap (current + forecast + alerts)
│   ├── purpleair.py           # PurpleAir sensor → PM1 / PM2.5 / PM10 / AQI + ambient readings
│   ├── host.py                # System metrics via /proc: uptime, load, RAM, disk, CPU temp, IP
│   ├── cache.py               # Multi-source JSON cache with per-source TTL
│   ├── circuit_breaker.py     # Per-source circuit breaker
│   └── quota_tracker.py       # Daily API call counter
└── render/
    ├── canvas.py              # Top-level render orchestrator (dispatches to components by theme)
    ├── theme.py               # Theme system (ComponentRegion, ThemeLayout, ThemeStyle); AVAILABLE_THEMES
    ├── random_theme.py        # Daily random theme selection + persistence (output/random_theme_state.json)
    ├── layout.py              # Default layout constants
    ├── fonts.py               # Font loader (@lru_cache)
    ├── icons.py               # OWM icon code → Weather Icons glyph
    ├── moon.py                # Moon phase calculator
    ├── primitives.py          # Shared draw utilities (truncation, wrapping, colors, fmt_time,
    │                          #   events_for_day, deg_to_compass)
    ├── themes/                # themes: default, terminal, minimalist, old_fashioned, today,
    │                          #   fantasy, qotd, qotd_invert, weather, fuzzyclock, fuzzyclock_invert,
    │                          #   diags
    └── components/            # One file per UI region: header, week_view, weather_panel,
                               #   weather_full, birthday_bar, today_view, info_panel, qotd_panel,
                               #   fuzzyclock_panel, diags_panel

config/
├── config.example.yaml        # Template (copy to config.yaml)
└── quotes.json                # Bundled daily quotes

tests/                         # test files, extensive mocking
fonts/                         # Bundled TTF fonts
deploy/                        # Systemd service + timer + configure.sh
output/                        # Generated PNGs + cache files (git-ignored except latest.png)
credentials/                   # Google service account JSON (git-ignored)
```

## Architecture Patterns

### Per-source independence
Fetchers, caching, circuit breaking, and staleness are all per-source (calendar, weather, birthdays, air_quality). A weather API failure doesn't block calendar rendering. PurpleAir is fully optional — when `purpleair.api_key` and `purpleair.sensor_id` are absent, the source is silently skipped.

### Theme system
Three-layer design: **ComponentRegion** (bounding box) → **ThemeLayout** (canvas + regions + draw order) → **ThemeStyle** (colors, fonts, spacing). Components receive region + style and draw only within bounds. Themes are frozen dataclasses.

Setting `theme: random` activates daily rotation: `random_theme.py` picks one theme from the eligible pool on the first run after midnight, persists it to `output/random_theme_state.json`, and reuses it for the rest of the day. The concrete theme name is resolved in `services_theme_service.py` before `load_theme()` is called — `load_theme()` itself never receives `"random"`.

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
--version              Print version and exit (e.g. "main.py 4.1.0")
```

## Adding New Features

**New component**: Create `src/render/components/my_component.py` → implement `draw_my_component(draw, data, region, style)` → add `ComponentRegion` to themes → register in `canvas.py` draw dispatch → add to theme `draw_order`.

**New theme**: Create `src/render/themes/my_theme.py` → implement `my_theme() -> Theme` factory → register in `load_theme()` in `theme.py` → add name to `AVAILABLE_THEMES`. New themes are automatically included in the `random` rotation pool. To exclude a theme from the pool (e.g. utility or diagnostic views), add its name to `_EXCLUDED_FROM_POOL` in `src/render/random_theme.py`.

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
| `PlayfairDisplay-*.ttf` | `playfair_regular/medium/semibold/bold` | `old_fashioned`, `qotd` |
| `Cinzel.ttf` | `cinzel_regular/semibold/bold/black` | `fantasy`, `old_fashioned` section labels |
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
- Random theme state persists in `output/random_theme_state.json`; delete it to force a new theme pick mid-day
- `terminal` theme: the month band font (`font_month_title`) starts at 33px and scales down to fit longer names (e.g. FEBRUARY, SEPTEMBER) within the combined date cell width
- Deploy paths (`PI_USER`, `PI_HOST`, `PI_DIR`) default to `pi`, `dashboard`, `/home/pi/home-dashboard`; override with `make deploy PI_USER=myuser PI_HOST=mypi.local`
- `make install` (remote deploy) uses `__INSTALL_DIR__` and `__USER__` placeholders in `dashboard.service` — these are substituted via `sed` during install, so no manual editing is needed for standard setups
- Service account credentials are cached for the process lifetime; tokens auto-refresh via google-auth (safe for the hourly cron use case)
- Weather forecast parsing skips malformed OWM slots (missing `"main"` key or empty `"weather"` array) rather than crashing
- `fuzzyclock` theme: time phrases snap to the nearest 5-minute bucket; the default systemd timer runs every 5 minutes; the image-hash check prevents eInk refreshes when the phrase hasn't changed
- `fuzzyclock` component uses `style.font_bold` / `style.font_medium` for the phrase / date — font-agnostic so the theme can be re-skinned by swapping the style callables
- `qotd_invert` and `fuzzyclock_invert` are inverted-color variants of their base themes; they are included in the random rotation pool by default
- Theme preview PNGs (`output/theme_*.png`) are git-ignored by `.gitignore` (`output/*.png`) but tracked as exceptions; use `git add -f output/theme_<name>.png` when adding a new one
- PurpleAir AQI card only appears in the `weather` theme; other themes have access to `DashboardData.air_quality` for future use
- `_pm25_to_aqi()` in `purpleair.py` implements the EPA AQI piecewise linear formula with standard breakpoints; PM2.5 is truncated (not rounded) to one decimal before lookup, and AQI is applied to the 60-minute PM2.5 average (`pm2.5_60minute`) for a smoother, less noisy reading — the result is stored on `AirQualityData.aqi` at fetch time; `AirQualityData` also carries `pm1` (PM1.0) and `pm10` (PM10) for display in the `weather` theme detail strip
- When `purpleair.api_key` or `purpleair.sensor_id` is `0`/`""`, the source is skipped silently (no circuit breaker entry, no cache miss); validation emits warnings only when one is set without the other
- `AirQualityData` includes optional `temperature` (°F), `humidity` (%), and `pressure` (hPa) fields from PurpleAir ambient readings; these appear in the `diags` panel; old cache entries missing these fields deserialize safely as `None`
- `HostData` is fetched synchronously (after concurrent API fetches complete) using only Python stdlib and `/proc`; fields that are unavailable (e.g. CPU temp on non-Pi) return `None` and are silently omitted in the `diags` panel
- `diags` theme is a utility/diagnostic view and is permanently excluded from the `random` rotation pool via `_EXCLUDED_FROM_POOL` in `random_theme.py`; it cannot be added via `random_theme.include` — use `theme: diags` directly instead
- `retry_fetch()` in `data_pipeline.py` retries only likely transient failures and does not retry likely permanent config/data errors (`RuntimeError`, `ValueError`, `TypeError`, `KeyError`)
- `gpiozero` pin factory is set to `lgpio` for Pi hardware runtime (required for modern Pi OS)
