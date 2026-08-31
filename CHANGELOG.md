# Changelog

All notable changes to Home Dashboard are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed

- **Releases are cut with one command instead of four manual edits.**
  `make release` (`scripts/release.py`) bumps `src/_version.py`, dates the
  `## [Unreleased]` block, commits, and creates the annotated `vX.Y.Z` tag.
  The bump size is inferred from the Unreleased section headings —
  `Added`/`Changed`/`Deprecated`/`Removed` means minor, `Fixed`/`Security`
  alone means patch. Major is never inferred and must be requested with
  `make release RELEASE_ARGS="--major"`. `make release-dry` prints the plan
  without writing. The script refuses a dirty tree, an existing tag, or a
  version that does not increase; pushing stays manual. If any step of the
  mutating phase fails — a rejecting pre-commit hook, an unset git identity, a
  signing key that will not load — the file rewrites and any release commit are
  rolled back, so the same release can simply be retried once the cause is
  fixed. The rollback never uses `git reset --hard`, since `--allow-dirty`
  means the tree may hold unrelated work.
- **The version has a single source of truth.** `pyproject.toml` now declares
  `dynamic = ["version"]` and reads `src/_version.py` via
  `[tool.setuptools.dynamic]` rather than restating the number. The two files
  had already drifted once — `4.6.0` was committed to one while the other
  said `5.2.0`. `tests/test_version_consistency.py` fails the build on that
  drift, on a non-semver `__version__`, on an undated or mismatched newest
  changelog entry, and on a missing `## [Unreleased]` heading.

- **`make lint` / `make fmt` now cover `scripts/` and `tools/`.** Both
  directories were outside the linted set, so `scripts/release.py`,
  `scripts/build_previews.py`, `tools/check_naive_datetime.py` and their
  neighbours could drift from the project's ruff config without CI noticing.
  Both were already clean, so this is a scope widening with no code changes.

### Fixed

- **Live preview rendered a different dashboard than the renderer does.**
  `POST /api/preview` passed a subset of the arguments `DashboardApp` passes,
  so `photo` previewed with no photo at all — the one theme whose entire
  content is the config value being previewed — `countdown` previewed with no
  events (so it looked broken in the picker), a custom `quotes.path` store was
  ignored, and the documented `(0.0, 0.0)` "unset" coordinate sentinel was
  passed through raw instead of becoming `None`, so `astronomy`,
  `light_cycle`, `moonphase`, `day_arc` and `constellation_map` previewed
  plausible-looking sun and moon geometry for the Gulf of Guinea rather than
  the unset-coordinates message the panel actually renders. The assembly now
  lives once in `src/services/render_args.py` (`build_render_kwargs()`) and
  both callers go through it; `state_dir=None` stays the preview's value so
  previews still persist no weatherglass pressure history.

- **`GET /api/status` picked and persisted the random theme.** Reporting the
  current theme went through `resolve_theme_name()`, which for `random_daily` /
  `random` / `random_hourly` is not a read: it draws from the pool and writes
  `state/random_theme_state.json` whenever the day/hour bucket has rolled over.
  The status page polls every 30 seconds and the renderer runs every 5 minutes,
  so the web process — not the renderer — won the race to choose the day's
  theme at nearly every rollover. `resolve_theme_name()` and both
  `pick_random_theme*` functions now take `persist=` (default `True`,
  unchanged for the renderer); the status page passes `persist=False`, reports
  the pick the renderer actually stored, and says the theme has not been drawn
  yet when the bucket is empty.

- **The web UI read the host clock where the renderer reads `cfg.timezone`.**
  `is_quiet_hours_now()` and `_build_status()` both called bare
  `datetime.now()`. On the documented Pi setup — system tz UTC, configured tz
  local, the case `_time.day_start_utc`'s docstring names — that is a wall
  clock 7–8 hours off: the status page reported "display refresh paused until
  6:00" while the panel was refreshing normally, `GET /api/health?max_age=…`
  exempted the age check during the wrong window (so a dead renderer read
  healthy overnight), and the reported theme was resolved for the wrong hour —
  near local midnight, for the wrong *day*, evaluating `theme_schedule` and the
  daypart/weekday `theme_rules` against a date the renderer never sees. Both
  now resolve through `state_reader.config_tz(cfg)`, and `is_quiet_hours_now()`
  takes the instant as an argument instead of reading a clock of its own.

- **An empty YAML section crashed the renderer, `--check-config` and the web
  UI.** Every section parser called `.get()` on `raw["<section>"]` without
  checking it was a mapping, so a header with nothing under it — the shape a
  user produces by commenting keys out one at a time — parsed as `None` and
  raised `AttributeError` out of `load_config()`. That is the one call with no
  error boundary above it: `--check-config` could not diagnose the very problem
  it exists for, `POST /api/config` and `POST /api/preview` returned 500 instead
  of a validation error, and `/config` 500'd outright, so the editor could not
  be used to fix the file that broke the editor. A shared `_section()` helper
  now normalises each section (and a non-mapping value) to `{}`, and the bare
  scalar keys `title` / `theme` / `timezone` / `state_dir` keep their defaults
  rather than becoming the string `"None"`. `purpleair.sensor_id` had the same
  problem one level down (`TypeError` on an empty value, `ValueError` on text);
  it now parses defensively and `validate_config()` reports the bad value as a
  `ConfigError` naming it. `main()` also wraps `load_config()` so any remaining
  parse failure — a YAML syntax error, say — prints a message naming the file
  instead of a traceback.

