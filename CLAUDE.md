# CLAUDE.md — Dashboard v6

## Project Overview

Python eInk dashboard for Raspberry Pi: weekly calendar (Google Calendar / ICS / CalDAV), weather (OpenWeatherMap), birthdays and a daily quote, rendered to a Waveshare or Pimoroni Inky panel or a PNG preview, with an optional Flask web UI.

Each fact has one home. Facts the code states live in the code: field comments in `src/render/theme.py`, font accessors in `src/render/fonts.py`, an "Editing notes" paragraph in each theme module's docstring, and a header comment or docstring beside any other single-task detail. Narrative architecture is [docs/architecture.md](docs/architecture.md); the full command and flag tables, dependencies and the recipes for a new fetcher, theme, component, web field or endpoint are [docs/development.md](docs/development.md).

## Everyday Commands

```bash
make setup          # venv, deps, config template
make test           # pytest (coverage gate fail_under = 94 in pyproject.toml)
make lint           # ruff check + dead-code scan + mypy (CI runs all three)
make fmt            # ruff format src/ tests/ scripts/ tools/
make docs-check     # scripts/check_docs.py: links, theme inventories, example config,
                    #   this file's word budget. Run by the lint CI job.
make dry            # dummy-data preview → output/latest.png
make previews       # all theme previews → assets/previews/ (previews-inky for Inky)
make release-dry    # show the next release inferred from the CHANGELOG; writes nothing
```

Pi, deploy and web-service targets are in the Makefile and [docs/setup.md](docs/setup.md). CLI flags: `--dry-run`, `--dummy`, `--config`, `--date` (dry-run only), `--theme`, `--message`, `--force-full-refresh`, `--ignore-breakers`, `--check-config`, `--version`.

## Stack

Python 3.10+, no async. Pillow for rendering, numpy for Inky quantization, requests, icalendar, caldav, PyYAML, google-api-python-client; Flask 3 + Waitress for the optional web UI (`pip install -e ".[web]"`). pytest with `unittest.mock`; ruff (line length 100) and mypy.

## Architecture

- **Plugin registries**: fetchers (`src/fetchers/registry.py`), themes (`src/render/themes/registry.py`, `register_theme(name, factory, *, inky_palette=...)`) and components (`src/render/components/registry.py`, `@register_component`). Each package `__init__` imports every built-in; re-registering a name is a silent no-op so test reloads don't raise.
- **Per-source independence**: fetch, cache, circuit breaker and staleness are per source; a weather failure never blocks the calendar. A source whose `Fetcher.enabled(cfg)` is False is skipped silently.
- **Data flow**: `main.py` parses args and validates config, then `DashboardApp.run()`: timezone → quiet hours → morning startup → `DataPipeline.fetch()` (one cache read, per-source freshness, breaker, concurrent fetches, cache fallback) → filter events → resolve theme → render → `OutputService.publish()` → `last_success.txt`.
- **Theme system**: `ComponentRegion` → `ThemeLayout` (canvas, regions, draw order, `canvas_mode`) → `ThemeStyle`. Themes are frozen dataclasses; components draw only within their region.
- **Rendering**: components are pure `draw_*(draw, data, region, style)` functions with no global state. `render_dashboard()` picks the canvas mode from theme plus display spec, then `build_display_backend(config).resize_and_finalize()` in `src/display/backend.py` resizes and quantizes per backend. The refresh-suppression hash is taken on the final backend-ready bytes.

## Key Conventions

