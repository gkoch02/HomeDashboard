← [README](../README.md)

# Upgrading from v3

v4 is a drop-in upgrade. Your existing credentials and `config.yaml` work without changes.

Pick the path that matches your setup:

- **Option A** — you run the dashboard directly on the Pi (most common)
- **Option B** — you develop on a separate machine and deploy to the Pi via `make deploy`

---

## Option A: Upgrade directly on the Pi

SSH into your Pi. Your v3 installation is likely in `~/home-dashboard`.

### 1. Clone v4 alongside v3

```bash
# On the Pi
git clone https://github.com/gkoch02/HomeDashboard.git ~/home-dashboard-v4
```

### 2. Copy your config and credentials from v3

```bash
# On the Pi
cp ~/home-dashboard/config/config.yaml   ~/home-dashboard-v4/config/config.yaml
cp ~/home-dashboard/credentials/service_account.json ~/home-dashboard-v4/credentials/service_account.json

# If you had a birthdays.json, copy that too:
cp ~/home-dashboard/config/birthdays.json ~/home-dashboard-v4/config/birthdays.json 2>/dev/null
```

### 3. Swap directories

```bash
# On the Pi
mv ~/home-dashboard ~/home-dashboard-v3-backup
mv ~/home-dashboard-v4 ~/home-dashboard
cd ~/home-dashboard
```

### 4. Install dependencies

```bash
# On the Pi — ~/home-dashboard
make pi-install
```

### 5. (Optional) Clear stale v3 cache files

v4 auto-migrates the runtime state files from `output/` to `state/` on the first run,
so you do **not** need to move anything by hand. Only run this step if you want a
fully clean cache and image-hash on first boot:

```bash
# On the Pi — ~/home-dashboard
rm -f output/calendar_cache.json output/weather_cache.json \
      output/birthday_cache.json output/calendar_sync_state.json \
      output/last_image_hash.txt
```

### 6. Validate and test

```bash
# On the Pi — ~/home-dashboard
make check          # validate config
make dry            # render a preview with dummy data
```

### 7. Re-enable the systemd timer

```bash
# On the Pi — ~/home-dashboard
make pi-enable      # reinstall systemd timer (unit file has changed in v4)
make pi-status      # confirm the timer is active
```

You can delete `~/home-dashboard-v3-backup` once you're satisfied everything works.

---

## Option B: Upgrade on a dev machine, then deploy to the Pi

All commands below run on your **dev machine** unless noted otherwise.

### 1. Clone v4

```bash
git clone https://github.com/gkoch02/HomeDashboard.git
cd HomeDashboard
```

### 2. Copy your config and credentials from v3

```bash
cp /path/to/Dashboard-v3/config/config.yaml config/config.yaml
cp /path/to/Dashboard-v3/credentials/service_account.json credentials/service_account.json

# If you had a birthdays.json, copy that too:
cp /path/to/Dashboard-v3/config/birthdays.json config/birthdays.json
```

### 3. Install dependencies and validate

```bash
make setup
make check
make dry            # render a preview with dummy data
```

### 4. Deploy to the Pi

```bash
make deploy         # rsync to pi@dashboard:~/home-dashboard
```

Then SSH into the Pi to finish setup. v4 auto-migrates runtime state from `output/`
to `state/` on the first run, so the manual `rm` step is **optional** — include it
only if you want a clean cache:

```bash
# On the Pi — ~/home-dashboard
# Optional clean-cache step:
rm -f output/calendar_cache.json output/weather_cache.json \
      output/birthday_cache.json output/calendar_sync_state.json \
      output/last_image_hash.txt

make pi-install     # install system deps and rebuild the venv
make pi-enable      # reinstall systemd timer (unit file has changed in v4)
make pi-status      # confirm the timer is active
```

---

## What's new in v4.1

Your existing config is fully compatible. These are opt-in additions:

| Feature | How to enable |
|---|---|
| **PurpleAir air quality** | Add `purpleair.api_key` and `purpleair.sensor_id` to `config.yaml`; an AQI card (EPA index from 60-minute PM2.5 average) appears in the `weather` theme metric row, and a PM1 · PM2.5 · PM10 µg/m³ breakdown appears in the detail strip |
| **ICS feed calendar (no GCP)** | Set `google.ical_url` to your calendar's "Secret address in iCal format" URL — no service account or GCP project needed; supports multiple calendars via `additional_ical_urls` |
| **Configurable quote refresh** | Set `cache.quote_refresh` to `daily` (default), `twice_daily`, or `hourly` to control how often the displayed quote rotates; uses a stable date-based hash so the same time slot always shows the same quote |
| **State directory** | Runtime state files (cache, circuit breaker, sync tokens, random theme state) now live in `state/` instead of `output/`. Existing files are auto-migrated on first run — no manual action needed |
| **Tooling** | `pyproject.toml` for project metadata; `ruff` for linting/formatting (`make lint`, `make fmt`); GitHub Actions CI; `.pre-commit-config.yaml` |

---

## What's new in v4

Your existing config is fully compatible. These are opt-in additions:

| Feature | How to enable |
|---|---|
| **Versioning** (`--version` flag) | Run `python -m src.main --version` or `make version` to print the current version |
| **Themes** (built-in layouts) | Set `theme: <theme_name>` in `config.yaml`, or pass `--theme THEME` on the command line. See [Themes](themes.md) for the current live theme catalog. |
| **Random theme rotation** | Set `theme: random_daily` (once per day) or `theme: random_hourly` (once per hour); optionally add a `random_theme:` block to include/exclude specific themes |
| **Event filtering** | Add a `filters:` block — hide events by calendar name, keyword, or all-day status |
| **Configurable cache TTLs** | Add a `cache:` block to tune per-source TTL and fetch intervals |
| **Circuit breaker tuning** | `cache.max_failures` and `cache.cooldown_minutes` |
| **API quota warnings** | `google.daily_quota_warning: 500` logs a warning when calls exceed the threshold |
| **`--check-config` flag** | Validate config and exit without running the dashboard |
| **`--force-full-refresh` flag** | Bypass fetch intervals and force a full eInk refresh for a one-off run |
| **`--ignore-breakers` flag** | Ignore OPEN circuit breakers for one run and attempt live fetches anyway |
