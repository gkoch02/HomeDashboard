# CLAUDE.md — Dashboard v6

## Project Overview

Python eInk dashboard for Raspberry Pi. Displays a weekly calendar (Google Calendar / ICS / CalDAV), weather (OpenWeatherMap), upcoming birthdays, and a daily quote. Renders to a supported eInk display (Waveshare or Pimoroni Inky Impression) or PNG preview. Includes an optional Flask web UI for status monitoring, config editing, and live theme preview.

**v5 architecture themes**: pluggable registries for fetchers / themes / components, schema-driven config + web editor, unified display backend, content-hash refresh throttle, CalDAV calendar source. See `docs/upgrading-from-v4.md` for the migration walkthrough.

## Quick Commands

```bash
make setup          # Create venv, install deps, copy config template
make test           # Run pytest
make coverage       # Run pytest with coverage report (term-missing + HTML in htmlcov/)
make dry            # Preview with dummy data → output/latest.png
make previews       # Generate all theme preview PNGs → assets/previews/theme_*.png
                    #   (scripts/build_previews.py — registry-driven, one process,
                    #    pinned render date; adding a theme needs no edit here)
make previews-inky  # Same batch for Inky → assets/previews/theme_*_inky.png
make check          # Validate config/config.yaml
make docs-check     # Run scripts/check_docs.py (markdown links + the canonical theme
                    #   inventories in docs/themes.md, docs/inky-previews.md and
                    #   docs/previews.md, plus config/config.example.yaml —
                    #   both its theme list and its coverage of every field in
                    #   src/config.py). Enforced by
                    #   the `lint` CI job, so drift here blocks a merge.
make version        # Print current version (e.g. main.py 6.0.0)
make release-dry    # Show the next release (inferred from the CHANGELOG) — writes nothing
make release        # Bump src/_version.py, date the CHANGELOG, commit, tag vX.Y.Z
                    #   (scripts/release.py; RELEASE_ARGS="--major" forces a bump size)
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
make banner         # Regenerate the eInk-faithful README logo → assets/banner.png
make lint           # ruff check src/ tests/ scripts/ tools/ + dead-code scan of src/
make fmt            # ruff format src/ tests/ scripts/ tools/
ruff check src/ tests/ scripts/ tools/         # Lint (direct invocation)
ruff format src/ tests/ scripts/ tools/        # Format (direct invocation)
```

## Tech Stack

- **Python 3.10+** — no async
- **Pillow** — image rendering (PIL)
- **google-api-python-client / google-auth** — Google Calendar & Contacts APIs
- **requests** — OpenWeatherMap API + ICS feed fetching
- **icalendar** — ICS feed parsing (used when `google.ical_url` is configured)
- **caldav** — CalDAV server support (used when `google.caldav_url` is configured); declared in core `dependencies`
- **PyYAML** — config parsing
- **numpy** — Inky palette quantization (`src/render/quantize.py` fast path) and Inky `show()`/`clear()` buffer assembly (`src/display/driver.py`); declared in core `dependencies`
- **Flask 3 + Waitress** — optional web UI (`requirements-web.txt`; `pip install -e ".[web]"`)
- **pytest** — testing (with unittest.mock); coverage via **pytest-cov** (gate: ≥94%, currently ~98%); theme pixel-hash snapshots in `tests/snapshots/theme_pixel_hashes.json`
- **ruff** — linting and formatting (max line length: 100)
- **AST-based custom guard** in `tools/check_naive_datetime.py` enforces aware-datetime discipline; CI runs it via `tests/test_naive_datetime_guard.py`

## Repository Structure

