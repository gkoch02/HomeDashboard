# CLAUDE.md — Dashboard-v4

## Project Overview

Python eInk dashboard for Raspberry Pi. Displays a weekly calendar (Google Calendar), weather (OpenWeatherMap), upcoming birthdays, and a daily quote. Renders to a supported eInk display (Waveshare or Pimoroni Inky Impression) or PNG preview. Includes an optional Flask web UI for status monitoring and config editing.

## Quick Commands

```bash
make setup          # Create venv, install deps, copy config template
make test           # Run pytest
make coverage       # Run pytest with coverage report (term-missing + HTML in htmlcov/)
make dry            # Preview with dummy data → output/latest.png
make previews       # Generate all theme preview PNGs → output/theme_*.png
make check          # Validate config/config.yaml
make version        # Print current version (e.g. main.py 4.3.1)
make deploy         # Rsync to Pi (configurable: PI_USER, PI_HOST, PI_DIR)
make install        # Install systemd timer on remote Pi (via ssh/scp)
make pi-install     # Full Pi setup: apt deps, venv, Inky + Waveshare drivers (run ON Pi)
make install-display-drivers  # Reinstall/verify hardware driver libraries in the venv
make pi-enable      # Install systemd units and enable timer (run ON Pi)
make pi-status      # Show timer status and recent logs (run ON Pi)
make pi-logs        # Tail output/dashboard.log (run ON Pi)
make configure      # Run deploy/configure.sh interactive setup
make web-enable     # Install and start web UI systemd service (run ON Pi)
make web-status     # Web service status + recent log tail (run ON Pi)
make web-logs       # Tail output/dashboard-web.log (run ON Pi)
ruff check src/ tests/                         # Lint
ruff format src/ tests/                        # Format
```

## Tech Stack

- **Python 3.9+** — no async
- **Pillow** — image rendering (PIL)
- **google-api-python-client / google-auth** — Google Calendar & Contacts APIs
- **requests** — OpenWeatherMap API + ICS feed fetching
- **icalendar** — ICS feed parsing (used when `google.ical_url` is configured)
- **PyYAML** — config parsing
- **Flask 3 + Waitress** — optional web UI (`requirements-web.txt`; `pip install -e ".[web]"`)
- **pytest** — testing (with unittest.mock); coverage via **pytest-cov** (target: ≥90%, currently ~99%)
- **ruff** — linting and formatting (max line length: 100)

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
│   └── output.py              # OutputService — publish image to display or PNG; write last_success.txt;
│                              #   Inky hourly throttle for non-fuzzyclock themes
├── _version.py                # Single source of truth: __version__ = "4.3.1"
├── config.py                  # YAML → typed dataclasses; validate_config()
├── dummy_data.py              # Realistic dummy data for --dummy / dev previews
├── filters.py                 # Event filtering (calendar, keyword, all-day)
├── data/models.py             # Pure dataclasses: CalendarEvent, WeatherData, AirQualityData,
│                              #   Birthday, HostData, DashboardData, StalenessLevel
├── display/
│   ├── driver.py              # DisplayDriver ABC → DryRunDisplay, WaveshareDisplay, InkyDisplay;
│   │                          #   provider/model specs + image_changed()
│   └── refresh_tracker.py     # Partial vs full refresh state machine
├── fetchers/
│   ├── calendar.py            # Dispatcher: routes to Google API or ICS; birthday extraction
│   ├── calendar_google.py     # Google Calendar API — full sync, incremental sync, sync state
│   ├── calendar_ical.py       # ICS feed fetching and parsing
│   ├── weather.py             # OpenWeatherMap (current + forecast + alerts)
│   ├── purpleair.py           # PurpleAir sensor → PM1 / PM2.5 / PM10 / AQI + ambient readings
│   ├── host.py                # System metrics via /proc: uptime, load, RAM, disk, CPU temp, IP
│   ├── cache.py               # Multi-source JSON cache with per-source TTL
│   ├── circuit_breaker.py     # Per-source circuit breaker
│   └── quota_tracker.py       # Daily API call counter
└── render/
    ├── canvas.py              # Top-level render orchestrator (dispatches to components by theme)
    ├── theme.py               # Theme system (ComponentRegion, ThemeLayout, ThemeStyle); AVAILABLE_THEMES
    ├── quantize.py            # quantize_for_display() for Waveshare 1-bit output +
    │                          #   quantize_to_palette() for Inky palette mapping
    ├── random_theme.py        # Daily/hourly random theme selection + persistence
    ├── layout.py              # Default layout constants
    ├── fonts.py               # Font loader (@lru_cache)
    ├── icons.py               # OWM icon code → Weather Icons glyph
    ├── moon.py                # Moon phase calculator
    ├── primitives.py          # Shared draw utilities (truncation, wrapping, colors, fmt_time,
    │                          #   events_for_day, deg_to_compass)
    ├── themes/                # themes (23): standard week-view (default, terminal,
    │                          #   minimalist, old_fashioned, today, fantasy); full-screen
    │                          #   focused (qotd, qotd_invert, fuzzyclock, fuzzyclock_invert,
    │                          #   weather, moonphase, moonphase_invert); specialized views
    │                          #   (timeline, year_pulse, monthly, sunrise, air_quality,
    │                          #   scorecard, tides); photo overlay (photo); utility (message, diags)
    └── components/            # One file per UI region: header, week_view, weather_panel,
                               #   weather_full, birthday_bar, today_view, info_panel, qotd_panel,
                               #   fuzzyclock_panel, diags_panel, air_quality_panel,
                               #   moonphase_panel, message_panel, timeline_panel,
                               #   year_pulse_panel, monthly_panel, sunrise_panel,
                               #   scorecard_panel, tides_panel