- **Dataclass-first**: pure data models with no I/O in `src/data/models.py`.
- **Config mirrors YAML**: the dataclass hierarchy in `config.py` matches the YAML; every field is optional with a default. `load_config()` never raises on an unreadable value (`_read_number()`, `_read_list()`): it keeps the default and appends to `cfg.unreadable`, which `validate_config()` reports. The web editor's `_load_raw_yaml()` instead raises `ConfigReadError`, because a save from an empty mapping would overwrite the file; a missing file is still `{}`.
- **Comments** state the rule and, when not obvious, one clause of why. How it was found goes in the commit; no issue numbers in code.
- **Testing**: helpers shared between test files live in `tests/conftest.py` as plain functions. `src/_version.py` and `src/main.py` are omitted from coverage.
- **Render-test assertions** measure ink, never `Image.getbbox()`, which returns the full canvas on a white `"1"` plate. Use `tests/inkutils.py` (`marks()`, `ink()`, `ink_bbox()`, `ink_x_extent()`, `text_line_heights()`, `ink_clusters()`, `record_text()`). The header, weather, environment and quote bands are inverted, so more content means less ink; a white-on-black panel must be rendered with its own theme style. Prefer differential assertions over hardcoded pixel counts.
- **Verify a render test by deleting what it names**: write the assertion, delete the behaviour, confirm red. A test that something is *not* drawn cannot detect a no-op; break the suppression instead.
- **Graceful degradation**: fetch failure → cached data → stale data → staleness indicator. Credential, parse and cache-write errors are logged, never fatal.

## Gotchas

Each bullet is a rule, where it lives, and the test that enforces it where one exists. The reasoning lives in the commit that introduced it (`git log -S <name>`) and, for art themes, in the panel's docstring. Keep new entries to that shape.

### Repo hygiene

- Four guards hold the code to the shape above; fix the code, not the guard. The test suite runs `tools/check_test_assertions.py`, which fails a `test_*` that asserts nothing (a deliberate smoke test marks its `def` line `# allow-no-assert`). `make lint` runs `tools/check_dead_code.py` (vulture over `src/`, scripts as callers, never tests). Ruff `PGH003` / `RUF100` require a `type: ignore` to name its code and drop stale `noqa`. `make docs-check` holds this file and each `docs/themes.md` entry to a word budget.

### Version and release

- The version has one home, `src/_version.py`; `pyproject.toml` reads it via `dynamic = ["version"]`. `tests/test_version_consistency.py` requires the newest CHANGELOG entry to match.
- `constraints/py3.11.txt` / `py3.13.txt` pin every Pi dependency and `constraints/waveshare-epd.ref` the vendor driver commit; `make pi-install` installs through them. Regenerate with `make lock`, never by hand; a changed file resets its `# Verified:` line until the hardware checklist in `docs/setup.md` runs. `tests/test_dependency_snapshot.py` holds each pin inside its `requirements*.txt` range.
- `make release` (`scripts/release.py`) bumps, dates `## [Unreleased]`, commits and tags in one step, rolling back on failure. Added/Changed/Deprecated/Removed → minor; Fixed/Security only → patch; major only via `RELEASE_ARGS="--major"`.

### State files

- All JSON state goes through `atomic_write_json()` in `src/_io.py`. A file both the renderer and the web service write (`dashboard_cache.json`, `dashboard_breaker_state.json`, `web_events.jsonl`) goes through `locked_update_json()` so the whole read-modify-write sits under the sidecar `flock`. `CircuitBreaker._save(source)` writes only the one source that changed. Missing `fcntl` degrades to no lock; bookkeeping never fails a render.
- All persisted timestamps are aware ISO strings via `src/_time.py` (`now_utc`, `now_local`, `to_aware`). `tools/check_naive_datetime.py` (run by `tests/test_naive_datetime_guard.py`) fails on a bare `datetime.now()` / `utcnow()` outside `_time.py`; lines that want naive wall-clock carry `# allow-naive-datetime`. Readers treat a legacy naive timestamp as UTC; a test asserting that pins `TZ` and calls `time.tzset()`.
- State lives in `state/` (sync tokens, random-theme picks, morning marker, refresh throttle, One Call health, weatherglass pressure history) and auto-migrates from `output/` on first run; delete a file to reset that behaviour. `output/last_success.txt` and `output/last_error.txt` are written on success and failure respectively, and the error marker is never cleared, so the web UI compares timestamps.
- `state/web_events.jsonl` is append-only, self-trims to the newest 500 records past 256 KB, and is written by both processes under thread lock plus sidecar flock.
- Inside `DataPipeline.fetch()` the cache file is read once via `load_cache_blob()`; decode sources from that blob with `load_cached_source_from_blob()`. A regression test asserts one open per fetch. Decoding dispatches on `schema_version`; v1 files keep working.

