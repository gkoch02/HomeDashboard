# Architecture

This document describes how Home Dashboard is structured internally. It's aimed at contributors and maintainers who need to understand the data flow, module boundaries, and key design decisions.

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
     │                  ├─ ThreadPoolExecutor (workers = enabled fetcher count)
     │                  │   ├─ fetch_events()    → CalDAV / ICS / Google API
     │                  │   ├─ fetch_weather()   → OpenWeatherMap
     │                  │   ├─ fetch_birthdays() → file / calendar / contacts
     │                  │   └─ fetch_air_quality() → PurpleAir (optional)
     │                  ├─ resolve results (cache fallback on failure)
     │                  ├─ fetch_host_data() (synchronous, stdlib only)
     │                  └─ return DashboardData with staleness metadata
     │
     ├─ apply filters (exclude calendars/keywords/all-day)
     │
     ├─ resolve theme name (two phases: once pre-fetch for event window,
     │   once post-fetch so weather-dependent rules can fire)
     │   ├─ CLI --theme override (highest priority)
     │   ├─ theme_rules (weather / daypart / season / weekday / calendar)
     │   ├─ theme_schedule entries (time-based)
     │   └─ cfg.theme / random_daily / random_hourly
     │
     ├─ load theme → Theme(name, style, layout)
     │
     ├─ render_dashboard()
     │   ├─ create canvas at theme's declared mode ("1" or "L") and size
     │   ├─ iterate theme.layout.draw_order
     │   │   └─ dispatch to component adapters via the component registry
     │   ├─ apply overlay (if theme defines one)
     │   └─ build_display_backend(config).resize_and_finalize(image, ...)
     │        ├─ Waveshare: LANCZOS resize → quantize to 1-bit
     │        └─ Inky:      LANCZOS resize in RGB; palette mapping deferred to driver
     │
     └─ OutputService.publish()
         ├─ dry-run: save PNG
         ├─ enforce display.min_refresh_interval_seconds cooldown
         ├─ check image_changed() via SHA-256 hash
         └─ <provider>Display.show() with refresh tracking
