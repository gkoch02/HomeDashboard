# Architecture

This document describes how Dashboard-v4 is structured internally. It's aimed at contributors and maintainers who need to understand the data flow, module boundaries, and key design decisions.

## High-Level Data Flow

```
CLI (main.py)
 │
 ├─ parse args + load config
 │
 └─ DashboardApp.run()  (app.py)
     │
     ├─ resolve timezone
     ├─ check quiet hours → exit early if in window
     ├─ check morning startup → force full refresh if needed
     │
     ├─ load data ─┬─ --dummy? → generate_dummy_data()
     │             └─ DataPipeline.fetch()
     │                  │
     │                  ├─ per-source: check cache freshness
     │                  ├─ per-source: check circuit breaker
     │                  ├─ ThreadPoolExecutor (3-4 workers)
     │                  │   ├─ fetch_events()    → Google API or ICS
     │                  │   ├─ fetch_weather()   → OpenWeatherMap
     │                  │   ├─ fetch_birthdays() → file / calendar / contacts
     │                  │   └─ fetch_air_quality() → PurpleAir (optional)
     │                  ├─ resolve results (cache fallback on failure)
     │                  ├─ fetch_host_data() (synchronous, stdlib only)
     │                  └─ return DashboardData with staleness metadata
     │
     ├─ apply filters (exclude calendars/keywords/all-day)
     │
     ├─ resolve theme name
     │   ├─ CLI --theme override (highest priority)
     │   ├─ theme_schedule entries (time-based)
     │   └─ cfg.theme / random_daily / random_hourly
     │
     ├─ load theme → Theme(name, style, layout)
     │
     ├─ render_dashboard()
     │   ├─ create canvas at theme's declared mode ("1" or "L") and size
     │   ├─ iterate theme.layout.draw_order
     │   │   └─ dispatch to component drawers
     │   ├─ apply overlay (if theme defines one)
     │   ├─ resize via LANCZOS if display ≠ canvas size  (stays in L)
     │   ├─ quantize_for_display() if canvas is "L" or resize occurred
     │   └─ return PIL Image (always mode "1")
     │
     └─ OutputService.publish()
         ├─ dry-run: save PNG
         ├─ check image_changed() via hash
         └─ WaveshareDisplay.show() with refresh tracking
```

## Module Layers

### Entry point
- **`main.py`** — Thin CLI: parse args, load config, validate, run `DashboardApp`
- **`cli.py`** — Argument parser definition
- **`app.py`** — Orchestrator: quiet hours → fetch → filter → theme → render → publish

### Configuration
- **`config.py`** — YAML → dataclass hierarchy. `load_config()` and `validate_config()`
- **`data/models.py`** — Pure dataclasses: `CalendarEvent`, `WeatherData`, `Birthday`, `AirQualityData`, `HostData`, `DashboardData`, `StalenessLevel`

### Data fetching
- **`data_pipeline.py`** — Concurrent fetch orchestration with per-source cache/breaker/staleness
- **`fetchers/calendar.py`** — Dispatcher: routes to Google API or ICS, plus birthday extraction
- **`fetchers/calendar_google.py`** — Google Calendar API: full sync, incremental sync, sync state
- **`fetchers/calendar_ical.py`** — ICS feed fetching and parsing
- **`fetchers/weather.py`** — OpenWeatherMap current + forecast + alerts
- **`fetchers/purpleair.py`** — PurpleAir sensor data + EPA AQI calculation
- **`fetchers/host.py`** — System metrics via `/proc` (stdlib only)
- **`fetchers/cache.py`** — Per-source JSON cache with TTL and staleness classification
- **`fetchers/circuit_breaker.py`** — Per-source circuit breaker (CLOSED → OPEN → HALF_OPEN)
- **`fetchers/quota_tracker.py`** — Daily API call counter with auto-reset

### Services (orchestration policy)
- **`services/run_policy.py`** — Quiet hours, morning startup detection
- **`services/theme.py`** — Theme name resolution (schedule → random → concrete)
- **`services/output.py`** — Publish to display or PNG, write health marker

