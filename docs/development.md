← [README](../README.md)

# Development

- [Prerequisites](#prerequisites)
- [Makefile targets](#makefile-targets)
- [CLI flags](#cli-flags)
- [Offline development](#offline-development)
- [Linting](#linting)
- [Project structure](#project-structure)
- [Dependencies](#dependencies)

---

## Prerequisites

- **Python 3.9+**
- **git**
- **make** (pre-installed on macOS/Linux; use WSL on Windows)

---

## Makefile targets

### On-Pi targets

| Command | What it does |
|---|---|
| `make pi-install` | apt deps, SPI enable, Python venv, Waveshare drivers — full Pi setup in one command |
| `make configure` | Interactive wizard: fills `config/config.yaml` with your API keys and settings |
| `make pi-enable` | Generate and install systemd service (with correct paths) + enable timer |
| `make pi-status` | Show timer status, last service run, and recent log tail |
| `make pi-logs` | `tail -f output/dashboard.log` |
| `make web-enable` | Install and start the web UI systemd service + trigger path unit |
| `make web-status` | Show web service status and recent web log tail |
| `make web-logs` | `tail -f output/dashboard-web.log` |

### Dev targets

| Command | What it does |
|---|---|
| `make setup` | Create venv, install dependencies, create config from template |
| `make dry` | Render with dummy data to `output/latest.png` |
| `make previews` | Generate preview PNGs for all themes to `output/theme_*.png` |
| `make test` | Run `pytest tests/ -v` across the full suite |
| `make lint` | Run `ruff check src/ tests/` |
| `make fmt` | Run `ruff format src/ tests/` |
| `make check` | Validate config file and exit |
| `make version` | Print the current version (e.g. `main.py 4.3.1`) |
| `make deploy` | rsync project to Raspberry Pi (`PI_USER`, `PI_HOST`, `PI_DIR` configurable) |
| `make install` | Copy systemd timer/service to Pi and enable (legacy remote path) |

---

## CLI flags

| Flag | Description |
|---|---|
| `--dry-run` | Save to PNG instead of writing to display |
| `--dummy` | Use built-in dummy data (no API calls needed) |
| `--config PATH` | Config file path (default: `config/config.yaml`) |
| `--theme THEME` | Override the theme set in `config.yaml`. Choices: `default`, `terminal`, `minimalist`, `old_fashioned`, `today`, `fantasy`, `moonphase`, `moonphase_invert`, `qotd`, `qotd_invert`, `weather`, `air_quality`, `fuzzyclock`, `fuzzyclock_invert`, `diags`, `message`, `random`, `random_daily`, `random_hourly` |
| `--message TEXT` | Text to display when using the `message` theme |
| `--date YYYY-MM-DD` | Override today's date for the dry-run preview (requires `--dry-run`) |
| `--force-full-refresh` | Force full eInk refresh and bypass fetch intervals |
| `--ignore-breakers` | Ignore OPEN circuit breakers for this run and attempt fetches anyway |
| `--check-config` | Validate config and exit |
| `--version` | Print version and exit |

---

## Offline development

```bash
venv/bin/python -m src.main --dry-run --dummy
```

No API keys, credentials, or hardware needed. Renders to `output/latest.png`.

---

## Linting and formatting

```bash
make lint               # ruff check src/ tests/
make fmt                # ruff format src/ tests/
```

Ruff is configured in `pyproject.toml` with rules E, F, W, I (isort), and UP (pyupgrade).
Max line length is 100. Pre-commit hooks are available via `.pre-commit-config.yaml`.

---

## Project structure

```
Dashboard-v4/
├── config/
│   ├── config.example.yaml       # Configuration template
│   └── quotes.json               # Daily quote pool (144 entries)
├── credentials/                  # Git-ignored -- Google service account JSON
├── deploy/
│   ├── dashboard.service         # Systemd service template (paths filled by make pi-enable)
│   ├── dashboard.timer           # Systemd timer (fires every 5 min)
│   ├── dashboard.logrotate       # Logrotate config template (paths filled by make pi-enable)
│   └── configure.sh              # Interactive config wizard (invoked by make configure)
├── fonts/                        # Bundled TTF fonts
├── state/                        # Git-ignored -- runtime state (cache, breaker, quota, sync tokens)
├── output/                       # Git-ignored (except latest.png) -- PNGs, logs, health marker
│   └── latest.png                # Latest dry-run preview (tracked)
├── src/
│   ├── main.py                   # Thin CLI entry point: parse args, load config, launch app
│   ├── app.py                    # Top-level dashboard run orchestration
│   ├── data_pipeline.py          # Live data fetching, cache fallback, breakers, quotas
│   ├── services/
│   │   ├── run_policy.py         # Quiet hours + morning full-refresh decisions
│   │   ├── theme.py              # Theme resolution (including random theme selection)
│   │   └── output.py             # Dry-run writes, display refresh decisions, health marker
│   ├── _version.py               # Version constant (__version__ = "4.1.3")
│   ├── config.py                 # YAML -> typed Config dataclass + validation
│   ├── dummy_data.py             # Realistic dummy data for --dummy / dev previews
│   ├── filters.py                # Event filtering (calendar, keyword, all-day)
│   ├── data/
│   │   └── models.py             # Pure dataclasses (no I/O)
│   ├── display/
│   │   ├── driver.py             # DisplayDriver ABC, DryRunDisplay, WaveshareDisplay
│   │   └── refresh_tracker.py    # Partial vs full refresh state
│   ├── fetchers/
│   │   ├── calendar.py           # Dispatcher: routes to Google API or ICS; birthday extraction
│   │   ├── calendar_google.py    # Google Calendar API -- full sync, incremental sync, sync state
│   │   ├── calendar_ical.py      # ICS feed fetching and parsing
│   │   ├── weather.py            # OpenWeatherMap (current + forecast + alerts)
│   │   ├── purpleair.py          # PurpleAir sensor → PM1 / PM2.5 / PM10 / AQI
│   │   ├── host.py               # System metrics via /proc (uptime, load, RAM, disk, CPU temp, IP)
│   │   ├── cache.py              # Per-source JSON cache with TTL staleness
│   │   ├── circuit_breaker.py    # Per-source circuit breaker
│   │   └── quota_tracker.py      # Daily API call counter
│   └── render/
│       ├── canvas.py             # Top-level render orchestrator (theme-driven)
│       ├── theme.py              # Theme system (ComponentRegion, ThemeLayout, ThemeStyle)
│       ├── quantize.py           # Final L→"1" quantization (threshold / floyd_steinberg / ordered)
│       ├── random_theme.py       # Daily/hourly random theme selection + persistence
│       ├── layout.py             # Default pixel geometry constants
│       ├── fonts.py              # Font loader with @lru_cache
│       ├── icons.py              # OWM icon code -> Weather Icons glyph
│       ├── moon.py               # Pure-math moon phase calculator
│       ├── primitives.py         # Shared draw helpers (truncation, wrapping, fmt_time, events_for_day, deg_to_compass)
│       ├── themes/               # Built-in theme factories
│       └── components/           # One file per UI region
├── tests/                        # Full test suite (1580+ tests)
├── docs/                         # User and contributor documentation
│   ├── architecture.md           # Data flow, module layers, design decisions
│   └── ...
├── CONTRIBUTING.md               # Local setup, code style, how to add themes/fetchers
├── pyproject.toml                # Project metadata, dependencies, tool config (ruff, pytest, mypy)
├── Makefile
├── requirements.txt              # Core dependencies (kept for Pi deployment compat)
└── requirements-pi.txt           # Raspberry Pi hardware dependencies
```

For a detailed walkthrough of data flow and module boundaries, see [Architecture](architecture.md).

---

## Dependencies

### Core (all platforms)

- [Pillow](https://pillow.readthedocs.io/) -- image rendering
- [google-api-python-client](https://googleapis.github.io/google-api-python-client/) -- Google Calendar and Contacts APIs
- [google-auth](https://google-auth.readthedocs.io/) -- service account authentication
- [requests](https://requests.readthedocs.io/) -- OpenWeatherMap API and ICS feed fetching
- [icalendar](https://icalendar.readthedocs.io/) -- ICS feed parsing (used when `ical_url` is set)
- [PyYAML](https://pyyaml.org/) -- configuration parsing

### Development

- [ruff](https://docs.astral.sh/ruff/) -- linting and formatting
- [pytest](https://docs.pytest.org/) -- test framework
- [mypy](https://mypy-lang.org/) -- optional static type checking

Install dev tools with: `pip install -e ".[dev]"` (uses `pyproject.toml` optional deps).

### Raspberry Pi only

- [RPi.GPIO](https://pypi.org/project/RPi.GPIO/) -- GPIO pin control
- [spidev](https://pypi.org/project/spidev/) -- SPI communication with display
- [lgpio](https://pypi.org/project/lgpio/) -- Linux GPIO interface (required by modern Pi OS)
- [gpiozero](https://pypi.org/project/gpiozero/) -- GPIO zero abstraction layer (pin factory set to lgpio)

### Web UI (optional)

- [Flask](https://flask.palletsprojects.com/) 3.x -- web framework
- [Waitress](https://docs.pylonsproject.org/projects/waitress/) -- pure-Python WSGI server (Pi-friendly, no C extensions)

Install with `pip install -r requirements-web.txt` or `pip install -e ".[web]"`.
For current setup, remember that `config/web.yaml` should now include a `secret_key` in addition to any optional Basic Auth credentials. See [Web UI](web-ui.md) for current setup and security instructions.
