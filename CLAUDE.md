# CLAUDE.md — Dashboard-v4

## Project Overview

Python eInk dashboard for Raspberry Pi. Displays a weekly calendar (Google Calendar), weather (OpenWeatherMap), upcoming birthdays, and a daily quote. Renders to a Waveshare eInk display or PNG preview. No web framework — pure CLI application.

## Quick Commands

```bash
make setup          # Create venv, install deps, copy config template
make test           # Run pytest (850+ tests across 34 files)
make dry            # Preview with dummy data → output/latest.png
make check          # Validate config/config.yaml
make version        # Print current version (e.g. main.py 3.0.0)
make deploy         # Rsync to Pi (configurable: PI_USER, PI_HOST, PI_DIR)
make install        # Install systemd timer on Pi
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
├── main.py                    # CLI entry point + orchestration
├── _version.py                # Single source of truth: __version__ = "4.1.0"
├── config.py                  # YAML → typed dataclasses
├── dummy_data.py              # Realistic dummy data for --dummy / dev previews
├── filters.py                 # Event filtering (calendar, keyword, all-day)
├── data/models.py             # Pure dataclasses (CalendarEvent, WeatherData, AirQualityData, Birthday, DashboardData)
├── display/
│   ├── driver.py              # DisplayDriver ABC → DryRunDisplay, WaveshareDisplay
│   └── refresh_tracker.py     # Partial vs full refresh state machine
├── fetchers/
│   ├── calendar.py            # Google Calendar API + incremental sync + birthdays
│   ├── weather.py             # OpenWeatherMap (current + forecast + alerts)
│   ├── purpleair.py           # PurpleAir sensor → PM1 / PM2.5 / PM10 / EPA AQI
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
    ├── primitives.py          # Shared draw utilities (truncation, wrapping, colors, fmt_time, events_for_day, deg_to_compass)
    ├── themes/                # 9 themes: default, terminal, minimalist, old_fashioned, today, fantasy, qotd, weather, fuzzyclock
    └── components/            # One file per UI region (header, week_view, weather_panel, weather_full, birthday_bar, today_view, info_panel, qotd_panel, fuzzyclock_panel)

config/
├── config.example.yaml        # Template (copy to config.yaml)
└── quotes.json                # Bundled daily quotes

tests/                         # 34 test files, extensive mocking
fonts/                         # Bundled TTF fonts
deploy/                        # Systemd service + timer
output/                        # Generated PNGs + cache files (git-ignored except latest.png)
credentials/                   # Google service account JSON (git-ignored)
```

## Architecture Patterns

### Per-source independence
Fetchers, caching, circuit breaking, and staleness are all per-source (calendar, weather, birthdays, air_quality). A weather API failure doesn't block calendar rendering. PurpleAir is fully optional — when `purpleair.api_key` and `purpleair.sensor_id` are absent, the source is silently skipped.

### Theme system
Three-layer design: **ComponentRegion** (bounding box) → **ThemeLayout** (canvas + regions + draw order) → **ThemeStyle** (colors, fonts, spacing). Components receive region + style and draw only within bounds. Themes are frozen dataclasses.

Setting `theme: random` activates daily rotation: `random_theme.py` picks one theme from the eligible pool on the first run after midnight, persists it to `output/random_theme_state.json`, and reuses it for the rest of the day. The concrete theme name is resolved in `main.py` before `load_theme()` is called — `load_theme()` itself never receives `"random"`.

### Data flow
`main.py`: parse args → load config → check quiet hours → fetch data (with cache/circuit breaker) → filter events → resolve theme (random → concrete name) → load theme → render → compare hash → write display → save cache.

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
- **API timeout**: Google API calls have no per-request timeout; the `ThreadPoolExecutor` in `main.py` enforces a 120-second upper bound per source

## CLI Flags

```
--dry-run              Save PNG instead of writing to eInk hardware
--dummy                Use built-in dummy data (no API keys needed)
--config PATH          Custom config file path
--date YYYY-MM-DD      Override today's date for dry-run previews (requires --dry-run)
--force-full-refresh   Bypass fetch intervals and circuit breaker
--check-config         Validate config and exit
--version              Print version and exit (e.g. "main.py 4.1.0")
```

## Adding New Features

