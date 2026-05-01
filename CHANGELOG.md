# Changelog

All notable changes to Home Dashboard are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [5.0.0] — Pluggable & Polished

The v5 release is a structural refactor that pays down v4's hard-coded
dispatch sites and ships the long-pending CalDAV calendar source on top of
the new plugin registries. Every v4 `config.yaml` parses unchanged; state
files migrate transparently on first read. See
[Upgrading from v4](docs/upgrading-from-v4.md) for the migration walkthrough.

### Added

- **Fetcher plugin registry** (`src/fetchers/registry.py`) — `Fetcher` +
  `FetchContext` describe how to fetch / serialise / cache a single data
  source. `DataPipeline.fetch()` iterates the registry instead of naming
  sources directly; `cache.py` delegates ser/deser through the same registry.
  Adding a new data source is one new file plus a `register_fetcher(...)`
  call.
- **Theme plugin registry** (`src/render/themes/registry.py`) — themes
  self-register via `register_theme(name, factory, *, inky_palette=...)`;
  the `(primary, secondary)` Inky Spectra-6 palette pair lives next to the
  theme module, not in a central dict.
- **Component plugin registry** (`src/render/components/registry.py`) —
  `RenderContext` + `@register_component(name)` decorator. The 200-line
  `component_drawers` dict in `canvas.py` collapsed to one
  `get_component(name)(ctx)` call.
- **CalDAV calendar source** (`src/fetchers/calendar_caldav.py`) —
  Nextcloud / Radicale / Apple iCloud / Fastmail / Synology / etc. via the
  `caldav>=1.3` package. Authenticates with HTTP Basic and a one-line
  password file (no inline secrets). New `google.caldav_url`,
  `caldav_username`, `caldav_password_file`, `caldav_calendar_url` fields.
- **`DisplayBackend` ABC** (`src/display/backend.py`) — unifies the
  Waveshare / Inky resize+finalize fork that v4 carried in `canvas.py`.
- **Content-hash + cooldown refresh throttle** in `services/output.py`
  replaces the v4 hourly Inky throttle. New
  `display.min_refresh_interval_seconds` config (default 60s on Inky, 0s
  on Waveshare). The fuzzyclock theme allowlist is gone — content-hash
  equality already short-circuits identical-content refreshes.
- **Config schema framework** (`src/config_schema.py`) — declarative
  `FieldSpec` / `SectionSpec` mirroring the dataclasses with extra
  metadata (label, description, secret/editable, choices). `to_json()`
  powers the new `GET /api/config/schema` endpoint; `editable_field_paths()`
  replaces the v4 hand-rolled `EDITABLE_FIELD_PATHS` allowlist.
- **Versioned config migration runner** (`src/config_migrations.py`) —
  `CURRENT_SCHEMA_VERSION = 5`. `v4_to_v5` is a metadata bump (v5 is a
  strict superset of v4); a versioned `.bak-v<N>` backup helper is wired
  in for future migrations.
- **Live theme preview endpoint** — `POST /api/preview` renders any
  registered theme to PNG against dummy data; CSRF-protected; rejects
  pseudo-themes and unknown names. Powers a "see what this theme looks
  like" affordance in the web editor.
- **Aware-datetime helpers and CI guard** — `src/_time.py` exposes
  `now_utc`, `now_local`, `to_aware`, `assert_aware`. The AST-based
  `tools/check_naive_datetime.py` (run by `tests/test_naive_datetime_guard.py`)
  fails on bare `datetime.now()` / `datetime.utcnow()` outside the
  sanctioned wrapper. Closes the v4 class of naive-vs-aware timestamp
  bugs.
- **`docs/upgrading-from-v4.md`** — migration walkthrough.

### Changed

- **Inky throttle behaviour**: replaces the v4 hardcoded 3600-second
  hourly window + fuzzyclock allowlist with a configurable cooldown
  (default 60s) plus the existing content-hash short-circuit. Set
  `display.min_refresh_interval_seconds: 3600` to restore the v4
  behaviour explicitly.
- **State file rename**: `state/inky_refresh_state.json` →
  `state/refresh_throttle_state.json`. v4's file is migrated transparently
  on first read.
- **`_THEME_REGISTRY` and `AVAILABLE_THEMES`** on `src.render.theme`
  remain as read-through proxies over the new registry — every existing
  caller (CLI, config validator, random-theme picker, tests) keeps
  working unchanged.
