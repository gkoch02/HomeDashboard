← [README](../README.md)

# Web UI

The dashboard includes an optional web interface hosted directly on the Pi. It provides
a read-only status view and a configuration editor — no SSH or file editing required for
day-to-day adjustments.

- [Overview](#overview)
- [Installation](#installation)
- [Configuration (web.yaml)](#configuration-webyaml)
- [Authentication](#authentication)
- [Pages and features](#pages-and-features)
- [Manual refresh](#manual-refresh)
- [Accessing the UI](#accessing-the-ui)
- [Logs](#logs)
- [Running without systemd](#running-without-systemd)
- [Security considerations](#security-considerations)

---

## Overview

| Feature | Detail |
|---|---|
| URL | `http://<pi-hostname>:8080` (default port) |
| Framework | Flask 3 + Waitress WSGI server |
| Auth | HTTP Basic Auth (optional but recommended) |
| Dependencies | `flask`, `waitress` (see `requirements-web.txt`) |
| Systemd unit | `dashboard-web.service` (persistent background process) |
| Trigger unit | `dashboard-trigger.path` (watch file for manual refresh) |

The web server is a **separate process** from the dashboard renderer. It reads state files
and config directly from disk and never writes to the eInk display itself.

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

Edit `config/web.yaml` to set your port and credentials (see
[Configuration](#configuration-webyaml) below).

### Step 3 — Set a password

```bash
venv/bin/python -m src.web.auth --set-password
```

Enter your chosen password. Copy the printed hash into `config/web.yaml`:

```yaml
auth:
  username: "admin"
  password_hash: "scrypt:..."
```

### Step 4 — Install and start the systemd service

```bash
make web-enable
```

This substitutes the correct paths into `deploy/dashboard-web.service` and
`deploy/dashboard-trigger.path`, installs both units, and starts them immediately.

Verify everything is running:

```bash
make web-status
```

---

## Configuration (web.yaml)

`config/web.yaml` is separate from `config/config.yaml`. It controls the web server
itself — not the dashboard rendering. The file is git-ignored.

```yaml
# Port to listen on (default: 8080)
port: 8080

# Bind address.
#   0.0.0.0   — accept connections from anywhere on the LAN (default)
#   127.0.0.1 — localhost only; access via SSH tunnel
host: "0.0.0.0"

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

Passwords are hashed with `scrypt` (N=2¹⁵, r=8, p=1, 32-byte key) — intentionally slow
to resist brute-force.

**No credentials configured:** the server starts with a warning in the log and all routes
are publicly accessible. Suitable for a trusted local network only.

---

## Pages and features

### Status page (`/`)

The main landing page. Refreshes automatically every 30 seconds.

| Section | What it shows |
|---|---|
| **Last run** | Timestamp and age of the most recent successful dashboard run |
| **Current theme** | Active theme name |
| **Latest image** | Live preview of `output/latest.png` (refreshed every 60 s) |
| **Data sources** | Per-source table: circuit breaker state, cache age, staleness level, quota usage today |
| **System** | Uptime, load average, RAM, disk, CPU temperature, IP address |
| **Log tail** | Last 100 lines of `output/dashboard.log` |

The **Refresh Now** button in the Data Sources card header triggers an immediate dashboard
run (see [Manual refresh](#manual-refresh)).

Each source row also has **Reset** (reset circuit breaker to closed) and **Clear**
(remove cached data) buttons for quick recovery without SSH.

### Config page (`/config`)

A full editor for `config/config.yaml`. Changes are validated server-side before saving —
the same validation that runs at startup.

| Section | Editable fields |
|---|---|
| General | Title, timezone, log level |
| Theme | Dropdown + visual thumbnail grid |
| Display | Show/hide panels, week days, partial refresh settings |
| Quiet Hours | Start and end hour |
| Weather & Location | Latitude, longitude, units |
| Birthdays | Source, lookahead days, calendar keyword |
| Event Filters | Exclude calendars, exclude keywords, exclude all-day |
| Cache & Intervals | TTLs, fetch intervals, circuit breaker settings, quote refresh |
| Random Theme Pool | Include/exclude lists |
| Theme Schedule | Time-based theme switching (add/remove rows) |
| Credentials Status | Read-only badges: which API keys and credentials are configured |

**Sensitive fields** (API keys, credential file paths) are never sent to the browser.
The credentials section shows only whether each credential is set (✓) or missing (✗).

**Save** validates the patch through `validate_config()` before writing. Fatal errors block
the save and are displayed inline. Warnings are shown but do not block saving.

---

## Manual refresh

Clicking **Refresh Now** on the status page causes the web server to touch
`state/web_trigger`. The `dashboard-trigger.path` systemd unit watches for this file
and immediately starts `dashboard.service`. The dashboard run deletes the trigger file
when it finishes, ready for the next request.

This approach requires no `sudo` and no inter-process communication — it is purely
file-based.

If the trigger file appears but nothing happens, check that `dashboard-trigger.path`
is enabled:

```bash
sudo systemctl status dashboard-trigger.path
```

---

## Accessing the UI

### Same network

Navigate to `http://<pi-hostname>:8080` from any browser on the same network. The Pi's
hostname is typically `raspberrypi.local` (mDNS) or whatever you set in `raspi-config`.

```
http://raspberrypi.local:8080
http://192.168.1.42:8080    # by IP
```

### SSH tunnel (more secure)

If you set `host: "127.0.0.1"` in `web.yaml`, the server only accepts local connections.
Access it remotely via an SSH tunnel:

```bash
ssh -L 8080:localhost:8080 pi@raspberrypi.local
```

Then open `http://localhost:8080` in your browser. The tunnel closes when you exit the
SSH session.

---

## Logs

| Log file | Content |
|---|---|
| `output/dashboard-web.log` | Web server access and error log |
| `output/dashboard.log` | Dashboard renderer log (also shown in the Status page UI) |

View the web server log:

```bash
make web-logs           # tail -f output/dashboard-web.log
make web-status         # systemd status + recent log tail
```

---

## Running without systemd

For quick testing or development without installing the systemd unit:

```bash
venv/bin/python -m src.web \
    --config config/web.yaml \
    --app-config config/config.yaml \
    --port 8080
```

If `waitress` is installed it is used automatically. Otherwise Flask's built-in dev
server is used (suitable for local testing only — not recommended for persistent use).

Override the port inline without editing `web.yaml`:

```bash
venv/bin/python -m src.web --port 9000
```

---

## Security considerations

- **Use a password.** Anyone on your local network can reach port 8080 by default.
- **The config editor can modify `config.yaml`.** It cannot touch API keys or credentials
  (those are never sent to the browser), but it can change your theme, timezone, filter
  settings, etc.
- **The Refresh Now button triggers a dashboard run.** It cannot execute arbitrary commands.
- **No HTTPS.** Traffic is unencrypted. For remote access outside your LAN, use an SSH
  tunnel or a reverse proxy with TLS (e.g. nginx + Let's Encrypt).
- **`config/web.yaml` contains your password hash.** The file is git-ignored. Do not
  commit it.
