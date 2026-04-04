← [README](../README.md)

# Themes

- [Switching themes](#switching-themes)
- [Random rotation](#random-rotation)
- [Time-of-day theme schedule](#time-of-day-theme-schedule)
- [Built-in themes](#built-in-themes)
- [Creating your own theme](#creating-your-own-theme)
- [Typography](#typography)

---

## Switching themes

Switch the entire dashboard layout and visual style with one line in `config.yaml`:

```yaml
theme: terminal   # default | terminal | minimalist | old_fashioned | today | fantasy | moonphase | moonphase_invert | qotd | qotd_invert | weather | fuzzyclock | fuzzyclock_invert | diags | air_quality | message | random | random_daily | random_hourly
```

Or override it from the command line without editing your config:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme terminal
```

The `--theme` flag takes precedence over `config.yaml`. All values are accepted,
including `random_daily` and `random_hourly` (which trigger the rotation logic as normal).

Themes control component positions, proportions, fonts, and visual style -- not just
colors. Each theme can hide sections, rearrange panels, or use entirely different fonts.

---

## Random rotation

Two rotation cadences are available:

| Theme value | Rotates | State file |
|---|---|---|
| `random_daily` | Once per day, at first refresh after midnight | `state/random_theme_state.json` |
| `random_hourly` | Once per hour, at first refresh after the hour turns | `state/random_theme_hourly_state.json` |
| `random` | Alias for `random_daily` (backwards compatible) | `state/random_theme_state.json` |

```yaml
theme: random_daily    # or random_hourly
```

The selected theme is persisted to the state file so restarts within the same
bucket (day or hour) do not re-roll the theme.

Use `random_theme` to control which themes are in the rotation — the same
`include`/`exclude` lists apply to both cadences:

```yaml
theme: random_daily    # or random_hourly
random_theme:
  include: []          # allowlist — only these themes rotate (empty = all themes)
  exclude: []          # denylist — never use these themes
```

**Examples:**

```yaml
# Only rotate among calm, readable themes
random_theme:
  include: ["default", "minimalist", "terminal"]

# Rotate everything except the full-screen quote theme
random_theme:
  exclude: ["qotd"]
```

- `include` is applied first; `exclude` is applied after.
- If both are empty, all standard themes are eligible (`diags` and `message` are always
  excluded from the pool — `diags` is a utility/diagnostic view; `message` requires a
  `--message` argument and is intended for manual runs only).
- If the pool is empty after filtering, the dashboard falls back to `"default"`.
- Run `make check` to catch invalid theme names in either list.

---

## Time-of-day theme schedule

Automatically switch themes at specific times of day without any manual intervention:

```yaml
theme_schedule:
  - time: "06:00"
    theme: "default"
  - time: "20:00"
    theme: "minimalist"
  - time: "22:00"
    theme: "fuzzyclock_invert"
```

The active theme is determined by the last entry whose `time` (HH:MM, 24-hour) is ≤ the
current local time. Before the first entry fires — e.g. at 4 AM when the first entry is
`06:00` — the normal `theme:` / random logic applies.

**Priority order (highest → lowest):**
1. `--theme` CLI flag — always wins; schedule is never consulted.
2. `theme_schedule` — the matching time window.
3. `theme:` in `config.yaml` (may be `random_daily`, `random_hourly`, or `random`).

The schedule works alongside random rotation: if no schedule entry matches, the dashboard
falls through to `theme: random_daily` / `random_hourly` as usual. `make check` validates
all time strings and theme names in the schedule.

---

## Built-in themes

### default

Classic layout. Black text on white. Filled black header, today column, and all-day
event bars. 7-day calendar grid with weather/birthdays/quote along the bottom.

![Default theme](../output/theme_default.png)

### terminal

Inverted canvas: **black background** with white text. Compact 34px header. Tighter event
spacing (0.85× scale). Today's column and all-day event bars both pop as white-fill/black-text
blocks. Multi-font typographic system: Share Tech Mono for event body text; Maratype for the
dashboard title, day column headers, and quote body; UESC Display for the month band, section
labels (WEATHER / BIRTHDAYS / QUOTE OF THE DAY), and quote attribution; Synthetic Genesis for
the large today date numeral. The month band font scales down automatically so long names
(FEBRUARY, SEPTEMBER) always fit the cell.

![Terminal theme](../output/theme_terminal.png)

### minimalist

Bauhaus editorial: form follows function. Ultra-slim 22px header with no fill or border.
The week grid dominates at 358px. Today's column is marked with a subtle outline (no fill).
All-day event bars are outlined, not filled. Events pack to a tight 1.0× grid. A 100px
bottom strip splits asymmetrically: weather at 500px, quote at 300px (labelled with a
single em dash). Section labels are 8pt regular — data leads. No structural borders or
separator lines. DM Sans font. Birthdays panel hidden.

![Minimalist theme](../output/theme_minimalist.png)

### old_fashioned

Victorian broadsheet layout. A 70px inverted masthead with white corner-bracket ornaments
and a thin inner frame rule. A triple-rule band separates the masthead from the body. The
left column (490px) shows today's schedule with Playfair Display serif body text. The right
sidebar (310px) stacks three panels — **The Weather**, **Social Notices**, and **Words of
Wisdom** — divided by double horizontal rules with diamond dingbats. A double vertical
column rule with a centre diamond separates the two columns. Cinzel Black Roman caps for
section labels. Double-rule bottom border.

![Old Fashioned theme](../output/theme_old_fashioned.png)

### today

Single-day focused view. Large inverted date panel on the left, spacious event list on the
right with full time ranges and locations. 60px header, 140px bottom strip. Ideal for a
desk display.

![Today theme](../output/theme_today.png)

### fantasy

D&D-inspired aesthetic. Black canvas with Cinzel Bold headers and sword-glyph accents in
the masthead. A 240px left sidebar ("Arcane Tower") stacks three panels — **The Oracle's
Omen** (weather), **The Fellowship** (birthdays), and **Ancient Wisdom** (quote). The
**Quest Log** (week view) fills the right 560px. A thick ornamental double-frame border runs
the full canvas, with concentric diamond corner ornaments at every inner-frame corner.
Triple-line vertical divider between sidebar and quest log with diamond ticks at 1/3, 1/2,
and 2/3 of the body height. Plus Jakarta Sans for event body text.

![Fantasy theme](../output/theme_fantasy.png)

### moonphase

Celestial moon phase display. The current moon phase is rendered as a large 140px Weather
Icons glyph at the centre of the canvas, flanked by three days on each side at graduated
sizes (42/36/30px) showing the lunar progression from past to future. Below the moon arc
sits the illumination percentage, sunrise and sunset times, moon age in days, and a compact
weather strip with current conditions and hi/lo temperatures. A small centered daily quote
fills the bottom. The entire canvas is framed by a whimsical vine border with triangular
leaf buds along each edge, concentric-arc corner flourishes, and scattered stars in the
upper corners. Dark canvas (white on black) for a night-sky aesthetic. Fonts: Cinzel Bold
for the date and phase name, Playfair Display for body text and quote.

![Moonphase theme](../output/theme_moonphase.png)

### moonphase_invert

Same layout as `moonphase` — central hero moon glyph, flanking day moons, celestial info
strip, weather, and quote — but with the color scheme inverted: black on white for a
parchment / fairy-tale illustrated-manuscript feel. The vine border, leaf buds, corner
flourishes, and star scatter adapt automatically to the inverted palette. Maximum eInk
contrast.

![Moonphase Invert theme](../output/theme_moonphase_invert.png)

### qotd

Quote of the day, full screen. Forgoes the calendar, birthdays, and info panel entirely.
The display is devoted to a single quote in large Playfair Display Bold, centered
typographically. Font size scales automatically — from 64px down to 20px — so the full
quote always fits without truncation. A compact full-width weather banner runs across the
bottom 80px: current conditions, hi/lo, feels-like, wind, a 3-day forecast strip, and
moon phase.

![QOTD theme](../output/theme_qotd.png)

### qotd_invert

Same layout as `qotd` — full-screen centered quote with compact weather banner — but with the
color scheme inverted: white Playfair Display text on a black canvas. The high-contrast strokes
of this transitional serif read especially well reversed out of a dark ground.

![QOTD Invert theme](../output/theme_qotd_invert.png)

### weather

Full-screen weather station. Devotes the entire 800×480 canvas to a rich weather display
inspired by iOS Weather and Foreca Weather. The upper two-thirds show current conditions at
a glance — an 80px weather icon, hero temperature in bold 72px DM Sans, description, and
hi/lo line. Below the hero sits a row of metric cards: feels-like, wind speed and direction,
humidity, UV index, and — when a PurpleAir sensor is configured — an AQI card showing the
EPA air quality index and category (Good / Moderate / Unhealthy / etc.). A details bar spans
the full width with sunrise/sunset times, barometric pressure, and moon phase; when a
PurpleAir sensor is present this bar also shows a PM1 · PM2.5 · PM10 µg/m³ breakdown. If an
active weather alert is present it appears as a prominent inverted full-width banner. The
lower third shows a clean five-day forecast grid with icon, hi/lo temperatures, and
precipitation probability for each day. All standard components (header, calendar, birthdays,
quote) are hidden — the display is weather only. Font: DM Sans throughout.

![Weather theme](../output/theme_weather.png)

### fuzzyclock

Natural-language clock. The current time is expressed as a human-readable phrase —
"half past seven", "quarter to nine", "twenty five past eleven" — rendered large and
centred in DM Sans Bold. The day name and date sit below in smaller regular weight. A
compact full-width weather banner fills the bottom 80px (identical to the `qotd` strip:
current conditions, hi/lo, feels-like, wind, 3-day forecast, moon phase). The calendar,
birthdays, and quote panels are hidden entirely.

Time phrases snap to the nearest 5-minute boundary, so the display changes at most twelve
times per hour. The default systemd timer runs every 5 minutes; the image-hash check
ensures no eInk refresh occurs when the phrase hasn't changed.

![Fuzzyclock theme](../output/theme_fuzzyclock.png)

### fuzzyclock_invert

Same layout as `fuzzyclock` — full-screen natural-language clock phrase with compact weather
banner — but with the color scheme inverted: white DM Sans text on a black canvas. The geometric
shapes of this screen-optimised sans-serif hold up well at large sizes when reversed out of a
dark background.

![Fuzzyclock Invert theme](../output/theme_fuzzyclock_invert.png)

### air_quality

Full-screen environmental health dashboard. Devotes the entire 800×480 canvas to PurpleAir
sensor data, organised into four horizontal zones:

- **AQI hero** (top 38%): the EPA Air Quality Index number in large bold type on the left,
  with the category label (Good / Moderate / Unhealthy for Sensitive Groups / Unhealthy /
  Very Unhealthy / Hazardous) below. On the right, a 6-zone health scale bar fills
  progressively from left to the current reading, with a triangle position indicator and
  zone labels.
- **Particulate matter row** (15%): PM1.0 · PM2.5 · PM10 readings in µg/m³, centred in
  three equal columns. Only fields returned by the sensor are shown.
- **Ambient sensor cards** (21%): up to three rounded-rect cards for sensor temperature (°F),
  relative humidity (%), and barometric pressure (hPa). Cards are hidden when the sensor does
  not provide those readings.
- **Weather + forecast strip** (bottom 27%): current conditions (icon, temperature,
  description, hi/lo) on the left; a 4-day forecast grid (day name, icon, hi/lo, precipitation
  probability) on the right.

Requires a configured PurpleAir sensor (`purpleair.api_key` + `purpleair.sensor_id` in
`config.yaml`). Weather data is optional — the strip degrades gracefully if unavailable.
Font: Space Grotesk — a proportional sans derived from Space Mono whose quirky
letterforms (a, G, R, t) give the data-dashboard layout personality while remaining legible
at all eInk display sizes.

![Air Quality theme](../output/theme_air_quality.png)

### diags

Diagnostic text readout. Devotes the entire 800×480 canvas to a structured two-column
key-value display of every available data field. No icons, no decorations — only labeled
sections rendered in a clean monospace font (Share Tech Mono for data rows, DM Sans Bold for
section labels).

**Left column:** WEATHER (condition, temperature, hi/lo, feels-like, humidity, wind speed and
direction, barometric pressure, UV index, sunrise/sunset, active alerts) followed by a
FORECAST strip (up to six days of date, hi/lo, description, and precipitation probability).

**Right column (top-to-bottom):** CALENDAR (per-day event counts for the current Mon–Sun week),
AIR QUALITY (AQI, PM2.5, PM1.0, PM10, plus PurpleAir ambient temperature/humidity/pressure
when configured), BIRTHDAYS (name, date, and age for upcoming birthdays), and STATUS (data
freshness level per source: Fresh / Aging / Stale / Expired).

Each section label includes a right-aligned source attribution (`OpenWeatherMap`, `Google
Calendar`, `PurpleAir`). `diags` is intentionally excluded from the random rotation pool —
it is a utility/sanity-check view, not a daily aesthetic.

![Diags theme](../output/theme_diags.png)

### message

Custom message display. Forgoes the calendar, birthdays, and info panel entirely.
The display is devoted to a single user-supplied message in large Space Grotesk Bold,
centered typographically. Font size scales automatically — from 64px down to 20px — so
the full message always fits without truncation. Decorative oversized quotation marks frame
the text as corner accents. A compact full-width weather banner runs across the bottom 80px
(identical to the `qotd` strip: current conditions, hi/lo, feels-like, wind, 3-day
forecast, and moon phase).

Intended for manual one-off runs — pipe a reminder, announcement, or note to the display
without touching `config.yaml`. Use `--message` to provide the text:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme message --message "Dentist at 3pm"
```

This theme is excluded from random rotation (`random_daily` / `random_hourly`) and must
always be specified explicitly via `--theme message`.

---

## Creating your own theme

Two steps -- no changes to any component code:

**1. Create `src/render/themes/<name>.py`:**

```python
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

def retro_theme() -> Theme:
    return Theme(
        name="retro",
        layout=ThemeLayout(
            canvas_w=800, canvas_h=480,
            header=ComponentRegion(0, 0, 800, 48),
            week_view=ComponentRegion(0, 48, 540, 432),
            weather=ComponentRegion(540, 48, 260, 144),
            birthdays=ComponentRegion(540, 192, 260, 144),
            info=ComponentRegion(540, 336, 260, 144),
        ),
        style=ThemeStyle(
            invert_header=True,
            invert_today_col=True,
            invert_allday_bars=False,
            spacing_scale=1.1,
        ),
    )
```

**2. Register in `src/render/theme.py`:**

Add a clause to `load_theme()` and add the name to `AVAILABLE_THEMES`. New themes are
automatically included in the random rotation pool. To exclude a theme from the pool (e.g.
utility or diagnostic views), add its name to `_EXCLUDED_FROM_POOL` in
`src/render/random_theme.py`.

Then preview:

```bash
venv/bin/python -m src.main --dry-run --dummy --config /dev/stdin <<'EOF'
theme: retro
display:
  model: "epd7in5_V2"
weather:
  api_key: "dummy"
  latitude: 40.7
  longitude: -74.0
google:
  service_account_path: "credentials/service_account.json"
  calendar_id: "dummy@group.calendar.google.com"
EOF
```

See the theme reference tables and font customization guide in [`CLAUDE.md`](../CLAUDE.md).

---

## Typography

| Font | Used for |
|---|---|
| [Plus Jakarta Sans](https://fonts.google.com/specimen/Plus+Jakarta+Sans) | Default UI text (all themes) |
| [Weather Icons](https://erikflowers.github.io/weather-icons/) | Weather condition icons + moon phase glyphs |
| [Share Tech Mono](https://fonts.google.com/specimen/Share+Tech+Mono) | `terminal` theme — event body text; `diags` theme — all data rows |
| Maratype | `terminal` theme — dashboard title, day column headers, quote body |
| UESC Display | `terminal` theme — month band, section labels, quote attribution |
| Synthetic Genesis | `terminal` theme — large today date numeral |
| [DM Sans](https://fonts.google.com/specimen/DM+Sans) | `minimalist` theme; `weather` theme; `fuzzyclock` theme; `diags` theme — section labels |
| [Playfair Display](https://fonts.google.com/specimen/Playfair+Display) | `old_fashioned` theme; `qotd` quote text; `moonphase` body text and quote |
| [Cinzel](https://fonts.google.com/specimen/Cinzel) | `fantasy` theme; `old_fashioned` section labels; `moonphase` date and phase name |
| [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk) | `air_quality` theme; `message` theme |

Custom fonts can be added per-theme via `ThemeStyle` font callables — see
[Creating your own theme](#creating-your-own-theme) and [`CLAUDE.md`](../CLAUDE.md).
