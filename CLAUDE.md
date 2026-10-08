# CLAUDE.md — Dashboard v6

## Project Overview

Python eInk dashboard for Raspberry Pi. Displays a weekly calendar (Google Calendar / ICS / CalDAV), weather (OpenWeatherMap), upcoming birthdays, and a daily quote. Renders to a supported eInk display (Waveshare or Pimoroni Inky Impression) or PNG preview. Includes an optional Flask web UI for status monitoring, config editing, and live theme preview.

Each fact in this file has one home here, and facts the code states (dataclass fields, font accessors, per-theme details) live in the code instead: field comments in `src/render/theme.py`, accessors in `src/render/fonts.py`, and an "Editing notes" paragraph in each theme module's docstring. Narrative architecture is in [docs/architecture.md](docs/architecture.md); step-by-step recipes are in [docs/development.md](docs/development.md#adding-a-fetcher--theme--component).

## Quick Commands

```bash
make setup          # Create venv, install deps, copy config template
make test           # Run pytest
make coverage       # pytest with coverage (term-missing + HTML in htmlcov/)
make dry            # Preview with dummy data → output/latest.png
make previews       # All theme preview PNGs → assets/previews/theme_*.png
                    #   (scripts/build_previews.py, registry-driven, pinned render date)
make previews-inky  # Same batch for Inky → assets/previews/theme_*_inky.png
make check          # Validate config/config.yaml
make docs-check     # scripts/check_docs.py: markdown links, the theme inventories in
                    #   docs/themes.md, docs/inky-previews.md and docs/previews.md, and
                    #   config/config.example.yaml against the registry and src/config.py.
                    #   Run by the `lint` CI job, so drift blocks a merge.
make lint           # ruff check + dead-code scan of src/ + mypy src/ (CI runs all three)
make fmt            # ruff format src/ tests/ scripts/ tools/
make version        # Print current version (e.g. main.py 6.0.0)
make release-dry    # Show the next release (inferred from the CHANGELOG); writes nothing
make release        # Bump src/_version.py, date the CHANGELOG, commit, tag vX.Y.Z
make lock           # Re-resolve the Pi dependency snapshot constraints/py*.txt (needs uv)
make banner         # Regenerate the eInk-faithful README logo → assets/banner.png
make deploy         # Rsync to Pi (PI_USER, PI_HOST, PI_DIR)
make install        # Install systemd timer on remote Pi (via ssh/scp)
make configure      # Run deploy/configure.sh interactive setup
# Run ON the Pi:
make pi-install     # apt deps, venv, Inky + Waveshare drivers
make install-display-drivers  # Reinstall/verify hardware driver libraries in the venv
make pi-enable      # Install systemd units and enable timer
make pi-status      # Timer status and recent logs
make pi-logs        # Tail output/dashboard.log
make web-enable     # Install and start web UI systemd service
make web-status     # Web service status + recent log tail
make web-logs       # Tail output/dashboard-web.log
```

## Tech Stack

- **Python 3.10+** — no async
- **Pillow** — image rendering (PIL)
- **google-api-python-client / google-auth** — Google Calendar & Contacts APIs
- **requests** — OpenWeatherMap API + ICS feed fetching
- **icalendar** — ICS feed parsing (used when `google.ical_url` is configured)
- **caldav** — CalDAV server support (used when `google.caldav_url` is configured)
- **PyYAML** — config parsing
- **numpy** — Inky palette quantization (`src/render/quantize.py`) and Inky buffer assembly (`src/display/driver.py`)
- **Flask 3 + Waitress** — optional web UI (`requirements-web.txt`; `pip install -e ".[web]"`)
- **pytest** — testing (with unittest.mock); coverage via **pytest-cov**; theme pixel-hash snapshots in `tests/snapshots/theme_pixel_hashes.json`
- **ruff** (max line length 100) and **mypy** — lint, format, types

## Repository Structure