### Run policy

- Quiet hours (default 23:00–06:00) exit immediately; `--dry-run` bypasses them. The first run within 30 min after `quiet_hours_end` forces a full refresh once per day via the morning marker; dry runs never write it, `--force-full-refresh` bypasses it.
- The daily quota counts HTTP requests: `DataPipeline._counted_fetch` wraps each fetch in `request_counter.counting()`. A new fetcher must call `request_counter.attach(session)` or `count_request()` or its requests go uncounted. The day rolls over on the configured timezone.
- `retry_fetch()` retries only likely transient failures: not `RuntimeError` / `ValueError` / `TypeError` / `KeyError`, and not an HTTP 4xx other than 408/429. `fetchers.errors.http_status()` follows `__cause__`, so wrap a library failure with `raise ... from exc`.
- `DataPipeline` bounds the resolve phase at one shared `FETCH_DEADLINE_SECONDS` (120 s). That bounds the render, not the worker thread, so every fetcher sets its own HTTP timeout (30 s); `src.main` exits via `os._exit` when a non-daemon thread outlives the run. `TimeoutStartSec=260` in `deploy/dashboard.service` bounds the rest; its SIGTERM raises `RunTerminated` (a `BaseException`) so the error marker is still written.

### Display and refresh

- Partial refresh is per model: `WAVESHARE_FAST_INIT` in `src/display/driver.py` names the fast init for the models that have one; `enable_partial_refresh` defaults to `False`. The fast waveform drives black less deeply than `init()`, which is the source of "blacks look grey" reports.
- Every `WAVESHARE_MODELS` entry must name a real `waveshare_epd` module with that driver's own `EPD_WIDTH` / `EPD_HEIGHT`; a size mismatch is a blank panel with no error. The comment above the table in `driver.py` lists the supported models and the pitfalls.
- `Theme.allows_partial_refresh` is derived from the plate by `plate_needs_full_waveform()`: a plate declines when it dithers or when `bg` is ink; `canvas_mode == "L"` is not the criterion. `ThemeLayout.supports_partial_refresh` exists only to overrule; `tests/test_theme_partial_refresh.py` lists the overrides and rejects one that merely agrees with the derivation. The derivation can only remove partial refresh, never add it.
- `OutputService.publish()` skips a hardware write when, in order: the final-image hash matches `output/last_image_hash.txt`; the theme's `repaint_slot_hours` slot already painted (`in_same_repaint_slot`; the state file records `theme`, so a rotation mid-slot paints at once); the cooldown `display.min_refresh_interval_seconds` (60 s on colour, 0 s on mono). `--force-full-refresh` bypasses all three.
- `output/latest.png` is the current render, not a mirror of the panel: a cooldown-deferred run writes it but does not persist the hash, so the next eligible run paints the pending change.
- Anything drawn from the render clock changes the hash every tick. "Updated" captions draw `DashboardData.content_at` via `primitives.content_time(data, now)`, never `now`. `tests/test_idle_tick_no_redraw.py` renders every theme at two idle ticks; clock-driven themes are listed in `TIME_DRIVEN`, which is itself asserted accurate.
- `DryRunDisplay.show()` writes `output/dashboard_<ts>.png` and prunes to `DRY_RUN_HISTORY` (20).
- `display.scaling` (`fit_canvas()` in `backend.py`): `auto` stretches unless distortion exceeds `FIT_DISTORTION_THRESHOLD`, then fits and pads with the theme `bg`. The 1360×480 `wide_*` themes letterbox on an 800×480 panel, which is what the snapshot and idle-tick suites hash; `random_theme.eligible_themes(..., panel=)` drops any theme that would be padded.
- The Waveshare 10.85" G is a four-ink colour model inside the Waveshare provider (`WAVESHARE_COLOR_MODELS`, `render_mode="RGB"`, no partial refresh). Themes draw against `WAVESHARE_G_STYLE_PALETTE`; the final `quantize_to_palette_nearest()` is a hard snap, never a dither, so a neutral grey always lands on black or white.
- Art regions are the one place a colour panel dithers: an adapter appends the panel's `art_rect(region)` to `RenderContext.dither_regions` (a `background_fn` returns its own), and `backend.dither_art_regions()` Floyd-Steinbergs that rectangle onto the inks before the snap. Never declare a region containing type, and never one already in exact inks (`test_native_pipeline_changes_nothing_but_the_ink_snap` pins `wide_horizon`'s sky). The mono backend ignores the list.

