← [README](../README.md)

# Themes

Audience: operators choosing a display style, and contributors verifying the live theme inventory.

Use this page for:
- picking a theme
- understanding random rotation and scheduled switching
- checking which built-in themes are currently available

- [Switching themes](#switching-themes)
- [Random rotation](#random-rotation)
- [Time-of-day theme schedule](#time-of-day-theme-schedule)
- [Built-in themes](#built-in-themes)
- [Creating your own theme](#creating-your-own-theme)
- [Color Themes](color-themes.md)
- [Color Theme Previews](color-theme-previews.md)
- [Typography](#typography)

---

## Switching themes

Set one concrete theme in `config.yaml`:

```yaml
theme: terminal   # default | terminal | minimalist | old_fashioned | today | fantasy | moonphase | moonphase_invert | qotd | qotd_invert | weather | fuzzyclock | fuzzyclock_invert | air_quality | message | diags | timeline | year_pulse | monthly | sunrise | scorecard | tides | photo | random | random_daily | random_hourly
```

Or override it from the CLI:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme terminal
```

The `--theme` flag takes precedence over `config.yaml`.

Themes control layout, font system, panel visibility, and rendering style. Some are week-view layouts, some are full-screen focused displays, and some are operator utilities.

For preview-generation workflow, see [Color Theme Previews](color-theme-previews.md). For a gallery-only view, see [Color Themes](color-themes.md).

---

## Random rotation

Three theme values trigger rotation logic:

| Theme value | Rotates | State file |
|---|---|---|
| `random_daily` | Once per day, at first refresh after midnight | `state/random_theme_state.json` |
| `random_hourly` | Once per hour, at first refresh after the hour turns | `state/random_theme_hourly_state.json` |
| `random` | Alias for `random_daily` | `state/random_theme_state.json` |

```yaml
theme: random_daily
random_theme:
  include: []
  exclude: []
```

- `include` is an allowlist. Empty means all eligible themes.
- `exclude` is a denylist applied after `include`.
- `diags`, `message`, and `photo` are excluded from the random pool by design.
- If the pool ends up empty, the app falls back to `default`.
- Run `make check` to validate theme names.

---

## Time-of-day theme schedule

Use `theme_schedule` to switch themes at specific local times:

```yaml
theme_schedule:
  - time: "06:00"
    theme: "default"
  - time: "20:00"
    theme: "minimalist"
  - time: "22:00"
    theme: "fuzzyclock_invert"
```

Priority order:
1. `--theme`
2. `theme_schedule`
3. `theme` in `config.yaml`

The active entry is the last row whose `time` is less than or equal to the current local time. When no row applies yet, normal fixed or random theme selection runs.

---

## Built-in themes

### Week-view themes

| Theme | Best for | Notes |
|---|---|---|
| `default` | general family wall display | Classic 7-day layout with bottom weather, birthdays, and quote panels |
| `terminal` | high-contrast retro look | Inverted black canvas with a distinct multi-font system |
| `minimalist` | clean editorial layout | Border-light, dense, hides birthdays |
| `old_fashioned` | decorative print-inspired display | Serif-heavy broadsheet layout |
| `today` | single-day focus | Large date panel and spacious agenda |
| `fantasy` | stylized themed display | Ornamental black-canvas week layout |

### Full-screen focused themes

| Theme | Best for | Notes |
|---|---|---|
| `qotd` | quote-first display | Full-screen quote plus compact weather strip |
| `qotd_invert` | dark quote display | Inverted variant of `qotd` |
| `weather` | weather station view | Current conditions, forecast, alerts, optional AQI |
| `fuzzyclock` | glanceable clock | Natural-language time plus weather strip |
| `fuzzyclock_invert` | dark clock display | Inverted variant of `fuzzyclock` |
| `moonphase` | moon and sky display | Moon progression, illumination, weather, quote |
| `moonphase_invert` | bright moon display | Inverted variant of `moonphase` |
| `photo` | custom photo background | Full-canvas image with a bottom header bar; requires `photo.path` |

### Specialized themes

| Theme | Best for | Notes |
|---|---|---|
| `air_quality` | indoor/outdoor AQI dashboard | PurpleAir-first full-screen layout |
| `timeline` | busy-day planning | Single-day hourly timeline |
| `year_pulse` | longer-horizon planning | Year progress plus upcoming events and birthdays |
| `monthly` | month-at-a-glance planning | Traditional month grid with event-density heatmap |
| `sunrise` | daylight-oriented planning | Sun arc, day/night split, compact footer metrics |
| `scorecard` | big-number metrics | KPI tiles for weather, AQI, calendar, and system data |
| `tides` | maximum information density | Alternating horizontal bands spanning many data sources |

### Utility themes

| Theme | Best for | Notes |
|---|---|---|
| `message` | one-off reminders | Requires `--message`; excluded from random rotation |
| `diags` | debugging and validation | Structured data readout; excluded from random rotation |

### Theme details and previews

#### default

Classic layout. Black text on white with a 7-day calendar grid and three bottom panels.

![Default theme](../output/theme_default.png)

#### terminal

High-contrast inverted week view with compact spacing and a retro terminal-inspired type system.

![Terminal theme](../output/theme_terminal.png)

#### minimalist

Border-light editorial layout focused on the calendar and weather, with birthdays hidden.

![Minimalist theme](../output/theme_minimalist.png)

#### old_fashioned

Victorian broadsheet layout with serif typography and decorative rules.

![Old Fashioned theme](../output/theme_old_fashioned.png)

#### today

Single-day agenda with a large date panel and roomy event list.

![Today theme](../output/theme_today.png)

#### fantasy

Ornamental black-canvas week view with a fantasy-inspired visual system.

![Fantasy theme](../output/theme_fantasy.png)

#### qotd

Full-screen quote layout with a compact weather strip across the bottom.

![QOTD theme](../output/theme_qotd.png)

#### qotd_invert

Inverted version of `qotd` with white quote text on black.

![QOTD Invert theme](../output/theme_qotd_invert.png)

#### weather

Full-screen weather dashboard with current conditions, alerts, forecast, and optional AQI.

![Weather theme](../output/theme_weather.png)

#### fuzzyclock

Natural-language clock with a compact weather strip and no calendar panels.

![Fuzzyclock theme](../output/theme_fuzzyclock.png)

#### fuzzyclock_invert

Inverted version of `fuzzyclock`.

![Fuzzyclock Invert theme](../output/theme_fuzzyclock_invert.png)

#### moonphase

Full-screen moon display with phase progression, sunrise/sunset, compact weather, and quote.

![Moonphase theme](../output/theme_moonphase.png)

#### moonphase_invert

Inverted version of `moonphase`.

![Moonphase Invert theme](../output/theme_moonphase_invert.png)

#### photo

Full-canvas photo theme driven by `photo.path`. Intended for custom-image displays rather than calendar-heavy use.

![Photo theme](../output/theme_photo.png)

#### air_quality

Full-screen PurpleAir-oriented AQI dashboard with particulate, ambient, weather, and forecast sections.

![Air Quality theme](../output/theme_air_quality.png)

#### timeline

Single-day hourly timeline that makes free blocks and overlaps easy to spot.

![Timeline theme](../output/theme_timeline.png)

#### year_pulse

Year progress plus a compact upcoming-items list for longer-horizon planning.

![Year Pulse theme](../output/theme_year_pulse.png)

#### monthly

Full-screen wall-calendar month view with day cells shaded by event density.
Waveshare uses a crisp monochrome month grid with compact density indicators; Inky uses a warm yellow-orange-red ramp.

![Monthly theme](../output/theme_monthly.png)

[![Monthly Inky theme](../output/theme_monthly_inky.png)](../output/theme_monthly_inky.png)

#### sunrise

Sun arc and day/night split layout organized around daylight.

![Sunrise theme](../output/theme_sunrise.png)

#### scorecard

Big-number tile dashboard for weather, AQI, calendar, and system metrics.

![Scorecard theme](../output/theme_scorecard.png)

#### tides

Alternating horizontal bands with the densest multi-source layout in the theme set.

![Tides theme](../output/theme_tides.png)

#### message

Manual message display for reminders or announcements. Use:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme message --message "Dentist at 3pm"
```

![Message theme](../output/theme_message.png)

#### diags

Structured diagnostic readout for validating live data and system state.

![Diags theme](../output/theme_diags.png)

---

## Creating your own theme

Contributor-facing implementation details live in [CONTRIBUTING.md](../CONTRIBUTING.md) and [CLAUDE.md](../CLAUDE.md). The operator-facing rule is simple: custom themes must be registered in the theme registry before they can be referenced from `config.yaml`.

If you are authoring a greyscale custom theme, set `ThemeLayout.canvas_mode = "L"` and use `fg=0, bg=255` in `ThemeStyle`.

---

## Typography

Bundled font families used by the current built-in themes:

| Font | Used by |
|---|---|
| Plus Jakarta Sans | default and general fallback |
| DM Sans | `minimalist`, `weather`, `fuzzyclock`, `timeline`, `diags`, `monthly` |
| Playfair Display | `old_fashioned`, `qotd`, `moonphase` |
| Cinzel | `fantasy`, `old_fashioned`, `moonphase` accents |
| Space Grotesk | `air_quality`, `message`, `year_pulse`, `scorecard` |
| Share Tech Mono / terminal fonts | `terminal`, `diags`, select utility text |

For the live gallery, see [Color Themes](color-themes.md). For batch preview generation and Inky-specific previews, see [Color Theme Previews](color-theme-previews.md).