```

## Module Layers

### Entry point
- **`main.py`** — Thin CLI: parse args, load config, validate, run `DashboardApp`
- **`cli.py`** — Argument parser definition
- **`app.py`** — Orchestrator: quiet hours → fetch → filter → theme → render → publish

### Configuration
- **`config.py`** — YAML → dataclass hierarchy. `load_config()` and `validate_config()`
- **`config_schema.py`** — v5 declarative schema (`FieldSpec`/`SectionSpec`); source of truth for editable / secret / enum metadata used by the web editor
- **`config_migrations.py`** — schema-versioned migration runner; `v4_to_v5` step plus a versioned `.bak-v<N>` backup helper
- **`data/models.py`** — Pure dataclasses: `CalendarEvent`, `WeatherData`, `Birthday`, `AirQualityData`, `HostData`, `DashboardData`, `StalenessLevel`

### Data fetching
- **`data_pipeline.py`** — Iterates the fetcher registry; concurrent fetch orchestration with per-source cache/breaker/staleness
- **`fetchers/registry.py`** — v5 plugin registry (`Fetcher` + `FetchContext`). Each fetcher self-registers; pipeline + cache delegate through the registry
- **`fetchers/calendar.py`** — Dispatcher: CalDAV → ICS → Google API; birthday extraction; registers `events` and `birthdays`
- **`fetchers/calendar_google.py`** — Google Calendar API: full sync, incremental sync, sync state
- **`fetchers/calendar_ical.py`** — ICS feed fetching and parsing
- **`fetchers/calendar_caldav.py`** — CalDAV server fetching (Nextcloud / Radicale / Apple iCloud / Fastmail / etc.)
- **`fetchers/weather.py`** — OpenWeatherMap current + forecast + alerts
- **`fetchers/purpleair.py`** — PurpleAir sensor data + EPA AQI calculation
- **`fetchers/host.py`** — System metrics via `/proc` (stdlib only; outside the registry — sync, no caching)
- **`fetchers/cache.py`** — Per-source JSON cache with TTL and staleness classification; ser/deser delegated through the registry
- **`fetchers/circuit_breaker.py`** — Per-source circuit breaker (CLOSED → OPEN → HALF_OPEN)
- **`fetchers/quota_tracker.py`** — Daily API call counter with auto-reset

### Services (orchestration policy)
- **`services/run_policy.py`** — Quiet hours, morning startup detection
- **`services/theme.py`** — Theme name resolution (CLI → rules → schedule → cfg.theme / random)
- **`services/theme_rules.py`** — Context-aware rule evaluator (weather / daypart / season / weekday / calendar)
- **`services/output.py`** — Publish to display or PNG, write health marker

### Rendering
- **`render/canvas.py`** — Top-level render: create canvas, iterate the component registry, hand off to the display backend
- **`render/theme.py`** — `Theme`, `ThemeLayout`, `ThemeStyle`, `load_theme()`; the `_THEME_REGISTRY` and `AVAILABLE_THEMES` exports are read-through proxies over `render/themes/registry.py`
- **`render/themes/registry.py`** — v5 theme plugin registry; each theme registers its factory + Inky `(primary, secondary)` palette pair
- **`render/components/registry.py`** — v5 component plugin registry; defines `RenderContext` and the `@register_component(name)` decorator
- **`render/components/_builtins.py`** — adapter registrations for all 25 built-in components
- **`render/quantize.py`** — `quantize_for_display(image, mode)`: converts greyscale L → mode "1" using threshold, floyd_steinberg, or ordered (Bayer) dithering. Also exports the Spectra-6 palette + Inky palette helpers used by `display.backend`
- **`render/themes/`** — One file per theme (25 concrete + `default` pseudo); each ends with a `register_theme(...)` call
- **`render/components/`** — One file per UI region: `draw_*(draw, data, region, style)`
- **`render/random_theme.py`** — Daily/hourly random theme selection with persistence
- **`render/fonts.py`** — Font loader with `@lru_cache`
- **`render/primitives.py`** — Shared draw utilities (truncation, wrapping, colors)

### Astronomy
- **`astronomy.py`** — Pure-Python NOAA solar calculator (sunrise/sunset/twilight), meteor-shower lookup, day-length delta. No network calls. Used by the `astronomy` theme.

### Display
- **`display/driver.py`** — `DisplayDriver` ABC → `DryRunDisplay`, `WaveshareDisplay`, `InkyDisplay`; `image_changed()` SHA-256 helper
- **`display/backend.py`** — v5 `DisplayBackend` ABC → `WaveshareBackend` (1-bit pipeline), `InkyBackend` (RGB pipeline). Unifies the resize + finalize step so `canvas.py` no longer forks on `config.provider`
- **`display/refresh_tracker.py`** — Partial vs. full refresh state machine

### Web UI (optional)
- **`web/app.py`** — Flask application factory; registers all route blueprints
- **`web/config_editor.py`** — Safe config read/write; `EDITABLE_FIELD_PATHS` derived from `config_schema.editable_field_paths()`
- **`web/routes/config.py`** — `GET/POST /api/config`, `GET /api/config/schema` (v5 schema-driven form metadata), `GET /config` (HTML editor)
- **`web/routes/preview.py`** — `POST /api/preview` (v5): render any registered theme to PNG against dummy data
- **`web/routes/status.py`** / **`image.py`** / **`logs.py`** / **`actions.py`** — read-only status, image proxy, log tail, mutating actions

## Key Design Decisions

### v5 plugin registries
Three internal plugin registries collapse the v4 hard-coded dispatch sites. Adding a new source / theme / component is now a single new file plus a registration call instead of edits across 6+ files:

- **`src/fetchers/registry.py`** — `Fetcher` dataclass + `FetchContext`; `DataPipeline` and `cache.py` iterate it.
- **`src/render/themes/registry.py`** — `register_theme(name, factory, *, inky_palette=...)`; the per-theme Inky palette pair lives next to the theme module, not in a central dict.
- **`src/render/components/registry.py`** — `RenderContext` + `@register_component(name)`; the 25 built-in adapters are registered in `src/render/components/_builtins.py`.

Each registry's package `__init__.py` runs side-effect imports of its members so consumers see a fully-populated registry by the time they read it. Re-registration of a name is a silent no-op so module reloads in tests don't raise. See [Adding a fetcher / theme / component](development.md) in the development guide for full recipes.

### Aware-datetime discipline
`src/_time.py` exposes `now_utc`, `now_local`, `to_aware`, and `assert_aware` as the sanctioned way to produce timestamps. The CI guard `tools/check_naive_datetime.py` (run via `tests/test_naive_datetime_guard.py`) fails the build on bare `datetime.now()` (no args) or `datetime.utcnow()` outside `src/_time.py`. Lines that genuinely want naive local wall-clock time (file-name timestamps, quiet-hours config comparisons, test fallbacks) carry an `# allow-naive-datetime` marker.