- **`_INKY_THEME_KEY_COLORS` removed from `canvas.py`** — palette pairs
  now live next to each theme via `register_theme(...)`. Theme modules
  get palette index constants from `src.render.theme` (`INKY_BLACK`,
  `INKY_WHITE`, `INKY_YELLOW`, `INKY_RED`, `INKY_BLUE`, `INKY_GREEN`).
- **`web/config_editor.EDITABLE_FIELD_PATHS`** is now derived from
  `src.config_schema.editable_field_paths()`.
- **Calendar dispatcher precedence** in `src/fetchers/calendar.py` is
  now CalDAV → ICS → Google API. When CalDAV or ICS is configured the
  Google API path is completely bypassed.
- **`caldav>=1.3`** added to core dependencies (`pyproject.toml` /
  `requirements.txt`).

### Deprecated

- The legacy `state/inky_refresh_state.json` file path. v4 readers still
  work; v5 readers migrate it once and never write to it again.

### Notes

- Test count: 2239 (pre-v5) → 2327. Coverage held at ~97%. Theme
  pixel-hash snapshots are byte-identical across all 26 themes.
- A full Pydantic rewrite of `config.py` was descoped from v5.0 — the
  declarative schema + migration scaffolding deliver the same
  user-facing wins (schema-driven editor, secret hiding, live preview,
  versioned migration) on top of the existing dataclasses, with a
  fraction of the risk. Full Pydantic adoption is a v5.1 candidate.

## [4.3.1] - 2026-04-07

### (Patch version bump for minor fixes)

## [4.3] - 2026-04-06

## [4.2.1] - 2026-04-04

### (Patch version bump for minor fixes)

## [4.2] - Unreleased

### Added
- 

## [4.1.3] - 2026-04-04

### Fixed
- **KeyError in data pipeline**: Resolved a race condition where `source_staleness`
  dictionary access could raise `KeyError` when a fetch failed and cached data was
  expired. The four duplicate `_resolve_*` methods have been consolidated into a
  single `_resolve_source()` method with safe `.get()` access throughout.
- **EPD sleep exception masking**: The `finally` block in `WaveshareDisplay.show()`
  now catches exceptions from `epd.sleep()` to avoid masking the original error.
- **Timezone resolution safety**: `resolve_tz("local")` now falls back to UTC with
  a warning if the system timezone cannot be determined.

### Added
- **NYC coordinate warning**: Config validation now warns when weather coordinates
  are still set to the example defaults (New York City).
- **API key format validation**: Config validation checks that the OpenWeatherMap
  API key matches the expected 32-character hex format.
- **Circuit breaker startup logging**: Non-closed breaker states are now logged at
  startup so users can see why a source might be skipped.
- **PurpleAir debug logging**: Malformed API responses now emit debug-level log
  messages with payload structure details.
- **Systemd restart limits**: `dashboard.service` now includes `StartLimitBurst`
  and `StartLimitIntervalSec` to prevent infinite restart loops on hardware failure.
- **SPI detection in Makefile**: `make pi-install` now detects whether SPI was
  already enabled and gives clear reboot guidance accordingly.
- **Auto-derived theme registry**: `AVAILABLE_THEMES` is now derived from
  `_THEME_REGISTRY`, eliminating the risk of the two lists drifting out of sync.
- **Documentation**: Added prerequisites, first-run checklist, reliability
  explanation, and troubleshooting table to README. Added `docs/faq.md` and
  `CHANGELOG.md`.

## [4.1.1]

### Added
- Moonphase theme (`moonphase`, `moonphase_invert`) -- full-canvas moon phase
  display with illumination percentage and daily quote
- PurpleAir air quality integration (`air_quality` theme and weather theme AQI card)
- ICS calendar feed support (`google.ical_url`) -- no GCP project required
- Quote rotation control (`cache.quote_refresh`: daily, twice_daily, hourly)
- Per-panel staleness indicators (! badge on weather and birthday panels)
- Host system diagnostics theme (`diags`)
- Additional Waveshare display models (epd9in7, epd13in3k)

### Changed
- Theme schedule (`theme_schedule`) for time-of-day theme switching
- Hourly random theme rotation (`random_hourly`)
- Configurable circuit breaker and cache TTL per source

## [4.0.0]

### Added
- Complete rewrite from v3 with dataclass-first architecture
- 16 built-in themes with random rotation
- Per-source caching, circuit breaking, and staleness tracking
- Concurrent data fetching via ThreadPoolExecutor
- Waveshare multi-model support with auto-scaling
- Systemd timer-based scheduling (replaces cron)
- Interactive configuration wizard (`make configure`)
- Comprehensive config validation (`make check`)