```
src/
├── main.py                    # Thin CLI entry point: parses args, loads config, runs DashboardApp
├── app.py                     # DashboardApp — top-level orchestrator (quiet hours, fetch, render, output)
├── cli.py                     # CLI argument parser (build_parser / parse_args)
├── data_pipeline.py           # DataPipeline — concurrent fetching, caching, circuit breaking per source
├── astronomy.py               # Pure-Python NOAA sunrise/sunset/twilight, day-length delta,
│                              #   meteor-shower lookup, GMST + LST, RA/Dec → alt/az,
│                              #   simplified Schlyter lunar position. Used by the astronomy,
│                              #   light_cycle, almanac, and constellation_map themes; no network.
├── _io.py                     # Shared `atomic_write_json()` (tempfile + os.replace);
│                              #   used by cache, breaker, quota, sync state, refresh tracker.
│                              #   Also `file_lock()` + `locked_update_json()` — a sidecar
│                              #   advisory flock covering a whole read-modify-write, for the
│                              #   state files the renderer and the web service both write
├── _time.py                   # Sanctioned aware-datetime helpers: now_utc, now_local,
│                              #   to_aware, assert_aware. Enforced by tools/check_naive_datetime.py.
│                              #   Also week_start() — the calendar event window's default
│                              #   Monday anchor, shared by the three calendar fetchers and
│                              #   app._event_window so they can't disagree
├── services/
│   ├── run_policy.py          # resolve_tz, should_skip_refresh, should_force_full_refresh
│   ├── theme.py               # resolve_theme_name (CLI → rules → schedule → cfg.theme / random)
│   ├── theme_rules.py         # Context-aware rule evaluator (weather / daypart / season / weekday / calendar)
│   ├── render_args.py         # build_render_kwargs() — the one place a Config becomes
│   │                          #   render_dashboard() arguments; shared by DashboardApp
│   │                          #   and POST /api/preview so a preview cannot diverge
│   └── output.py              # OutputService — publish to display or PNG; write last_success.txt;
│                              #   content-hash + cooldown refresh throttle (replaces v4 hourly Inky throttle)
├── _version.py                # Single source of truth: __version__
├── config.py                  # YAML → typed dataclasses; validate_config()
├── config_schema.py           # v5 declarative schema (FieldSpec/SectionSpec) — source of truth
│                              #   for editable / secret / enum metadata; powers the web editor
├── config_migrations.py       # Schema-versioned migration runner; v4_to_v5 step
├── config_validation.py       # validate_config / ConfigError / ConfigWarning (split from
│                              #   config.py; every name re-exported from src.config)
├── dummy_data.py              # Realistic dummy data for --dummy / dev previews
├── filters.py                 # Event filtering (calendar, keyword, all-day)
├── data/models.py             # Pure dataclasses: CalendarEvent, WeatherData (+ its 3-hour
│                              #   HourlyForecast grid), AirQualityData,
│                              #   Birthday, HostData, DashboardData, StalenessLevel
├── display/
│   ├── driver.py              # DisplayDriver ABC → DryRunDisplay, WaveshareDisplay, InkyDisplay;
│   │                          #   provider/model specs + image_changed()
│   ├── backend.py             # DisplayBackend ABC → WaveshareBackend, WaveshareColorBackend
│   │                          #   (four-ink "G" panels), InkyBackend; unifies the resize +
│   │                          #   finalize step (canvas.py no longer forks on provider), and
│   │                          #   fit_canvas() stretches or fits-and-pads per display.scaling
│   └── refresh_tracker.py     # Partial vs full refresh state machine
├── fetchers/
│   ├── registry.py            # v5 fetcher plugin registry (Fetcher dataclass + FetchContext);
│   │                          #   DataPipeline iterates this instead of naming sources directly
│   ├── __init__.py            # Side-effect imports populate the fetcher registry
│   ├── calendar.py            # Dispatcher: routes to CalDAV / ICS / Google API; birthday extraction;
│   │                          #   registers events + birthdays via the registry
│   ├── calendar_google.py     # Google Calendar API — full sync, incremental sync, sync state
│   ├── calendar_ical.py       # ICS feed fetching and parsing
│   ├── calendar_caldav.py     # CalDAV server fetching (Nextcloud / Radicale / iCloud / etc.)
│   ├── weather.py             # OpenWeatherMap current + forecast (free /data/2.5/ endpoints);
│   │                          #   registry adapter; owns the One Call degradation boundary
│   ├── weather_onecall.py     # One Call transport for alerts + UV only — 3.0 / 4.0 / off,
│   │                          #   selected by weather.one_call_version
│   ├── purpleair.py           # PurpleAir sensor → PM1 / PM2.5 / PM10 / AQI + ambient readings; registry adapter
│   ├── host.py                # System metrics via /proc (sync, no caching, no breaker — outside the registry)
│   ├── cache.py               # Multi-source JSON cache with per-source TTL; ser/deser delegated through registry
│   ├── circuit_breaker.py     # Per-source circuit breaker
│   ├── one_call_health.py     # Persisted One Call outcome (ok / auth_failed / transient);
│   │                          #   classifies 401/403 as permanent, warns once per
│   │                          #   healthy→failing transition, read by the status page
│   ├── request_counter.py     # Thread-local tally of the HTTP requests one fetch makes
│   └── quota_tracker.py       # Daily per-source request counter (day in cfg timezone)
└── render/
    ├── artkit.py              # Shared art-theme helpers: mode-aware colours (grey/ink/
    │                          #   accent_red), meteorological season, and the naive/aware
    │                          #   datetime normalisers (to_local_naive / hours_of_day) used by
    │                          #   any panel plotting a time axis; used by weatherglass,
    │                          #   postcard, naturalist, halftone, halftone_agenda, almanac,
    │                          #   light_cycle, day_arc
    ├── skyart.py              # Procedural sky-illustration vocabulary shared by the dithered
    │                          #   weather themes: sky gradients, sun + rays, phase-shaded moon,
    │                          #   clouds, rain/snow, lightning, fog, ordered-Bayer rule, and
    │                          #   screened_paste() for Bayer-perforated content, plus
    │                          #   draw_weather_scene() — the whole icon→illustration dispatch.
    │                          #   Extracted from halftone_panel so day_arc and
    │                          #   halftone_agenda could share it
    ├── canvas.py              # Top-level render orchestrator; iterates the component registry
    │                          #   and delegates resize+finalize to display.backend
    ├── theme.py               # Theme system (ComponentRegion, ThemeLayout, ThemeStyle);
    │                          #   exports INKY_BLACK/WHITE/YELLOW/RED/BLUE/GREEN palette indices;
    │                          #   AVAILABLE_THEMES is a live set view over
    │                          #   src.render.themes.registry
    ├── quantize.py            # quantize_for_display() for Waveshare 1-bit output +
    │                          #   quantize_to_palette() for Inky palette mapping
    ├── quotes.py              # Shared daily-quote store: one loader + the stable
    │                          #   bucket-hash selection for every panel that shows a
    │                          #   quote (per-panel key prefixes keep the picks
    │                          #   independent); path from the `quotes.path` config
    ├── random_theme.py        # Daily/hourly random theme selection + persistence
    ├── layout.py              # Default layout constants
    ├── fonts.py               # Font loader (@lru_cache)
    ├── icons.py               # OWM icon code → Weather Icons glyph
    ├── moon.py                # Moon phase calculator (+ next full/new moon dates)
    ├── moon_render.py         # Lunar-disc renderer: procedural disc (terminator, maria,
    │                          #   craters, earthshine) by default, or a real moon photo
    │                          #   (assets/moon_full.png) occluded per phase when use_photo=True
    │                          #   (moonphase_photo theme); mode-aware (L/RGB/1)
    ├── primitives.py          # Shared draw utilities (truncation, wrapping, colors, fmt_time,
    │                          #   events_for_day, deg_to_compass, location_line — the one
    │                          #   cut of an event location every panel row uses)
    ├── star_catalog.py        # Curated J2000 bright-star + constellation-outline catalogue
    │                          #   (~45 named stars); backs the constellation_map theme
    ├── themes/                # themes (45 — 44 concrete + `default` pseudo): standard week-view
    │                          #   (default, agenda, terminal, minimalist, old_fashioned, today,
    │                          #   fantasy); full-screen focused (qotd, qotd_invert, fuzzyclock,
    │                          #   fuzzyclock_invert, weather, moonphase, moonphase_invert,
    │                          #   moonphase_photo);
    │                          #   specialized views (timeline, year_pulse, monthly, sunrise,
    │                          #   light_cycle, air_quality, astronomy, constellation_map,
    │                          #   almanac, scorecard, tides, halftone, halftone_agenda,
    │                          #   day_arc, trends, weatherglass);
    │                          #   dithered art (postcard, naturalist); photo overlay (photo);
    │                          #   panoramic 1360×480 (wide_week, wide_day, wide_forecast, wide_horizon,
    │                          #   wide_night, wide_night_invert, halftone_agenda_wide);
    │                          #   utility (countdown, message, diags, wide_diags — 1360×480)
    │   ├── registry.py        # v5 theme plugin registry (register_theme + per-theme
    │   │                      #   inky_palette pair); adding a theme is one new file plus a
    │   │                      #   register_theme(...) call at its bottom
    │   └── __init__.py        # Side-effect imports of every theme module populate the registry
    └── components/            # One file per UI region (38): header, week_view, weather_panel,
        │                      #   weather_full, birthday_bar, today_view, info_panel, qotd_panel,
        │                      #   fuzzyclock_panel, diags_panel, air_quality_panel,
        │                      #   astronomy_panel, constellation_map_panel, moonphase_panel,
        │                      #   message_panel, timeline_panel, year_pulse_panel, monthly_panel,
        │                      #   sunrise_panel, light_cycle_panel, scorecard_panel, tides_panel,
        │                      #   countdown_panel, almanac_panel, halftone_panel, trends_panel,
        │                      #   postcard_panel, naturalist_panel, weatherglass_panel,
        │                      #   day_arc_panel, halftone_agenda_panel, wide_day_panel,
        │                      #   wide_forecast_panel, wide_horizon_panel,
        │                      #   wide_week_rail_panel, halftone_agenda_wide_panel, wide_night_panel,
        │                      #   wide_diags_panel
        ├── registry.py        # v5 component plugin registry (RenderContext + @register_component)
        ├── _builtins.py       # Adapter registrations for the built-in components
        └── __init__.py        # Side-effect import of _builtins populates the component registry
└── web/                       # Optional Flask web UI (install: pip install -e ".[web]")
    ├── __main__.py            # Entry point: python -m src.web [--config web.yaml] [--port 8080]
    ├── app.py                 # Flask application factory (create_app); registers all blueprints
    ├── auth.py                # HTTP Basic Auth middleware; scrypt password hashing
    ├── csrf.py                # CSRF protection: session-bound token via X-CSRF-Token header
    ├── event_store.py         # Append-only JSONL event stream (state/web_events.jsonl) for
    │                          #   status history — web actions AND renderer runs; self-trims
    │                          #   to the newest 500 records once past 256 KB
    ├── sources.py             # Canonical source names for the web layer, derived from the
    │                          #   fetcher registry (built-ins first, new ones behind them)
    ├── state_reader.py        # Pure read functions: last_success, breakers, cache ages, quota, host
    ├── config_editor.py       # Safe config read/write: EDITABLE_FIELD_PATHS derived from
    │                          #   src.config_schema.editable_field_paths(); apply_patch()
    ├── routes/
    │   ├── status.py          # GET / (HTML), GET /api/status (JSON), GET /api/health (probe)
    │   ├── image.py           # GET /image/latest, GET /image/theme/<name>
    │   ├── logs.py            # GET /api/logs?lines=N
    │   ├── config.py          # GET/POST /api/config, GET /config (HTML editor),
    │   │                      #   GET /api/config/schema (v5: schema + current values, for API clients)
    │   ├── preview.py         # POST /api/preview — render any registered theme to PNG
    │   │                      #   against dummy data or a candidate config patch; CSRF-protected
    │   └── actions.py         # POST /api/trigger-refresh, /api/reset-breaker, /api/clear-cache
    ├── templates/             # Jinja2 templates: base.html, status.html, config.html
    └── static/                # dashboard.js, style.css

config/
├── config.example.yaml        # Template (copy to config.yaml)
├── web.example.yaml           # Web UI config template (copy to web.yaml)
└── quotes.json                # Bundled daily quotes

docs/
├── setup.md                   # Google Calendar, ICS feed, CalDAV, birthdays, Pi hardware setup
├── web-ui.md                  # Web UI setup, auth, pages, manual refresh, live preview, security
├── themes.md                  # All themes, random rotation, schedule, custom themes; embeds the
│                              #   monochrome Waveshare preview PNGs
├── inky-previews.md           # The same catalog in Inky Spectra 6 color: how color is assigned,
│                              #   plus each theme's registered accent pair + _inky.png preview
├── wide-themes.md             # Guide to the eight panoramic 1360×480 themes: panel setup, choosing,
│                              #   repaint cadence, data needs; embeds the four-ink _g.png previews
├── previews.md                # How to regenerate either preview set
├── configuration.md           # Full config.yaml reference
├── development.md             # Makefile, CLI, project structure, dependencies, registry recipes
├── faq.md                     # Frequently asked questions (quiet hours, troubleshooting, etc.)
├── architecture.md            # Architecture overview and design decisions (incl. v5 registries)
├── upgrading-from-v3.md       # Migration guide from v3
└── upgrading-from-v4.md       # Migration guide from v4 → v5

tests/                         # test files, extensive mocking; `inkutils.py` holds the shared
                               #   pixel-measurement helpers for render tests (not collected — it is
                               #   not a `test_*.py`)
tools/                         # check_naive_datetime.py — AST guard enforcing aware-datetime discipline
fonts/                         # Bundled TTF fonts
deploy/                        # Systemd service + timer + configure.sh + logrotate
scripts/                       # Build/dev helpers: build_previews.py,
                               #   check_docs.py, build_banner.py
assets/                        # Tracked image assets: banner.png (README hero) + previews/ (theme PNGs)
state/                         # Runtime state: cache, breaker, quota, sync tokens (git-ignored)
output/                        # Generated PNGs + logs + health marker (git-ignored except latest.png).
                               #   DryRunDisplay keeps only the newest `DRY_RUN_HISTORY` (20)
                               #   timestamped dashboard_*.png; latest.png never matches the glob
credentials/                   # Google service account JSON (git-ignored)
pyproject.toml                 # Project metadata, dependencies, tool config (ruff, pytest, mypy)
requirements.txt               # Core Python dependencies (kept for Pi deployment compat)
requirements-web.txt           # Optional web-UI deps (Flask 3 + Waitress); mirrors the ".[web]" extra
requirements-pi.txt            # Raspberry Pi-specific deps (gpiozero, lgpio, inky; Waveshare lib installed by Makefile)
```

