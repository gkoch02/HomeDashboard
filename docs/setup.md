← [README](../README.md)

# Setup Guide

- [Google Calendar Setup](#google-calendar-setup)
- [ICS Feed (No GCP Required)](#ics-feed-no-gcp-required)
- [Birthday Configuration](#birthday-configuration)
- [PurpleAir Air Quality (Optional)](#purpleair-air-quality-optional)
- [Photo Theme (Optional)](#photo-theme-optional)
- [Raspberry Pi Reference](#raspberry-pi-reference)
- [Web UI (Optional)](web-ui.md)
- [Supported Displays](#supported-displays)
- [Hardware](#hardware)
- [Troubleshooting and Recovery](#troubleshooting-and-recovery)
- [Symptom-driven troubleshooting](#symptom-driven-troubleshooting)
- [Next steps](#next-steps)

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

## PurpleAir Air Quality (Optional)

Display real-time air quality data from a [PurpleAir](https://www.purpleair.com/) sensor.
AQI data appears in the `weather` theme (compact card) and the `air_quality` theme
(full-screen dashboard). This is entirely optional — the dashboard works fine without it.

### Step 1 — Get an API key

1. Go to [develop.purpleair.com](https://develop.purpleair.com/) and create an account
2. Request a **Read** API key (free for personal use)

### Step 2 — Find your sensor ID

1. Go to [map.purpleair.com](https://map.purpleair.com/)
2. Click on the sensor you want to monitor
3. The sensor ID is the number in the URL (e.g. `map.purpleair.com/...?select=12345` → sensor ID is `12345`)

### Step 3 — Add to config.yaml

```yaml
purpleair:
  api_key: "YOUR_PURPLEAIR_API_KEY"
  sensor_id: 12345
```

The sensor is polled at the interval set by `cache.air_quality_fetch_interval` (default:
15 minutes). Data is cached for `cache.air_quality_ttl_minutes` (default: 30 minutes).

If either `api_key` or `sensor_id` is missing or empty, the source is silently skipped —
no errors, no circuit breaker entry.

---

## Photo Theme (Optional)

Display a custom image as a full-canvas wallpaper instead of dashboard data. Useful for
ambient frames, art rotations, or seasonal wallpapers.

### Step 1 — Pick an image

Any JPEG or PNG works. Higher-resolution sources dither more cleanly than ones already
near the display's native resolution. The image is automatically resized to fit the
canvas (LANCZOS), so you do not need to pre-crop it.

Copy the file somewhere persistent on the Pi, for example:

```bash
mkdir -p ~/dashboard-photos
cp ~/Downloads/family-portrait.jpg ~/dashboard-photos/
```

### Step 2 — Enable the theme in config.yaml

```yaml
theme: photo
photo:
  path: "/home/pi/dashboard-photos/family-portrait.jpg"
```

That's it — the next refresh will paint the dithered photo across the full display. The
photo theme renders edge-to-edge with no header bar.

### How rendering works

| Backend | Pipeline |
|---|---|
| `waveshare` | Greyscale → resize → Floyd-Steinberg dither to 1-bit black/white |
| `inky` | Greyscale + saturation blending → resize → Spectra 6 palette mapping |

Dark-canvas variants invert the greyscale source so bright regions of the photo stay
white on the eInk panel rather than rendering as solid black.

### Tips

- Portraits and high-contrast scenes dither best on Waveshare's 1-bit panel.
- For Inky Spectra 6, photos with naturally warm or limited palettes (sunsets, sepia
  prints) match the panel's color gamut more faithfully than full-color modern photos.
- Run `venv/bin/python -m src.main --dry-run --dummy --theme photo` to preview the
  dithered output in `output/latest.png` before deploying to the Pi. (`make dry` does
  not pass through `--theme`, so invoke the module directly when overriding the theme.)
- The `photo` theme is **excluded** from the random rotation pool — pick it explicitly
  via `theme: photo` rather than relying on randomization.

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

### Step 4 -- Display drivers

Install the package that matches your `display.provider`:

#### Waveshare

```bash
git clone --depth=1 https://github.com/waveshare/e-Paper /tmp/waveshare-epd
venv/bin/pip install /tmp/waveshare-epd/RaspberryPi_JetsonNano/python/
venv/bin/python -c "import waveshare_epd; print('OK')"
```

#### Pimoroni Inky Impression

```bash
venv/bin/pip install inky
```

On Raspberry Pi OS Bookworm (and later), the kernel SPI driver claims the chip-select
pin (GPIO8) which conflicts with the Inky library's lgpio usage.  Release it with:

```bash
echo "dtoverlay=spi0-0cs" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

On older Pi OS the config file is `/boot/config.txt` instead.

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
| All other active hours | Waveshare refreshes only when image content changes; Inky also applies a one-refresh-per-hour cap except for `fuzzyclock` themes; API calls remain gated by per-source fetch intervals |

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

| Provider | Model | Resolution | Notes |
|---|---|---|---|
| `waveshare` | `epd7in5` | 640x384 | V1 (older) |
| `waveshare` | `epd7in5_V2` | 800x480 | **Default / recommended Waveshare** |
| `waveshare` | `epd7in5_V3` | 800x480 | V3 variant |
| `waveshare` | `epd7in5b_V2` | 800x480 | B/W/Red model; dashboard currently renders B/W only |
| `waveshare` | `epd7in5_HD` | 880x528 | HD variant |
| `waveshare` | `epd9in7` | 1200x825 | 9.7 inch |
| `waveshare` | `epd13in3k` | 1600x1200 | 13.3 inch |
| `inky` | `impression_7_3_2025` | 800x480 | Pimoroni Inky Impression 7.3" 2025 Edition, Spectra 6 |

Set both `display.provider` and `display.model` in `config.yaml`. Width and height are
derived automatically from the selected backend/model. The dashboard renders at 800x480 base
resolution and scales to the display's native resolution when needed. Inky Impression panels
do not support partial refresh; non-fuzzyclock themes are therefore throttled to one hardware
update per hour unless `--force-full-refresh` is used.

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

See [CLI flags](development.md#cli-flags) for the full flag reference.

### Circuit breaker behavior

- Repeated failures open the breaker for that source and fallback to cache.
- After cooldown, one probe request is allowed (`HALF_OPEN`).
- `--ignore-breakers` bypasses OPEN state for one run only; breaker state still persists.

---

## Symptom-driven troubleshooting

For symptom-driven diagnostics ("weather isn't loading", "calendar shows no events",
"display isn't updating", staleness badges, and so on), see the
[FAQ](faq.md#general). The pointers below cover only the recovery actions specific
to v4's runtime state files.

### Reset cached data or sync state

State files live in `state/` (auto-migrated from `output/` on the first v4 run):

- `state/dashboard_cache.json` — per-source data cache
- `state/calendar_sync_state.json` — Google Calendar incremental sync token
- `state/dashboard_breaker_state.json` — circuit breaker state

Delete the file matching the symptom to start that piece of state from scratch on
the next run. The image-hash marker `output/last_image_hash.txt` lives in `output/`
(it is a render artifact, not state) — delete it to force the next run to re-push
the image to the display even if the content hasn't changed.

---

## Next steps

- Tune `config/config.yaml` — see the [Configuration Reference](configuration.md).
- Pick or schedule a theme — see [Themes](themes.md).
- Optionally enable the [Web UI](web-ui.md) for browser-based status and config edits.
