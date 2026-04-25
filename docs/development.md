← [README](../README.md)

# Development

Audience: contributors and maintainers.

Use this page for local workflow, dev commands, and repo orientation. For architecture details, see [Architecture](architecture.md). For contribution rules, see [Contributing](../CONTRIBUTING.md).

- [Prerequisites](#prerequisites)
- [Core Commands](#core-commands)
- [CLI flags](#cli-flags)
- [Offline development](#offline-development)
- [Preview workflow](#preview-workflow)
- [Project structure](#project-structure)
- [Dependencies](#dependencies)

---

## Prerequisites

- Python 3.9+
- `git`
- `make`

---

## Core Commands

| Command | What it does |
|---|---|
| `make setup` | create venv, install deps, create config from template |
| `make dry` | render `output/latest.png` with dummy data |
| `make previews` | generate standard theme preview PNGs |
| `make test` | run the full pytest suite |
| `make coverage` | run pytest with coverage; prints missing lines and writes `htmlcov/index.html` |
| `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py` | regenerate theme pixel-hash baselines after an intentional theme change (commit the updated `tests/snapshots/theme_pixel_hashes.json`) |
| `make lint` | run `ruff check src/ tests/` |
| `make fmt` | run `ruff format src/ tests/` |
| `make check` | validate `config/config.yaml` |
| `make docs-check` | validate markdown links and doc theme inventories |
| `make version` | print the app version |

Pi/operator commands such as `make pi-install`, `make pi-enable`, and `make web-enable` are documented for operators in [Setup Guide](setup.md) and [Web UI](web-ui.md).

---

## CLI flags

| Flag | Description |
|---|---|
| `--dry-run` | save to PNG instead of writing to display |
| `--dummy` | use built-in dummy data |
| `--config PATH` | custom config file path |
| `--theme THEME` | override the configured theme |
| `--message TEXT` | text for the `message` theme |
| `--date YYYY-MM-DD` | override the render date for dry runs |
| `--force-full-refresh` | bypass normal refresh suppression |
| `--ignore-breakers` | bypass OPEN circuit breakers for one run |
| `--check-config` | validate config and exit |
| `--version` | print version and exit |

---

## Offline development

```bash
venv/bin/python -m src.main --dry-run --dummy
```

This path needs no hardware, API keys, or credentials.

---

## Preview workflow

- Use `make dry` for the default dummy preview.
- Use `make previews` for the batch of standard preview PNGs.
- Use [Theme Previews](previews.md) when you need to regenerate the Waveshare or Inky preview PNGs that are embedded in [Themes](themes.md).

---

## Project structure

```text
home-dashboard/
├── config/          # example config, web config template, bundled quotes
├── deploy/          # systemd units and setup helpers
├── docs/            # operator and contributor docs
├── fonts/           # bundled fonts
├── output/          # previews, logs, and image-hash marker
├── state/           # runtime state (cache, breaker, sync tokens, theme state)
├── src/             # application code
├── tests/           # pytest suite
├── CONTRIBUTING.md
├── CLAUDE.md
├── Makefile
└── pyproject.toml
```

Key code areas:

- `src/config.py` for config parsing and validation
- `src/data_pipeline.py` for fetch orchestration
- `src/services/` for runtime policy
- `src/render/` for theme registry, rendering, and preview output
- `src/web/` for the optional Web UI

---

## Dependencies

### Core

- Pillow
- google-api-python-client
- google-auth
- requests
- icalendar
- PyYAML
- numpy — required at runtime by the Inky driver and the palette-quantize fast path

### Development

- ruff
- pytest
- pytest-cov (coverage gate: ≥90%, configured in `pyproject.toml`)
- mypy

### Optional

- Flask and Waitress for the Web UI
- Raspberry Pi display dependencies from `requirements-pi.txt`