## Architecture Patterns

### Plugin registries (v5)
Three internal plugin registries replace the v4 hard-coded dispatch sites. Adding a new source/theme/component is a single new file plus a registration call:

- **Fetcher registry** (`src/fetchers/registry.py`) — `Fetcher(name, fetch, serialize, deserialize, ttl_minutes, interval_minutes, enabled, save_metadata, cache_metadata_valid, log_success)`. `DataPipeline.fetch()` iterates `all_fetchers()`; `cache.py` delegates ser/deser through the same registry. The `events` fetcher's `cache_metadata_valid` enforces the events-window cache invalidation rule.
- **Theme registry** (`src/render/themes/registry.py`) — `register_theme(name, factory, *, inky_palette=(primary, secondary))`. The Inky Spectra-6 colour story for each theme lives next to its registration, not in a central dict. `AVAILABLE_THEMES` on `src.render.theme` is a live set view over the registry for the CLI, validation and web callers.
- **Component registry** (`src/render/components/registry.py`) — `RenderContext` + `@register_component(name)`. Adapters take a `RenderContext` and pull what they need from it. The built-in adapters live in `src/render/components/_builtins.py`; new components can register directly inside their own module.

Each registry's package `__init__.py` imports every built-in module so consumers see a fully-populated registry by the time they read it. Re-registration of a name is a silent no-op — module reloads in tests don't raise.

### Per-source independence
Fetchers, caching, circuit breaking, and staleness are all per-source (calendar, weather, birthdays, air_quality). A weather API failure doesn't block calendar rendering. PurpleAir is fully optional — when `purpleair.api_key` and `purpleair.sensor_id` are absent, the source's `Fetcher.enabled(cfg)` returns False and it's skipped silently (no breaker entry, no cache miss).

### Theme system
Three-layer design: **ComponentRegion** (bounding box) → **ThemeLayout** (canvas + regions + draw order + `canvas_mode`) → **ThemeStyle** (colors, fonts, spacing). Components receive region + style and draw only within bounds. Themes are frozen dataclasses.

`ThemeLayout.canvas_mode` is `"1"` (1-bit, default — used by every built-in theme except `constellation_map`) or `"L"` (8-bit greyscale, opt-in). L-mode themes whose `bg` is white must use `fg=0, bg=255` in `ThemeStyle` (`bg=1` is near-black in L mode, not white); the dark-canvas `constellation_map` inverts that with `fg=255, bg=0` for white-stars-on-black-sky. For Waveshare, the final L→`"1"` conversion is handled by `quantize_for_display()` in `render/quantize.py` and is controlled by `display.quantization_mode` (`threshold` / `floyd_steinberg` / `ordered`). For Inky, the final image is mapped to the limited Spectra 6 palette instead of being quantized to 1-bit.

Two rotation cadences are available: `theme: random_daily` (alias: `random`) picks once per day after midnight and persists to `state/random_theme_state.json`; `theme: random_hourly` picks once per hour and persists to `state/random_theme_hourly_state.json`. Both use the same `random_theme.include` / `random_theme.exclude` lists. The concrete theme name is resolved in `services/theme.py` before `load_theme()` is called — `load_theme()` itself never receives a pseudo-theme name.

Theme-resolution priority (highest → lowest): **CLI `--theme` > `theme_rules` > `theme_schedule` > `cfg.theme` / random**. `theme_rules` (evaluated by `services/theme_rules.py`) is the first-match-wins context system — conditions are any combination of `weather`, `weather_alert_present`, `daypart`, `season`, `weekday`, `calendar`. `theme_schedule` entries are sorted by HH:MM and the active entry is the last one whose time ≤ current local time. When no rule or schedule row fires, `cfg.theme` applies.

`resolve_theme_name()` is called **twice** in `DashboardApp.run()` when `theme_rules.rules` is non-empty: once pre-fetch with `data=None` (for sizing the calendar event window) and once post-fetch with the loaded `DashboardData` (so weather-dependent rules can fire). When no rules are configured, the second call is skipped to avoid a duplicate `pick_random_theme()` log line. Rules requiring weather data silently skip on the first call so offline boots fall through cleanly.

### Data flow
`main.py` (thin): parse args → load config → validate config → `DashboardApp.run()`.

`DashboardApp.run()`: resolve timezone → check quiet hours → check morning startup (auto-force-full-refresh) → load data (dummy or `DataPipeline.fetch()`) → filter events → resolve theme name → load theme → render → `OutputService.publish(now=..., theme_name=...)` → write `last_success.txt`. The whole body is wrapped in a top-level `try/except` that calls `OutputService.write_error_marker(exc)` → `output/last_error.txt` (JSON: `timestamp`, `exception_type`, `message`) and re-raises so systemd still records the failure.

