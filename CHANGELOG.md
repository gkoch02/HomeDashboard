# Changelog

All notable changes to Home Dashboard are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **ICS feeds expand recurring events.** The ICS path walked raw VEVENTs, so
  a weekly standup exported from Google/Outlook appeared only in the week of
  its original `DTSTART` and never again — while the CalDAV backend expanded
  server-side, so the two backends disagreed on the same calendar. RRULE /
  RDATE / EXDATE / RECURRENCE-ID are now expanded per-occurrence inside the
  fetch window via the new `recurring-ical-events` core dependency, with a
  graceful raw-walk fallback (plus warning) when the package is missing.
  (#212)

### Changed

- **The Google API client stack is no longer imported on every tick.**
  `calendar_google` pulled googleapiclient + friends at module top, and every
  run reaches that module through the fetcher registry — including ICS-only,
  CalDAV-only, and `--dummy` runs, and the web server via `state_reader`.
  That import costs 1–2 s on a Pi. The imports are now deferred into
  `_build_service`, so only runs that actually talk to the Google API pay
  for them; a subprocess guard test fences the boundary. (#211)

### Fixed

- **Weather alerts and UV work again.** The alerts/UV fetch still called
  OpenWeatherMap's One Call **2.5** endpoint, which OWM retired in mid-2024 —
  and because the helper is best-effort, every run silently returned no
  alerts and no UV. The `weather_alert_present` theme rule could never fire,
  the weather theme's alert banner never showed, and weatherglass's UV bar
  stayed empty. The fetch now targets One Call 3.0; keys without the (free
  opt-in) "One Call by Call" subscription degrade exactly as before. (#202)
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
  how `today` is derived in that case). (#203)
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