### Rendering
- **`render/canvas.py`** — Top-level render: create canvas, dispatch to components, quantize to 1-bit
- **`render/theme.py`** — Theme registry, `load_theme()`, `ThemeLayout`, `ThemeStyle`
- **`render/quantize.py`** — `quantize_for_display(image, mode)`: converts greyscale L → mode "1" using threshold, floyd_steinberg, or ordered (Bayer) dithering
- **`render/themes/`** — One file per theme (20 built-in themes), each exports a factory function
- **`render/components/`** — One file per UI region: `draw_*(draw, data, region, style)`
- **`render/random_theme.py`** — Daily/hourly random theme selection with persistence
- **`render/fonts.py`** — Font loader with `@lru_cache`
- **`render/primitives.py`** — Shared draw utilities (truncation, wrapping, colors)

### Display
- **`display/driver.py`** — `DisplayDriver` ABC → `DryRunDisplay`, `WaveshareDisplay`
- **`display/refresh_tracker.py`** — Partial vs. full refresh state machine

## Key Design Decisions

### Per-source independence
Every data source (calendar, weather, birthdays, air_quality) has independent:
- Cache entries with separate TTL and fetch intervals
- Circuit breaker state
- Staleness tracking
- Failure handling

A weather API failure doesn't block calendar rendering. PurpleAir is fully optional.

### Datetime invariant
All `CalendarEvent.start`/`.end` datetimes are stored as **naive local wall-clock time**. Timezone-aware datetimes from APIs are converted at fetch time via `astimezone(tz).replace(tzinfo=None)`. This simplifies rendering code — components never deal with timezone conversion.

### Cache staleness levels
Based on the ratio of cache age to TTL:
- **FRESH**: age ≤ TTL
- **AGING**: TTL < age ≤ 2×TTL
- **STALE**: 2×TTL < age ≤ 4×TTL
- **EXPIRED**: age > 4×TTL (discarded, not used)

### Theme system
Three-layer design:
1. **`ComponentRegion(x, y, w, h, visible)`** — bounding box for a UI element
2. **`ThemeLayout`** — canvas dimensions + regions + draw order + `canvas_mode`
3. **`ThemeStyle`** — colors, fonts, spacing, inversion flags

Themes are frozen dataclasses. Components are pure functions that receive `(draw, data, region, style)` and draw within bounds.

**Canvas mode** (`ThemeLayout.canvas_mode`) controls the internal rendering surface:
- `"1"` (default) — strict 1-bit bilevel. All 20 built-in themes use this. `fg=0` (black), `bg=1` (white in 1-bit mode).
- `"L"` (opt-in) — 8-bit greyscale. New themes that need intermediate grey values (gradients, photo backgrounds) set this explicitly. **Must use `fg=0, bg=255`** in `ThemeStyle` (in L mode, `1` is near-black, not white).

The final quantization step (`quantize_for_display()` in `render/quantize.py`) is applied whenever the canvas is `"L"` or a resize occurred, converting the greyscale image to the 1-bit output expected by the display drivers. The algorithm is controlled by `display.quantization_mode` in `config.yaml`.

### State vs. output separation
- **`state/`** — Runtime state (cache, breaker, quota, sync tokens, theme state). Machine-readable, not user-facing.
- **`output/`** — User-visible artifacts (PNGs, logs, health marker, image hash).

State files auto-migrate from `output/` to `state/` on first run after upgrade.

## Cache, Breaker, and Staleness Interaction

```
fetch request for source X
  │
  ├─ cache recent (< fetch_interval)? → use cache, mark FRESH, skip fetch
  │
  ├─ circuit breaker OPEN? → use cache (AGING/STALE), skip fetch
  │
  ├─ fetch via ThreadPoolExecutor
  │   ├─ success → save to cache, mark FRESH, record breaker success
  │   └─ failure → record breaker failure
  │       ├─ cache available? → use cache (AGING/STALE/EXPIRED check)
  │       └─ no cache? → return None/empty
  │
  └─ staleness metadata → baked into DashboardData
      └─ rendering can show staleness indicators per component
```

## Adding New Features

See [CONTRIBUTING.md](../CONTRIBUTING.md) for step-by-step guides on adding themes, fetchers, components, and config options.