### Rendering

- Default canvas 800×480, LANCZOS-resized to the panel, then `quantize_for_display()` per `display.quantization_mode` (`threshold` default).
- `ThemeLayout.canvas_mode` is `"1"` (default) or `"L"`. L-mode themes use `fg=0, bg=255` (or inverted for a dark plate); `bg=1` is near-black in L. Read which themes are L from their layouts.
- `ThemeLayout.background_fn(image, layout, style, config)` runs before any component on the raw PIL image and returns rects of source imagery, which the backend dithers like art regions.
- Inky colour: `register_theme(..., inky_palette=(primary, secondary))`; `_resolve_style()` remaps `fg` / `bg` and fills unset accent roles. Components call `style.primary_accent_fill()` / `secondary_accent_fill()`, which return `fg` on mono. Index constants live on `src.render.theme`.
- `tests/test_theme_pixel_snapshots.py` hashes every theme at `FIXED_NOW` against `tests/snapshots/theme_pixel_hashes.json`; a mismatch fails on the reference Pillow (pinned by the `snapshot-tests` CI job) and xfails elsewhere. Intentional changes regenerate with `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py`. Replacing `assets/moon_full.png` or bumping the version (`diags` renders it) changes hashes.
- `artkit.to_local_naive(dt, tz)` drops tzinfo without conversion when `tz is None`; a bare `astimezone()` would make renders host-dependent. `CalendarEvent.start` / `end` are naive local; sun times and `RenderContext.now` are aware.
- `scripts/build_banner.py` loads faces by bare filename, so a font swap must be applied there by hand.
- Quote loading has one home, `src/render/quotes.py`; each panel passes its own key prefix so two panels on one plate never share a quote. The store path is threaded through `render_dashboard(quotes_path=...)`, never module state.
- `skyart.harden_typeset(image, box)` snaps a type region to 0/255 before Floyd-Steinberg; call it only on type over a solid field. `skyart.draw_weather_scene()` is the shared icon→illustration dispatch.
- Staleness glyphs come from `draw_staleness_glyph()` in `primitives.py`; `primitives.next_birthday()` is the one home of the Feb 29 rollover. `(0.0, 0.0)` for `weather.latitude` / `longitude` means unset.

### Themes

