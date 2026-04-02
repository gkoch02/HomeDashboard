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

### Dev targets

| Command | What it does |
|---|---|
| `make setup` | Create venv, install dependencies, create config from template |
| `make dry` | Render with dummy data to `output/latest.png` |
| `make previews` | Generate preview PNGs for all themes to `output/theme_*.png` |
| `make test` | Run `pytest tests/ -v` across the full suite |
| `make check` | Validate config file and exit |
| `make version` | Print the current version (e.g. `main.py 4.1.1`) |
| `make deploy` | rsync project to Raspberry Pi (`PI_USER`, `PI_HOST`, `PI_DIR` configurable) |
| `make install` | Copy systemd timer/service to Pi and enable (legacy remote path) |

---

## CLI flags

| Flag | Description |
|---|---|
| `--dry-run` | Save to PNG instead of writing to display |
| `--dummy` | Use built-in dummy data (no API calls needed) |
| `--config PATH` | Config file path (default: `config/config.yaml`) |
| `--theme THEME` | Override the theme set in `config.yaml`. Choices: `default`, `terminal`, `minimalist`, `old_fashioned`, `today`, `fantasy`, `moonphase`, `moonphase_invert`, `qotd`, `qotd_invert`, `weather`, `air_quality`, `fuzzyclock`, `fuzzyclock_invert`, `diags`, `random_daily`, `random_hourly` |
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

## Linting

```bash
flake8 src/ tests/ --max-line-length=100
```

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
├── output/                       # Mostly git-ignored
│   └── latest.png                # Latest dry-run preview (tracked)
├── src/
│   ├── main.py                   # Thin CLI entry point: parse args, load config, launch app
│   ├── app.py                    # Top-level dashboard run orchestration
│   ├── data_pipeline.py          # Live data fetching, cache fallback, breakers, quotas
│   ├── services_run_policy.py    # Quiet hours + morning full-refresh decisions
│   ├── services_theme_service.py # Theme resolution (including random theme selection)
│   ├── services_output_service.py# Dry-run writes, display refresh decisions, health marker
│   ├── _version.py               # Version constant (__version__ = "4.1.1")
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
│       ├── random_theme.py       # Daily/hourly random theme selection + persistence
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
│       │   ├── moonphase.py
│       │   ├── moonphase_invert.py
│       │   ├── qotd.py
│       │   ├── qotd_invert.py
│       │   ├── weather.py
│       │   ├── air_quality.py
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
│           ├── air_quality_panel.py
│           ├── moonphase_panel.py
│           └── diags_panel.py
├── tests/                        # Full test suite
├── Makefile
├── requirements.txt              # Core dependencies
└── requirements-pi.txt           # Raspberry Pi hardware dependencies
```

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
- [lgpio](https://pypi.org/project/lgpio/) -- Linux GPIO interface (required by modern Pi OS)
- [gpiozero](https://pypi.org/project/gpiozero/) -- GPIO zero abstraction layer (pin factory set to lgpio)