### Display backend abstraction
`src/display/backend.py` defines `DisplayBackend.resize_and_finalize(image, ...)` with two implementations:

- **`WaveshareBackend`** — LANCZOS-resize onto an `"L"` canvas, then quantize to `"1"` using the algorithm from `display.quantization_mode` (`threshold` / `floyd_steinberg` / `ordered`).
- **`InkyBackend`** — LANCZOS-resize in RGB; defer palette mapping to the Inky library at write time. Pre-quantizing with an approximated palette would snap LANCZOS grey pixels onto the wrong physical ink.

`canvas.render_dashboard` no longer branches on `config.provider`; it hands the post-component image straight to `build_display_backend(config).resize_and_finalize(...)`.

### Refresh throttle (content-hash + cooldown)
`OutputService.publish` skips hardware writes when the SHA-256 of the rendered image matches `output/last_image_hash.txt` OR a cooldown window has not yet elapsed since the last refresh. The cooldown is `display.min_refresh_interval_seconds` — defaults: 60s on Inky, 0s on Waveshare. Setting 3600 on Inky restores the v4 "exactly once an hour" behaviour. State persists in `state/refresh_throttle_state.json`; the legacy `inky_refresh_state.json` is migrated transparently on first read. The fuzzyclock allowlist v4 carried is gone — content-hash equality already short-circuits identical-content refreshes for any theme.

### Config schema framework
`src/config_schema.py` defines `FieldSpec` / `SectionSpec` and a hand-curated `schema()` that mirrors the dataclasses in `src.config` with extra metadata the web UI needs (label, description, secret/editable flags, enum choices). The schema is the single source of truth for:

- Which fields the web `/api/config` endpoint may patch (`editable_field_paths()` — replaces v4's hand-rolled `EDITABLE_FIELD_PATHS`).
- Which fields are secret and must never be returned to the browser as plaintext (`secret_field_paths()`).
- Form metadata served by `GET /api/config/schema` for the schema-driven editor.

`src/config_migrations.py` runs at the top of `load_config()` and upgrades older YAML shapes to `CURRENT_SCHEMA_VERSION = 5` in-memory before parsing. The v4→v5 step is a metadata bump (v5 is a strict superset of v4) and the attachment point for future renames; `write_pre_migration_backup` writes versioned `.bak-v<N>` siblings for migrations that mutate state on disk.

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
- `"1"` (default) — strict 1-bit bilevel. All 25 built-in themes use this. `fg=0` (black), `bg=1` (white in 1-bit mode).
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

See [Development → Adding a fetcher / theme / component](development.md#adding-a-fetcher--theme--component) for step-by-step recipes built on the v5 registries, and [CONTRIBUTING.md](../CONTRIBUTING.md) for the full project contribution guide.