- Retired themes live in `retired/` (not imported, tested or deployed). Their names stay in `RETIRED_THEME_NAMES` in the theme registry, which `resolve_theme_name()` maps to `default` with a warning.
- Theme resolution: CLI `--theme` > `theme_rules` > `theme_schedule` > `cfg.theme` / random. `resolve_theme_name()` runs twice when rules exist (pre-fetch with `data=None` to size the event window, post-fetch with data); rules needing missing data skip silently. Pseudo-names (`random*`) resolve in `services/theme.py`; `load_theme()` never sees one.
- `theme_rules` conditions: `weather`, `weather_alert_present`, `daypart`, `season`, `weekday`, `calendar`, `temp_at_least` / `temp_at_most`, `aqi_at_least` (values are listed in `config.example.yaml`). An unreadable numeric bound drops the whole rule rather than widening it; booleans are rejected because YAML reads `yes` as `True`. Calendar states are emitted only when the source is present in `data.source_staleness`.
- `_event_window()` fetches the union of the ranges every rule candidate needs. `EXTRA_EVENT_DAYS` in `src/app.py` maps theme → days past the week; add any theme that rolls its agenda forward.
- Random rotation: `random_daily` (alias `random`) and `random_hourly`, honouring `random_theme.include` / `exclude`; `_EXCLUDED_FROM_POOL` in `random_theme.py` permanently excludes the diagnostic, message, countdown, photo and night themes. New themes join the pool automatically.
- `theme_schedule` entries sort by HH:MM; the active one is the last at or before now.
- Adding a theme: [docs/development.md](docs/development.md#new-theme). `make docs-check` reads `docs/themes.md` and `docs/inky-previews.md` with one regex (`### ` group headings, `#### <theme>` entries).

### Calendar

- Backend precedence in `fetch_events`: `caldav_url` > `ical_url` > Google API. The alternatives bypass Google entirely, including incremental sync.
- A backend fails rather than returning a short calendar: ICS and CalDAV raise `CalendarFetchError` (a plain `Exception`, so it gets one retry) on any failure, including one bad feed among `additional_ical_urls`, and the pipeline falls back to the cached calendar with the stale glyph. A genuinely empty week is `[]`.
- ICS recurrence is expanded by `recurring-ical-events`; the padding, per-series cap and per-component retry are explained by the constants at the top of `src/fetchers/calendar_ical.py`. Tz-aware DTSTARTs become naive local, so tests in `tests/test_ical_edge_cases.py` must pin `tz=`.
- CalDAV requires `caldav_url`, `caldav_username`, `caldav_password_file`; `import caldav` is local to `fetch_from_caldav`. `validate_config()` adjusts its warnings per backend. `contacts_email` is required when `birthdays.source` is `contacts`.

### Weather and air quality

- One Call is the only paid part (alerts and UV, `src/fetchers/weather_onecall.py`), selected by `weather.one_call_version` (`"3.0"` default, `"4.0"`, `"off"`; the parser folds YAML's float/int/bool readings onto those strings). An account holds one subscription, so the wrong version returns 401 and cannot be auto-detected; the module docstring has the shape contract.
- `one_call_health.py` classifies 401/403 as permanent (warn once, status-page row) and everything else as transient, reading `exc.response.status_code` only. The status page reconciles the record against the configured version, so switching versions clears the banner at once.
- Forecast parsing skips malformed OWM slots. `WeatherData.location_name` comes from `current["name"]`.
- PurpleAir is on only when both `api_key` and `sensor_id` are set, so `config.example.yaml` ships it commented out (`tests/test_config_validation.py` pins that). The AQI breakpoints and housing correction are constants in `purpleair.py`; `fallback_fields` records which readings came from OWM and the `air_quality` and `diags` panels suppress those.
- `HostData` is stdlib plus `/proc`, fetched synchronously after the pool; `None` fields are omitted.

### Config and web

- `config/config.example.yaml` is checked by `check_docs`: every `Config` field present, commented out at its default if optional, theme-name block matching the registry (group labels UPPERCASE because the scan collects lowercase tokens). Exemptions live in `EXAMPLE_CONFIG_EXEMPT` / `EXAMPLE_CONFIG_CONTAINERS`. Optional sources ship commented out, because a placeholder credential turns the fetcher on.
- `src/config_schema.py` is the source of truth for web-editable, secret and enum fields; secrets surface as `_*_set` flags, never plaintext. `theme_rules` is web-edited as YAML text and `config_editor._normalise_patch()` blocks the save on a malformed entry, because `load_config()` would silently skip it.
- `apply_patch()` validates in a temp file through `load_config()` + `validate_config()`; tests calling it patch `src.web.config_editor.validate_config` to avoid PIL. `config_write_lock()` is public for multi-step swaps.
- `POST /api/preview` renders any registered theme against dummy data or a candidate patch; pseudo-names and failed validation return 400. `/api/health` is the one route in `auth.PUBLIC_PATHS`. An expired CSRF token returns a JSON 403.
- Manual refresh: the web UI touches `state/web_trigger`; `dashboard-trigger.path` starts `dashboard.service`, which removes the file in `ExecStartPre` so a crashing run cannot re-fire. The web server is a separate process sharing only the filesystem. `config/web.yaml` holds the password hash and is git-ignored.
- `make deploy` rsyncs the tree and spares only `config/config.yaml`; a custom quote store goes via `QUOTES_FILE=`. `make install` substitutes `__INSTALL_DIR__` / `__USER__` into the units.
- `[tool.setuptools.packages.find] include = ["src*"]` keeps `pip install .` from scattering modules; the `test-core-install` CI job imports the installed package from `/tmp`, so add new top-level subpackages to that import list.