└── web/                       # Optional Flask web UI (install: pip install -r requirements-web.txt)
    ├── __main__.py            # Entry point: python -m src.web [--config web.yaml] [--port 8080]
    ├── app.py                 # Flask application factory (create_app); registers all blueprints
    ├── auth.py                # HTTP Basic Auth middleware; scrypt password hashing
    ├── csrf.py                # CSRF protection: session-bound token via X-CSRF-Token header
    ├── event_store.py         # Append-only JSONL event stream (state/web_events.jsonl) for status history
    ├── state_reader.py        # Pure read functions: last_success, breakers, cache ages, quota, host
    ├── config_editor.py       # Safe config read/write: EDITABLE_FIELD_PATHS allowlist, apply_patch()
    ├── routes/
    │   ├── status.py          # GET / (HTML), GET /api/status (JSON)
    │   ├── image.py           # GET /image/latest, GET /image/theme/<name>
    │   ├── logs.py            # GET /api/logs?lines=N
    │   ├── config.py          # GET/POST /api/config, GET /config (HTML editor)
    │   └── actions.py         # POST /api/trigger-refresh, /api/reset-breaker, /api/clear-cache
    ├── templates/             # Jinja2 templates: base.html, status.html, config.html
    └── static/                # dashboard.js, style.css

config/
├── config.example.yaml        # Template (copy to config.yaml)
├── web.example.yaml           # Web UI config template (copy to web.yaml)
└── quotes.json                # Bundled daily quotes

docs/
├── setup.md                   # Google Calendar, ICS feed, birthdays, Pi hardware setup
├── web-ui.md                  # Web UI setup, auth, pages, manual refresh, security
├── themes.md                  # All themes, random rotation, schedule, custom themes
├── color-themes.md            # Visual gallery of dry-run theme previews (Waveshare 1-bit)
├── color-theme-previews.md    # Inky Spectra 6 color theme preview gallery
├── configuration.md           # Full config.yaml reference
├── development.md             # Makefile, CLI, project structure, dependencies
├── faq.md                     # Frequently asked questions (quiet hours, troubleshooting, etc.)
├── architecture.md            # Architecture overview and design decisions
└── upgrading-from-v3.md       # Migration guide from v3

