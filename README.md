# Home Dashboard

A Python eInk dashboard for Raspberry Pi. Displays your weekly calendar, current weather,
upcoming birthdays, and a daily quote on any supported Waveshare black-and-white eInk
display.

![Default theme preview](output/theme_default.png)

---

## Choose Your Path

- **First install on a Raspberry Pi:** start with [Quick Start](#quick-start), then finish
  [Google Calendar Setup](#google-calendar-setup) if you use calendar/birthdays.
- **Want calendar without a GCP project?** Use [ICS Feed (No GCP Required)](#ics-feed-no-gcp-required)
  — just paste one URL from Google Calendar settings, no credentials file needed.
- **Upgrading from an older release:** go to [Upgrading from v3](#upgrading-from-v3).
- **Local dev / preview only:** jump to [Development](#development) and run `make setup`
  + `make dry` (no hardware required).

## Table of Contents

- [Quick Start](#quick-start)
- [Google Calendar Setup](#google-calendar-setup)
- [ICS Feed (No GCP Required)](#ics-feed-no-gcp-required)
- [Raspberry Pi Reference](#raspberry-pi-reference)
- [Themes](#themes)
- [Advanced Configuration](#advanced-configuration)
- [Troubleshooting and Recovery](#troubleshooting-and-recovery)
- [Development](#development)
- [Upgrading from v3](#upgrading-from-v3)

---

## Quick Start

SSH into your Pi, then run these commands from the project directory:

```bash
git clone https://github.com/gkoch02/Dashboard-v4.git ~/home-dashboard
cd ~/home-dashboard
make pi-install    # apt deps, SPI, Python venv, Waveshare drivers — all in one
make configure     # interactive prompts fill in your API keys and settings
make dry           # render a preview with dummy data — no hardware needed
make pi-enable     # install and start the systemd refresh timer
make pi-status     # confirm the timer is active and healthy
```

That's it. The dashboard starts refreshing every 5 minutes automatically.

> **Note:** `make pi-install` enables SPI via `raspi-config`. If SPI was not previously
> enabled on your Pi, reboot once before running on real hardware (`sudo reboot`).
> `make configure` and `make dry` work fine before the reboot.
>
> **Next:** if you use Google Calendar or Google Contacts birthdays, complete
> [Google Calendar Setup](#google-calendar-setup) before your first live run.

---

## make configure

`make configure` is an interactive wizard that writes your settings directly into
`config/config.yaml`. Run it after `make pi-install`.

```
Display model [epd7in5_V2]:
OpenWeatherMap API key:
Latitude:
Longitude:
Units (imperial/metric) [imperial]:
Google Calendar ID:
Timezone [America/New_York]:
PurpleAir API key (optional, press Enter to skip):
PurpleAir sensor ID (optional, press Enter to skip):
```

Existing values are shown as defaults — it is safe to re-run at any time to change a
setting. The wizard ends by running `make check` to validate your configuration.

**Google service account JSON** cannot be fetched automatically — it requires a
one-time browser download from Google Cloud Console. The wizard guides you through
placing it at `credentials/service_account.json` and links to the
[Google Calendar Setup](#google-calendar-setup) instructions.

---

## Themes

If you're still setting up APIs/credentials, finish [Google Calendar Setup](#google-calendar-setup)
first and come back here for customization.

Switch the entire dashboard layout and visual style with one line in `config.yaml`:

```yaml
theme: terminal   # default | terminal | minimalist | old_fashioned | today | fantasy | qotd | qotd_invert | weather | fuzzyclock | fuzzyclock_invert | diags | air_quality | random
```

Or override it from the command line without editing your config:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme terminal
```

The `--theme` flag takes precedence over `config.yaml`. All values are accepted,
including `random` (which triggers the daily rotation logic as normal).

Themes control component positions, proportions, fonts, and visual style -- not just
colors. Each theme can hide sections, rearrange panels, or use entirely different fonts.

### Random daily rotation

Set `theme: random` to automatically pick a different theme each day:

```yaml
theme: random
```

A theme is chosen once per day on the first refresh after midnight and reused for every
subsequent refresh that day. The selection is persisted to
`output/random_theme_state.json` so restarts mid-day do not re-roll the theme.

Use `random_theme` to control which themes are in the rotation:

```yaml
theme: random
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
- If both are empty, all standard themes are eligible (`diags` and `air_quality` are always
  excluded — they are specialised views, not general-purpose daily aesthetics).
- If the pool is empty after filtering, the dashboard falls back to `"default"`.
- Run `make check` to catch invalid theme names in either list.

### Time-of-day theme schedule

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
`06:00` — the normal `theme:` / `random` logic applies.

**Priority order (highest → lowest):**
1. `--theme` CLI flag — always wins; schedule is never consulted.
2. `theme_schedule` — the matching time window.
3. `theme:` in `config.yaml` (may be `random`).

The schedule works alongside `random`: if no schedule entry matches, the dashboard falls
through to `theme: random` as usual. `make check` validates all time strings and theme names
in the schedule.

### Built-in themes

#### default

Classic layout. Black text on white. Filled black header, today column, and all-day
event bars. 7-day calendar grid with weather/birthdays/quote along the bottom.

![Default theme](output/theme_default.png)

#### terminal

Inverted canvas: **black background** with white text. Compact 34px header. Tighter event
spacing (0.85× scale). Today's column and all-day event bars both pop as white-fill/black-text
blocks. Multi-font typographic system: Share Tech Mono for event body text; Maratype for the
dashboard title, day column headers, and quote body; UESC Display for the month band, section
labels (WEATHER / BIRTHDAYS / QUOTE OF THE DAY), and quote attribution; Synthetic Genesis for
the large today date numeral. The month band font scales down automatically so long names
(FEBRUARY, SEPTEMBER) always fit the cell.

![Terminal theme](output/theme_terminal.png)

#### minimalist

Bauhaus editorial: form follows function. Ultra-slim 22px header with no fill or border.
The week grid dominates at 358px. Today's column is marked with a subtle outline (no fill).
All-day event bars are outlined, not filled. Events pack to a tight 1.0× grid. A 100px
bottom strip splits asymmetrically: weather at 500px, quote at 300px (labelled with a
single em dash). Section labels are 8pt regular — data leads. No structural borders or
separator lines. DM Sans font. Birthdays panel hidden.

![Minimalist theme](output/theme_minimalist.png)

#### old_fashioned

Victorian broadsheet layout. A 70px inverted masthead with white corner-bracket ornaments
and a thin inner frame rule. A triple-rule band separates the masthead from the body. The
left column (490px) shows today's schedule with Playfair Display serif body text. The right
sidebar (310px) stacks three panels — **The Weather**, **Social Notices**, and **Words of
Wisdom** — divided by double horizontal rules with diamond dingbats. A double vertical
column rule with a centre diamond separates the two columns. Cinzel Black Roman caps for
section labels. Double-rule bottom border.

![Old Fashioned theme](output/theme_old_fashioned.png)

#### today

Single-day focused view. Large inverted date panel on the left, spacious event list on the
right with full time ranges and locations. 60px header, 140px bottom strip. Ideal for a
desk display.

![Today theme](output/theme_today.png)

#### fantasy

D&D-inspired aesthetic. Black canvas with Cinzel Bold headers and sword-glyph accents in
the masthead. A 240px left sidebar ("Arcane Tower") stacks three panels — **The Oracle's
Omen** (weather), **The Fellowship** (birthdays), and **Ancient Wisdom** (quote). The
**Quest Log** (week view) fills the right 560px. A thick ornamental double-frame border runs
the full canvas, with concentric diamond corner ornaments at every inner-frame corner.
Triple-line vertical divider between sidebar and quest log with diamond ticks at 1/3, 1/2,
and 2/3 of the body height. Plus Jakarta Sans for event body text.

![Fantasy theme](output/theme_fantasy.png)

#### qotd

Quote of the day, full screen. Forgoes the calendar, birthdays, and info panel entirely.
The display is devoted to a single quote in large Playfair Display Bold, centered
typographically. Font size scales automatically — from 64px down to 20px — so the full
quote always fits without truncation. A compact full-width weather banner runs across the
bottom 80px: current conditions, hi/lo, feels-like, wind, a 3-day forecast strip, and
moon phase.

![QOTD theme](output/theme_qotd.png)

#### qotd_invert

Same layout as `qotd` — full-screen centered quote with compact weather banner — but with the
color scheme inverted: white Playfair Display text on a black canvas. The high-contrast strokes
of this transitional serif read especially well reversed out of a dark ground.

![QOTD Invert theme](output/theme_qotd_invert.png)

#### weather

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

![Weather theme](output/theme_weather.png)

#### fuzzyclock

Natural-language clock. The current time is expressed as a human-readable phrase —
"half past seven", "quarter to nine", "twenty five past eleven" — rendered large and
centred in DM Sans Bold. The day name and date sit below in smaller regular weight. A
compact full-width weather banner fills the bottom 80px (identical to the `qotd` strip:
current conditions, hi/lo, feels-like, wind, 3-day forecast, moon phase). The calendar,
birthdays, and quote panels are hidden entirely.

Time phrases snap to the nearest 5-minute boundary, so the display changes at most twelve
times per hour. The default systemd timer runs every 5 minutes; the image-hash check
ensures no eInk refresh occurs when the phrase hasn't changed.

![Fuzzyclock theme](output/theme_fuzzyclock.png)

#### fuzzyclock_invert

Same layout as `fuzzyclock` — full-screen natural-language clock phrase with compact weather
banner — but with the color scheme inverted: white DM Sans text on a black canvas. The geometric
shapes of this screen-optimised sans-serif hold up well at large sizes when reversed out of a
dark background.

![Fuzzyclock Invert theme](output/theme_fuzzyclock_invert.png)

#### air_quality

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
`air_quality` is excluded from the `random` rotation pool; activate it with `theme: air_quality`
directly. Font: Space Grotesk — a proportional sans derived from Space Mono whose quirky
letterforms (a, G, R, t) give the data-dashboard layout personality while remaining legible
at all eInk display sizes.

![Air Quality theme](output/theme_air_quality.png)

#### diags

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
Calendar`, `PurpleAir`). `diags` is intentionally excluded from the `random` rotation pool —
it is a utility/sanity-check view, not a daily aesthetic.

![Diags theme](output/theme_diags.png)

### Creating your own theme

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
automatically included in the `random` rotation pool. To exclude a theme from the pool (e.g.
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

See the theme reference tables and font customization guide in [`CLAUDE.md`](CLAUDE.md).

---

## Upgrading from v3

v4 is a drop-in upgrade. Your existing credentials and `config.yaml` work without changes.

### Step 1 -- Clone the new repo

```bash
git clone https://github.com/gkoch02/Dashboard-v4.git
cd Dashboard-v4
```

### Step 2 -- Copy your config and credentials

```bash
cp /path/to/Dashboard-v3/config/config.yaml config/config.yaml
cp /path/to/Dashboard-v3/credentials/service_account.json credentials/service_account.json
```

If you had a `config/birthdays.json`, copy that too:

```bash
cp /path/to/Dashboard-v3/config/birthdays.json config/birthdays.json
```

### Step 3 -- Install dependencies

```bash
make setup
```

The dependency list is identical to v3; `make setup` creates a fresh venv.

### Step 4 -- Clear the old cache

Delete v3's output files before the first run to avoid stale cache conflicts:

```bash
rm -f output/calendar_cache.json output/weather_cache.json \
      output/birthday_cache.json output/calendar_sync_state.json \
      output/last_image_hash.txt
```

### Step 5 -- Validate your config

```bash
make check
```

### Step 6 -- Test

```bash
make dry            # renders output/latest.png with dummy data
venv/bin/python -m src.main --dry-run --config config/config.yaml   # live data
```

### Step 7 -- Redeploy to Pi

```bash
make deploy
ssh pi@raspberrypi.local "cd ~/home-dashboard && make setup"
make install        # reinstall systemd timer (unit file has changed)
```

### What's new in v4.1

Your existing config is fully compatible. These are opt-in additions:

| Feature | How to enable |
|---|---|
| **PurpleAir air quality** | Add `purpleair.api_key` and `purpleair.sensor_id` to `config.yaml`; an AQI card (EPA index from 60-minute PM2.5 average) appears in the `weather` theme metric row, and a PM1 · PM2.5 · PM10 µg/m³ breakdown appears in the detail strip |
| **ICS feed calendar (no GCP)** | Set `google.ical_url` to your calendar's "Secret address in iCal format" URL — no service account or GCP project needed; supports multiple calendars via `additional_ical_urls` |
| **Configurable quote refresh** | Set `cache.quote_refresh` to `daily` (default), `twice_daily`, or `hourly` to control how often the displayed quote rotates; uses a stable date-based hash so the same time slot always shows the same quote |

### What's new in v4

Your existing config is fully compatible. These are opt-in additions:

| Feature | How to enable |
|---|---|
| **Versioning** (`--version` flag) | Run `python -m src.main --version` or `make version` to print the current version |
| **Themes** (built-in layouts) | Add `theme: terminal` (or `minimalist`, `old_fashioned`, `today`, `fantasy`, `qotd`, `qotd_invert`, `weather`, `fuzzyclock`, `fuzzyclock_invert`) to `config.yaml`, or pass `--theme THEME` on the command line |
| **Random daily theme rotation** | Set `theme: random`; optionally add a `random_theme:` block to include/exclude specific themes |
| **Event filtering** | Add a `filters:` block — hide events by calendar name, keyword, or all-day status |
| **Configurable cache TTLs** | Add a `cache:` block to tune per-source TTL and fetch intervals |
| **Circuit breaker tuning** | `cache.max_failures` and `cache.cooldown_minutes` |
| **API quota warnings** | `google.daily_quota_warning: 500` logs a warning when calls exceed the threshold |
| **`--check-config` flag** | Validate config and exit without running the dashboard |
| **`--force-full-refresh` flag** | Bypass fetch intervals and force a full eInk refresh for a one-off run |
| **`--ignore-breakers` flag** | Ignore OPEN circuit breakers for one run and attempt live fetches anyway |

---

## Google Calendar Setup

The dashboard reads your calendar via a **Google service account** (no interactive login
needed).

### Step 1 -- Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in
2. Click the project dropdown > **New Project** > name it > **Create**

### Step 2 -- Enable the Calendar API

1. Go to **APIs & Services > Library**
2. Search **Google Calendar API** > **Enable**

### Step 3 -- Create a service account

1. Go to **APIs & Services > Credentials > + Create Credentials > Service account**
2. Name it (e.g. `dashboard-reader`) > **Create and Continue** > **Done**

### Step 4 -- Download the key

1. Click the service account > **Keys** tab > **Add Key > Create new key > JSON**
2. Move the downloaded file to `credentials/service_account.json`

> The `credentials/` directory is git-ignored.

### Step 5 -- Share your calendar

1. Copy the service account email (looks like `dashboard-reader@your-project.iam.gserviceaccount.com`)
2. In [Google Calendar](https://calendar.google.com), click the three-dot menu next to your
   calendar > **Settings and sharing > Share with specific people > + Add people**
3. Paste the email, set permission to **See all event details**, click **Send**

### Step 6 -- Find your Calendar ID

1. In the same calendar settings page, scroll to **Integrate calendar**
2. Copy the **Calendar ID** and paste it into `google.calendar_id` in `config.yaml`

To display events from additional calendars, share them with the same service account
and list their IDs:

```yaml
google:
  additional_calendars:
    - "family@group.calendar.google.com"
    - "work@group.calendar.google.com"
```

---

## ICS Feed (No GCP Required)

If the service account setup above feels like too much friction, you can use Google
Calendar's built-in ICS export instead. No GCP project, no credentials file, no OAuth —
just a URL.

### Trade-offs vs service account

| | ICS feed | Service account |
|---|---|---|
| GCP project required | No | Yes |
| Credentials file | None | `service_account.json` |
| Setup time | ~1 minute | ~10 minutes |
| Incremental sync | No (full fetch every time) | Yes (only changed events) |
| Multiple calendars | Yes (one URL each) | Yes |
| Contacts birthdays | Not available | Available |

The ICS path always fetches the full feed (~50–200 KB). At the default 2-hour event
fetch interval this is negligible. Google does not rate-limit ICS fetches aggressively.

### Step 1 — Get the ICS URL

1. Open [Google Calendar](https://calendar.google.com) in a browser
2. Click the three-dot menu next to your calendar > **Settings and sharing**
3. Scroll to **Integrate calendar**
4. Copy the **Secret address in iCal format** (not the public URL)

> **Keep this URL private.** Anyone with it can read your calendar. It is safe to store
> in `config/config.yaml` on your Pi since that file is git-ignored.

### Step 2 — Add to config.yaml

```yaml
google:
  ical_url: "https://calendar.google.com/calendar/ical/.../.../basic.ics"
```

That's it. Remove or leave `service_account_path` in place — it is ignored when
`ical_url` is set.

### Multiple calendars

```yaml
google:
  ical_url: "https://calendar.google.com/calendar/ical/.../basic.ics"
  additional_ical_urls:
    - "https://calendar.google.com/calendar/ical/.../basic.ics"
    - "https://calendar.google.com/calendar/ical/.../basic.ics"
```

### Birthdays

Contacts-based birthdays (`birthdays.source: contacts`) require the People API and are
not available via ICS. Use `birthdays.source: file` or `birthdays.source: calendar`
(birthday events in your calendar will appear in the ICS feed automatically).

---

## Birthday Configuration

Set `birthdays.source` in config to one of three modes:

### `file` (default)

Create `config/birthdays.json`:

```json
[
  {"name": "Alice", "date": "1990-03-20"},
  {"name": "Bob",   "date": "07-04"}
]
```

Use `YYYY-MM-DD` to show age, or `MM-DD` for date only.

### `calendar`

Events containing the keyword `"Birthday"` (configurable via `calendar_keyword`) are
picked up automatically from your Google Calendar.

### `contacts`

Reads birthdays from Google Contacts via the People API. Requires a **Google Workspace**
account with domain-wide delegation:

1. Enable the **People API** in Cloud Console
2. In [Google Workspace Admin](https://admin.google.com) > **Security > API controls >
   Manage domain-wide delegation > Add new**: enter the service account's client ID and
   scope `https://www.googleapis.com/auth/contacts.readonly`
3. Set in `config.yaml`:

```yaml
google:
  contacts_email: "you@yourdomain.com"

birthdays:
  source: "contacts"
```

---

## Raspberry Pi Reference

> The steps below are what `make pi-install`, `make configure`, and `make pi-enable` do
> under the hood. Use this section for troubleshooting or if you prefer a manual setup.

### Step 1 -- Enable SPI

```bash
sudo raspi-config nonint do_spi 0
sudo reboot
```

Or interactively: **Interface Options > SPI > Yes > reboot**.

### Step 2 -- System dependencies

```bash
TIFF_PKG=$(apt-cache show libtiff5 2>/dev/null | grep -q "^Package" && echo libtiff5 || echo libtiff6)
sudo apt-get install -y python3-dev python3-venv libopenjp2-7 $TIFF_PKG git swig liblgpio-dev
```

### Step 3 -- Python environment

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-pi.txt
```

### Step 4 -- Waveshare display drivers

```bash
git clone --depth=1 https://github.com/waveshare/e-Paper /tmp/waveshare-epd
venv/bin/pip install /tmp/waveshare-epd/RaspberryPi_JetsonNano/python/
venv/bin/python -c "import waveshare_epd; print('OK')"
```

### Step 5 -- Configure and test

```bash
cp config/config.example.yaml config/config.yaml
# edit config/config.yaml and place credentials/service_account.json
make check
make dry
venv/bin/python -m src.main --config config/config.yaml
```

### Step 6 -- Install the systemd timer

`make pi-enable` generates the service file with the correct paths for your user and
install directory automatically:

```bash
make pi-enable
make pi-status
```

The timer fires every 5 minutes. The app handles scheduling internally:

| Time window | Behaviour |
|---|---|
| `quiet_hours_start` to `quiet_hours_end` | Process exits immediately -- no fetch, render, or display write |
| First run after quiet hours end | Forces a full eInk refresh |
| All other active hours | eInk refreshed only when image content changes (hash check); API calls gated by per-source fetch intervals |

Configure quiet hours:

```yaml
schedule:
  quiet_hours_start: 23   # 11 PM
  quiet_hours_end: 6      # 6 AM
```

### Remote deploy (dev machine → Pi)

If you prefer to develop on a separate machine and push to the Pi via rsync:

```bash
make deploy                                          # rsync to pi@dashboard:~/home-dashboard
make deploy PI_USER=myuser PI_HOST=mypi.local        # override target
```

After deploying, SSH to the Pi and run `make pi-install` once to install system
dependencies, then `make pi-enable` to start the timer.

---

## Supported Displays

| Model | Resolution | Notes |
|---|---|---|
| `epd7in5` | 640x384 | V1 (older) |
| `epd7in5_V2` | 800x480 | **Default / recommended** |
| `epd7in5_V3` | 800x480 | V3 variant |
| `epd7in5b_V2` | 800x480 | B/W/Red model -- renders B&W only |
| `epd7in5_HD` | 880x528 | HD variant |
| `epd9in7` | 1200x825 | 9.7 inch |
| `epd13in3k` | 1600x1200 | 13.3 inch |

Set `display.model` in `config.yaml`. Width and height are derived automatically from the
model. The dashboard renders at 800x480 base resolution and scales to the display's native
resolution via LANCZOS resampling.

---

## Hardware

### Bill of materials

A minimal build (Pi Zero 2 W + 7.5" display) costs approximately **$65--75**.

| Component | Recommended | Price |
|---|---|---|
| **Raspberry Pi** | [Pi Zero 2 WH](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/) (with headers) | ~$15 |
| **eInk display** | [Waveshare 7.5" HAT V2](https://www.waveshare.com/7.5inch-e-paper-hat.htm) (800x480) | ~$30--35 |
| **MicroSD card** | 32 GB Class 10 / A1 | ~$8--10 |
| **Power supply** | 5V 2.5A micro-USB (or USB-C for Pi 4) | ~$8--12 |

Optional: picture frame, 3D-printed stand, short USB cable for routing inside an enclosure.

---

## Advanced Configuration

### Full config reference

All fields are optional. Missing fields use defaults shown below.

```yaml
display:
  model: "epd7in5_V2"             # Waveshare model name
  # width: 800                    # override auto-derived width
  # height: 480                   # override auto-derived height
  enable_partial_refresh: false    # use partial eInk refresh (faster, lower quality)
  max_partials_before_full: 6     # partial refreshes before forcing a full one
  week_days: 7                    # number of days in the week view
  show_weather: true
  show_birthdays: true
  show_info_panel: true

google:
  service_account_path: "credentials/service_account.json"
  calendar_id: "primary"
  additional_calendars: []
  # contacts_email: "you@yourdomain.com"  # required for birthdays.source: "contacts"
  daily_quota_warning: 500         # log warning when daily API calls exceed this

  # ICS feed alternative — when set, service_account_path is ignored for events.
  # Get the URL: Google Calendar → Settings → [calendar] → "Secret address in iCal format"
  # ical_url: "https://calendar.google.com/calendar/ical/.../.../basic.ics"
  # additional_ical_urls: []

weather:
  api_key: ""
  latitude: 0.0
  longitude: 0.0
  units: "imperial"                # "imperial", "metric", or "standard"

purpleair:                         # optional — adds AQI card to the weather theme
  api_key: ""                      # get a free key at develop.purpleair.com
  sensor_id: 0                     # find at map.purpleair.com (click sensor → URL)

birthdays:
  source: "file"                   # "file", "calendar", or "contacts"
  file_path: "config/birthdays.json"
  calendar_keyword: "Birthday"
  lookahead_days: 30

schedule:
  quiet_hours_start: 23            # hour (0-23)
  quiet_hours_end: 6               # hour (0-23)

timezone: "local"                  # IANA name or "local"
title: "Home Dashboard"            # text shown in the header bar
theme: "default"                   # default | terminal | minimalist | old_fashioned | today | fantasy | qotd | qotd_invert | weather | fuzzyclock | fuzzyclock_invert | diags | random

random_theme:                      # only used when theme: random
  include: []                      # allowlist (empty = all themes eligible)
  exclude: []                      # denylist (e.g. ["fantasy", "qotd"])

# theme_schedule:                  # time-of-day theme switching (checked before random/config.theme)
#   - time: "06:00"                # HH:MM, 24-hour; active theme = last entry whose time <= now
#     theme: "default"
#   - time: "22:00"
#     theme: "fuzzyclock_invert"

cache:
  weather_ttl_minutes: 60          # data older than 4x TTL is discarded
  events_ttl_minutes: 120
  birthdays_ttl_minutes: 1440
  air_quality_ttl_minutes: 30
  weather_fetch_interval: 30       # skip API call if cache is younger
  events_fetch_interval: 120
  birthdays_fetch_interval: 1440
  air_quality_fetch_interval: 15
  max_failures: 3                  # circuit breaker: failures before tripping
  cooldown_minutes: 30             # circuit breaker: wait before probing
  quote_refresh: daily             # daily | twice_daily | hourly

filters:
  exclude_calendars: []            # case-insensitive substring match
  exclude_keywords: []             # case-insensitive match against event summary
  exclude_all_day: false

output:
  dry_run_dir: "output"

logging:
  level: "INFO"
```

### Cache and staleness

Cached data progresses through four levels based on age relative to its TTL:

| Level | Age vs TTL | Behaviour |
|---|---|---|
| **FRESH** | <= TTL | Normal display |
| **AGING** | 1--2x TTL | Normal display |
| **STALE** | 2--4x TTL | Header shows "! Stale" indicator |
| **EXPIRED** | > 4x TTL | Data discarded, not displayed |

### Fetch intervals

Each data source has an independent fetch interval. When cached data is younger than the
interval, the API call is skipped entirely. This reduces API quota usage significantly.

| Source | Default interval | Default TTL |
|---|---|---|
| Weather | 30 min | 60 min |
| Calendar events | 120 min | 120 min |
| Birthdays | 1440 min (24h) | 1440 min |
| Air quality (PurpleAir) | 15 min | 30 min |

### Event filtering

```yaml
filters:
  exclude_calendars: ["US Holidays", "Spam Calendar"]
  exclude_keywords: ["OOO", "Focus Time", "Block"]
  exclude_all_day: false
```

Filters use case-insensitive substring matching. Filtered events remain in cache for
incremental sync correctness -- they are only hidden at render time.

### Circuit breaker

After 3 consecutive failures (configurable), a source is "tripped" and goes straight to
cache on subsequent runs. After the cooldown period, a single probe request is sent. If it
succeeds, normal fetching resumes.
Use `--ignore-breakers` to bypass OPEN breaker state for one run (useful for manual recovery checks).

### Conditional display refresh

The dashboard computes a SHA-256 hash of each rendered image and compares it to the
previous render. When nothing has changed (common overnight or on quiet days), the eInk
refresh is skipped entirely. This extends display lifespan and saves power.
`--force-full-refresh` bypasses this check.

### Incremental calendar sync

After the first full sync, subsequent fetches download only changed events using Google
Calendar sync tokens. This dramatically reduces API quota usage. Sync state is persisted
to `output/calendar_sync_state.json`.

This applies to the **service account path only**. When using `ical_url`, the full feed
is re-fetched on every calendar refresh (no sync tokens — ICS has no equivalent mechanism).

---

## Troubleshooting and Recovery

### Fast checks

- Validate config only: `make check`
- See recent logs on Pi: `make pi-status` and `make pi-logs`
- Render without hardware: `make dry`

### Force a live refresh now

- `--force-full-refresh` bypasses fetch intervals and forces a full display refresh.
- If a source is blocked by an OPEN circuit breaker, also pass `--ignore-breakers`.

```bash
venv/bin/python -m src.main --dry-run --theme diags --force-full-refresh --ignore-breakers
```

### Circuit breaker behavior

- Repeated failures open the breaker for that source and fallback to cache.
- After cooldown, one probe request is allowed (`HALF_OPEN`).
- `--ignore-breakers` bypasses OPEN state for one run only; breaker state still persists.

---

## Development

### Prerequisites

- **Python 3.9+**
- **git**
- **make** (pre-installed on macOS/Linux; use WSL on Windows)

### Makefile targets

#### On-Pi targets

| Command | What it does |
|---|---|
| `make pi-install` | apt deps, SPI enable, Python venv, Waveshare drivers — full Pi setup in one command |
| `make configure` | Interactive wizard: fills `config/config.yaml` with your API keys and settings |
| `make pi-enable` | Generate and install systemd service (with correct paths) + enable timer |
| `make pi-status` | Show timer status, last service run, and recent log tail |
| `make pi-logs` | `tail -f output/dashboard.log` |

#### Dev targets

| Command | What it does |
|---|---|
| `make setup` | Create venv, install dependencies, create config from template |
| `make dry` | Render with dummy data to `output/latest.png` |
| `make test` | Run `pytest tests/ -v` across the full suite |
| `make check` | Validate config file and exit |
| `make version` | Print the current version (e.g. `main.py 4.1.0`) |
| `make deploy` | rsync project to Raspberry Pi (`PI_USER`, `PI_HOST`, `PI_DIR` configurable) |
| `make install` | Copy systemd timer/service to Pi and enable (legacy remote path) |

### CLI flags

| Flag | Description |
|---|---|
| `--dry-run` | Save to PNG instead of writing to display |
| `--dummy` | Use built-in dummy data (no API calls needed) |
| `--config PATH` | Config file path (default: `config/config.yaml`) |
| `--theme THEME` | Override the theme set in `config.yaml`. Choices: `default`, `terminal`, `minimalist`, `old_fashioned`, `today`, `fantasy`, `qotd`, `qotd_invert`, `weather`, `fuzzyclock`, `fuzzyclock_invert`, `diags`, `random` |
| `--date YYYY-MM-DD` | Override today's date for the dry-run preview (requires `--dry-run`) |
| `--force-full-refresh` | Force full eInk refresh and bypass fetch intervals |
| `--ignore-breakers` | Ignore OPEN circuit breakers for this run and attempt fetches anyway |
| `--check-config` | Validate config and exit |
| `--version` | Print version and exit |

### Offline development

```bash
venv/bin/python -m src.main --dry-run --dummy
```

No API keys, credentials, or hardware needed. Renders to `output/latest.png`.

### Linting

```bash
flake8 src/ tests/ --max-line-length=100
```

---

## Project Structure

```
Dashboard-v4/
├── config/
│   ├── config.example.yaml       # Configuration template
│   └── quotes.json               # Daily quote pool (125 entries)
├── credentials/                  # Git-ignored -- Google service account JSON
├── deploy/
│   ├── dashboard.service         # Systemd service template (paths filled by make pi-enable)
│   ├── dashboard.timer           # Systemd timer (fires every 5 min)
│   └── configure.sh              # Interactive config wizard (invoked by make configure)
├── fonts/                        # Bundled TTF fonts
├── output/                       # Mostly git-ignored
│   └── latest.png                # Latest dry-run preview (tracked)
├── src/
│   ├── main.py                   # Thin CLI entry point: parse args, load config, launch app
│   ├── app.py                    # Top-level dashboard run orchestration
│   ├── data_pipeline.py          # Live data fetching, cache fallback, breakers, quotas
│   ├── services_run_policy.py    # Quiet hours + morning full-refresh decisions
│   ├── services_theme_service.py # Theme resolution (including random theme selection)
│   ├── services_output_service.py# Dry-run writes, display refresh decisions, health marker
│   ├── _version.py               # Version constant (__version__ = "4.1.0")
│   ├── config.py                 # YAML -> typed Config dataclass + validation
│   ├── dummy_data.py             # Realistic dummy data for --dummy / dev previews
│   ├── filters.py                # Event filtering (calendar, keyword, all-day)
│   ├── data/
│   │   └── models.py             # Pure dataclasses (no I/O)
│   ├── display/
│   │   ├── driver.py             # DisplayDriver ABC, DryRunDisplay, WaveshareDisplay
│   │   └── refresh_tracker.py    # Partial vs full refresh state
│   ├── fetchers/
│   │   ├── calendar.py           # Google Calendar + incremental sync + birthdays
│   │   ├── weather.py            # OpenWeatherMap (current + forecast + alerts + UV)
│   │   ├── purpleair.py          # PurpleAir sensor → PM1 / PM2.5 / PM10 / AQI
│   │   ├── host.py               # System metrics via /proc (uptime, load, RAM, disk, CPU temp, IP)
│   │   ├── cache.py              # Per-source JSON cache with TTL staleness
│   │   ├── circuit_breaker.py    # Per-source circuit breaker
│   │   └── quota_tracker.py      # Daily API call counter
│   └── render/
│       ├── canvas.py             # Top-level render orchestrator (theme-driven)
│       ├── theme.py              # Theme system (ComponentRegion, ThemeLayout, ThemeStyle)
│       ├── random_theme.py       # Daily random theme selection + persistence
│       ├── layout.py             # Default pixel geometry constants
│       ├── fonts.py              # Font loader with @lru_cache
│       ├── icons.py              # OWM icon code -> Weather Icons glyph
│       ├── moon.py               # Pure-math moon phase calculator
│       ├── primitives.py         # Shared draw helpers (truncation, wrapping, fmt_time, events_for_day, deg_to_compass)
│       ├── themes/               # Built-in theme factories
│       │   ├── terminal.py
│       │   ├── minimalist.py
│       │   ├── old_fashioned.py
│       │   ├── today.py
│       │   ├── fantasy.py
│       │   ├── qotd.py
│       │   ├── qotd_invert.py
│       │   ├── weather.py
│       │   ├── fuzzyclock.py
│       │   ├── fuzzyclock_invert.py
│       │   └── diags.py
│       └── components/           # One file per UI region
│           ├── header.py
│           ├── week_view.py
│           ├── weather_panel.py
│           ├── weather_full.py
│           ├── birthday_bar.py
│           ├── today_view.py
│           ├── info_panel.py
│           ├── qotd_panel.py
│           ├── fuzzyclock_panel.py
│           └── diags_panel.py
├── tests/                        # Full test suite
├── Makefile
├── requirements.txt              # Core dependencies
└── requirements-pi.txt           # Raspberry Pi hardware dependencies
```

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
| [Playfair Display](https://fonts.google.com/specimen/Playfair+Display) | `old_fashioned` theme; `qotd` quote text |
| [Cinzel](https://fonts.google.com/specimen/Cinzel) | `fantasy` theme |

Custom fonts can be added per-theme via `ThemeStyle` font callables -- see
[Creating your own theme](#creating-your-own-theme) and [`CLAUDE.md`](CLAUDE.md).

---

## Dependencies

### Core (all platforms)

- [Pillow](https://pillow.readthedocs.io/) -- image rendering
- [google-api-python-client](https://googleapis.github.io/google-api-python-client/) -- Google Calendar and Contacts APIs
- [google-auth](https://google-auth.readthedocs.io/) -- service account authentication
- [requests](https://requests.readthedocs.io/) -- OpenWeatherMap API and ICS feed fetching
- [icalendar](https://icalendar.readthedocs.io/) -- ICS feed parsing (used when `ical_url` is set)
- [PyYAML](https://pyyaml.org/) -- configuration parsing

### Raspberry Pi only

- [RPi.GPIO](https://pypi.org/project/RPi.GPIO/) -- GPIO pin control
- [spidev](https://pypi.org/project/spidev/) -- SPI communication with display
