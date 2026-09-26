# Changelog

All notable changes to Home Dashboard are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **`wide_horizon` theme** — the next 72 hours on one time axis at 1360 × 480,
  the first plate built around what the panoramic strip can do and an 800 × 480
  panel cannot. A sky coloured by the sun's real altitude at every column
  (paper by day, twilights, night with stars and a phase-correct moon, a sun
  at each solar noon), clouds, rain, snow, lightning and fog drawn per
  forecast slot, the temperature as one cased line with each day's turning
  points labelled, rain chance hanging beneath, and the calendar's all-day
  events, birthdays and timed events as bars on the same hours. A hero block
  carries the conditions now and a three-line outlook (warmest, coldest,
  first rain). On a colour panel the twilights are ordered dithers between
  pairs of inks, so the four-ink panel shows pale yellow, orange and maroon;
  every pixel is already an exact ink, so the panel's final snap is the
  identity. Waking hours get more of the axis than the night. The window
  starts at the current 3-hour forecast slot, so the clock moves the plate at
  most eight times a day.
- **Hourly forecast data** — `WeatherData.hourly`, a list of
  `HourlyForecast(time, temp, icon, precip_chance, precip_mm)`: the OWM
  5-day / 3-hour grid the weather fetcher already downloads, kept at its own
  resolution instead of only collapsed to daily rows. Cached with the rest of
  the weather; an older cache entry loads with an empty list. Dummy data
  carries a realistic 40-slot grid.
- `astronomy.solar_altitude(dt, lat, lon)` — the sun's altitude at an instant.
- **Big Shoulders Display** (OFL) — SemiBold, ExtraBold and Black cuts, via
  `fonts.big_shoulders_semibold/extrabold/black`.

## [6.0.0] - 2026-09-26

A major release: **Waveshare 10.85" (G) support** — the project's first
four-ink panel and first non-800 × 480 shape — with `display.scaling` and four
panoramic 1360 × 480 themes (`wide_week`, `wide_day`, `wide_forecast`,
`halftone_agenda_wide`) built for it. Existing `config.yaml` files load
unchanged. A few smaller surfaces were removed (`display.week_days`, split
previews, five unlicensed fonts); see **Removed**.

### Added

- **Waveshare 10.85" e-Paper (G) support** — `display.model: epd10in85g`, a
  1360 × 480 strip with four inks (black, white, yellow, red). The new
  `WaveshareColorBackend` renders themes in colour the way the Inky path does,
  folds the two Spectra 6 inks the panel lacks (blue, green) onto black, and
  snaps the final image to the panel's four inks by nearest colour so the
  driver's own palette mapping is exact; greyscale art themes keep their
  dither. Colour models never take the fast waveform (`enable_partial_refresh`
  is ignored, with a config warning). `DisplaySpec` gains `palette` and
  `is_color`; `canvas.py` decides colour by the display spec rather than by
  `provider == "inky"`.
- **`display.scaling`** — `auto` (default) / `stretch` / `fit`. Until now every
  off-size panel got the 800 × 480 canvas stretched, which on a 1360 × 480 strip
  pulls a week grid 1.7× wide. `fit` keeps the canvas shape and pads with the
  theme's background; `auto` stretches unless the distortion would exceed a
  third, so 4:3 panels render exactly as before and the strip fits. Web-editable.
- **Three panoramic themes** for the strip, each with a native 1360 × 480 canvas:
  `wide_week` (the standard dashboard reflowed — 128-px week columns and a
  full-height rail of weather, birthdays and quote), `wide_day` (today as a
  timeline across the plate, events as lanes of bars with their labels packed
  alongside, a NOW marker, an up-next rail that reaches into tomorrow) and
  `wide_forecast` (hero conditions, five forecast cards with precipitation
  bars, and a band for alerts, air quality and the moon). On an 800 × 480 panel
  they letterbox. `scripts/build_previews.py` renders every theme at its own
  canvas size and takes `--model` / `--suffix` for a four-ink preview set.