tests/                         # test files, extensive mocking
fonts/                         # Bundled TTF fonts
deploy/                        # Systemd service + timer + configure.sh + logrotate
state/                         # Runtime state: cache, breaker, quota, sync tokens (git-ignored)
output/                        # Generated PNGs + logs + health marker (git-ignored except latest.png)
credentials/                   # Google service account JSON (git-ignored)
pyproject.toml                 # Project metadata, dependencies, tool config (ruff, pytest, mypy)
requirements.txt               # Core Python dependencies (kept for Pi deployment compat)
requirements-pi.txt            # Raspberry Pi-specific deps (gpiozero, lgpio, inky; Waveshare lib installed by Makefile)
```

## Architecture Patterns

### Per-source independence
Fetchers, caching, circuit breaking, and staleness are all per-source (calendar, weather, birthdays, air_quality). A weather API failure doesn't block calendar rendering. PurpleAir is fully optional — when `purpleair.api_key` and `purpleair.sensor_id` are absent, the source is silently skipped.

### Theme system
Three-layer design: **ComponentRegion** (bounding box) → **ThemeLayout** (canvas + regions + draw order + `canvas_mode`) → **ThemeStyle** (colors, fonts, spacing). Components receive region + style and draw only within bounds. Themes are frozen dataclasses.

`ThemeLayout.canvas_mode` is `"1"` (1-bit, default — all 23 built-in themes) or `"L"` (8-bit greyscale, opt-in for new themes). L-mode themes must use `fg=0, bg=255` in `ThemeStyle` (`bg=1` is near-black in L mode, not white). For Waveshare, the final L→`"1"` conversion is handled by `quantize_for_display()` in `render/quantize.py` and is controlled by `display.quantization_mode` (`threshold` / `floyd_steinberg` / `ordered`). For Inky, the final image is mapped to the limited Spectra 6 palette instead of being quantized to 1-bit.

Two rotation cadences are available: `theme: random_daily` (alias: `random`) picks once per day after midnight and persists to `state/random_theme_state.json`; `theme: random_hourly` picks once per hour and persists to `state/random_theme_hourly_state.json`. Both use the same `random_theme.include` / `random_theme.exclude` lists. The concrete theme name is resolved in `services/theme.py` before `load_theme()` is called — `load_theme()` itself never receives a pseudo-theme name.

`theme_schedule` is a higher-priority override: `resolve_theme_name()` checks the schedule entries (sorted by HH:MM) before consulting `cfg.theme` or the random pool. The active entry is the last one whose time ≤ current local time. When no entry matches, control falls through to `cfg.theme` / random as normal. CLI `--theme` always wins over the schedule.

### Data flow
`main.py` (thin): parse args → load config → validate config → `DashboardApp.run()`.

`DashboardApp.run()`: resolve timezone → check quiet hours → check morning startup (auto-force-full-refresh) → load data (dummy or `DataPipeline.fetch()`) → filter events → resolve theme name → load theme → render → `OutputService.publish(now=..., theme_name=...)` → write `last_success.txt`.

`DataPipeline.fetch()`: check cache freshness per source → check circuit breaker → launch concurrent fetches via `ThreadPoolExecutor` → resolve results (cache fallback on failure) → fetch host data synchronously → return `DashboardData`.

### Rendering
Components are pure functions: `draw_*(draw, data, region, style) -> None`. No global state. Same input produces the same PNG.

`render_dashboard()` creates the canvas in a mode derived from theme + display provider. After drawing and any optional overlay, a resize via LANCZOS is applied if display dimensions differ from canvas dimensions. Waveshare output is quantized to final 1-bit output via `quantize_for_display()`. Inky output is mapped to the limited Spectra 6 RGB palette via `quantize_to_palette()`. The SHA-256 image hash used for refresh suppression is computed on the final backend-ready image bytes.

## Key Conventions

- **Dataclass-first**: pure data models with no I/O in `src/data/models.py`
- **Config mirrors YAML**: dataclass hierarchy in `config.py` matches YAML structure; all fields optional with defaults
- **Max line length**: 100 characters
- **Testing**: heavy use of `unittest.mock.patch`; fixtures for temp dirs and dummy data; every public render function has dedicated smoke tests plus logic unit tests. Coverage gate is `fail_under = 90` in `pyproject.toml` (`[tool.coverage.report]`). Run `make coverage` to print missing lines and write an HTML report to `htmlcov/`. `src/_version.py` and `src/main.py` are omitted from coverage
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
--message TEXT         Text to display when using the message theme
--force-full-refresh   Force full eInk refresh and bypass fetch intervals
--ignore-breakers      Ignore OPEN circuit breakers for this run
--check-config         Validate config and exit
--version              Print version and exit (e.g. "main.py 4.3.1")
```

