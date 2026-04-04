# Contributing to Dashboard-v4

## Local Setup

```bash
git clone <repo-url> && cd Dashboard-v4
make setup              # creates venv, installs deps, copies config template
make dry                # preview with dummy data → output/latest.png
```

## Development Commands

```bash
make test               # run pytest
make lint               # ruff check src/ tests/
make fmt                # ruff format src/ tests/
make dry                # preview with dummy data
make previews           # generate all theme previews
make check              # validate config/config.yaml
```

## Code Style

- **Max line length**: 100 characters
- **Formatter**: ruff format (configured in `pyproject.toml`)
- **Linter**: ruff check with rules E, F, W, I (isort), UP (pyupgrade)
- **Imports**: stdlib → third-party → local (`src.*`), sorted by ruff
- **Type annotations**: use `from __future__ import annotations` for forward refs; prefer `X | None` over `Optional[X]`

Run `make lint` and `make fmt` before committing.

## Project Structure

```
src/
├── main.py                     # CLI entry point
├── app.py                      # DashboardApp orchestrator
├── config.py                   # YAML config → dataclasses
├── data_pipeline.py            # Concurrent fetch orchestration
├── data/models.py              # Pure dataclasses (no I/O)
├── fetchers/                   # Data source adapters
│   ├── calendar.py             # Dispatcher + birthday extraction
│   ├── calendar_google.py      # Google Calendar API + sync
│   ├── calendar_ical.py        # ICS feed fetching
│   ├── weather.py              # OpenWeatherMap
│   ├── purpleair.py            # PurpleAir sensor
│   ├── host.py                 # System metrics
│   ├── cache.py                # Per-source JSON cache
│   ├── circuit_breaker.py      # Per-source circuit breaker
│   └── quota_tracker.py        # Daily API call counter
├── services/                   # Orchestration policy
│   ├── run_policy.py           # Quiet hours, morning startup
│   ├── theme.py                # Theme name resolution
│   └── output.py               # Publish image, health marker
├── display/                    # Display hardware abstraction
│   ├── driver.py               # DryRunDisplay, WaveshareDisplay
│   └── refresh_tracker.py      # Partial/full refresh tracking
└── render/                     # Rendering system
    ├── canvas.py               # Top-level render orchestrator
    ├── theme.py                # Theme registry + dataclasses
    ├── themes/                 # One file per theme
    ├── components/             # One file per UI region
    ├── random_theme.py         # Daily/hourly random selection
    ├── fonts.py                # Font loader
    ├── primitives.py           # Shared draw utilities
    └── icons.py                # Weather icon mapping

tests/                          # pytest tests (mirrors src/ structure)
state/                          # Runtime state (gitignored)
output/                         # PNGs, logs (gitignored except latest.png)
```

See [docs/architecture.md](docs/architecture.md) for detailed data flow and design decisions.

## How to Add a Theme

1. Create `src/render/themes/my_theme.py`
2. Implement a factory function:
   ```python
   from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

   def my_theme() -> Theme:
       style = ThemeStyle(bg_color="white", fg_color="black", ...)
       layout = ThemeLayout(
           canvas_width=800, canvas_height=480,
           header=ComponentRegion(0, 0, 800, 40),
           week=ComponentRegion(0, 40, 560, 380),
           weather=ComponentRegion(560, 40, 240, 200),
           info=ComponentRegion(560, 240, 240, 180),
           draw_order=["header", "week", "weather", "info"],
       )
       return Theme(name="my_theme", style=style, layout=layout)
   ```
3. Register in `src/render/theme.py`:
   ```python
   _THEME_REGISTRY["my_theme"] = ("src.render.themes.my_theme", "my_theme")
   ```
4. Add to `AVAILABLE_THEMES` (automatic from registry)
5. To exclude from random rotation, add to `_EXCLUDED_FROM_POOL` in `random_theme.py`
6. Run `make dry -- --theme my_theme` to preview

## How to Add a Fetcher/Data Source

1. Create `src/fetchers/my_source.py`
   - Use `requests` with a timeout for external APIs
   - Return a dataclass from `data/models.py`
2. Add the model to `data/models.py` if needed
3. Add cache serialization in `cache.py` (`save_source`/`load_cached_source`)
4. Integrate into `data_pipeline.py`:
   - Add TTL/interval to `__init__`
   - Add to `_launch_fetches` and `_resolve_source` flow
5. Add to `DashboardData` if it's a new field
6. See `purpleair.py` as a reference implementation

## How to Add a Config Option

1. Add field to the relevant dataclass in `config.py` (with a default)
2. Add parsing in `load_config()` if the YAML key differs from the field name
3. Add validation in `validate_config()` if applicable
4. Add to `config/config.example.yaml` with a comment
5. Use in the relevant module

## Testing

- Tests use `pytest` with `unittest.mock.patch`
- Each public function should have at least one test
- Use `tmp_path` fixture for files, not real directories
- Mock external APIs — never make real network calls in tests
- Run `make test` to verify all tests pass

## PR Checklist

- [ ] `make test` passes (all tests green)
- [ ] `make lint` passes (no ruff errors)
- [ ] `make fmt` produces no changes (code formatted)
- [ ] New features have tests
- [ ] CLAUDE.md updated if module structure changed
- [ ] `config.example.yaml` updated if new config options added