- **Art regions dither in colour.** A panel that draws artwork can declare the
  rectangle it occupies (`RenderContext.dither_regions`, filled by the
  adapter from the panel's pure `art_rect()`), and the colour backends
  error-diffuse those rectangles onto the panel's inks instead of snapping
  them. Until now a colour panel flattened the halftone family's sky ramp to a
  single ink (nearest colour) while the monochrome path kept its engraving;
  now the gradient is a halftone of the inks on both, and a tone the panel
  has no ink for — orange over yellow and red — becomes a mixture rather than
  whichever ink is nearest. Type and rules outside the regions stay solid.
  Registered for `halftone`, `halftone_agenda`, `halftone_agenda_wide` and
  `day_arc`; the four Inky previews are regenerated. Neutral pixels diffuse
  against black and white only, and the Spectra-6 accents the art helpers
  draw with are remapped onto the G inks before diffusion, so a solid sun
  stays solid and a night sky stays free of coloured speckle.
- **Random rotation respects the panel's shape.** A theme whose canvas would
  be fitted with padding on the configured panel — the 1360 × 480 themes on an
  800 × 480 panel, and the reverse — is left out of the `random_daily` /
  `random_hourly` pool. The default refresh cooldown is now keyed on the
  display spec rather than the provider, so the four-ink Waveshare model gets
  the 60 s Inky has for the same reason. Applies on the 10.85" G
  panel and on Inky (where the diffusion targets the measured Spectra 6
  values so the driver's own mapping is the identity on them).
- **`halftone_agenda_wide`** — the split-plate agenda drawn for the 1360 × 480
  strip. The engraving and weather band at the left, today's agenda at half
  again its usual width in the middle (the original's `_draw_agenda_pane`,
  every treatment intact), and a rail for what the 800 × 480 plate leaves out:
  alerts, the next day's events, the forecast, birthdays, air quality and the
  moon. The theme fetches two days past the week (`EXTRA_EVENT_DAYS` in
  `src/app.py`, which now generalises `THEMES_NEEDING_TOMORROW`) because the
  rail shows the day after tomorrow once the agenda has rolled over. The
  agenda pane spends its width on data: a header dateline with the day's
  totals, a schedule strip with a block per event, a duration column,
  `— Nh Nm free` markers between events, and condensed Antonio time cells so
  titles get the room. It deliberately drops the original's state treatments
  (perforated past rows, the inverted running event, the next-up accent):
  each one repaints the panel at an event boundary, and on the four-ink
  panel a repaint is a twenty-second flash. The after-dark rollover is the
  one clock-driven change left.

- **Licence texts for the nine families that were bundled without one.**
  Playfair Display, Plus Jakarta Sans, DM Sans, Cinzel, Share Tech Mono, Space
  Grotesk and Weather Icons had shipped with no `OFL.txt` — 20 of 29 font files
  were uncovered. All are OFL-licensed upstream, so this was a compliance
  failure rather than a licensing one: OFL 1.1 §2 requires the licence text to
  accompany the font, so every clone and every `make deploy` rsync was shipping
  them out of compliance. Every font in `fonts/` now has its licence beside it.
- **`tests/test_font_licenses.py`** enforces that going forward, in both
  directions: every bundled font must have a sibling licence file containing the
  OFL text, *and* must assert terms in its own `name` table. The second check is
  what distinguishes a font whose licence someone documented from a font that
  actually carries one.
- **A `Third-party content` section in `LICENSE`**, recording what the MIT grant
  does not reach: the bundled typefaces and their licence files, the provenance
  of `assets/moon_full.png` (an original photograph by the copyright holder) and
  the generated images, the quotation collection in `config/quotes.json` (whose
  selection and arrangement are MIT but whose underlying quotations are not the
  copyright holder's to license), and the two non-permissive runtime
  dependencies — `recurring-ical-events` (LGPL-3.0-or-later) and `caldav`
  (GPL-3.0-or-later **or** Apache-2.0, relied on under Apache-2.0). A `License`
  section in `README.md` points at it.
- **PEP 639 packaging metadata.** `pyproject.toml` declares
  `license = "MIT"` as an SPDX expression plus
  `license-files = ["LICENSE", "fonts/*OFL*.txt"]`, so a built wheel carries
  `License-Expression: MIT` and all eighteen bundled font licences in its
  `dist-info`. The build requirement moves to `setuptools>=77`, below which the
  string form is not understood and the OFL texts would silently not ship.

### Changed

- **`halftone_agenda_wide` uses its two accents on the agenda and dateline.**
  On a colour panel a timed event's tick is yellow and an all-day event's red
  (on mono the all-day tick stays outlined), the weather band's date is red and
  the "updated" stamp yellow. The colours key on the kind of event, never the
  clock, so the plate still repaints only when the data moves. The air-and-moon
  foot grows from 52 to 72 px with its type scaled up, taken from the birthdays
  cell, which now shows up to five rows in whatever room is left.
- **Config validation warns** about non-positive cache TTLs and air-quality
  fetch interval, `max_failures` below 1, a negative breaker cooldown,
  `max_partials_before_full` below 1 with partial refresh on, coordinates off
  the globe, and an explicit `display.width`/`height` that disagrees with the
  model. Warnings, not errors, so an upgrade cannot stop a running panel (#306).
- **The web editor covers more of the config.** Log level offers every name
  `logging` accepts (`CRITICAL`, `FATAL`, `WARN` included); quantization mode,
  the photo path, the birthdays file, additional Google calendars, the daily
  request warning and the refresh cooldown are editable; provider and model
  are shown read-only (#307).
- **`google.caldav_url` and `caldav_calendar_url` are treated as secrets** by the
  web layer: such URLs often embed credentials, so the browser gets only a
  set/unset flag and `POST /api/config` no longer edits them — change them in
  `config.yaml`, like the private ICS URL.
- **`make configure` asks which calendar source you use** — ICS, CalDAV or the
  Google API — writes that source's settings, switches off a
  higher-precedence one left from an earlier answer, and points at
  `docs/setup.md`. It now checks for the venv it runs (#302).
- **The shipped template carries `schema_version: 5`**, and the in-memory
  v4→v5 stamp logs at DEBUG, not INFO on every load (#304).
- **ruff is pinned** to one version in `[dev]` and the pre-commit hook, with a
  test that they agree (#303).

- **`halftone_agenda` sets whole-hour time ranges on one line.** A row whose
  event starts and ends on the hour now reads `10a–12p` beside its title
  instead of `10a –` over `12p`. Only a pair that needs minutes on either end
  still stacks, because an inline `11:30a–1:15p` would not fit the column its
  neighbours use. The inline form uses a tight en dash: the widest real
  whole-hour pair, `10a–10p`, fits every density tier's column that way, and
  the spaced dash overran the three roomiest. The densest tier, which drops a
  stacked pair's end time for want of a second line, keeps it for a whole-hour
  pair.
- **Event locations show their first line only.** Google Calendar stores a
  place as the business name, a newline, then the street and city separated
  by commas. The `today`, week-view, `day_arc` and `halftone_agenda` rows cut
  at the first comma but folded the newline into a space, so a gym booking
  read `Ultimate Condition Fitness 535 W H…` — the name and the street run
  together and ellipsized mid-street. The cut is now at whichever comes first,
  the first line or its first comma segment, via one shared
  `primitives.location_line()`, so the row reads `Ultimate Condition Fitness`
  (or the street, when that is the first line).
- **The theme catalog is monochrome again, with a separate color page.**
  `docs/themes.md` embedded one composite image per theme, cut diagonally
  between the Waveshare and Inky renders. That asked the reader to mentally
  un-shear two half-renders in order to compare them, and neither backend was
  ever shown whole — the monochrome render most people actually run was only
  ever visible as a triangle. Every preview on that page is now the plain
  Waveshare 1-bit render, and the Inky Spectra 6 catalog moved to a new
  [Inky Previews](docs/inky-previews.md) page, cross-linked from the themes
  page, the README and `docs/previews.md`. The color page also documents how
  color is assigned — the four semantic accent roles, and each theme's
  registered `(primary, secondary)` accent pair.
- `make docs-check` now holds `docs/inky-previews.md` to the theme registry the
  same way it already held `docs/themes.md`: a theme with no entry, or an entry
  with no `_inky.png` embed, fails the check. Both pages share one heading
  convention (`###` for groups, `#### <theme>` for entries).

- **The `terminal`, `sunrise` and `tides` themes are re-set in OFL faces.**
  `terminal` now uses **Oxanium** for its title, day column headers and quote
  body, **Rajdhani** for the month band, section labels and quote attribution,
  and **Orbitron Black** for the hero date numeral; `sunrise` and `tides` use
  **Antonio** for their titles and section labels. The three-role split of the
  original is preserved, and each face is bundled with its OFL text.

  The date numeral is a visible improvement rather than a like-for-like swap:
  Synthetic Genesis is a constructed-alphabet display face whose digits are not
  legible as digits — its `6` renders as a bar, a diamond and a block — so
  `terminal` had never actually shown a readable day of the month. Oxanium was
  chosen over Orbitron for the body roles because Orbitron's width forces a
  dense quote down to an unreadable size; Orbitron is kept for the one hero
  element where width is an asset.

  Consequence worth knowing: Rajdhani is semi-condensed, so no real month name
  now overflows the `terminal` month band (SEPTEMBER measures 157px against a
  228px cell) and its shrink loop no longer fires in production. The loop is
  still live code and still tested — `tests/test_week_view.py` drives it through
  a narrowed region and separately asserts that all twelve names fit.

- **The README banner is re-set in the same replacement faces.**
  `scripts/build_banner.py` loads its fonts by filename rather than through
  `src/render/fonts.py`, so it held the only two remaining references to the
  removed files and `make banner` would have failed at `ImageFont.truetype`.
  The wordmark moves to **Oxanium Bold** and the temperature numeral to
  **Antonio Bold**, and `assets/banner.png` is regenerated. Two details fell
  out of the swap: the helper now pins a weight for variable faces (Oxanium's
  default instance is ExtraLight, which dithers to hairlines at 1-bit), and the
  temperature is set as a real `72°` — the drawn ring it replaces was a
  workaround for the old face having no degree glyph, not the design echo of
  `weather_panel.py` its comment claimed. The wordmark is set at 100pt rather
  than 130: Oxanium is the wider face, and 100pt is the largest size at which
  "HOME DASHBOARD" still fits the 928px wordmark zone, which cost the wordmark
  column ~56px of height it cannot get back. Top-aligned that left 131px of dead
  space beneath it against the motif column's 53, reading as a layout fault
  rather than a short column, so the column is dropped by `WORDMARK_DROP` (34px)
  to share the motif column's optical centre — measured from the two columns'
  ink extents rather than chosen by eye.

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

### Removed

- **`display.week_days`.** It was parsed and web-editable but nothing read it;
  every week layout is a fixed seven-column grid. A config that still sets it
  loads without complaint (#305).
- **`astronomy.dark_sky_window()`**, which had no callers and returned an
  inverted window (#294).
- **`docs/improvement-plan.md`**, a dated snapshot linked from nowhere (#300).

- **Combined split previews.** `scripts/build_split_previews.py`, the
  `make previews-split` target, and the 37 `assets/previews/theme_*_split.png`
  images are gone, superseded by the two independent preview sets above. The
  script's `_THEME_SPLIT_MODES` orientation table went with it; it referenced
  an `_INKY_THEME_KEY_COLORS` constant that no longer existed in
  `src/render/canvas.py`.
- **Five bundled display faces that carried no licence at all.**
  `Maratype.otf`, `NuCore.otf`, `NuCore Condensed.otf`, `Synthetic Genesis.otf`
  and `UESC Display.otf` shipped in `fonts/` with no accompanying licence file
  and — the part that settles it — no copyright string, no licence description
  and no licence URL in their own `name` tables. Each carried only a designer
  link to a portfolio site. The project's MIT grant purports to let anyone
  "use, copy, modify, merge, publish, distribute, sublicense, and/or sell"
  everything in the repository, and that is not a claim this project could make
  about those files. They are replaced below rather than documented. If a
  written grant for any of them turns up, the face can come back.
- `nucore` (the non-condensed accessor) is gone with the file. It had no
  production caller — it was reached only by its own smoke test.

### Fixed

- **Idle ticks on a cooldown-throttled panel are no longer "deferred changes."**
  `OutputService.publish()` checks the image hash before the cooldown, so an
  unchanged frame inside the cooldown is logged as unchanged and does not
  rewrite `latest.png` — unless it holds a frame deferred and then reverted
  inside the cooldown, which a sidecar hash now detects (#292).
- **`daypart` rules survive weather served from cache across midnight.**
  Sunrise and sunset are read as a time of day in the configured zone, so
  yesterday's cached sun times no longer make the whole day read as `night`
  (#293).
- **A rejected API key is not retried every run.** `retry_fetch` treats an
  HTTP 4xx (other than 408/429) as permanent — from `requests`, from the
  Google API client, or wrapped in a `CalendarFetchError` — reading the
  status the library attached, never the message (#295).
- **Contacts birthdays with a text-only entry first are no longer skipped.**
  Every `birthdays[]` entry is inspected; the first with a month and day
  wins, preferring one with a year (#298).
- **A long dashboard title no longer overprints the timestamp**; it is
  truncated short of it (#310).
- **`halftone_agenda_wide` books only the part of a multi-day timed event
  that falls on the agenda day** (#311).
- **The quota warning counts what it says.** Each source's HTTP requests are
  tallied on its worker thread as they are sent (OWM, PurpleAir and CalDAV by
  wrapping the session, ICS per feed, Google per page), so timeouts and
  failed fetches count, and a birthdays file counts nothing; the warning
  is checked for every enabled source, not a hard-coded three; and the day
  resets on the configured timezone. The status page no longer shows a
  previous day's counts as today's (#296).
- **PurpleAir temperature and humidity are ambient readings in your units.**
  PurpleAir's documented housing offsets (−8 °F, +4 % RH) are applied and the
  temperature converted to `weather.units`, so a metric install no longer
  shows a Fahrenheit card beside Celsius weather (#297).
- **Web config page** — Discard and Restore reset the One Call dropdown;
  validation messages are HTML-escaped; an expired session (after a restart
  with the ephemeral key) says to reload instead of "check network"; and
  `/api/health` answers uptime probes without Basic Auth, returning only the
  status code and `{healthy}` to an anonymous caller (#309).
- **`/api/config/schema` reports secrets truthfully.** Flags are named after
  their schema paths, so a set service account or CalDAV password file no
  longer reads as unset, and PurpleAir's sensor ID is no longer reported as
  `True`. A coverage test now holds the schema, the web read model and the
  hand-written form together — it found the quotes path, rendered on the
  config page but never saved, and `min_refresh_interval_seconds`, editable
  through the API but not on the page; both now work (#308).
- **The renderer waits for a synced clock after boot.** Each run waits up to
  45 s for NTP (`systemd-time-wait-sync`, instant once synced), so an RTC-less
  Pi no longer judges quiet hours and cache ages against its last shutdown
  time. Bounded so an offline boot still renders from cache (#301).
- **`pip install ".[pi]"` installs the Inky driver**: the extra mirrors
  `requirements-pi.txt`, with a parity test (#299).
- **Docs** — README theme count (now checked against the registry), a link to
  the v4 upgrade guide, the 94 % coverage gate, and the `photo` theme, which
  has no header bar despite four places saying it did (#300).

- **A failure in post-fetch bookkeeping is no longer a fetch failure.** The
  cache write, breaker and quota saves and the success log ran inside the
  same `try` as the fetch, so an exception there was logged as a fetch error,
  counted against the breaker and threw the fetched data away (#272).
- **A `theme_rules` / `theme_schedule` entry may name a rotation pseudo-theme.**
  `random`, `random_daily` and `random_hourly` are expanded to the panel-aware
  pool when sizing the calendar event window and the partial-refresh warning,
  so a post-fetch pick of `monthly` or a rollover theme renders from a window
  that was fetched (#273).
- **ICS feeds served without a charset decode as UTF-8** (RFC 5545) instead of
  requests' ISO-8859-1 default, which turned "Café" into "CafÃ©" (#274).
- **Timed events that began before the week but overlap it are kept** on ICS
  and Google incremental sync, matching CalDAV and Google full sync (#275).
- **Today's high can no longer sit below the current temperature.** The
  forecast grid only holds the remaining 3-hour slots; the current reading and
  period extremes are folded in (#276).
- **PM2.5 → AQI uses the May 2024 EPA breakpoints.** Displayed AQI values
  change: 10 µg/m³ is now 53 Moderate (was 42 Good), 100 µg/m³ is 182 (was
  174), and `aqi_at_least` rules fire at the revised thresholds (#277).
- **A Google calendar that fails with nothing previously synced fails the
  fetch** (`CalendarFetchError`) instead of being silently omitted and the
  partial calendar cached as fresh (#278).
- **The status page prints only the ICS feed's hostname.** The URL carries the
  access token and the config editor already withholds it (#279).
- **Cache ages treat a legacy naive `fetched_at` as UTC**, as the renderer
  does, instead of host-local (#280).
- **Concurrent web saves and restores no longer discard each other.** The
  whole read → patch → validate → write sequence runs under the write lock
  (#281).
- **The template's placeholder `secret_key` is ignored.** It, and any key
  shorter than 16 characters, is treated as unset with a warning and an
  ephemeral key, instead of signing sessions with a string published in the
  repo (#282).
- **`dashboard-web.log` is rotated**, and the renderer stanza's `weekly`
  interval is live again alongside `maxsize` (#283).
- **`.gitignore` covers runtime logs and tool caches**, so a Pi checkout stays
  clean and `make release` is not blocked by `output/dashboard.log` (#284).
- **`docs/setup.md` and `docs/faq.md` describe the v5 refresh throttle.** Five
  passages still promised the v4 "once an hour on Inky" behaviour and the
  fuzzyclock allowlist (#285).
- **A malformed refresh-tracker state file no longer aborts every Waveshare
  write** (#286).
- **Colour-panel art-region dithering is ~4× faster.** The pure-Python
  serial Floyd-Steinberg loop replaces the per-pixel numpy variant; output is
  pixel-identical on every shipped art preview (#287).
- **A title with no spaces no longer runs across the whole plate.** Words
  wider than the column are broken by character in every wrapped-text site,
  and the week view's autofit picks the largest size whose broken line count
  fits instead of collapsing to 9 px (#288).
- **The week view's "+N more" marker stays inside its column** instead of
  overprinting the panel below (#289).
- **The `timeline` theme shows events before 7 AM and after 9 PM.** The axis
  widens to cover the day's timed events instead of silently dropping them
  (#290).
- **`wide_day` labels bars that end near midnight.** The label goes on
  whichever side of the bar has more room (#291).
- **Two tests no longer depend on the host timezone** (#271).
- **The calendar window ends on a local midnight.** All three calendar
  backends computed `time_max` as `time_min + days × 24 h`, which across a DST
  change is not `days` local days: the fall-back week ended at Sunday 23:00
  local, so every Sunday all-day event and any late-evening timed event was
  filtered out on ICS, CalDAV and Google incremental sync. Both bounds now
  come from `_time.event_window_utc()` (#258).
- **Calendar-sourced birthday names keep their trailing "s".** The keyword was
  removed with a case-sensitive `replace` and a character-set `strip`, so
  "James's Birthday" became "Jame" and "Sam's birthday" kept the keyword
  (#259).
- **A web save can no longer wipe `config.yaml`.** When the file could not be
  read or parsed the editor merged the form into an empty mapping and wrote
  only the patched keys back, reporting "Saved". The save is now refused with
  an error naming the cause, and a failed pre-write backup aborts it (#260).
- **A failing web-triggered run no longer locks the renderer.** The trigger
  file was removed in `ExecStartPost`, which a oneshot runs only on success,
  so a crash left it for the path unit to re-fire on until the start limit
  disabled the unit, the timer and every later "Refresh Now". It is removed
  in `ExecStartPre` and the oneshot has no `Restart=` (#261).
- **The config page's change summary reports only the fields edited.** It
  compared the flat patch against the nested config, so an untouched form
  listed every field as changed and the confirmation dialog buried real
  edits (#262).
- **The status page shows when the last run failed.** `output/last_error.txt`
  was read only by `/api/health`; the health card reported "healthy" through
  any number of consecutive crashes until the two-hour threshold (#263).
- **`make deploy` leaves the Pi's runtime state alone.** The rsync now
  excludes `state/`, `output/`, `config/web.yaml`, the config backups and
  local tool caches; a dev box that had ever rendered was resetting the Pi's
  cache, breaker and sync state and stamping its own "last success" (#264).
- **`make configure` writes the PurpleAir key.** The wizard looked for an
  uncommented `purpleair:` block the template never ships, dropped the key
  silently and appended `sensor_id` at the top level; it now uncomments or
  inserts the section and exits non-zero without touching the file when a
  key cannot be located (#265).
- **Waveshare models match the vendor library.** `epd13in3k` is 960 × 680,
  not 1600 × 1200 — with the wrong size `getbuffer()` returned a blank buffer
  and the panel stayed white with no error. `epd9in7` and `epd7in5_V3` are
  removed: no such modules exist upstream (#266).
- **`epd7in5b_V2` displays.** Its `display()` takes a black and a red plane
  and its fast init is `init_Fast`; every write raised `TypeError`. The
  driver now sends the mono buffer with a blank red plane (#267).
- **Partial refresh is a per-model fact.** Only `epd7in5_V2` and
  `epd7in5b_V2` have a fast full-frame waveform; on any other model
  `enable_partial_refresh` raised `AttributeError` on the second run and
  stuck there. Those models now drop the option with a warning (#268).
- **`load_config()` no longer crashes on plausible YAML.** Quoted numbers
  (`"23"`, `"40.7"`, `"30"`) are coerced; an unreadable number or list keeps
  its default and is reported by `validate_config()` as a `ConfigError`
  instead of a `TypeError` out of the validator; an empty list key reads as
  `[]` instead of `None` (which failed every calendar fetch); and a
  non-mapping `theme_schedule` entry is skipped and named (#269).
- **Wind speed is labelled in the units it was fetched in.** Five panels
  hardcoded "mph", so a metric install read "Wind 12mph" for a 12 m/s wind.
  One `primitives.wind_unit()` helper now serves every wind label (#270).
- **`config/config.example.yaml` is complete again, and stays that way.** The
  template `make setup` copies had fallen behind the code: five parsed options
  were missing from it entirely (`display.min_refresh_interval_seconds`,
  `cache.max_failures`, `cache.cooldown_minutes`, `google.daily_quota_warning`
  and the top-level `state_dir`), three of them editable from the web UI — so a
  user could discover them in the editor but not in the file the editor writes.
  `state_dir` was undocumented everywhere, `docs/configuration.md` included.
  The `theme:` option list named 24 of 36 registered themes, hiding `almanac`,
  `constellation_map`, `day_arc`, `halftone`, `halftone_agenda`, `light_cycle`,
  `message`, `moonphase_photo`, `naturalist`, `postcard`, `trends` and
  `weatherglass` from anyone reading only the template. `scripts/check_docs.py`
  now holds the example to the config dataclasses *and* to the theme registry,
  the same way it already held `docs/themes.md` — the drift was invisible
  because nothing checked this file.
- **The example no longer ships PurpleAir switched on with a placeholder key.**
  The air-quality source is fetched when `api_key` and `sensor_id` are both
  truthy, and placeholder strings are truthy, so every install derived from the
  template called the PurpleAir API with a bogus key on each run, failed, and
  tripped the circuit breaker — while the comment above the section called it
  optional. It is now commented out like every other optional section.
- **Three stale notes in the example corrected.** The `random_theme` comment
  pointed at v4's `output/random_theme_state.json` (state moved to `state_dir`
  in v5); the quantization block claimed the resize path "already uses
  floyd_steinberg via PIL default", which stopped being true when
  `quantize_for_display()` took over with a `threshold` default; and the
  "partial refresh is Waveshare-only" note had drifted eight lines from
  `enable_partial_refresh` to sit above `quantization_mode`, where it read as a
  note about quantization. The same v4 path leak in `random_theme.py`'s module
  docstring is fixed too.
- **`docs/configuration.md` no longer describes pre-#234 ICS behaviour.** It
  said a failing feed in `additional_ical_urls` "is logged as a warning and
  skipped while the others render"; since #234 any feed failure raises
  `CalendarFetchError` so the last complete calendar renders from cache with a
  staleness indicator, rather than a partial calendar being shown as complete.

- **`output/` had no housekeeping.** `DryRunDisplay.show()` wrote a timestamped
  `dashboard_<ts>.png` on every dry run in addition to `latest.png`, and
  nothing ever removed them or capped the count. They are gitignored
  (`output/*.png` with a `!output/latest.png` exception), so they never showed
  up in `git status` while quietly filling the card at ~50–100 KB each — and
  `make dry` / preview loops produce them in bulk. The log file next door gets
  a logrotate config; these got nothing. Only the newest `DRY_RUN_HISTORY`
  (20) are kept now.
- **`latest.png` went stale whenever a refresh was deferred.**
  `OutputService.publish()` returned early on both suppression paths and only
  saved `latest.png` after a successful hardware write. The unchanged-hash case
  is fine — the file already matches. The cooldown case was not: the content
  *did* change, the panel just was not allowed to redraw yet, so the web UI's
  "current display" image showed the previous frame for up to
  `display.min_refresh_interval_seconds` — an hour for anyone who sets `3600`
  on Inky to restore the v4 hourly throttle, which is the configuration the
  docs recommend. The rendered image is now written to `latest.png` on that
  path too. A deferred run still does not persist the image hash, so the next
  eligible run paints the pending change.

- **Web cache and breaker writes raced the renderer.** `POST /api/reset-breaker`
  and `POST /api/clear-cache` did read-all → mutate → write on
  `state/dashboard_breaker_state.json` and `state/dashboard_cache.json`, both of
  which the renderer rewrites wholesale from a **separate process** on every
  fetch. `atomic_write_json` makes each write atomic, so the file was never
  torn — but it does nothing about the interleaving, and the reset button is
  most likely to be pressed *while* a run is in flight. Whichever process wrote
  last erased the other's change: a reset could report success while the
  breaker stayed open, a failure the renderer had just recorded could vanish,
  and a source the renderer had just refreshed could be resurrected from the
  web process's stale read. `src/_io.py` now carries `file_lock()` and
  `locked_update_json()` — the sidecar-`flock` approach `web/event_store.py`
  already used, generalised so the lock covers the whole read-modify-write —
  and `actions.py`, `cache.save_source()` and `CircuitBreaker._save()` all go
  through it. `CircuitBreaker._save()` additionally writes exactly the one
  source that just changed, so writing back its in-memory copy can no longer
  undo a reset made since it loaded. `event_store` now shares the one lock
  implementation instead of keeping its own.

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
