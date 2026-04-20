← [README](../README.md)

# Web UI

The dashboard includes an optional web interface hosted directly on the Pi. It has grown past a simple status page: it now acts as a lightweight control panel for day-to-day checks, safe configuration edits, and quick recovery actions without SSH.

- [Overview](#overview)
- [Installation](#installation)
- [Configuration (web.yaml)](#configuration-webyaml)
- [Authentication](#authentication)
- [Pages and features](#pages-and-features)
- [Manual refresh](#manual-refresh)
- [Accessing the UI](#accessing-the-ui)
- [Mobile support](#mobile-support)
- [Logs and events](#logs-and-events)
- [Running without systemd](#running-without-systemd)
- [Security considerations](#security-considerations)

---

## Overview

| Feature | Detail |
|---|---|
| URL | `http://<pi-hostname>:8080` (default port) |
| Framework | Flask 3 + Waitress WSGI server |
| Auth | HTTP Basic Auth (optional but strongly recommended) |
| CSRF protection | Enabled for all mutating actions (`POST`/`PUT`/`PATCH`/`DELETE`) |
| Dependencies | `flask`, `waitress` (see `requirements-web.txt`) |
| Systemd unit | `dashboard-web.service` (persistent background process) |
| Trigger unit | `dashboard-trigger.path` (watch file for manual refresh) |

The web server is a **separate process** from the dashboard renderer. It reads runtime state from disk, edits the dashboard config through a safe allowlist, and never writes to the eInk display directly.

---

## Installation

### Step 1 — Install web dependencies

On the Pi (inside the project directory):

```bash
venv/bin/pip install -r requirements-web.txt
```

Or equivalently:

```bash
venv/bin/pip install flask waitress
```

### Step 2 — Create web.yaml

```bash
cp config/web.example.yaml config/web.yaml
```

Edit `config/web.yaml` to set your port, credentials, and `secret_key` (see [Configuration](#configuration-webyaml) below).

### Step 3 — Set a password and session secret

```bash
venv/bin/python -m src.web.auth --set-password
```

Enter your chosen password. Copy the printed hash into `config/web.yaml`, and also set a random `secret_key` for Flask session/CSRF handling:

```yaml
secret_key: "replace-me-with-a-random-secret"
auth:
  username: "admin"
  password_hash: "scrypt:..."
```

Use a long random value for `secret_key` on any persistent install.

### Step 4 — Install and start the systemd service

```bash
make web-enable
```

This substitutes the correct paths into `deploy/dashboard-web.service` and `deploy/dashboard-trigger.path`, installs both units, and starts them immediately.

Verify everything is running:

```bash
make web-status
```

---

## Configuration (web.yaml)

`config/web.yaml` is separate from `config/config.yaml`. It controls the web server itself — not the dashboard rendering. The file is git-ignored.

```yaml
# Port to listen on (default: 8080)
port: 8080

# Bind address.
#   0.0.0.0   — accept connections from anywhere on the LAN (default)
#   127.0.0.1 — localhost only; access via SSH tunnel
host: "0.0.0.0"

# Optional Flask session secret used for CSRF/session handling.
# Set this explicitly for persistent deployments.
secret_key: "replace-me-with-a-random-secret"

# HTTP Basic Auth. Leave password_hash empty for open access (not recommended).
auth:
  username: "admin"
  password_hash: "scrypt:..."   # generate with: python -m src.web.auth --set-password
```

To change the port after installation, edit `web.yaml` and restart the service:

```bash
sudo systemctl restart dashboard-web.service
```

---

## Authentication

HTTP Basic Auth is used. Credentials are checked on every request.

**Generating a password hash:**

```bash
venv/bin/python -m src.web.auth --set-password
```

Passwords are hashed with `scrypt` (N=2¹⁵, r=8, p=1, 32-byte key) — intentionally slow to resist brute-force.

**No credentials configured:** the server starts with a warning in the log and all routes are publicly accessible. Suitable only for a trusted local network.

The status page also shows an **auth disabled** banner when the UI is exposed without credentials.

---

## Pages and features

### Status page (`/`)

The main landing page. Refreshes automatically every 30 seconds.

| Section | What it shows |
|---|---|
| **System Health** | Overall dashboard state (healthy / degraded / paused / needs attention) with short issue summaries |
| **Theme Resolution** | Effective theme, configured theme, theme mode (fixed / randomized / scheduled), and next scheduled change |
| **Quick Troubleshooting** | Likely causes when data is stale, auth is open, quiet hours are active, or no successful run has been recorded |
| **Integration Readiness** | Whether key dependencies appear configured: OpenWeather, Google credentials, calendar/ICS, birthdays source, PurpleAir |
| **Recent Events** | Structured recent actions/history (refresh requested, config saved, breaker reset, cache cleared, config restored) |
| **Latest image** | Live preview of `output/latest.png` (refreshed every 60 s) |
| **Data Sources** | Per-source table: breaker state, cache age, staleness, quota usage, and human-readable summary |
| **System** | Uptime, load average, RAM, disk, CPU temperature, IP address |
| **Log tail** | Last 100 lines of `output/dashboard.log` |

The **Refresh Now** button in the Data Sources card header triggers an immediate dashboard run (see [Manual refresh](#manual-refresh)). If quiet hours are currently active, clicking Refresh Now shows a confirmation dialog with the active window's start and end times before proceeding. If the live image has not rendered yet, the page shows an explicit empty-state hint instead of a dead-looking blank area.

Each source row also has:
- **Reset** — reset the circuit breaker to `closed` (asks for confirmation before proceeding)
- **Clear** — remove cached data for that source so the next refresh fetches live data again (asks for confirmation before proceeding)

### Config page (`/config`)

A browser editor for `config/config.yaml`. Changes are validated server-side before saving — the same validation that runs at startup.

| Section | What it does |
|---|---|
| **Basic / Advanced mode** | Basic mode hides most operator-only knobs; Advanced mode exposes cache tuning and schedule controls |
| **General** | Title, timezone, log level |
| **Theme** | Dropdown + visual thumbnail grid |
| **Display Appearance** | Show/hide panels, week days, partial refresh settings |
| **Sleep / Quiet Hours** | Start and end hour |
| **Weather & Location** | Latitude, longitude, units |
| **Birthdays** | Source, lookahead days, calendar keyword |
| **Calendar & Event Filters** | Exclude calendars, exclude keywords, exclude all-day |
| **Advanced: Cache & Intervals** | TTLs, fetch intervals, circuit breaker settings, quote refresh |
| **Advanced: Random Theme Pool** | Include/exclude theme lists |
| **Advanced: Theme Schedule** | Time-based theme switching (add/remove rows) |
| **Credential Status (read-only)** | Which API keys / credentials appear configured |
| **Change Summary** | Shows unsaved changes at a glance while you edit |
| **Config Backups** | Lists recent backups and allows restoring the latest one |
| **Save Review Dialog** | Shows a diff-style Before / After confirmation before Save or Save + Refresh |

Additional config-page behavior:

- **Save** first opens a review dialog showing the changed fields and their before/after values, then validates the patch before writing.
- **Save + Refresh** uses the same review step, then writes config and requests a dashboard refresh.
- Fatal validation errors block the save and are shown inline with a red border on the offending field.
- Warnings are shown but do not block saving.
- **Unsaved-change indicator**: an "unsaved changes" badge and **Discard** button appear as soon as the first edit is made; both clear automatically on successful save. Clicking Discard reloads all fields from `/api/config` and reverts any edits (asks for confirmation first).
- Navigating away from the page with unsaved changes triggers a browser `beforeunload` warning.
- Existing config backups are rotated instead of silently overwritten.
- **Theme thumbnail grid**: click a thumbnail to select a theme; double-click to open a full-size preview in a native dialog overlay (click the backdrop or ✕ to close). A hint below the grid reminds you of this.
- **Quiet hours context hint**: a live status hint below the quiet-hours inputs shows whether quiet hours are currently active (updated from the 30-second status poll — no extra requests).
- **Theme schedule**: duplicate times are detected client-side and flagged before the form is submitted.
- **Latitude / Longitude**: HTML5 `min`/`max` constraints enforce valid ranges (−90–90 / −180–180) directly in the browser.

**Sensitive fields** (API keys, credential file paths) are never sent to the browser. The credentials section shows only whether each credential is set or missing.

---

## Manual refresh

Clicking **Refresh Now** on the status page causes the web server to touch `state/web_trigger`. The `dashboard-trigger.path` systemd unit watches for this file and immediately starts `dashboard.service`. The dashboard run deletes the trigger file when it finishes, ready for the next request.

This approach requires no `sudo` and no inter-process communication — it is purely file-based.

If the trigger file appears but nothing happens, check that `dashboard-trigger.path` is enabled:

```bash
sudo systemctl status dashboard-trigger.path
```

---

## Accessing the UI

### Same network

Navigate to `http://<pi-hostname>:8080` from any browser on the same network. The Pi hostname is typically `raspberrypi.local` (mDNS) or whatever you set in `raspi-config`.

```text
http://raspberrypi.local:8080
http://192.168.1.42:8080    # by IP
```

### SSH tunnel (more secure)

If you set `host: "127.0.0.1"` in `web.yaml`, the server accepts local connections only. Access it remotely via an SSH tunnel:

```bash
ssh -L 8080:localhost:8080 pi@raspberrypi.local
```

Then open `http://localhost:8080` in your browser. The tunnel closes when you exit the SSH session.

---

## Mobile support

The UI is fully responsive and works on phones and tablets.

- **Navigation**: on screens narrower than 600 px, the nav links collapse behind a hamburger menu (☰). Tap to toggle; tapping outside the menu or navigating away closes it automatically.
- **Touch targets**: buttons use enlarged minimum tap areas; card hover effects are suppressed on touch screens.
- **Config page**: a scrollable pill row of section anchors appears on mobile so you can jump directly to any section without scrolling.
- **Theme grid**: switches to a 2-column CSS grid on mobile instead of a wrapping flex row.

---

## Logs and events

| File | Content |
|---|---|
| `output/dashboard-web.log` | Web server access and error log |
| `output/dashboard.log` | Dashboard renderer log (also shown in the Status page UI) |
| `state/web_events.jsonl` | Structured web UI event history used by the Recent Events card |

View the web server log:

```bash
make web-logs           # tail -f output/dashboard-web.log
make web-status         # systemd status + recent log tail
```

### Event store (`state/web_events.jsonl`)

`state/web_events.jsonl` is an append-only audit log written by `src/web/event_store.py`.
It records every UI-initiated action — manual refresh requests, config saves, breaker
resets, cache clears, and config restores — one JSON object per line.

```json
{"timestamp": "2026-04-20T15:32:11+00:00", "kind": "config_saved",
 "message": "Saved 3 changes from /config", "details": {"fields": ["theme", "title"]}}
```

A few operator notes:

- **Retention is unbounded.** The file only grows. Rotate or truncate it manually if it
  becomes unwieldy. `state/` is on the same disk as the rest of the project, so a runaway
  log can fill the SD card on small Pi installs.
- **It is sensitive but not user-attributed.** The file logs *what* changed (e.g.
  "saved theme: minimalist") and the field set involved, but it does **not** record
  the authenticated username — basic-auth gates access at the request boundary and
  is not threaded into `append_event`. Don't rely on this log for per-user
  accountability in shared deployments. Treat it with the same care as `web.yaml`:
  do not commit it, do not paste it into bug reports without redaction.
- **It is best-effort.** Write failures are logged at DEBUG level and silently swallowed
  so a missing/unwritable `state/` directory never breaks the UI.
- **It is read-truncated.** The status page's "Recent Events" card only loads the most
  recent ~20 entries; the full file is preserved untouched.

---

## Running without systemd

For quick testing or development without installing the systemd unit:

```bash
venv/bin/python -m src.web \
    --config config/web.yaml \
    --app-config config/config.yaml \
    --port 8080
```

If `waitress` is installed it is used automatically. Otherwise Flask's built-in dev server is used (suitable for local testing only — not recommended for persistent use).

Override the port inline without editing `web.yaml`:

```bash
venv/bin/python -m src.web --port 9000
```

---

## Security considerations

- **Use a password.** Anyone on your local network can reach port 8080 by default.
- **Set `secret_key` in `web.yaml`.** This protects Flask session integrity and CSRF token handling.
- **CSRF protection is enabled for mutating routes.** Browser clients must send the UI-provided CSRF token for config saves and action buttons.
- **The config editor can modify `config.yaml`.** It cannot touch API keys or credential file paths (those are never sent to the browser), but it can change dashboard behavior, theme, filters, cache timings, and schedules.
- **The Refresh Now button triggers a dashboard run.** It cannot execute arbitrary commands.
- **No HTTPS.** Traffic is unencrypted. For remote access outside your LAN, use an SSH tunnel or a reverse proxy with TLS (for example nginx + Let's Encrypt).
- **`config/web.yaml` contains your password hash and possibly your session secret.** The file is git-ignored. Do not commit it.
- **`state/web_events.jsonl` is an unbounded audit log.** It records every UI action and grows forever; rotate it manually if it gets large. Treat it as sensitive — see [Event store](#event-store-stateweb_eventsjsonl).