See [Architecture](docs/architecture.md) for module boundaries and data flow,
and [Development](docs/development.md#project-structure) for the entry points.
Runtime assets remain in `fonts/`, `config/quotes.json`, and `assets/moon_full.png`;
`setup.py` copies them into `src/_assets/` in distributions, and `src/_assets.py`
locates the checkout or installed copy.

## Architecture Patterns

### Plugin registries
Adding a source, theme or component is mostly a new file plus a registration call. Each registry package's `__init__.py` imports every built-in module so consumers see a fully-populated registry; re-registering a name is a silent no-op, so module reloads in tests don't raise.

- **Fetchers** (`src/fetchers/registry.py`) — `Fetcher(name, fetch, serialize, deserialize, ttl_minutes, interval_minutes, enabled, save_metadata, cache_metadata_valid, log_success)`. `DataPipeline.fetch()` iterates `all_fetchers()`; `cache.py` delegates ser/deser through the same registry. The `events` fetcher's `cache_metadata_valid` enforces the events-window cache invalidation rule.
- **Themes** (`src/render/themes/registry.py`) — `register_theme(name, factory, *, inky_palette=(primary, secondary))`. `AVAILABLE_THEMES` on `src.render.theme` is a live set view over the registry.
- **Components** (`src/render/components/registry.py`) — `RenderContext` + `@register_component(name)`. Built-in adapters live in `src/render/components/_builtins.py`.

### Per-source independence
Fetching, caching, circuit breaking and staleness are per source (calendar, weather, birthdays, air_quality). A weather failure doesn't block calendar rendering. A source whose `Fetcher.enabled(cfg)` is False is skipped silently (no breaker entry, no cache miss).

### Theme system
**ComponentRegion** (bounding box) → **ThemeLayout** (canvas, regions, draw order, `canvas_mode`) → **ThemeStyle** (colours, fonts, spacing). Components receive region + style and draw only within bounds. Themes are frozen dataclasses. Field meanings are the comments on those dataclasses.

### Data flow
`main.py` (thin): parse args → load config → validate config → `DashboardApp.run()`.

`DashboardApp.run()`: resolve timezone → quiet hours → morning startup → load data (dummy or `DataPipeline.fetch()`) → filter events → resolve theme name → load theme → render → `OutputService.publish()` → write `last_success.txt`.

`DataPipeline.fetch()`: read the cache once → per-source freshness → circuit breaker → concurrent fetches via `ThreadPoolExecutor` → resolve (cache fallback on failure) → host data synchronously → `DashboardData`. `self.fetched_at` is always aware (`now_local(tz)`).

### Rendering
Components are pure functions: `draw_*(draw, data, region, style) -> None`, no global state; the same input produces the same PNG. `render_dashboard()` picks the canvas mode from theme + display spec (`_is_color_display()`: a `DisplaySpec` whose `render_mode` is `"RGB"`, i.e. Inky and the Waveshare "G" models), then hands the canvas to `build_display_backend(config).resize_and_finalize(..., background=style.bg)` in `src/display/backend.py`: `WaveshareBackend` (resize, quantize to 1-bit), `WaveshareColorBackend` (four-ink snap) or `InkyBackend` (RGB resize; palette mapping at write time). The refresh-suppression hash is taken on the final backend-ready bytes.

### Config migrations
`src/config_migrations.py` runs at the top of `load_config()` and upgrades older YAML shapes to `CURRENT_SCHEMA_VERSION = 5` in memory before parsing. `v4_to_v5` is a metadata bump and the attachment point for future renames; a step that must mutate the file on disk needs its own backup.

## Key Conventions

- **Dataclass-first**: pure data models with no I/O in `src/data/models.py`
- **Config mirrors YAML**: the dataclass hierarchy in `config.py` matches the YAML structure; every field is optional with a default. **`load_config()` never raises on a value it cannot read** (nothing above it catches): numeric fields go through `_read_number()`, lists through `_read_list()`, and an unreadable value keeps the default and is appended to `cfg.unreadable` (an instance attribute, not a dataclass field, so the schema and `check_docs` don't see it), which `validate_config()` reports as a `ConfigError`. The web editor's `_load_raw_yaml()` has the opposite contract and raises `ConfigReadError`, because a save that starts from an empty mapping would replace the file with only the form's keys; a missing file is still `{}`
- **Comments**: a comment states the rule and, when it is not obvious, one clause of why. How it was found goes in the commit message; no issue numbers in code
- **Testing**: heavy use of `unittest.mock.patch`; helpers copied between test files live in `tests/conftest.py` (plain functions, imported by name). Coverage gate `fail_under = 94` in `pyproject.toml`; `src/_version.py` and `src/main.py` are omitted
- **Render-test assertions**: measure ink, never `Image.getbbox()`, which returns the full canvas on a white `"1"` plate whether or not anything was drawn. Use `tests/inkutils.py`: `marks()` (pixels differing from the background, works on every canvas polarity), `ink()`, `ink_bbox()`, `ink_x_extent()`, `text_line_heights()`, `ink_clusters()`, `record_text()`. Two traps: the header, weather, environment and quote bands are inverted, so more content means less ink; and a white-on-black panel (`constellation_map`, `moonphase`) must be rendered with its own theme style. Prefer differential assertions over hardcoded pixel counts
- **Verify a render test by deleting what it names**: write the assertion, delete the behaviour it is named for, and confirm it goes red before trusting it. A test that asserts something is *not* drawn cannot detect a no-op; check those by breaking the suppression instead
- **Graceful degradation**: fetch failure → cached data → stale data → staleness indicator. Credential failures, malformed API responses and cache write errors are caught and logged without crashing

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

Recipes for a new fetcher, theme, component, web-editable config field and web endpoint are in [docs/development.md](docs/development.md#adding-a-fetcher--theme--component); the theme recipe there is the only copy. The rules that bite are in Gotchas below.

## Gotchas

Each bullet is a rule, where it lives, and the test that enforces it where one exists. The
reasoning behind a rule lives in the commit that introduced it (`git log -S <name>`) and, for the
art themes, in the panel's module docstring. Keep new entries to that shape.

### Repo hygiene

- Four guards hold the code to the shape above; fix the code, not the guard. The test suite runs `tools/check_test_assertions.py`, which fails a `test_*` that asserts nothing (a deliberate smoke test marks its `def` line `# allow-no-assert`). `make lint` runs `tools/check_dead_code.py`: vulture over `src/` with scripts, never tests, as callers. Ruff `PGH003` and `RUF100` require a `type: ignore` to name its code and drop stale `noqa`. `make docs-check` holds this file to its word budget and each `docs/themes.md` entry to `THEME_ENTRY_MAX_WORDS` (200).

### Version and release

- The version has one home, `src/_version.py`. `pyproject.toml` reads it via `dynamic = ["version"]`; never restate a literal there. `tests/test_version_consistency.py` also requires the newest CHANGELOG entry to match `__version__`.
- Reproducible Pi installs: `constraints/py3.11.txt` / `py3.13.txt` pin every dependency for 64-bit Pi OS, and `constraints/waveshare-epd.ref` the vendor driver commit. `make pi-install` installs through them via `_pip-locked`. Regenerate with `make lock`, never by hand; a changed file resets its `# Verified:` line to pending until the hardware checklist in `docs/setup.md` is run. `tests/test_dependency_snapshot.py` holds each pin inside its `requirements*.txt` range.
- `make release` (`scripts/release.py`) bumps, dates the `## [Unreleased]` block, commits and tags in one step, rolling back on failure. Bump size is inferred from the Unreleased headings (Added/Changed/Deprecated/Removed → minor; Fixed/Security only → patch). Major is never inferred: `RELEASE_ARGS="--major"`.

### State files

- All JSON state goes through `atomic_write_json()` in `src/_io.py`. A file both the renderer and the web service write (`dashboard_cache.json`, `dashboard_breaker_state.json`, `web_events.jsonl`) must be changed through `locked_update_json()` so the whole read-modify-write sits under the sidecar `flock` (`<file>.lock`; a sidecar because an atomic write replaces the inode). `CircuitBreaker._save(source)` writes only the one source that changed. Missing `fcntl` degrades to no lock; bookkeeping never fails a render.
- All persisted timestamps are aware ISO strings. Use `src/_time.py` (`now_utc`, `now_local`, `to_aware`); `tools/check_naive_datetime.py` (run by `tests/test_naive_datetime_guard.py`) fails the build on a bare `datetime.now()` / `utcnow()` outside `_time.py`. Lines that genuinely want naive wall-clock carry `# allow-naive-datetime`. Readers treat a legacy naive timestamp as UTC, never local; a test asserting that must pin `TZ` and call `time.tzset()`.
- State paths: sync tokens `state/calendar_sync_state.json` (delete to force a full resync); random theme `state/random_theme_state.json` and `state/random_theme_hourly_state.json` (delete to force a new pick); morning refresh marker `state/morning_refresh_state.json`; refresh throttle `state/refresh_throttle_state.json` (v4's `inky_refresh_state.json` is migrated on first read); One Call health `state/one_call_health.json`; weatherglass pressure history `state/weatherglass_pressure_history.json`. State files auto-migrate from `output/` to `state/` on first run.
- `output/last_success.txt` is written on every successful run and `output/last_error.txt` on every failed one; the error marker is deliberately not cleared on success. The web UI compares the two timestamps.
- `state/web_events.jsonl` is append-only, self-trims to the newest 500 records once past 256 KB, and is written by both processes: thread lock plus sidecar flock, `mkstemp` temp file for the trim.
- Inside `DataPipeline.fetch()` the cache file is read once via `load_cache_blob()`; decode each source from that blob with `load_cached_source_from_blob()`. A regression test asserts the file is opened at most once per fetch. Decoding dispatches on `schema_version` (`_decode_v2_block` / `_decode_v1_legacy`); v1 files keep working.

### Run policy

- Quiet hours (default 23:00–06:00) exit immediately; `--dry-run` bypasses them.
- Morning startup: the first run within 30 min after `quiet_hours_end` forces a full refresh once per day, recorded in the morning marker. Dry runs never write the marker; `--force-full-refresh` bypasses it and does not update it. A missing or malformed marker reads as "never".
- The daily quota counts HTTP requests, not fetches: `DataPipeline._counted_fetch` runs each fetch inside `request_counter.counting()`. A new fetcher must call `request_counter.attach(session)` or `count_request()` or its requests go uncounted. `google.daily_quota_warning` applies to every source; the day rolls over on the configured timezone.
- `retry_fetch()` retries only likely transient failures: not `RuntimeError` / `ValueError` / `TypeError` / `KeyError`, and not an HTTP 4xx other than 408/429. The status comes from `fetchers.errors.http_status()`, which follows `__cause__`, so wrap a library failure with `raise ... from exc`.
- `DataPipeline` bounds the resolve phase at one shared 120 s deadline (`FETCH_DEADLINE_SECONDS`). That bounds the render, not the worker thread, so every fetcher sets its own HTTP timeout (Google 30 s, ICS 30 s, CalDAV `DAVClient(timeout=30)`); `src.main` exits via `os._exit` when a non-daemon thread is still alive after the run, since the interpreter would join it forever. `TimeoutStartSec=260` in `deploy/dashboard.service` bounds the rest; its SIGTERM raises `RunTerminated` (a `BaseException`) so the panel sleeps and the error marker is written.

### Display and refresh

- Partial refresh is a per-model fact: `WAVESHARE_FAST_INIT` in `src/display/driver.py` names the fast init for the models that have one; the others drop `enable_partial` with a warning. `enable_partial_refresh` defaults to `False`. The fast waveform does not drive black as deeply as `init()`, which is the source of "blacks look grey" reports. The tri-colour `epd7in5b_V2` sends an all-zero red plane because the vendor `getbuffer()` XORs with 0xFF.
- Every Waveshare model entry must name a real `waveshare_epd` module and carry that driver's `EPD_WIDTH` / `EPD_HEIGHT`; `getbuffer()` returns a blank buffer on a size mismatch with no error. Check the vendor repo before adding one. `epd10in85g` is vendor demo code, copied in by `scripts/install_epd10in85g.py`. Supported: `epd7in5`, `epd7in5_V2` (default), `epd7in5b_V2`, `epd7in5_HD`, `epd13in3k`, `epd10in85g`; `inky` → `impression_7_3_2025`.
- `Theme.allows_partial_refresh` is derived from the plate by `plate_needs_full_waveform()`: a plate declines when it dithers (`preferred_quantization_mode` of `floyd_steinberg` / `ordered`, or a dithered `background_fn`) or when `bg` is ink. `canvas_mode == "L"` is not the criterion. `ThemeLayout.supports_partial_refresh` defaults to `None` (derive) and exists only to overrule; `tests/test_theme_partial_refresh.py` lists the overrides in `OVERRIDES` and rejects a declaration that merely agrees with the derivation. The derivation can only remove partial refresh, never add it, and never reads `display.quantization_mode`.
- `OutputService.publish()` skips a hardware write on any of, in order: the final-image hash matches `output/last_image_hash.txt`; the theme's `repaint_slot_hours` slot (below); the cooldown `display.min_refresh_interval_seconds` (default 60 s on any colour display, 0 s on monochrome Waveshare; keyed on the display spec). `--force-full-refresh` bypasses all three.
- `output/latest.png` is the current render, not a mirror of the panel: it is written after a hardware write and on the cooldown-deferred path, and a deferred run does not persist the image hash, so the next eligible run paints the pending change. Inky has no partial refresh; `display.min_refresh_interval_seconds: 3600` gives once-an-hour behaviour.
- `ThemeLayout.repaint_slot_hours` adds a per-theme write limit: a changed image is deferred when the same theme already wrote in the current clock-aligned slot (`in_same_repaint_slot`). The state file records `theme`, so rotating to a theme mid-slot paints at once. `wide_horizon` and `wide_night` set 1.
- Anything drawn from the render clock makes the hash differ every tick. "Updated" captions must draw `DashboardData.content_at` via `primitives.content_time(data, now)`, never `now`. `tests/test_idle_tick_no_redraw.py` renders every theme at two idle ticks and fails any whose image changes; clock-driven themes are listed in `TIME_DRIVEN`, which is itself asserted to stay accurate.
- `DryRunDisplay.show()` writes a timestamped `output/dashboard_<ts>.png` and prunes to the newest `DRY_RUN_HISTORY` (20) by name.
- `display.scaling` (`fit_canvas()` in `src/display/backend.py`): `auto` stretches unless the aspect distortion exceeds `FIT_DISTORTION_THRESHOLD` (4/3), then fits and pads with the theme `bg`. The 1360×480 `wide_*` themes letterbox on an 800×480 panel, which is what the snapshot and idle-tick suites hash; `random_theme.eligible_themes(..., panel=)` drops any theme that would be padded.
- The Waveshare 10.85" G is a colour model inside the Waveshare provider (`WAVESHARE_COLOR_MODELS`: four inks, `render_mode="RGB"`, no partial refresh). Themes draw against `WAVESHARE_G_STYLE_PALETTE` (Spectra indices with blue and green folded onto black, pure-white ground); the final `quantize_to_palette_nearest()` is a hard snap, never a dither, and a neutral grey always lands on black or white.
- Art regions are the one place a colour panel dithers: an adapter appends the panel's `art_rect(region)` to `RenderContext.dither_regions` (a `background_fn` returns its own, as `image_regions`), and `backend.dither_art_regions()` Floyd-Steinbergs that rectangle onto the inks before the snap (`G_EXACT_REMAP` substitutes the G inks first; neutrals diffuse against black and white only). Never declare a region containing type, and never one that is already exact inks (`wide_horizon`'s sky; `test_native_pipeline_changes_nothing_but_the_ink_snap` pins it). The mono backend ignores the list.

### Rendering

- Default canvas 800×480, LANCZOS-resized to the panel, then `quantize_for_display()` per `display.quantization_mode` (`threshold` default; `floyd_steinberg` restores the pre-v5 look).
- `ThemeLayout.canvas_mode` is `"1"` (default) or `"L"`. L-mode themes use `fg=0, bg=255` (or `fg=255, bg=0` for a dark plate); `bg=1` is near-black in L. Read which themes are L from their layouts; a list here goes stale.
- `ThemeLayout.background_fn(image, layout, style, config)` runs before any component and receives the raw PIL image, so it can paste a photo or grey field beneath the UI. It returns rects of source imagery (or `None`), which the backend dithers like art regions but never through `G_EXACT_REMAP`; `photo` returns the full canvas on the four-ink G and pre-dithers itself on Inky and mono.
- Inky colour: each theme registers `inky_palette=(primary, secondary)` with `register_theme`; `_resolve_style()` remaps `fg` / `bg` and fills unset accent roles (`accent_info` blue, `accent_warn` yellow, `accent_alert` red, `accent_good` green). Components call `style.primary_accent_fill()` / `secondary_accent_fill()`, which return `fg` on mono. Index constants live on `src.render.theme`.
- `tests/test_theme_pixel_snapshots.py` hashes every theme's render at `FIXED_NOW = 2026-04-06 10:30` against `tests/snapshots/theme_pixel_hashes.json`. Every run compares; a mismatch fails at `reference_env.pillow_version` and xfails under any other Pillow, which the `snapshot-tests` CI job pins to the reference. Intentional theme changes regenerate with `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py`. Replacing `assets/moon_full.png` or bumping the version (`diags` renders it) changes hashes.
- `artkit.to_local_naive(dt, tz)` drops tzinfo without conversion when `tz is None`; a bare `astimezone()` would make renders host-dependent. `CalendarEvent.start` / `end` are already naive local; sun times and `RenderContext.now` are aware.
- `scripts/build_banner.py` loads faces by bare filename and does not import `fonts.py`, so a font swap must be applied there by hand.
- Quote loading has one home, `src/render/quotes.py`; each panel passes its own key prefix so two panels on one plate never show the same quote. The store path (`quotes.path`) is threaded through `render_dashboard(quotes_path=...)`, never module state. `cache.quote_refresh` is `daily` / `twice_daily` / `hourly`.
- `skyart.harden_typeset(image, box)` snaps a type region to 0/255 before Floyd-Steinberg; call it only on type over a solid field. `skyart.draw_weather_scene()` is the shared icon→illustration dispatch for `halftone`, `halftone_agenda`, `halftone_agenda_wide` and `day_arc`.
- Per-panel staleness glyphs come from `draw_staleness_glyph()` in `primitives.py`; `weather_panel` and `birthday_bar` take a `staleness` kwarg.
- `primitives.next_birthday()` is the one home of the Feb 29 → Feb 28 rollover.
- `(0.0, 0.0)` for `weather.latitude` / `longitude` means unset; panels then fall back to OWM sunrise/sunset.

### Themes

- Retired themes live in `retired/` (not imported, tested, linted or deployed; `retired/README.md` says how to restore one). Their names stay in `RETIRED_THEME_NAMES` in `src/render/themes/registry.py`, which `resolve_theme_name()` maps to `default` with a warning so an old config keeps rendering.
- Theme resolution: CLI `--theme` > `theme_rules` > `theme_schedule` > `cfg.theme` / random. `resolve_theme_name()` runs twice when rules exist (pre-fetch with `data=None` to size the event window, post-fetch with data); rules needing weather, AQI or calendar data skip silently when it is missing. Pseudo-names (`random*`) resolve in `services/theme.py`; `load_theme()` never sees one.
- `theme_rules` conditions: `weather`, `weather_alert_present`, `daypart` (`dawn` / `day` / `dusk` / `night`), `season`, `weekday`, `calendar` (`empty` / `done` / `active` / `upcoming_soon` / `busy` / `birthday_today`), `temp_at_least` / `temp_at_most`, `aqi_at_least`. An unreadable numeric bound drops the whole rule rather than widening it; booleans are rejected (YAML reads `yes` as `True`). Calendar states come from `_calendar_states()` and are emitted only when the source is present in `data.source_staleness`.
- `_event_window()` fetches the union of the ranges every rule candidate needs, anchored on `_time.week_start()`. `EXTRA_EVENT_DAYS` in `src/app.py` (theme → days past the week) feeds it; add any theme that rolls its agenda to tomorrow (`day_arc`, `halftone_agenda`, `wide_day`, `wide_week` = 1, `halftone_agenda_wide` = 2, `wide_horizon` = 3).
- Random rotation: `random_daily` (alias `random`) and `random_hourly`, both honouring `random_theme.include` / `exclude`. `_EXCLUDED_FROM_POOL` in `random_theme.py` permanently excludes `diags`, `wide_diags`, `message`, `countdown`, `photo`, `wide_night`, `wide_night_invert`. New themes join the pool automatically.
- `theme_schedule` entries sort by HH:MM; the active one is the last at or before now; none fired → normal resolution.
- Theme-local facts live in the theme module's docstring ("Editing notes"), not here; read it before editing a theme.
- Adding a theme: follow [docs/development.md](docs/development.md#new-theme). `make docs-check` reads `docs/themes.md` and `docs/inky-previews.md` with one regex (`### ` group headings, `#### <theme>` entries).

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