`DataPipeline.fetch()`: read `state/dashboard_cache.json` once into `_cache_blob` (via `load_cache_blob()`) → check cache freshness per source (`load_cached_source_from_blob()`) → check circuit breaker → launch concurrent fetches via `ThreadPoolExecutor` → resolve results (cache fallback on failure) → fetch host data synchronously → return `DashboardData`. `self.fetched_at` is always an aware datetime (`datetime.now(tz or timezone.utc)`) so subtraction against cache timestamps never raises `TypeError`.

### Rendering
Components are pure functions: `draw_*(draw, data, region, style) -> None`. No global state. Same input produces the same PNG. The component registry wraps each in an adapter `(ctx: RenderContext) -> None` that pulls the right kwargs from `ctx`.

`render_dashboard()` creates the canvas in a mode derived from theme + display spec (`_is_color_display()` — a `DisplaySpec` whose `render_mode` is `"RGB"`, which is Inky and the Waveshare "G" models; `canvas.py` no longer tests `provider == "inky"`). After drawing and any optional overlay, the rendered canvas is handed to `build_display_backend(config).resize_and_finalize(..., background=style.bg)` from `src/display/backend.py`. `WaveshareBackend` does LANCZOS-resize-then-quantize-to-1-bit; `WaveshareColorBackend` (four-ink "G" panels) runs a greyscale plate through that same pipeline and promotes it, or resizes a colour plate in RGB and snaps every pixel to the panel's inks by nearest colour; `InkyBackend` does an RGB resize and defers palette mapping to the Inky library at write time. All three resize through `fit_canvas()`, which stretches (the historical behaviour) or fits-and-pads with the theme background per `display.scaling` (`auto` = stretch unless the distortion would exceed a third). The SHA-256 image hash used for refresh suppression is computed on the final backend-ready image bytes.

### Display refresh throttle (v5)
`OutputService.publish()` skips hardware writes when both:
1. The image hash matches the last persisted hash (`output/last_image_hash.txt`), OR
2. The cooldown window since the last refresh has not yet elapsed.

The cooldown is `display.min_refresh_interval_seconds` (config), defaulting to 60s on any colour display (Inky and the four-ink Waveshare `epd10in85g`) and 0s on monochrome Waveshare; the default is keyed on the display spec, not the provider string. Setting 3600 on Inky restores the v4 "exactly once an hour" behaviour. `--force-full-refresh` bypasses both checks. State persists in `state/refresh_throttle_state.json` (the legacy `inky_refresh_state.json` is migrated transparently on first read). The fuzzyclock theme allowlist that v4 carried is gone — content-hash equality already short-circuits identical-content refreshes for any theme.

### Config schema + migration runner (v5)
`src/config_schema.py` is the single source of truth for which fields are editable via the web UI, which are secret (and must never be sent to the browser as plaintext), and which have enumerated choices. `editable_field_paths()` replaces the v4 hand-rolled `EDITABLE_FIELD_PATHS` constant in `web.config_editor`. `to_json(values=...)` powers `GET /api/config/schema` for the schema-driven web editor.

`src/config_migrations.py` runs at the top of `load_config()` and upgrades older YAML shapes to `CURRENT_SCHEMA_VERSION = 5` in-memory before parsing. `v4_to_v5` is currently a metadata bump (v5 is a strict superset of v4 — every v4 config still parses unchanged) and the attachment point for future renames. Migrations run in memory only; a step that must mutate the file on disk needs to add its own backup.

## Key Conventions