## Adding New Features

**New component**: Create `src/render/components/my_component.py` → implement `draw_my_component(draw, data, region, style)` → add `ComponentRegion` to themes → register in `canvas.py` draw dispatch → add to theme `draw_order`.

**New theme**: Create `src/render/themes/my_theme.py` → implement `my_theme() -> Theme` factory → register in `load_theme()` in `theme.py` → add name to `AVAILABLE_THEMES`. New themes are automatically included in the random rotation pool (both daily and hourly). To exclude a theme from the pool (e.g. utility or diagnostic views), add its name to `_EXCLUDED_FROM_POOL` in `src/render/random_theme.py`. To author a greyscale theme, set `canvas_mode="L"` in `ThemeLayout` and use `fg=0, bg=255` in `ThemeStyle` — the quantize step handles the final L→`"1"` conversion automatically.

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
| `SpaceGrotesk-Regular.ttf` | `sg_regular` | `air_quality`, `message` |
| `SpaceGrotesk-Medium.ttf` | `sg_medium` | `air_quality`, `message` |
| `SpaceGrotesk-Bold.ttf` | `sg_bold` | `air_quality`, `message` |
| `NuCore.otf` / `NuCore Condensed.otf` | *(unused — available for new themes)* | — |

### `ThemeLayout` rendering fields