**New component**: Create `src/render/components/my_component.py` → implement `draw_my_component(draw, data, region, style)` → add `ComponentRegion` to themes → register in `canvas.py` draw dispatch → add to theme `draw_order`.

**New theme**: Create `src/render/themes/my_theme.py` → implement `my_theme() -> Theme` factory → register in `load_theme()` in `theme.py` → add name to `AVAILABLE_THEMES`. New themes are automatically included in the `random` rotation pool.

**New fetcher**: Create `src/fetchers/my_fetcher.py` → use `cache.py` and `circuit_breaker.py` → integrate into `main.py` orchestration → extend `DashboardData` if needed → add ser/deser branch to `cache.py` `save_source()`/`load_cached_source()`. See `purpleair.py` as a reference implementation.

**New config option**: Add field to relevant dataclass in `config.py` → add to `config.example.yaml` → use in main or components.

## Fonts

### Bundled fonts (`fonts/`)

| File | Accessor(s) in `fonts.py` | Used by |
|---|---|---|
| `PlusJakartaSans-*.ttf` | `regular`, `medium`, `semibold`, `bold` | Default font for all themes |
| `weathericons-regular.ttf` | `weather_icon` | Weather condition icons + moon phase glyphs (all themes) |
| `ShareTechMono-Regular.ttf` | `cyber_mono` | `terminal` — event body text |
| `Maratype.otf` | `maratype` | `terminal` — dashboard title, day column headers, quote body |
| `UESC Display.otf` | `uesc_display` | `terminal` — month band, section labels, quote attribution |
| `Synthetic Genesis.otf` | `synthetic_genesis` | `terminal` — large today date numeral |
| `DMSans.ttf` | `dm_regular/medium/semibold/bold` | `minimalist`, `weather`, `fuzzyclock` |
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
- Quiet hours (default 23:00–06:00): app exits immediately during this window
- eInk partial refreshes degrade quality; full refresh forced after `max_partials_before_full` partials
- Default canvas: 800×480; scaled via LANCZOS to match display resolution
- Image hash comparison (`last_image_hash.txt`) skips eInk writes when content unchanged
- Random theme state persists in `output/random_theme_state.json`; delete it to force a new theme pick mid-day
- `terminal` theme: the month band font (`font_month_title`) starts at 33px and scales down to fit longer names (e.g. FEBRUARY, SEPTEMBER) within the combined date cell width
- Deploy paths (`PI_USER`, `PI_HOST`, `PI_DIR`) default to `pi`, `raspberrypi.local`, `~/home-dashboard`; override with `make deploy PI_USER=myuser PI_HOST=mypi.local`
- `dashboard.service` contains hardcoded `/home/pi/home-dashboard` paths that must be edited manually for non-default setups
- Service account credentials are cached for the process lifetime; tokens auto-refresh via google-auth (safe for the hourly cron use case)
- Weather forecast parsing skips malformed OWM slots (missing `"main"` key or empty `"weather"` array) rather than crashing
- `fuzzyclock` theme: time phrases snap to the nearest 5-minute bucket; the default systemd timer runs every 5 minutes; the image-hash check prevents eInk refreshes when the phrase hasn't changed
- `fuzzyclock` component uses `style.font_bold` / `style.font_medium` for the phrase / date — font-agnostic so the theme can be re-skinned by swapping the style callables
- Theme preview PNGs (`output/theme_*.png`) are git-ignored by `.gitignore` (`output/*.png`) but tracked as exceptions; use `git add -f output/theme_<name>.png` when adding a new one
- PurpleAir AQI card only appears in the `weather` theme; other themes have access to `DashboardData.air_quality` for future use
- `_pm25_to_aqi()` in `purpleair.py` implements the EPA AQI piecewise linear formula with standard breakpoints; it is applied to the 60-minute PM2.5 average (`pm2.5_60minute`) for a smoother, less noisy reading — the result is stored on `AirQualityData.aqi` at fetch time; `AirQualityData` also carries `pm1` (PM1.0) and `pm10` (PM10) for display in the `weather` theme detail strip
- When `purpleair.api_key` or `purpleair.sensor_id` is `0`/`""`, the source is skipped silently (no circuit breaker entry, no cache miss); validation emits warnings only when one is set without the other
