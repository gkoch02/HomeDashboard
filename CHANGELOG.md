# Changelog

All notable changes to Home Dashboard are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **`postcard` theme** — vintage dithered postcard.  Left two-thirds is a
  Floyd-Steinberg-dithered procedural "view" — sky gradient, layered
  mountains, water with horizontal ripple lines, foreground shore, plus
  a sun (with engraved rays), moon, clouds, rain streaks, snowflakes,
  lightning bolt, or fog bands depending on the OWM icon and daypart.
  Right third is the postcard back: cursive Playfair greeting, a
  circular red postmark stamped with today's month + day, a perforated
  postage stamp carrying the moon-phase glyph and phase name, four
  ruled "address" lines listing today's events, and the daily quote as
  the "wish you were here" signature.  Inky palette `(RED, BLACK)`.
- **`naturalist` theme** — Victorian botanical plate.  Blackletter
  Astloch masthead ("PLATE LXXIII — MMXXVI · MAY") above a Cinzel small-
  caps Latin specimen name (e.g. `QUERCUS AESTIVALIS · sub fulmine`)
  that shifts with season + weather.  The hero is a procedurally drawn
  specimen branch — solid black trunk with engraved highlight strokes,
  curving roots, six branches with mixed filled / outlined almond
  leaves whose density and treatment vary by season (bare in winter,
  buds + sparse leaves in spring, full canopy in summer, scattered
  fallen leaves in autumn) and by weather (frost stipple when cold and
  clear, rain streaks behind the foliage, snow caps on every branch,
  fog bands across the plate).  Four leader-line callouts pin EVENT,
  LUNA, SOL, and AER data to anatomical features on the specimen, the
  way a botanical engraver would.  Triple-rule footer carries the daily
  quote in Playfair regular with the author in red small caps.  Inky
  palette `(RED, BLACK)`.
- **`light_cycle` theme** — full-canvas 24-hour radial clock.  The rim
  carries hour ticks + 00 / 06 / 12 / 18 numerals; a twilight ring fills
  with progressively denser radial dashes (civil → nautical →
  astronomical) and a solid wedge for true night.  Today's timed events
  appear as small radial dashes inside the ring, a triangular needle
  marks the current moment, and a sun (or moon, when the sun is below
  the horizon) glyph rides the rim.  The centre disc shows day name +
  big day-of-month numeral (Righteous, OFL) + month + weather summary.
  Pure-Python sky math; falls back to OWM-reported sunrise/sunset when
  `weather.latitude` / `longitude` are absent.  Inky palette
  `(YELLOW, BLUE)`.
- **`almanac` theme** — Old-Farmer's-Almanac front page in **Astloch**
  (OFL blackletter masthead + dateline) plus Playfair Display body and
  Cinzel section labels.  Editorial 2×2 body grid (Heavens, From the
  Sky, The Week Ahead, Next in the Garden) reuses every existing data
  source — weather, astronomy, moon, calendar, birthdays, quote — with
  no new fetcher.  Inky palette `(RED, BLACK)` lights up the rules,
  ornaments, bullets, attribution, and shower name.
- **`constellation_map` theme** — dark-canvas star chart projected for
  the configured `weather.latitude` / `longitude` using a "looking up"
  equidistant azimuthal projection.  Bundled J2000 catalogue covers
  ~45 named bright stars and seven recognisable northern
  constellations (Ursa Major, Cassiopeia, Orion, Lyra, Cygnus, Boötes,
  Leo); the moon is plotted at its computed alt/az when above the
  horizon.  During daylight the chart auto-projects for tonight's
  solar midnight.  Star and constellation labels render in
  **Audiowide** (OFL retro-futuristic display sans).  Inky palette
  `(YELLOW, BLUE)` — yellow chrome + labels, blue constellation lines
  and altitude rings.
- **Astronomy module extensions** — `gmst_degrees`,
  `local_sidereal_time`, `equatorial_to_horizontal` (RA/Dec → alt/az),
  and `moon_equatorial` (simplified Schlyter lunar position).  Pure
  Python, no network calls.  Used by the new `light_cycle`,
  `almanac`, and `constellation_map` themes.
- **`src/render/star_catalog.py`** — curated J2000 bright-star +
  constellation outline data.  Pure data, no I/O.
- **Bundled OFL fonts** — Astloch (Regular + Bold), Audiowide
  (Regular), Righteous (Regular).  Each ships alongside its upstream
  `OFL.txt` license file under `fonts/`.
- **eInk-faithful README logo banner** — `scripts/build_banner.py`
  (`make banner`) renders a 1600×400 hero image at `assets/banner.png`
  combining a Maratype wordmark, a DM Sans tagline, and a compressed
  motif strip; output is quantized to 1-bit with Floyd-Steinberg dither
  (mirroring `render/quantize.py::quantize_for_display()`) so the
  banner reads as authentic eInk on screen.  Standalone PIL script — no
  imports from the rest of the project — and deterministic (no
  `datetime.now()`), so re-running produces byte-identical output.

### Changed

- **Preview images moved** from `output/theme_*.png` to
  `assets/previews/theme_*.png`.  The `output/` directory is now
  exclusively for runtime artefacts (`latest.png`, dry-run scratch,
  `last_success.txt`, image-hash marker); committed documentation
  assets live under `assets/previews/`.  `make previews`,
  `scripts/build_split_previews.py`, the web `/image/theme/<name>`
  route, and every doc reference were updated; `.gitignore` no longer
  needs the `!output/theme_*.png` exception.
- **`almanac` body fonts bumped 2–4 pt** for readability across the
  page.  Day-length and today's lengthening rows now combine into a
  single editorial line so the Heavens column fits cleanly above the
  mid-rule.
- **`light_cycle` centre disc spacing** — date / month / weather lines
  now position from `draw.textbbox()` rather than approximate font
  metrics, so the tall day numeral never overlaps the month label.
- **`constellation_map`** uses Audiowide instead of Cinzel for star /
  constellation / cardinal labels — heavier strokes stay legible at
  small sizes against the dark sky on both Waveshare 1-bit and Inky
  Spectra-6.

### Fixed

- **Leap-day birthdays in `almanac`** no longer drop silently in
  non-leap years (the `except ValueError: continue` branch) or crash
  on the year-+1 rollover.  Both branches now follow the convention
  `birthday_bar.py` already uses (Feb 29 → Feb 28 in non-leap years).
- **README banner — sun glyph / weather label overlap** in
  `scripts/build_banner.py`.  The weather-icons font for the sunny
  glyph carries a 15 px top margin and rays extending to `y0 + 108`,
  but the "CLEAR" label was placed at `y0 + 96` so the text sat in
  the same vertical band as the sun's lower-left rays.  Dropped the
  label to `y0 + 116` so it clears the glyph.

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
  `caldav>=1.5` package. Authenticates with HTTP Basic and a one-line
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
- **`caldav>=1.5`** added to core dependencies (`pyproject.toml` /
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