| Field | Default | Effect |
|---|---|---|
| `canvas_mode` | `"1"` | PIL image mode for the internal canvas. `"1"` = 1-bit bilevel (all built-in themes). `"L"` = 8-bit greyscale (opt-in for new themes). L-mode themes must use `fg=0, bg=255` in `ThemeStyle`. |
| `background_fn` | `None` | Optional callable `(Image, ThemeLayout, ThemeStyle) -> None` executed BEFORE component rendering. Receives the raw PIL Image so it can paste photo/grayscale content beneath UI elements. Used by the `photo` theme to dither and paste a user photo onto the canvas. |
| `prefer_color_on_inky` | `False` | When `True` AND `canvas_mode="L"` AND `display.provider: inky`, the canvas is rendered in RGB so the component can draw tuple-`fg`/`bg` colors directly (used by the `monthly` theme's heatmap palette). Ignored on Waveshare and on `"1"`-mode themes. |

### `ThemeStyle` fields

#### Boolean / scalar flags

| Field | Default | Effect |
|---|---|---|
| `fg` / `bg` | `0` / `1` | Base foreground/background values. For `canvas_mode="L"` themes use `fg=0, bg=255` instead. Inky remaps these to palette entries internally. |
| `accent_info` / `accent_warn` / `accent_alert` / `accent_good` | `None` | Optional semantic accent roles. Waveshare falls back to monochrome-safe values; Inky maps these to palette colors for low-risk status emphasis. |
| `accent_primary` / `accent_secondary` | `None` | General-purpose accent fills. Waveshare falls back to `fg`; Inky maps to per-theme key color pair from `_INKY_THEME_KEY_COLORS` in `canvas.py`. Accessed via `style.primary_accent_fill()` / `style.secondary_accent_fill()` methods. |
| `photo_path` | `""` | Absolute or relative path to a JPEG/PNG image for the `photo` theme. Set by `app.py` from `cfg.photo.path` at runtime. Ignored by all other themes. |
| `invert_header` | `True` | Fill header bar with `fg`, draw text in `bg` |
| `invert_today_col` | `True` | Fill today column with `fg`, draw text in `bg` |
| `invert_allday_bars` | `True` | Filled (vs outlined) all-day event bars |
| `show_borders` | `True` | Draw structural border lines and section separators; set `False` for borderless themes like `minimalist` |
| `show_forecast_strip` | `True` | Draw the 3-day forecast grid at the bottom of the weather panel; set `False` for compact strips where the panel is too short to accommodate it without overlap — the four current-conditions rows are then spread evenly across the full panel height |
| `spacing_scale` | `1.0` | Event row height multiplier in the week view |
| `label_font_size` | `12` | Point size for section labels (WEATHER, BIRTHDAYS, …) |
| `label_font_weight` | `"bold"` | Weight for section labels when `font_section_label` is `None`: `"bold"` / `"semibold"` / `"regular"` |
| `component_labels` | `{}` | Override section label strings per component (keys: `"weather"`, `"birthdays"`, `"info"`, `"year_pulse"`, …) |

#### Font callables

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

- Incremental sync tokens persist in `state/calendar_sync_state.json`; delete to force full resync
- Quiet hours (default 23:00–06:00): app exits immediately during this window (dry-run bypasses this)
- Morning startup: first run within 30 minutes after `quiet_hours_end` automatically forces a full refresh, regardless of `--force-full-refresh`
- eInk partial refreshes degrade quality; full refresh forced after `max_partials_before_full` partials
- Inky Impression panels do not support partial refresh. For `display.provider: inky`, non-fuzzyclock themes are limited to one hardware refresh per hour; `fuzzyclock` and `fuzzyclock_invert` bypass that limit; `--force-full-refresh` also bypasses it
- Default canvas: 800×480; scaled via LANCZOS to match display resolution
- LANCZOS resize produces greyscale pixels; those are quantized to 1-bit by `quantize_for_display()`. The default `threshold` mode differs from the previous hard `.convert("1")` which used Floyd-Steinberg by Pillow default — set `display.quantization_mode: "floyd_steinberg"` to restore the old resize behavior if needed
- `canvas_mode = "L"` themes must use `bg=255` (not `bg=1`) in `ThemeStyle`; `bg=1` is near-black in L mode. All 23 built-in themes use `canvas_mode="1"` (default) and are unaffected
- Image hash comparison (`last_image_hash.txt`) skips eInk writes when content unchanged
- Inky throttle state persists in `state/inky_refresh_state.json`
- Health marker written to `output/last_success.txt` on every successful run (ISO timestamp)
- Daily random theme state persists in `state/random_theme_state.json`; delete it to force a new pick mid-day
- Hourly random theme state persists in `state/random_theme_hourly_state.json`; delete it to force a new pick mid-hour
- State files auto-migrate from `output/` to `state/` on first run after upgrade
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
- `AirQualityData` includes optional `temperature` (°F), `humidity` (%), and `pressure` (hPa) fields sourced from PurpleAir ambient readings when available, with OWM acting as a per-field fallback for any value the sensor does not report; which fields came from OWM is tracked in `AirQualityData.fallback_fields` (a `set[str]`); the `air_quality` theme suppresses the temperature card when it came from the OWM fallback; the `diags` panel suppresses all three ambient fields when they came from the OWM fallback; old cache entries missing these fields deserialize safely as `None`
- `HostData` is fetched synchronously (after concurrent API fetches complete) using only Python stdlib and `/proc`; fields that are unavailable (e.g. CPU temp on non-Pi) return `None` and are silently omitted in the `diags` panel
- `diags` and `message` themes are permanently excluded from the random rotation pool via `_EXCLUDED_FROM_POOL` in `random_theme.py`; use `theme: diags` or `theme: message` directly instead. `air_quality` is included in the pool and will appear in normal random rotation.
- `air_quality` theme uses `draw_air_quality_full()` in `air_quality_panel.py`, which receives the full `DashboardData` object (same pattern as `diags_panel`); the component dispatches via the `air_quality_full` region on `ThemeLayout`
- `retry_fetch()` in `data_pipeline.py` retries only likely transient failures and does not retry likely permanent config/data errors (`RuntimeError`, `ValueError`, `TypeError`, `KeyError`)
- `gpiozero` pin factory is set to `lgpio` for Pi hardware runtime (required for modern Pi OS)
- Supported display providers/models: `waveshare` → `epd7in5` (640×384), `epd7in5_V2` (800×480, default), `epd7in5_V3` (800×480), `epd7in5b_V2` (800×480), `epd7in5_HD` (880×528), `epd9in7` (1200×825), `epd13in3k` (1600×1200); `inky` → `impression_7_3_2025` (800×480). Set via `display.provider` + `display.model`; canvas renders at 800×480 and scales when needed.
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
- Web UI config is in `config/web.yaml` (separate from `config/config.yaml`); it is git-ignored and contains the password hash — never commit it
- `EDITABLE_FIELD_PATHS` in `config_editor.py` is the sole allowlist for web-editable config keys; sensitive fields (API keys, credential paths) are never sent to the browser — they appear only as `_*_set: bool` flags in API responses
- `apply_patch()` in `config_editor.py` validates the patched YAML through `load_config()` + `validate_config()` in a temp file before writing; `validate_config()` does a lazy import of `src.display.driver.WAVESHARE_MODELS` (which imports PIL) — tests that call `apply_patch` must patch `src.web.config_editor.validate_config` to avoid the PIL dependency
- Manual refresh uses a trigger-file approach: the web UI touches `state/web_trigger`; the `dashboard-trigger.path` systemd unit watches for this file and starts `dashboard.service`; the service deletes the file via `ExecStartPost`; no sudo required
- `dashboard-web.service` and `dashboard-trigger.path` are installed by `make web-enable` using the same `__USER__`/`__INSTALL_DIR__` substitution as `dashboard.service`
- The web server is a long-running process (`Type=simple`, `Restart=on-failure`); the dashboard renderer remains a short-lived timer job — they are completely separate processes sharing only the filesystem
- `photo` theme displays a dithered user photo as the full-canvas background with a 50 px inverted header bar at the bottom. Configured via `photo.path` in config.yaml (maps to `PhotoConfig`). The photo is loaded, converted to grayscale, resized to canvas dimensions with LANCZOS, and dithered to 1-bit via Floyd-Steinberg. For dark-canvas variants (`bg=0`) grayscale values are inverted so bright areas stay white. `photo` is excluded from the random rotation pool via `_EXCLUDED_FROM_POOL`. The `background_fn` hook on `ThemeLayout` executes before component rendering to paste the dithered image.
- `load_and_dither_image()` in `primitives.py` is a shared utility for loading, resizing, and dithering images to 1-bit; currently used only by the `photo` theme's background function
- `additional_ical_urls` in `GoogleConfig` allows fetching events from multiple ICS feeds. When `ical_url` is set, both it and all `additional_ical_urls` are fetched and merged by `fetch_from_ical()` in `calendar_ical.py`
- `contacts_email` in `GoogleConfig` is required when `birthdays.source` is `"contacts"` — the service account must have domain-wide delegation, and this field specifies whose contacts to read via the People API
- Inky Spectra 6 color mapping: `_INKY_THEME_KEY_COLORS` in `canvas.py` assigns a `(primary, secondary)` palette index pair to each theme. When `display.provider: inky`, `_resolve_style()` remaps `fg`/`bg` to Inky palette indices and fills unset accent roles (`accent_info` → blue, `accent_warn` → yellow, `accent_alert` → red, `accent_good` → green, `accent_primary`/`accent_secondary` → per-theme key colors). Palette indices: 0=black, 1=white, 2=red, 3=blue, 4=yellow, 5=green
- `accent_primary` and `accent_secondary` on `ThemeStyle` are general-purpose accent fills; `primary_accent_fill()` and `secondary_accent_fill()` methods return `fg` when the accent is `None` (monochrome fallback). Components should call these methods rather than reading the fields directly
- `monthly` theme uses the `monthly` region on `ThemeLayout` and dispatches via `draw_monthly()` in `monthly_panel.py`. The grid is Sunday-first and always renders a six-row layout (cells outside the current month are blanked). On Inky it opts into the RGB canvas path via `prefer_color_on_inky=True` and uses a 5-step heatmap palette (`(255,249,235)` → `(175,28,28)`); on Waveshare the same density is shown via a 1-bit outlined meter (`_draw_monochrome_density_indicator`). `monthly` is included in the random rotation pool. Typography: DM Sans family (`dm_bold`/`dm_semibold`/`dm_medium`/`dm_regular`)