- **An ICS or CalDAV outage blanked the calendar and destroyed the cache.**
  Both backends swallowed every failure and returned `[]`, which
  `DataPipeline._resolve_source` cannot tell from "no events this week": it
  wrote the empty list to the cache, marked the source `FRESH`, and recorded a
  breaker **success**. So a feed being down rendered an empty week, overwrote
  the last known good calendar, showed no staleness indicator, and kept the
  breaker closed so nothing ever fell back to cache. Both now raise
  `CalendarFetchError` (`src/fetchers/errors.py`) and the existing
  cache-fallback path renders the last complete calendar with the stale
  marker. **Partial failure is a failure too**: with several
  `additional_ical_urls`, one bad feed no longer returns the others, because
  there is no way to express "partial" in the value the pipeline caches — the
  working feeds still reach the panel from cache, and only a first-ever run
  with a broken feed renders nothing, loudly. The new exception subclasses
  `Exception` rather than any of the four types `retry_fetch` treats as
  permanent, so transient network failures keep their retry. A genuinely empty
  week is still `[]` and still cached. The ICS walk stops at the **first**
  failing feed: collecting them all cost one 30-second timeout per feed and the
  retry repeated the sequence, so three dead feeds spent ~180s against the
  pipeline's 120s per-source ceiling — which releases the render but cannot
  kill the worker thread, so the renderer process stayed alive until the walk
  finished. Since any failure discards the whole result, the remaining feeds
  were pure waste.

- **CalDAV requests had no timeout.** Every other fetcher sets one (weather
  10s, ICS 30s, Google 30s); `DAVClient` was constructed without one, so
  `caldav` left its requests session unbounded and an unresponsive server
  blocked the fetch thread forever. The pipeline's `future.result(timeout=120)`
  does not bound that: it releases the *render*, but `concurrent.futures` joins
  its worker threads at interpreter exit, so the renderer process stayed alive
  — holding the `oneshot` systemd unit active and blocking the next timer tick
  — for as long as the server hung. Now `timeout=30`, matching the ICS path.

- **A lowercase `logging.level` crashed every run before it started.**
  `getattr(logging, cfg.log_level, logging.INFO)` only guarded against names
  the `logging` module does not have — but `info`, `debug`, `warning` and
  `error` all exist there as *functions*, so `level: info` in config.yaml
  resolved to a callable and `setLevel` rejected it with `TypeError`. It
  happened after argument parsing and before `DashboardApp`, so there was no
  `last_error.txt`, no render, and nothing but a traceback in the log. Levels
  now resolve case-insensitively through `config.resolve_log_level()`, and an
  unrecognised name falls back to INFO with `validate_config()` naming it as a
  warning. The validator asks the resolver via `is_known_log_level()` rather
  than keeping a list of its own — a separate allowlist drifts from what
  `setLevel` actually accepts, and did: it omitted the `FATAL` alias, so a
  working `level: FATAL` was reported as unknown and as falling back to INFO
  while the root logger really was set to CRITICAL.

- **A malformed `birthdays.json` failed the source instead of being skipped.**
  `_birthdays_from_file()` caught `KeyError`/`ValueError` per entry but not
  `TypeError`, so a top-level JSON object (the natural guess for a name→date
  mapping) or a list of strings raised out of the fetcher, failed the whole
  birthdays source, and counted toward opening its circuit breaker. Both
  shapes are now reported by name and skipped, and one bad entry no longer
  drops the valid ones beside it.

- **Config backups are gitignored and pruned.** Every save through the web
  editor rotates the previous `config.yaml.bak` to a timestamped archive; the
  archives were never deleted and — unlike the config itself, which is matched
  by an exact path in `.gitignore` — none of them were ignored. Each is a
  byte-for-byte copy carrying the OpenWeatherMap and PurpleAir API keys, so
  the directory grew without bound and one `git add -A` away from committing
  secrets. `.gitignore` now covers `config/*.yaml.bak*` (including the
  `.bak-v<N>` pre-migration snapshots), and a rotation prunes to the newest
  `_MAX_ROTATED_BACKUPS` (10) — the plain `.bak` and the pre-migration
  snapshots are never candidates, and a backup that cannot be deleted logs a
  warning rather than failing the save.

- **The random-theme state files are written atomically.** Both
  `random_theme_state.json` and `random_theme_hourly_state.json` used a plain
  `write_text`, the only two JSON state files not going through
  `src/_io.atomic_write_json()`. A kill mid-write left a truncated file, which
  the read path discards — so the theme changed mid-day after a power cut.

- **CLAUDE.md documented daypart values that no code path produces.** The
  `theme_rules` section listed `dawn`/`morning`/`afternoon`/`dusk`/`night`
  with `day` as an alias for the middle two. `_current_daypart()` returns
  exactly `dawn`/`day`/`dusk`/`night` and `_VALID_DAYPARTS` accepts only
  those, so a rule written from the CLAUDE.md list validated as a warning and
  then never fired.

- **A theme flip after fetch could render an agenda with no events for tomorrow.**
  `DashboardApp` sized the calendar event window by picking one candidate theme
  by fixed priority, with `monthly` always winning. But `monthly`'s window is the
  Sunday-first month grid, which ends on the last day of the month, while
  `day_arc` / `halftone_agenda` are anchored to the week plus one day — so
  `monthly` is not the superset the priority order assumed. When a month ends on
  a Saturday the grid did not reach tomorrow, and a `theme_rules` flip to either
  rollover theme on that date left their after-dark agenda rendering "Nothing
  scheduled" (2026: Jan 31, Feb 28, Oct 31). The window is now the **union** of
  every candidate's range. The Monday anchor the fetchers apply to a `None`
  start moved into `src/_time.week_start()` so the union resolves it the same
  way they do, and the union still returns `None` when it begins on that anchor,
  so installs with one candidate keep their exact cached events window.