- **Dataclass-first**: pure data models with no I/O in `src/data/models.py`
- **Config mirrors YAML**: the dataclass hierarchy in `config.py` matches the YAML structure; every field is optional with a default. **`load_config()` never raises on a value it cannot read** (nothing above it catches): numeric fields go through `_read_number()`, lists through `_read_list()`, and an unreadable value keeps the default and is appended to `cfg.unreadable` (an instance attribute, not a dataclass field, so the schema and `check_docs` don't see it), which `validate_config()` reports as a `ConfigError`. The web editor's `_load_raw_yaml()` has the opposite contract and raises `ConfigReadError`, because a save that starts from an empty mapping would replace the file with only the form's keys; a missing file is still `{}`
- **Max line length**: 100 characters
- **Comments**: a comment states the rule and, when it is not obvious, one clause of why. How it was found goes in the commit message; no issue numbers in code
- **Testing**: heavy use of `unittest.mock.patch`; fixtures for temp dirs and dummy data; every public render function has dedicated smoke tests plus logic unit tests. Coverage gate is `fail_under = 94` in `pyproject.toml` (`[tool.coverage.report]`). Run `make coverage` to print missing lines and write an HTML report to `htmlcov/`. `src/_version.py` and `src/main.py` are omitted from coverage
- **Render-test assertions**: measure ink, never `Image.getbbox()`, which returns the full canvas on a white `"1"` plate whether or not anything was drawn. Use `tests/inkutils.py`: `marks()` (pixels differing from the background, works on every canvas polarity), `ink()`, `ink_bbox()`, `ink_x_extent()`, `text_line_heights()`, `ink_clusters()`. Two traps: the header, weather, environment and quote bands are inverted, so more content means less ink; and a white-on-black panel (`constellation_map`, `moonphase`) must be rendered with its own theme style. Prefer differential assertions (with and without the feature, compare the band it owns) over hardcoded pixel counts
- **Verify a render test by deleting what it names**: write the assertion, delete the behaviour it is named for, and confirm it goes red before trusting it. A test that asserts something is *not* drawn cannot detect a no-op; check those by breaking the suppression instead
- **Thread safety**: cache operations use `threading.Lock()`
- **Graceful degradation**: fetch failure → load cached → use stale data → staleness indicator in header
- **Error boundaries**: credential loading failures, malformed API responses, and cache write errors are caught and logged without crashing the app. A top-level `try/except` in `DashboardApp.run()` writes `output/last_error.txt` (read by the web UI for "is the last run current?") and re-raises so the failure propagates to systemd
- **Atomic state writes**: every JSON state file (`dashboard_cache.json`, `dashboard_breaker_state.json`, `api_quota_state.json`, `calendar_sync_state.json`, refresh-tracker state) is written via the shared `atomic_write_json()` helper in `src/_io.py` (tempfile in the same dir + `os.replace`) so a kill mid-write can't truncate the file
- **API timeout**: `ThreadPoolExecutor` in `DataPipeline` enforces a 120-second upper bound per source via `future.result(timeout=120)`. Google Calendar API calls additionally use a 30-second per-request HTTP timeout (`_HTTP_TIMEOUT_SECONDS` in `calendar_google.py`) so a stalled DNS lookup can't waste the full 120-second slot

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
--version              Print version and exit (e.g. "main.py 6.0.0")
```

## Adding New Features

**New component**: Create `src/render/components/my_component.py` → implement `draw_my_component(draw, data, region, style)` → add a `ComponentRegion` to `ThemeLayout` if the new component is full-canvas → register the adapter (either with a `@register_component("my_component")` decorator inside the new module, or by adding an entry to `src/render/components/_builtins.py`) → add `"my_component"` to the relevant theme's `draw_order`. No edits to `canvas.py` required — the registry handles dispatch.

**New theme**: Create `src/render/themes/my_theme.py` → implement `my_theme() -> Theme` factory → at the bottom of the module call `register_theme("my_theme", my_theme, inky_palette=(INKY_X, INKY_Y))` (palette indices imported from `src.render.theme`) → add the new module to `src/render/themes/__init__.py` so the side-effect import fires → partial-refresh capability needs no declaration; `Theme.allows_partial_refresh` derives it from the plate (see the gotcha below) → regenerate the pixel-hash baseline with `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py` and commit the updated `tests/snapshots/theme_pixel_hashes.json`. An L-mode theme must declare a `preferred_quantization_mode`: the partial-refresh derivation reads the theme, never `display.quantization_mode`, so one that declares nothing inherits a global `floyd_steinberg` unseen. New themes are automatically included in the random rotation pool (both daily and hourly). To exclude a theme from the pool (e.g. utility or diagnostic views), add its name to `_EXCLUDED_FROM_POOL` in `src/render/random_theme.py`. To author a greyscale theme, set `canvas_mode="L"` in `ThemeLayout` and use `fg=0, bg=255` in `ThemeStyle` — the Waveshare backend handles the final L→`"1"` conversion automatically.

**New fetcher**: Create `src/fetchers/my_fetcher.py` → implement a `fetch_my_source(cfg, ...)` function → at the bottom of the module call `register_fetcher(Fetcher(name="my_source", fetch=..., serialize=..., deserialize=..., ttl_minutes=lambda cfg: ..., interval_minutes=lambda cfg: ..., enabled=lambda cfg: ..., log_success=...))` → add the module import to `src/fetchers/__init__.py`. Extend `DashboardData` in `src/data/models.py` if a new top-level field is needed. The cache, breaker, quota tracker, and pipeline orchestration are all driven by the registry — no edits to `data_pipeline.py` or `cache.py` are required. See `src/fetchers/calendar_caldav.py` + the `_register()` block in `src/fetchers/calendar.py` as the v5 reference.

**New config option**: Add the field to the relevant dataclass in `config.py` → wire it into the YAML parser in the same file → add a sample value to `config.example.yaml` → if the field should be web-editable, add a `FieldSpec` entry to the appropriate `SectionSpec` in `src/config_schema.py` (mark `secret=True` for credentials) → use the field in `DashboardApp`, `DataPipeline`, or components. The web UI's `EDITABLE_FIELD_PATHS` allowlist regenerates from the schema automatically.

**New web endpoint**: Create `src/web/routes/my_route.py` → declare a `Blueprint("my_route", __name__)` → register it in `src/web/app.py` → mutating endpoints must call `csrf_protect()` from `src.web.csrf` and clients must echo the session's CSRF token via the `X-CSRF-Token` header. See `src/web/routes/preview.py` as a v5 reference.

## Fonts

### Bundled fonts (`fonts/`)

| File | Accessor(s) in `fonts.py` | Used by |
|---|---|---|
| `PlusJakartaSans-*.ttf` | `regular`, `medium`, `semibold`, `bold` | Default font for all themes |
| `weathericons-regular.ttf` | `weather_icon` | Weather condition icons + moon phase glyphs (all themes) |
| `ShareTechMono-Regular.ttf` | `cyber_mono` | `terminal` — all four base text slots (`font_regular`/`medium`/`semibold`/`bold`), so every element not claimed by a specialised slot: event rows, weather readings, birthday rows, header timestamp; `diags` — all data rows |
| `Oxanium-Variable.ttf` (OFL, variable) | `oxanium`, `oxanium_bold`, `oxanium_extrabold` | `terminal` — dashboard title, day column headers, quote body; `wide_night` — the tracked labels (ExtraBold) |
| `Rajdhani-Regular.ttf` / `Rajdhani-SemiBold.ttf` (OFL) | `rajdhani`, `rajdhani_semibold` | `terminal` — month band, section labels, quote attribution |
| `Orbitron-Variable.ttf` (OFL, variable) | `orbitron_black` | `terminal` — large today date numeral |
| `DMSans.ttf` | `dm_regular/medium/semibold/bold` | `minimalist`, `weather`, `fuzzyclock`, `diags` (section labels), `countdown`, `astronomy`, `agenda`, `light_cycle`, `constellation_map` (margin) |
| `PlayfairDisplay-*.ttf` | `playfair_regular/medium/semibold/bold` | `old_fashioned`, `qotd`, `almanac` (body + quote), `wide_week` rail (masthead, temperature, NEXT time, quote mark) |
| `Literata-SemiBold.ttf` / `Literata-Bold.ttf` (OFL; static instances at opsz 12 cut from the upstream variable font with `fonttools varLib.instancer`) | `literata_semibold`, `literata_bold` | `wide_week` rail — the quote (SemiBold ≥ 18 px, Bold below, via `wide_week_rail_panel.quote_font`) |
| `Figtree-ExtraBold.ttf` (OFL; static full-glyph Google Fonts build, via `@expo-google-fonts/figtree`) | `figtree_extrabold` | `wide_horizon` — event rows (21-px titles, 17-px times) |
| `Cinzel.ttf` | `cinzel_regular/semibold/bold/black` | `fantasy`, `old_fashioned` section labels, `moonphase`, `almanac` (section labels + small caps) |
| `CormorantGaramond.ttf` / `CormorantGaramond-Italic.ttf` (OFL, variable) | `cormorant_regular/medium/semibold/italic` | `moonphase` — date, illumination, celestial + weather strips, quote body (italic) |
| `Tangerine-Regular.ttf` (OFL) | `tangerine_regular` | `moonphase` — calligraphic script quote attribution |
| `ManufacturingConsent-Regular.ttf` (OFL) | `manufacturing_consent` | `moonphase` — Fraktur blackletter phase-name headline |
| `SpaceGrotesk-Regular.ttf` | `sg_regular` | `air_quality`, `message` |
| `SpaceGrotesk-Medium.ttf` | `sg_medium` | `air_quality`, `message` |
| `SpaceGrotesk-Bold.ttf` | `sg_bold` | `air_quality`, `message` |
| `Antonio-Variable.ttf` (OFL, variable) | `antonio_semibold`, `antonio_bold` | `sunrise`, `tides` — title + section labels (condensed display); `halftone_agenda_wide` — agenda time cells and duration column |
| `Astloch-Bold.ttf` (OFL) | `astloch_bold` | `almanac` — blackletter masthead + dateline character font |
| `Audiowide-Regular.ttf` (OFL) | `audiowide` | `constellation_map` — cardinal letters, star + constellation labels |
| `Righteous-Regular.ttf` (OFL) | `righteous` | `light_cycle` — hero day-of-month numeral; `halftone` — every typeset element; `day_arc` — chrome (dateline, numeral, labels) |
| `Rye-Regular.ttf` (OFL) | `rye` | `weatherglass` — Western-saloon instrument-deck masthead |
| `Jura-Variable.ttf` (OFL, variable, wght 300–700) | `jura_semibold` | `wide_night` — numerals |
| `BigShouldersDisplay-{SemiBold,ExtraBold,Black}.ttf` (OFL; static cuts converted from the Fontsource latin subset) | `big_shoulders_semibold/extrabold/black` | `wide_horizon` — day names, temperature labels, hero reading and outlook |

### `ThemeLayout` rendering fields

| Field | Default | Effect |
|---|---|---|
| `canvas_mode` | `"1"` | PIL image mode for the internal canvas. `"1"` = 1-bit bilevel (all built-in themes). `"L"` = 8-bit greyscale (opt-in for new themes). L-mode themes must use `fg=0, bg=255` in `ThemeStyle`. |
| `background_fn` | `None` | Optional callable `(Image, ThemeLayout, ThemeStyle) -> None` executed BEFORE component rendering. Receives the raw PIL Image so it can paste photo/grayscale content beneath UI elements. Used by the `photo` theme to dither and paste a user photo onto the canvas. |
| `prefer_color_on_inky` | `False` | When `True` AND `canvas_mode="L"` AND `display.provider: inky`, the canvas is rendered in RGB so the component can draw tuple-`fg`/`bg` colors directly (used by the `monthly` theme's heatmap palette). Ignored on Waveshare and on `"1"`-mode themes. |
| `supports_partial_refresh` | `True` | When `False`, `OutputService.publish()` drives the panel with the full waveform even if `display.enable_partial_refresh` is on. Declared by every theme whose plate is dithered greyscale or large solid ink — Waveshare's `init_fast()` fades those in bands (#222). `validate_config()` names the configured opt-outs. |

### `ThemeStyle` fields

#### Boolean / scalar flags

| Field | Default | Effect |
|---|---|---|
| `fg` / `bg` | `0` / `1` | Base foreground/background values. For `canvas_mode="L"` themes use `fg=0, bg=255` instead. Inky remaps these to palette entries internally. |
| `accent_info` / `accent_warn` / `accent_alert` / `accent_good` | `None` | Optional semantic accent roles. Waveshare falls back to monochrome-safe values; Inky maps these to palette colors for low-risk status emphasis. |
| `accent_primary` / `accent_secondary` | `None` | General-purpose accent fills. Waveshare falls back to `fg`; Inky maps to the per-theme `inky_palette` registered via `register_theme(...)`. Accessed via `style.primary_accent_fill()` / `style.secondary_accent_fill()` methods. |
| `inky_palette` | `None` | Optional per-theme override of the registered palette pair. Tuple `(primary, secondary)` of Spectra-6 indices. Useful for variant themes that want to flip palette without re-registering. |
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

Each bullet is a rule, where it lives, and the test that enforces it where one exists. The
reasoning behind a rule lives in the commit that introduced it (`git log -S <name>`) and, for the
art themes, in the panel's module docstring. Keep new entries to that shape.

### Repo hygiene

- Four guards hold the code to the shape above; fix the code, not the guard. The test suite runs `tools/check_test_assertions.py`, which fails a `test_*` that asserts nothing (a deliberate smoke test marks its `def` line `# allow-no-assert`). `make lint` runs `tools/check_dead_code.py`: vulture over `src/` with scripts, never tests, as callers; `TEST_ONLY_BASELINE` there may only shrink. Ruff `PGH003` and `RUF100` require a `type: ignore` to name its code and drop stale `noqa`. `make docs-check` holds this file to its word budget.

### Version and release

- The version has one home, `src/_version.py`. `pyproject.toml` reads it via `dynamic = ["version"]`; never restate a literal there. `tests/test_version_consistency.py` also requires the newest CHANGELOG entry to match `__version__`.
- `make release` (`scripts/release.py`) bumps, dates the `## [Unreleased]` block, commits and tags in one step, rolling back on failure. Bump size is inferred from the Unreleased headings (Added/Changed/Deprecated/Removed → minor; Fixed/Security only → patch). Major is never inferred: `RELEASE_ARGS="--major"`.

### State files

- All JSON state goes through `atomic_write_json()` in `src/_io.py`. A file both the renderer and the web service write (`dashboard_cache.json`, `dashboard_breaker_state.json`, `web_events.jsonl`) must be changed through `locked_update_json()` so the whole read-modify-write sits under the sidecar `flock` (`<file>.lock`; a sidecar because an atomic write replaces the inode). `CircuitBreaker._save(source)` writes only the one source that changed. Missing `fcntl` degrades to no lock; bookkeeping never fails a render.
- All persisted timestamps are aware ISO strings. Use `src/_time.py` (`now_utc`, `now_local`, `to_aware`); `tools/check_naive_datetime.py` (run by `tests/test_naive_datetime_guard.py`) fails the build on a bare `datetime.now()` / `utcnow()` outside `_time.py`. Lines that genuinely want naive wall-clock carry `# allow-naive-datetime`. Readers treat a legacy naive timestamp as UTC, never local; a test asserting that must pin `TZ` and call `time.tzset()`.
- State paths: sync tokens `state/calendar_sync_state.json` (delete to force a full resync); random theme `state/random_theme_state.json` and `state/random_theme_hourly_state.json` (delete to force a new pick); morning refresh marker `state/morning_refresh_state.json`; refresh throttle `state/refresh_throttle_state.json` (v4's `inky_refresh_state.json` is migrated on first read); One Call health `state/one_call_health.json`; weatherglass pressure history `state/weatherglass_pressure_history.json`. State files auto-migrate from `output/` to `state/` on first run.
- `output/last_success.txt` is written on every successful run and `output/last_error.txt` on every failed one; the error marker is deliberately not cleared on success. The web UI compares the two timestamps.
- `state/web_events.jsonl` is append-only, self-trims to the newest 500 records once past 256 KB, and is written by both processes: thread lock plus sidecar flock, `mkstemp` temp file for the trim.
- Inside `DataPipeline.fetch()` the cache file is read once via `load_cache_blob()`; use `load_cached_source_from_blob()`, never `load_cached_source()`, there. A regression test asserts the file is opened at most once per fetch. Decoding dispatches on `schema_version` (`_decode_v2_block` / `_decode_v1_legacy`); v1 files keep working.

### Run policy

- Quiet hours (default 23:00–06:00) exit immediately; `--dry-run` bypasses them.
- Morning startup: the first run within 30 min after `quiet_hours_end` forces a full refresh once per day, recorded in the morning marker. Dry runs never write the marker; `--force-full-refresh` bypasses it and does not update it. A missing or malformed marker reads as "never".
- The daily quota counts HTTP requests, not fetches: `DataPipeline._counted_fetch` runs each fetch inside `request_counter.counting()`. A new fetcher must call `request_counter.attach(session)` or `count_request()` or its requests go uncounted. `google.daily_quota_warning` applies to every source; the day rolls over on the configured timezone.
- `retry_fetch()` retries only likely transient failures: not `RuntimeError` / `ValueError` / `TypeError` / `KeyError`, and not an HTTP 4xx other than 408/429. The status comes from `fetchers.errors.http_status()`, which follows `__cause__`, so wrap a library failure with `raise ... from exc`.
- `DataPipeline` bounds each source at 120 s via `future.result(timeout=120)`. That bounds the render, not the worker thread, so every fetcher sets its own HTTP timeout (Google 30 s, ICS 30 s, CalDAV `DAVClient(timeout=30)`).

### Display and refresh

- Partial refresh is a per-model fact: `WAVESHARE_FAST_INIT` in `src/display/driver.py` names the fast init for the models that have one; the others drop `enable_partial` with a warning. `enable_partial_refresh` defaults to `False`. The fast waveform does not drive black as deeply as `init()`, which is the source of "blacks look grey" reports. The tri-colour `epd7in5b_V2` sends an all-zero red plane because the vendor `getbuffer()` XORs with 0xFF.
- Every Waveshare model entry must name a real `waveshare_epd` module and carry that driver's `EPD_WIDTH` / `EPD_HEIGHT`; `getbuffer()` returns a blank buffer on a size mismatch with no error. Check the vendor repo before adding one. Supported: `epd7in5`, `epd7in5_V2` (default), `epd7in5b_V2`, `epd7in5_HD`, `epd13in3k`, `epd10in85g`; `inky` → `impression_7_3_2025`.
- `Theme.allows_partial_refresh` is derived from the plate by `plate_needs_full_waveform()`: a plate declines when it dithers (`preferred_quantization_mode` of `floyd_steinberg` / `ordered`, or a dithered `background_fn`) or when `bg` is ink. `canvas_mode == "L"` is not the criterion. `ThemeLayout.supports_partial_refresh` defaults to `None` (derive) and exists only to overrule; `tests/test_theme_partial_refresh.py` lists the overrides in `OVERRIDES` and rejects a declaration that merely agrees with the derivation. The derivation can only remove partial refresh, never add it, and never reads `display.quantization_mode`.
- Refresh suppression (see Architecture Patterns): the hash is checked before the cooldown. `output/latest.png` is the current render, not a mirror of the panel: it is written after a hardware write and on the cooldown-deferred path, and a deferred run does not persist the image hash, so the next eligible run paints the pending change. Inky has no partial refresh; `display.min_refresh_interval_seconds: 3600` gives once-an-hour behaviour.
- `ThemeLayout.repaint_slot_hours` adds a per-theme write limit: a changed image is deferred when the same theme already wrote in the current clock-aligned slot (`in_same_repaint_slot`). The state file records `theme`, so rotating to a theme mid-slot paints at once. `wide_horizon` and `wide_night` set 1.
- Anything drawn from the render clock makes the hash differ every tick. "Updated" captions must draw `DashboardData.content_at` via `primitives.content_time(data, now)`, never `now`. `tests/test_idle_tick_no_redraw.py` renders every theme at two idle ticks and fails any whose image changes; clock-driven themes are listed in `TIME_DRIVEN`, which is itself asserted to stay accurate.
- `DryRunDisplay.show()` writes a timestamped `output/dashboard_<ts>.png` and prunes to the newest `DRY_RUN_HISTORY` (20) by name.
- `display.scaling` (`fit_canvas()` in `src/display/backend.py`): `auto` stretches unless the aspect distortion exceeds `FIT_DISTORTION_THRESHOLD` (4/3), then fits and pads with the theme `bg`. The 1360×480 `wide_*` themes letterbox on an 800×480 panel, which is what the snapshot and idle-tick suites hash; `random_theme.eligible_themes(..., panel=)` drops any theme that would be padded.
- The Waveshare 10.85" G is a colour model inside the Waveshare provider (`WAVESHARE_COLOR_MODELS`: four inks, `render_mode="RGB"`, no partial refresh). Themes draw against `WAVESHARE_G_STYLE_PALETTE` (Spectra indices with blue and green folded onto black, pure-white ground); the final `quantize_to_palette_nearest()` is a hard snap, never a dither, and a neutral grey always lands on black or white.
- Art regions are the one place a colour panel dithers: an adapter appends the panel's `art_rect(region)` to `RenderContext.dither_regions`, and `backend.dither_art_regions()` Floyd-Steinbergs that rectangle onto the inks before the snap (`G_EXACT_REMAP` substitutes the G inks first; neutrals diffuse against black and white only). Never declare a region containing type, and never one that is already exact inks (`wide_horizon`'s sky; `test_native_pipeline_changes_nothing_but_the_ink_snap` pins it). The mono backend ignores the list.

### Rendering

- Default canvas 800×480, LANCZOS-resized to the panel, then `quantize_for_display()` per `display.quantization_mode` (`threshold` default; `floyd_steinberg` restores the pre-v5 look).
- L-mode themes use `fg=0, bg=255` (or `fg=255, bg=0` for a dark plate); `bg=1` is near-black in L. Every built-in theme except `constellation_map` is mode `"1"`.
- Inky colour: each theme registers `inky_palette=(primary, secondary)` with `register_theme`; `_resolve_style()` remaps `fg` / `bg` and fills unset accent roles (`accent_info` blue, `accent_warn` yellow, `accent_alert` red, `accent_good` green). Components call `style.primary_accent_fill()` / `secondary_accent_fill()`, which return `fg` on mono. Index constants live on `src.render.theme`.
- `tests/test_theme_pixel_snapshots.py` hashes every theme's render at `FIXED_NOW = 2026-04-06 10:30` against `tests/snapshots/theme_pixel_hashes.json`. The assertion runs only when the runtime Pillow equals `reference_env.pillow_version`; the `snapshot-tests` CI job pins it, so install that Pillow locally to see real failures. Intentional theme changes regenerate with `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py`. Replacing `assets/moon_full.png` or bumping the version (`diags` renders it) changes hashes.
- `artkit.to_local_naive(dt, tz)` drops tzinfo without conversion when `tz is None`; a bare `astimezone()` would make renders host-dependent. `CalendarEvent.start` / `end` are already naive local; sun times and `RenderContext.now` are aware.
- `scripts/build_banner.py` loads faces by bare filename and does not import `fonts.py`, so a font swap must be applied there by hand.
- Quote loading has one home, `src/render/quotes.py`; each panel passes its own key prefix so two panels on one plate never show the same quote. The store path (`quotes.path`) is threaded through `render_dashboard(quotes_path=...)`, never module state. `cache.quote_refresh` is `daily` / `twice_daily` / `hourly`.
- `skyart.harden_typeset(image, box)` snaps a type region to 0/255 before Floyd-Steinberg; call it only on type over a solid field. `skyart.draw_weather_scene()` is the shared icon→illustration dispatch for `halftone`, `halftone_agenda`, `halftone_agenda_wide` and `day_arc`.
- Per-panel staleness glyphs come from `draw_staleness_glyph()` in `primitives.py`; `weather_panel` and `birthday_bar` take a `staleness` kwarg.
- `primitives.next_birthday()` is the one home of the Feb 29 → Feb 28 rollover.
- `(0.0, 0.0)` for `weather.latitude` / `longitude` means unset; panels then fall back to OWM sunrise/sunset.

### Themes

- Theme resolution: CLI `--theme` > `theme_rules` > `theme_schedule` > `cfg.theme` / random. `resolve_theme_name()` runs twice when rules exist (pre-fetch with `data=None` to size the event window, post-fetch with data); rules needing weather, AQI or calendar data skip silently when it is missing.
- `theme_rules` conditions: `weather`, `weather_alert_present`, `daypart` (`dawn` / `day` / `dusk` / `night`), `season`, `weekday`, `calendar` (`empty` / `done` / `active` / `upcoming_soon` / `busy` / `birthday_today`), `temp_at_least` / `temp_at_most`, `aqi_at_least`. An unreadable numeric bound drops the whole rule rather than widening it; booleans are rejected (YAML reads `yes` as `True`). Calendar states come from `_calendar_states()` and are emitted only when the source is present in `data.source_staleness`.
- `_event_window()` fetches the union of the ranges every rule candidate needs, anchored on `_time.week_start()`. `EXTRA_EVENT_DAYS` in `src/app.py` (theme → days past the week) feeds it; add any theme that rolls its agenda to tomorrow (`day_arc`, `halftone_agenda`, `wide_day`, `wide_week` = 1, `halftone_agenda_wide` = 2, `wide_horizon` = 3).
- Random rotation: `random_daily` (alias `random`) and `random_hourly`, both honouring `random_theme.include` / `exclude`. `_EXCLUDED_FROM_POOL` in `random_theme.py` permanently excludes `diags`, `wide_diags`, `message`, `countdown`, `photo`, `wide_night`, `wide_night_invert`. New themes join the pool automatically.
- `theme_schedule` entries sort by HH:MM; the active one is the last at or before now; none fired → normal resolution.
- Per-theme facts that matter when editing:
  - `terminal`: the month-band shrink loop no longer fires with Rajdhani but is still driven through a narrowed region in `tests/test_week_view.py`.
  - `fuzzyclock`: phrases snap to 5-minute buckets; the hash check prevents refreshes when the phrase is unchanged.
  - `countdown`: offline, reads `cfg.countdown.events`, caps at 5, plumbed via the `countdown_events` kwarg.
  - `astronomy`, `light_cycle`, `moonphase`, `day_arc`, `constellation_map`, `almanac`, `weatherglass`: pure math from `src/astronomy.py` and `src/render/moon.py`; no fetcher.
  - `moonphase*`: discs come from `moon_render.py` (procedural; `moonphase_photo` occludes `assets/moon_full.png` via `ThemeStyle.use_moon_photo`); `moonphase_invert` and `moonphase_photo` derive from `moonphase_theme()` with `dataclasses.replace`.
  - `monthly`: Sunday-first six-row grid; `prefer_color_on_inky=True` heatmap.
  - `photo`: `background_fn` pastes a Floyd-Steinberg-dithered `photo.path`; `draw_order` is empty.
  - `postcard`, `naturalist`: seeded procedural art; `naturalist` seeds from `_stable_seed(...)` because `str.__hash__` is per-process.
  - `weatherglass`: 2× supersampled, `threshold` quantization, pressure history in state (`state_dir=None` on dry and dummy runs).
  - `day_arc`: axis-strip elements have disjoint row bands (`TestAxisStripBands`); `build_time_axis()` needs events already filtered to the day; `agenda_day()` rolls over only after sunset and after every timed event has ended.
  - `halftone_agenda`: imports `agenda_day` from `day_arc_panel` rather than copying it; sun times are normalised once in `_sun_times`; `TEMP_PT = 78` and the `inline_range` / `stacks_time` rules are pinned by tests; `supports_partial_refresh=False`.
  - `halftone_agenda_wide`: imports the private band and time-cell helpers from `halftone_agenda_panel` on purpose; draws no event-state treatments so the plate repaints once a day; marks and type use `artkit.accent_yellow_solid`, not `skyart.accent_yellow`, whose L-mode grey `harden_typeset` snaps to paper; `tests/test_halftone_agenda_wide_theme.py` pins before/during/after byte-identity.
  - `wide_horizon`: the window starts at the 3-hour slot holding now, so it stays out of `TIME_DRIVEN`; take slot ends from `slot_spans()` (DST); stand-in lead-in slots are excluded from extremes via `real_from`; the sky is exact inks and must not be an art region; Figtree is Latin-only, so `title_font()` falls back to Literata via `fonts.has_glyphs()`.
  - `wide_week`: the rail sets `draw.fontmode = "1"` (`TestBilevelType`) and pins quote stem width (`TestQuoteWeight`); yellow is only ever a fill behind ink type, and the grid's `secondary_accent_fill()` colours weekend-header *text*, so the theme's secondary accent must never be yellow.
  - `wide_day`: `pack_lanes()` packs by bar-plus-label pixel extent, not time span.
  - `wide_night`: red comes from `primary_accent_fill()`, not `bg`; measure icon glyphs with `ink_box()`, not `textbbox()`.
  - `wide_diags`: reads the ink set from the resolved style (`panel_inks()`); the DIFFUSED row is its one art region; in `ALWAYS_LIVE` in the idle-tick test.
- Adding a theme needs `make previews`, `make previews-inky`, and an entry in both `docs/themes.md` and `docs/inky-previews.md`, or `make docs-check` fails; both pages use `### ` for group headings and `#### <theme>` for entries, and one regex in `scripts/check_docs.py` reads them. A `wide_*` theme also needs its `_g` preview and a section in `docs/wide-themes.md` added by hand.

### Calendar

- Backend precedence in `fetch_events`: `caldav_url` > `ical_url` > Google API. The alternatives bypass Google entirely, including incremental sync.
- A backend fails rather than returning a short calendar: ICS and CalDAV raise `CalendarFetchError` (a plain `Exception` subclass, so it still gets one retry) on any failure, including one bad feed among `additional_ical_urls`, and the pipeline falls back to the cached calendar with the stale glyph. A genuinely empty week is `[]`.
- ICS: the feed is re-downloaded on every fetch, and `_fetch_from_ical()` fails on the first dead feed rather than collecting them. Recurrence is expanded by `recurring-ical-events` in `_expand_components()`; the expander raises on bad input, so `_drop_unusable_vevents()` prunes DTSTART-less VEVENTs and `_expand_one_by_one()` retries per component. Floating DTSTARTs resolve against UTC in the expander, so the span is padded by `_EXPAND_PAD` (1 day) and the window filter still decides. `_cap_runaway_series()` caps each series at 500 after the window filter. The calendar name comes from `X-WR-CALNAME`, else the hostname. Tz-aware DTSTARTs become naive local. Tests in `tests/test_ical_edge_cases.py` must pin `tz=`.
- CalDAV: `caldav_url`, `caldav_username`, `caldav_password_file` are required; `caldav_calendar_url` is optional. `import caldav` is local to `fetch_from_caldav`.
- `validate_config()` adjusts its warnings per backend: it skips the service-account warnings when `ical_url` is set, errors on a non-http URL, and warns when CalDAV and ICS are both set.
- `contacts_email` is required when `birthdays.source` is `contacts`.

### Weather and air quality

- One Call is the only paid part: alerts and UV only, via `src/fetchers/weather_onecall.py`, selected by `weather.one_call_version` (`"3.0"` default, `"4.0"`, `"off"`; the parser folds YAML's float, int and bool readings back onto those strings). An account holds one subscription, so the wrong version returns 401 and cannot be auto-detected. The v4 shape wraps the record in `data[]` and lists alert IDs that cost up to `_V4_MAX_ALERT_DETAILS` (3) extra requests.
- `one_call_health.py` classifies 401/403 as permanent (warn once, status-page row) and everything else as transient (DEBUG), reading `exc.response.status_code` only. An unwritable state dir degrades to classify-and-log, and the status page reconciles the persisted record against the configured version, so switching to `off` or between 3.0 and 4.0 clears the banner at once.
- Forecast parsing skips malformed OWM slots. `WeatherData.location_name` comes from `current["name"]`.
- PurpleAir is on only when both `api_key` and `sensor_id` are set; `config.example.yaml` ships it commented out and `tests/test_config_validation.py` pins that. `_pm25_to_aqi()` uses the May 2024 EPA breakpoints on the 60-minute PM2.5 average. Ambient readings get PurpleAir's housing correction (−8 °F, +4 % RH) and are converted to `weather.units` with the suffix in `temperature_unit`; `fallback_fields` records which came from OWM, and the `air_quality` and `diags` panels suppress those.
- `HostData` is stdlib plus `/proc`, fetched synchronously after the pool; `None` fields are omitted.

### Config and web

- `config/config.example.yaml` is checked against the code by `check_docs`: every `Config` field present, commented out at its default if optional, and the theme-name block matching the registry. Group labels inside the theme block are UPPERCASE because the scan collects lowercase tokens. Exemptions live in `EXAMPLE_CONFIG_EXEMPT` / `EXAMPLE_CONFIG_CONTAINERS`. Optional sources must ship commented out, because a placeholder credential turns the fetcher on.
- `display.week_days` was removed and is ignored on load.
- `src/config_schema.py` is the source of truth for web-editable, secret and enum fields; `EDITABLE_FIELD_PATHS` derives from it. Secrets surface as `_*_set` flags, never plaintext. `GET /api/config/schema` returns `to_json(values=...)`.
- `theme_rules` is web-edited as YAML text: `config_editor._normalise_patch()` parses and shape-checks every entry and blocks the save on a malformed one, because `load_config()` would silently skip it.
- `apply_patch()` validates in a temp file through `load_config()` + `validate_config()`; tests calling it must patch `src.web.config_editor.validate_config` to avoid PIL. `config_write_lock()` is public for multi-step swaps; `_refresh_in_memory_config()` assigns `DASH_CFG` and `SOURCE_TTLS` inside it.
- `POST /api/preview` renders any registered theme against dummy data or a candidate patch; pseudo-names and failed validation return 400.
- `/api/health` is the one route in `auth.PUBLIC_PATHS` and returns only `{"healthy": …}` to an unauthenticated caller. An expired CSRF token returns a JSON 403.
- Manual refresh: the web UI touches `state/web_trigger`; `dashboard-trigger.path` starts `dashboard.service`, which removes the file in `ExecStartPre`, before the run, so a crashing run cannot re-fire the path unit. The web server is a separate long-running process sharing only the filesystem. `config/web.yaml` holds the password hash and is git-ignored.
- `make deploy` rsyncs the tree and spares only `config/config.yaml`; a custom quote store belongs outside the repo or goes via `QUOTES_FILE=`. Deploy defaults: `PI_USER=pi`, `PI_HOST=dashboard`, `PI_DIR=/home/pi/home-dashboard`; `make install` substitutes `__INSTALL_DIR__` / `__USER__` into the units. The `gpiozero` pin factory is `lgpio`.
- `numpy` and `caldav` are core dependencies. `[tool.setuptools.packages.find] include = ["src*"]` keeps `pip install .` from scattering modules at top level, and the `test-core-install` job imports the installed package from `/tmp` because pytest always resolves `src.*` to the checkout. Add new top-level subpackages to that import list.