- **`pip install .` produced an unimportable package.** With no explicit
  `packages` config, setuptools auto-discovery read the repo as a *src-layout*
  and installed every module at the top level of `site-packages` — `app.py`,
  `config.py`, `cli.py`, `main.py`, `filters.py`, a bare `__init__.py`, plus
  `data/`, `display/`, `fetchers/`, `render/`, `services/` and `web/`. Nothing
  was importable afterwards: `import src.config` failed (`No module named
  'src'`) because the `src` package no longer existed, and `import config`
  failed too, because the module's own body does `from src.config_validation
  import ...`. The generic names also collided with anything else in the
  environment. `[tool.setuptools.packages.find] include = ["src*"]` now installs
  the single `src` package that the codebase actually imports. The
  `test-core-install` CI job never caught this because pytest's
  `pythonpath = ["."]` makes the source tree importable, shadowing the
  installed copy entirely.

- **The `test-core-install` CI job could not fail.** Its whole purpose is to
  prove `pip install .` is usable, but it ran pytest from the repo checkout,
  where three separate mechanisms put the repo root on `sys.path` ahead of
  site-packages: `tests/__init__.py` makes pytest prepend the rootdir,
  `python -m pytest` prepends the cwd, and `pyproject.toml`'s
  `pythonpath = ["."]` adds it a third time. `import src.*` therefore always
  resolved to the source tree, and the job stayed green through an install in
  which every module was unimportable. It now also imports the installed
  package from a directory where the source tree is not importable. Verified
  both ways: the new step exits 0 against a correct install and exits 1
  against the pre-fix one.

## [5.2.0] - 2026-08-21

### Added

- **`theme_rules` gained numeric conditions.** `temp_at_least` / `temp_at_most`
  (inclusive, in your configured `weather.units`) and `aqi_at_least` (inclusive
  EPA AQI floor) make the obvious operator wants reachable — "`air_quality`
  when AQI is over 100", "`weatherglass` on freezing mornings". They follow the
  existing weather condition's contract: a rule silently skips when the backing
  source is unavailable, including the pre-fetch resolution pass and, for AQI,
  any install without PurpleAir configured. (#215)
- **`quotes.path` config option.** Points the daily-quote store anywhere.
  `make deploy` rsyncs the tree over the Pi install and spares only
  `config/config.yaml`, so a customised `config/quotes.json` used to be
  clobbered by the next deploy; a store outside the tree survives, and
  `make deploy QUOTES_FILE=...` covers keeping it inside. Web-editable. (#217)
- **Renderer runs are recorded in the web event stream.** The status page's
  Recent Events card showed manual button presses but never the renders
  themselves. It now carries `run_completed` / `run_failed` with duration,
  theme, and which sources were live versus served from cache. A quiet-hours
  skip records nothing. The stream also self-trims now (newest 500 records
  past 256 KB) rather than growing forever — it needed a ceiling before adding
  ~288 records a day to it. (#218)
- **`make previews-inky`** renders the Inky preview batch, which the docs
  previously described as a hand-run shell loop. (#219)

### Fixed

- **The staleness badge is no longer dropped when the forecast is empty.** With
  the forecast strip enabled but no forecast data and no weather alerts,
  `draw_weather` returned at its `n_cols == 0` early exit before reaching the
  staleness call at the end of the function — so the "!" badge was silently
  skipped in precisely the degraded state it exists to announce, an empty
  forecast usually being a symptom of the stale fetch itself. The parallel
  no-forecast-strip early return already drew it. (#229)
- **A malformed `theme_rules` threshold no longer crashes the dashboard.** A
  YAML list or mapping for `temp_at_least` / `temp_at_most` / `aqi_at_least`
  reached `int()`/`float()` as a `TypeError`, which escaped `load_config()` and
  took down every renderer run, `--check-config`, and both web pages. Such a
  rule is now dropped like any other unreadable threshold. (#215)
- **The One Call warning no longer outlives its cause.** The recorded health
  state only refreshes on the next weather fetch, and the disabled path
  deliberately records nothing, so setting `one_call_version: "off"` left a
  permanent "check `one_call_version`" banner against a config that no longer
  calls One Call — and switching 3.0 → 4.0 left the banner naming 3.0. The
  status page now reconciles the record against the configured version. (#223)
- **A malformed custom quote store no longer breaks the render.** Panels index
  `["text"]` and `["author"]` directly, so a store containing `[{}]`, a bare
  string, or an entry missing either key raised out of whichever panel selected
  it — making a hand-edited quotes file the one config mistake that took down
  the whole dashboard. Unusable entries are now skipped with a warning, and a
  store with none left falls back to the bundled list. (#217)
- **`quotes.path` is actually editable on the config page.** The schema entry
  made it patchable through the API, but `get_config_for_web()` omitted the
  block and the hand-written form had no control, so the page never showed it
  and `GET /api/config/schema` reported a null value even when it was set.
  (#217)
- **The status page's TTL map derives from the fetcher registry.** #213 moved
  the source *names* to the registry but left the TTLs naming the four
  built-ins, so a newly registered fetcher was classified against an unrelated
  60-minute fallback — the status page could call a cache stale while the
  pipeline still considered it fresh. (#213)
- **The web event stream is safe against its second writer.** #218 made the
  renderer a writer of a file the web service also appends to, from a separate
  process, where the trim's read-all → rename window silently discarded the
  other process's appends and both used the same fixed `.tmp` path. Appends and
  trims are now serialised with an advisory lock, and the temp file is unique
  per trim. (#218)

### Changed

- **Two dead component parameters removed.** `draw_week` accepted a `forecast`
  argument it never read, and `draw_air_quality_full` accepted a `today` it
  threaded two levels down to a function that takes its day names from the
  forecast entries instead. Both were being fed by the component registry on
  every render. No rendered output changes. (#229)
- **The render tests now assert what they claim to.** The suites had settled on
  `assert img.getbbox() is not None`, which on a white 1-bit plate reports the
  bounds of non-zero pixels and so returns the full canvas whether or not
  anything was drawn — whole files passed with their draw function stubbed to a
  no-op. All 60 such assertions are gone, replaced by per-region ink
  measurements and differential comparisons, with the shared helpers in
  `tests/inkutils.py`. The weak-assertion count is down from 403 of 3238 tests
  to 73. (#229)
- **`_cache_is_recent` no longer guards on a callable default.** The check
  `fetcher.save_metadata is not None` was always true — `save_metadata`
  defaults to a function, not `None` — leaving the branch behind it
  unreachable, and incoherent besides: it fell through to an `interval_map`
  lookup that would have raised `KeyError` for the very sources it claimed to
  serve. Behaviour is unchanged. (#228)
- **The weatherglass pressure history goes through `atomic_write_json`.**
  `_save_pressure_sample` hand-rolled its own `mkstemp` + `os.replace` instead
  of the shared helper in `src/_io.py`, which is documented as the only
  sanctioned way to persist JSON state from the renderer. The helper re-raises
  where this call site must swallow, so the `try`/`except` stays local and the
  contract is unchanged: history bookkeeping never breaks a render. The
  rendered plate is byte-identical, so no snapshot baselines moved.
- **The four largest test-coverage gaps are closed.** Overall coverage was
  96%, but the misses were concentrated rather than diffuse:
  `weatherglass_panel` sat at 70% with 60% of every missed statement in the
  repo and was the only substantive module never referenced by name from a
  test — its rolling pressure history and every metric/standard unit branch
  had no protection at all. Also covered now: the deepest tier of the ICS
  recurrence-expansion fallback, and the event stream's cross-process `fcntl`
  lock, which had only ever been tested through the fallback taken when
  `fcntl` is absent. Three `week_view` tests that named a visual behaviour and
  then asserted only that the plate was non-blank now measure the thing they
  describe. Coverage is ~98%.

- **A lapsed One Call subscription is now visible.** A 401/403 from an
  unsubscribed One Call version was handled identically to a read timeout:
  one `DEBUG` line and no other trace. The degradation contract is unchanged —
  a One Call failure still never breaks a render — but the permanent case now
  logs at `WARNING` once on the healthy→failing transition and shows on the
  status page as a degraded row naming `weather.one_call_version`. This is the
  failure that arrives *after* a working install (subscription lapses, account
  migrated between products, key rotated), where alerts and UV silently stop
  appearing while everything else stays green. (#223)
- **Quote loading is one loader instead of four.** `src/render/quotes.py`
  replaces the copy of the path, the fallback list, and the bucket-hash
  selection that `info_panel`, `tides_panel`, `scorecard_panel`, and
  `moonphase_panel` each carried. Selection is unchanged — every panel keeps
  its own key prefix, and all theme pixel-snapshot hashes are identical. The
  one behaviour change is in the degraded path: the per-panel two-entry
  fallback lists are gone in favour of the single bundled one, reached only
  when the store is missing, malformed, or empty. (#217)
- **The web UI follows the fetcher registry.** The breaker/cache actions, the
  cache-age reads, and the status payload each named the four built-in sources
  inline, so a fetcher added per the documented recipe cached and rendered
  correctly while staying invisible in the UI and unresettable from it. All
  three now derive from the registry. `web/routes/actions.py`'s private
  `_atomic_write_json` copy is gone in favour of the shared `src/_io` helper.
  (#213)
- **The status page's integrations panel is CalDAV-aware.** A CalDAV-only
  install — the highest-precedence calendar backend — reported a missing
  Google service account and a Google calendar warning on an otherwise healthy
  dashboard. The panel now mirrors the dispatch precedence in `fetch_events`
  and names the backend actually in use. The service-account row survives on
  CalDAV when birthdays come from contacts, the one case that still reaches
  Google. (#214)
- **`theme` is an enum in the config schema**, so `GET /api/config/schema`
  serves the full list of theme names and the field renders as a dropdown
  rather than free text. Looked up lazily, so importing the schema still does
  not pull in PIL. (#216)
- **`make previews` is registry-driven.** It hardcoded 24 of the 36 concrete
  themes and spawned a full interpreter per theme; twelve themes had silently
  fallen out of the list. `scripts/build_previews.py` enumerates the registry
  and renders everything in one process against a pinned date. Adding a theme
  needs no Makefile edit. (#219)

- **Partial-refresh capability is now derived from the plate rather than
  declared per theme.** `Theme.allows_partial_refresh` works it out — a theme
  declines the fast waveform when it dithers (`preferred_quantization_mode` of
  `floyd_steinberg`/`ordered`, or a dithered `background_fn`) or its
  `ThemeStyle.bg` is ink, so the whole plate is one solid fill. Previously
  every theme hand-set a flag that defaulted to "partials are fine", which
  meant a new dithered theme that declared nothing failed open on hardware and
  was caught only by a CI test. Now it gets the right answer from the code.
  `ThemeLayout.supports_partial_refresh` defaults to `None` and remains as the
  override for the three themes that overrule the derivation on purpose
  (`fuzzyclock_invert`, `moonphase`, `moonphase_photo`); a declaration that
  merely agrees with the derivation is now rejected by the test suite, so the
  only flags left in the tree are real decisions. No change to which themes
  take a full refresh, and no pixel change. (#222)

### Added

- **One Call 4.0 support for weather alerts and the UV index**, selected by the
  new `weather.one_call_version` setting (`"3.0"` default / `"4.0"` / `"off"`).
  OpenWeather sells One Call 3.0 and 4.0 as separate products and an account can
  hold only one subscription, so calling the version you are not subscribed to
  401s exactly like having none — which the dashboard could not previously work
  around. Current conditions and the forecast are unaffected; they stay on the
  free `/data/2.5/` endpoints. `"off"` skips the request entirely for users with
  no One Call subscription, who were paying a guaranteed-401 round trip on every
  fetch. On 4.0 a quiet day costs the same single request as 3.0; active alerts
  cost one extra lookup each (capped at three) because 4.0 reports alerts as
  bare IDs. The setting is editable from the web UI's config page. See
  [Weather API tiers](docs/configuration.md#weather-api-tiers).

- **`halftone_agenda` encodes event state again.** Elapsed rows are perforated
  on a Bayer lattice, the event in progress inverts into a solid bar, the next
  one up carries an accented tick, and a rolled-over agenda sits behind an
  inverted `TOMORROW` chip. All four were dropped to buy partial-refresh
  compatibility the plate never had; they come back now that the theme takes
  the full waveform every time. On Inky the accent is red, which puts colour
  back on the calendar side of the plate. State is the only thing in the pane
  reading the clock, and only at event boundaries, so a tick that crosses none
  still renders identically and writes nothing to the panel. (#222)

### Changed

- **The Google API client stack is no longer imported on every tick.**
  `calendar_google` pulled googleapiclient + friends at module top, and every
  run reaches that module through the fetcher registry — including ICS-only,
  CalDAV-only, and `--dummy` runs, and the web server via `state_reader`.
  That import costs 1–2 s on a Pi. The imports are now deferred into
  `_build_service`, so only runs that actually talk to the Google API pay
  for them; a subprocess guard test fences the boundary. (#211)

### Fixed

- **`halftone_agenda` no longer fades in bands under partial refresh.** The
  theme's plate is dithered ink, and Waveshare's fast waveform does not drive
  black deeply enough to hold it: every partial update lightened the engraving
  and everything sharing its rows, including the agenda beside it. Lowering
  `display.max_partials_before_full` only shortened the drift. Themes now
  declare whether their plate survives a partial refresh
  (`ThemeLayout.supports_partial_refresh`), and `OutputService.publish` uses
  the full waveform for those that say no, whatever
  `display.enable_partial_refresh` is set to. Eleven themes opt out — the ones
  that dither (`day_arc`, the `halftone` pair, `naturalist`, `photo`,
  `postcard`, `trends`) and the ones whose canvas ground is solid ink
  (`constellation_map`, `fantasy`, `qotd_invert`, `terminal`). What counts is
  the dither and not the greyscale: `moonphase_invert` and `weatherglass`
  render on an `"L"` canvas but quantize with `threshold`, a hard cut that
  diffuses nothing, and are lighter than `default` — they keep the fast path.
  So do `fuzzyclock_invert`, `moonphase` and `moonphase_photo`, which are solid
  plates that keep it deliberately: the clock face because declining would
  flash the panel every five minutes, and the moon pair because no fade shows
  on real hardware — an evenly greying black ground has nothing to read the
  drift against, and the flash is most intrusive on a theme left up at night.
  Each reason is recorded at the theme and pinned by a guard test.
  `make check` names the configured themes that opt out, so the setting never
  quietly means less than it says. (#222)

- **One malformed VEVENT no longer disables ICS recurrence expansion for the
  whole feed.** `recurring_ical_events` raises on a VEVENT with no `DTSTART`
  and on an unparseable `RRULE`; the expander caught that and fell back to the
  raw walk for the *entire* calendar, so a single bad component silently
  reverted every recurring series in the feed to first-week-only — reinstating
  the bug the expansion was added to fix. DTSTART-less VEVENTs are now pruned
  before expansion (`_parse_ical_event` already skipped them), and a failure
  that still escapes retries event by event, so a bad `RRULE` costs only its
  own series and that series survives unexpanded rather than vanishing.
- **An unbounded ICS recurrence rule can no longer swamp the fetch.** A
  `FREQ=MINUTELY` series with no COUNT/UNTIL (broken exporter or hostile feed)
  expands to five figures inside a one-week window, and every occurrence was
  then parsed, written to the cache, sorted, and handed to a renderer sized
  for a normal week. Occurrences are now capped per series at 500 with a
  warning naming the UID. The cap is per series rather than per feed because
  `between()` groups occurrences by series instead of sorting them — a flat
  cap would keep the whole runaway series and drop the real events behind it.
  A dense but legitimate `FREQ=HOURLY` series (168 a week) is unaffected.
- **Floating-time ICS events at the start of the window are no longer
  dropped.** `between()` resolves a floating `DTSTART` (no `TZID`, no `Z`)
  against UTC while the caller's filter resolves it against the configured
  zone, so a western-zone install lost short floating events in the first
  `|utcoffset|` hours of day one — everything before 07:00 on
  `America/Los_Angeles`, before 04:00 on `America/New_York` — which the raw
  walk used to keep. The expansion span is padded a day either side; the
  caller's per-event filter still decides what is in window.
- **Weather alerts and UV work again.** The alerts/UV fetch still called
  OpenWeatherMap's One Call **2.5** endpoint, which OWM retired in mid-2024 —
  and because the helper is best-effort, every run silently returned no
  alerts and no UV. The `weather_alert_present` theme rule could never fire,
  the weather theme's alert banner never showed, and weatherglass's UV bar
  stayed empty. The fetch now targets One Call 3.0; keys without that
  subscription degrade exactly as before. Note that OpenWeather has since
  released One Call 4.0 as a separate product on its own endpoint, and an
  account cannot hold both subscriptions — a 4.0 subscriber calling the 3.0
  endpoint gets the same 401 as an unsubscribed key, so alerts and UV need a
  One Call *3.0* subscription specifically. 3.0 remains live; 4.0 support is
  not implemented. See "Weather API tiers" in docs/configuration.md. (#202)
- **Calendar fetch windows are built in the configured timezone.** All four
  window builders (Google API, ICS, CalDAV, birthday-calendar) combined the
  local window date with a *naive* midnight and let `astimezone()` interpret
  it in the **host machine's** timezone. On the default Pi setup (system tz
  UTC, `timezone:` local) the 7-day window shifted by the UTC offset and
  events at the end of the displayed week were silently dropped; the CalDAV
  variant stamped local midnight as UTC outright and has no client-side
  filter to mask it. Boundaries now go through the new
  `src._time.day_start_utc(day, tz)` helper, which anchors midnight in the
  configured zone (host zone only when no timezone is configured, matching
  how `today` is derived in that case).

  Note for CalDAV users with **no** `timezone:` configured: this is a
  behaviour change, not only a fix. That path previously stamped the window
  date as UTC midnight outright, and it now resolves to host-zone midnight —
  so the window moves by the host's UTC offset. This matches how `today` is
  derived on that path (`date.today()`, host clock), which is what makes the
  pair consistent, but a tz-unconfigured CalDAV install will see its week
  boundary shift once on upgrade. Setting `timezone:` explicitly pins it.
  (#203)
- **A Feb-29 birthday no longer crashes the contacts source for the whole
  year.** `date(today.year, 2, 29)` raised `ValueError` in non-leap years,
  `retry_fetch` classified it as permanent, and once the cache expired the
  birthday panel stayed blank with the breaker open. Both the contacts and
  file parsers now roll Feb 29 → Feb 28 in non-leap years (the convention
  `birthday_bar.py` already renders with), and one malformed contact is
  logged and skipped instead of aborting the whole fetch. (#204)
- **Google incremental sync actually activates now.** The Calendar API omits
  `nextSyncToken` from responses when `orderBy` is set, so `_fetch_full`'s
  `orderBy="startTime"` meant the token was always `None` and every run was
  a full re-download — the entire incremental-sync machinery was dead code.
  The parameter is gone; events were already sorted client-side. (#205)
- **Negative PurpleAir readings no longer display as AQI 500 "Hazardous".**
  Sensors report small negative PM2.5 values in clean air (baseline drift);
  those matched no EPA breakpoint bracket and fell through to the ≥500.4
  clamp. Readings are clamped to 0 before lookup. (#206)
- **A failed display write no longer pins the panel on stale content.** The
  image hash was persisted as a side effect of the *comparison*, before the
  hardware write ran — one transient SPI/eInk error and the next run saw
  "image unchanged" and skipped the retry until the content itself changed.
  `image_changed()` is now a pure comparison and the hash is recorded via
  `persist_image_hash()` only after `show()` succeeds. (#207)
- **A legacy naive refresh-throttle timestamp no longer wedges publishing.**
  v4's `inky_refresh_state.json` was written with naive `utcnow()`
  timestamps and migrated bit-for-bit; subtracting one from the aware `now`
  raised `TypeError` on every publish until the state file was deleted by
  hand. The reader now applies the repo-wide "naive ISO timestamps are UTC"
  convention. (#208)
- **Registry-added fetchers honour their skip decisions.** The pipeline
  computed cache/interval/breaker decisions for every registered fetcher but
  only forwarded the four built-ins' to the launch step — anything added via
  the documented "New fetcher" recipe was fetched on every 5-minute run
  regardless of its configured interval, and its breaker never actually
  paused it. (#209)
- **Daily random theme rotates at configured-timezone midnight.** The daily
  pick fell back to the system clock's `date.today()`, so the "new theme
  after midnight" flip landed at host-tz midnight and `--dry-run --date`
  previews ignored the date override for the daily variant (the hourly
  variant already honoured it). (#210)
- **An idle tick no longer redraws the panel.** Every "updated" caption was
  rendered from the run's own clock, so the image differed on every tick even
  when nothing had been fetched — around 12 hardware writes an hour on the
  default 5-minute timer, each one repainting a few hundred pixels. With
  partial refresh enabled those all go through Waveshare's fast waveform,
  which is what makes static ink drift grey between full refreshes.
  `DashboardData` now carries `content_at` — the newest timestamp among the
  sources actually backing the snapshot — and captions draw that instead, so
  an idle tick produces a byte-identical image and no write at all. Affects
  the shared header (every week-view theme) plus `halftone` and
  `halftone_agenda`: 22 of 34 themes are now silent on an idle tick, up from
  12. `diags` is deliberately not among them — it reports live host telemetry
  that moves every run, so it redraws regardless and keeps its render-clock
  stamp.
- The captions were also wrong: `updated 12:45 pm` over weather fetched at
  12:20 reported when the pixels were painted, not when the data arrived.
- **"Restore latest backup" no longer rolls the config back two or more
  edits.** The web UI's backup list sorted filenames in reverse lexicographic
  order, and `config.yaml.bak.<timestamp>` sorts after the shorter
  `config.yaml.bak` — so a rotated archive outranked the plain backup that is
  actually the snapshot from the immediately preceding save. After saves
  A → B → C, restoring "the latest" gave you A. The plain `.bak` now always
  ranks first and rotated archives follow by modification time, so the list
  shown on the config page is genuinely newest-first too.
- Pre-migration backups (`config.yaml.bak-v4`) match the same glob and were
  offered as restorable config backups, which would have rolled the file back
  to an older schema. They are no longer listed.
- Backup rotation carried only second precision, so two saves inside the same
  second rotated onto the same filename and the second one silently discarded
  an archive. Rotated names now carry microseconds.

### Added

- **ICS feeds expand recurring events.** The ICS path walked raw VEVENTs, so
  a weekly standup exported from Google/Outlook appeared only in the week of
  its original `DTSTART` and never again — while the CalDAV backend expanded
  server-side, so the two backends disagreed on the same calendar. RRULE /
  RDATE / EXDATE / RECURRENCE-ID are now expanded per-occurrence inside the
  fetch window via the new `recurring-ical-events` core dependency, with a
  graceful raw-walk fallback (plus warning) when the package is missing.
  (#212)
- **`halftone_agenda`'s weather band reads larger.** The temperature numeral
  goes 64 → 78 pt with the condition and high/low sized to match (16 → 19 and
  18 → 21). The column reservation was over-sized for the numeral it held, so
  most of this came free; 78 pt is the ceiling at which the widest OWM phrase
  still wraps to two lines.
- A condition too long for two lines now ellipsizes instead of dropping its
  tail, so `thunderstorm with light drizzle` no longer renders as a
  complete-looking `THUNDERSTORM WITH LIGHT`.

- **`halftone_agenda` rows show event end times**, stacked under the start
  (`12:30p –` / `2p`). Stacking keeps the treatment uniform: an inline range's
  width depends on the times themselves, so at one density some rows would
  show an end time and their neighbours wouldn't. The stacked cell is never
  wider than a single label, so the time columns stay narrow and the question
  is only vertical — every tier but the densest has room, and that one shows
  the start alone, as do all-day events and any event running past midnight.

### Changed

- **`halftone_agenda`'s agenda pane no longer encodes event state.** The
  inverted "now" bar, the Bayer-screened elapsed rows and the next-up accent
  tick are gone; every row is set identically and the `TOMORROW` chip is plain
  type. Each of those treatments needed a large or dithered area of ink to
  survive the panel, and none of them does under partial refresh, where
  Waveshare's fast waveform leaves a filled bar reading as charcoal rather
  than ink. The pane is the day's list, and row rendering is now a pure
  function of the event rather than of the clock.

### Fixed

- **`config.example.yaml` no longer ships partial refresh enabled.** It set
  `enable_partial_refresh: true`, contradicting both the code default and
  `docs/configuration.md`, so anyone starting from the template drove the
  panel with Waveshare's fast waveform on 19 of every 20 refreshes. That
  waveform does not drive black as deeply as a full init, which reads as grey
  blacks in large filled areas — an inverted event row, a header bar. Added an
  FAQ entry for the symptom and a note at the driver branch that reaches it.

- **`halftone_agenda`'s calendar side now carries the same weight of ink as
  its weather side.** Both panes are pure black on pure white by the time the
  panel sees them, so the calendar reading grey was stroke mass, not tone: at
  22 px Righteous sets ~4.4 px stems while DM Sans SemiBold sets ~3.7 px. The
  agenda now runs one weight heavier than the role each element fills — bold
  titles, semibold times, medium locations and footer — and the theme's bold
  role points at DM Sans Bold instead of Righteous, which was only ever
  reached as a fallback.

- **`halftone_agenda` agenda pane reads better on a panel.** Rows are
  top-justified under the rule at a pitch sized to their type, instead of a
  stretch-to-fill pitch that left a two-event day floating mid-pane; the
  elapsed-row Bayer cut now rises as the type shrinks (a single cut left the
  17 px type of a packed day as a row of dots); and `+N more` is drawn in
  plain ink rather than screened, since it sits alone under the last row and
  is the one mark saying the day continues past what is shown.

- **`halftone_agenda` type is no longer chewed by the dither.** PIL antialiases
  TrueType glyphs on an `"L"` canvas, and the theme's Floyd-Steinberg pass then
  diffused that edge error across glyph boundaries — stems came off the panel
  serrated and doubled letters lost notches. The two typeset regions are now
  snapped to pure ink or paper (`skyart.harden_typeset`) before the backend
  quantizes, which is the same footing a `"1"`-mode theme starts from, while
  the illustration is left to dither as before.

### Added

- **`halftone_agenda` theme** — a split-plate variant of `halftone` following
  the layout sketch: the procedural weather engraving and the weather
  read-out take the left 372 px, a full-height ordered-Bayer rule divides the
  plate, and the right 422 px are given entirely to today's events. The
  agenda reuses `day_arc`'s state dithering (elapsed events Bayer-screened,
  the event in progress inverted, upcoming ones crisp), marks the next timed
  event still ahead with an accent tick, and rolls over to tomorrow after
  dark once the day is spent. Pure-Python — no external assets. Joins
  `day_arc` in `THEMES_NEEDING_TOMORROW` so the rolled-over agenda has
  Monday's events on a Sunday evening.
- `skyart.draw_weather_scene()` — the icon→illustration dispatch lifted out
  of `halftone_panel` so both halftone themes compose the same scene.
  Placements map onto whatever rect is handed in and element sizes come from
  a `scale` argument, so the composition survives a half-width plate; the
  nominal rect at `scale=1.0` reproduces halftone's placement pixel for
  pixel, and its snapshot hash is unchanged.
- `skyart.draw_bayer_rule(..., orientation="vertical")` — side hairlines for
  a vertical rule, used by `halftone_agenda`'s pane divider. The horizontal
  default is byte-identical to the previous behaviour.
- **`day_arc` theme** — a calendar-forward sibling of `halftone`. A dithered
  ribbon draws today as a left-to-right arc keyed to the real sunrise and
  sunset, with the sun (or the moon at its true phase, after dark) riding at
  the current time's actual position and weather art around it; the ribbon's
  baseline is a time axis with hour ticks, a NOW caret and one pip per event.
  Below it the day's agenda takes the bulk of the plate, with dithering used
  as an encoding rather than decoration — elapsed events are Bayer-screened,
  the event in progress is inverted, upcoming ones are crisp. Dims after
  sunset and rolls the agenda over to tomorrow once the day is spent.
- `src/render/skyart.py` — the procedural sky-illustration vocabulary
  (gradients, sun, phase-shaded moon, clouds, precipitation, lightning, fog,
  ordered-Bayer rule and Bayer screening) extracted from `halftone_panel` so
  `day_arc` can share it rather than duplicating ~430 lines. Pixel output of
  `halftone` is unchanged.
- `.github/PULL_REQUEST_TEMPLATE.md` — seeds new PRs with the contribution
  checklist, including the conditional steps that are easy to miss (pixel-hash
  baselines, preview regeneration, `mypy`, changelog entry).
- `artkit.to_local_naive()` / `artkit.hours_of_day()` — the naive/aware
  datetime normalisers promoted out of `light_cycle_panel` for reuse by any
  panel plotting a time axis.

- **`GET /api/health`** web endpoint — uptime-monitor probe returning
  HTTP 200 when the last renderer run succeeded and 503 otherwise, with
  an optional `?max_age=<seconds>` freshness requirement that is skipped
  during quiet hours. Points cleanly at Uptime Kuma / healthchecks.io.
- **Patch-preview** — `POST /api/preview` accepts an optional `patch`
  dict (same shape as `POST /api/config`) and renders against a
  candidate config without persisting anything; the config page gained a
  **Live preview** button that sends the current unsaved form values.
- **Theme-rules editor** — `theme_rules` is now editable from the web UI
  as a validated YAML textarea (Advanced mode), wired into save,
  dirty-tracking, the change summary, and Live preview.
- `src/render/artkit.py` — shared mode-aware colour + season helpers for
  the procedural art themes (previously copy-pasted per panel).

### Changed

- `make docs-check` now runs in the `lint` CI job. It previously existed but
  nothing enforced it, so the "all concrete themes" preview batch loop in
  `docs/previews.md` silently drifted — `day_arc` and `moonphase_photo` were
  both missing from it. `scripts/check_docs.py` now validates that list
  against the theme registry as well, and both themes were added.
- `CONTRIBUTING.md` coverage figures corrected — the gate has been 94% (with
  actual ≈96%) since it was ratcheted; the doc still claimed ≥90% and ~99%.
- `to_local_naive` no longer consults the host machine's timezone when no
  timezone is supplied, so a render of identical inputs is reproducible
  across machines (the theme pixel snapshots hash that render).
- Python floor raised to **3.10** (3.9 is EOL; mypy can no longer check
  a 3.9 target). CI matrix is now 3.10 / 3.11 / 3.13.
- mypy now checks **every** module: the `ignore_errors` blanket covering
  all 29 render components was removed via root-cause typing fixes
  (non-Optional core fonts on `ThemeStyle`, widened `Fill`/coordinate
  types in `primitives.py`/`icons.py`). Pixel output is unchanged.
- Deprecated Pillow `getdata()` (removal scheduled for Pillow 14)
  replaced with a `tobytes()`-based `flatten_pixels()` helper; Pillow
  deprecation warnings now fail the test suite immediately.
- Coverage gate raised from 90% to 94% (actual ≈ 96%).
- `validate_config` and friends moved to `src/config_validation.py`
  (re-exported from `src.config`, so imports keep working).
- `requirements*.txt` are now guarded against drift from
  `pyproject.toml` by a test.

## [5.1.0] - 2026-06-09

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

## [5.0.0] - 2026-05-01 — Pluggable & Polished

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

## [4.2]

### (Version bump only — never released separately; see 4.2.1)

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
