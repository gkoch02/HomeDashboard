# Contributing to Home Dashboard

Audience: contributors changing code, tests, or documentation.

Use this page for contribution workflow and guardrails. For architecture details, see [docs/architecture.md](docs/architecture.md). For day-to-day dev commands and repo layout, see [docs/development.md](docs/development.md).

## Local Setup

```bash
git clone https://github.com/gkoch02/HomeDashboard.git ~/home-dashboard
cd ~/home-dashboard
make setup
make dry
```

## Core Commands

```bash
make test         # run pytest
make coverage     # run pytest with coverage report (htmlcov/index.html)
make lint         # ruff check src/ tests/
make fmt          # ruff format src/ tests/
make dry          # preview with dummy data
make previews     # generate theme previews
make check        # validate config/config.yaml
make docs-check   # validate markdown links and theme inventories
```

## Contribution Rules

- Keep docs aligned with user-facing behavior when themes, setup flow, or config shape change.
- Prefer updating canonical docs instead of duplicating explanations across pages.
- Run `make lint`, `make test`, and `make docs-check` before opening a PR when your change touches code or docs.
- Do not document removed themes, deprecated config fields, or speculative behavior.

## Adding a Theme

v5 themes self-register via a `register_theme(...)` call at the bottom of their own
module — there is no central registry dict to edit.

1. Create `src/render/themes/my_theme.py`.
2. Return a `Theme` built from the current theme API:

```python
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def my_theme() -> Theme:
    style = ThemeStyle(
        fg=0,
        bg=1,
        invert_header=True,
        show_borders=True,
    )
    layout = ThemeLayout(
        header=ComponentRegion(0, 0, 800, 40),
        week_view=ComponentRegion(0, 40, 800, 320),
        weather=ComponentRegion(0, 360, 300, 120),
        birthdays=ComponentRegion(300, 360, 250, 120),
        info=ComponentRegion(550, 360, 250, 120),
        draw_order=["header", "week_view", "weather", "birthdays", "info"],
    )
    return Theme(name="my_theme", style=style, layout=layout)
```

3. At the bottom of the same module, register the theme and its Inky palette pair:

```python
def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_RED
    from src.render.themes.registry import register_theme

    register_theme("my_theme", my_theme, inky_palette=(INKY_BLUE, INKY_RED))

_register()
```

4. Add the module to `src/render/themes/__init__.py` so the side-effect import fires
   on package load.
5. If it should never appear in random rotation (utility / diagnostic views), add the
   name to `_EXCLUDED_FROM_POOL` in `src/render/random_theme.py`.
6. Regenerate the pixel-hash baseline — the snapshot guard fails on any unregistered
   theme:

```bash
UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py
```

   Commit the updated `tests/snapshots/theme_pixel_hashes.json` alongside the source.

7. If the theme is user-facing, update:
   - `docs/themes.md` (add a `#### <name>` section with a short description and both
     the Waveshare and Inky preview images — see existing entries for the pattern)
   - any theme lists in config or setup docs that are intended to be exhaustive
8. Regenerate the preview PNGs that `docs/themes.md` embeds — see
   [docs/previews.md](docs/previews.md) for the Waveshare and Inky commands.
   For a quick sanity check before committing previews:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme my_theme
```

For greyscale custom themes, set `ThemeLayout.canvas_mode = "L"` and use `fg=0, bg=255` in `ThemeStyle` (or `fg=255, bg=0` for a dark canvas — `bg=1` is near-black in L mode).

## Adding a Fetcher or Data Source

v5 fetchers self-register via a `register_fetcher(...)` call. The `DataPipeline`,
cache layer, circuit breaker, and quota tracker all iterate the registry — no edits
to `data_pipeline.py` or `cache.py` are required.

1. Create the fetcher module in `src/fetchers/` with a function that takes the
   relevant config (or the full `Config`) and returns a serialisable value.
2. Return typed data models from `src/data/models.py`; extend `DashboardData` if a
   new top-level field is needed.
3. At the bottom of the module, register the adapter:

```python
from src.fetchers.registry import Fetcher, register_fetcher

def _ser(value): ...   # value → JSON-able primitives
def _deser(blob): ...  # JSON-able → value

register_fetcher(Fetcher(
    name="my_source",
    fetch=lambda ctx: my_source_fetch(ctx.cfg.my_source, tz=ctx.tz),
    serialize=_ser,
    deserialize=_deser,
    ttl_minutes=lambda cfg: cfg.cache.my_source_ttl_minutes,
    interval_minutes=lambda cfg: cfg.cache.my_source_fetch_interval,
    enabled=lambda cfg: bool(cfg.my_source.api_key),
    log_success=lambda v: f"Fetched my_source: {v}",
))
```

4. Add `from src.fetchers import my_source as _my_source  # noqa: F401` to
   `src/fetchers/__init__.py` so the side-effect import fires.
5. Add tests that mock all external I/O.
6. Update operator docs if the source introduces new config or new UI behavior.

See `src/fetchers/calendar_caldav.py` plus the `_register()` block at the bottom of
`src/fetchers/calendar.py` as the v5 reference.

## Adding a Config Option

1. Add the field to the relevant dataclass in `src/config.py`.
2. Parse the YAML key in `load_config()` if needed.
3. Add validation in `validate_config()` when invalid input should be surfaced clearly.
4. Update `config/config.example.yaml`.
5. Update `docs/configuration.md` if the field is operator-facing.
6. Update any setup or web UI docs that depend on that field.

## Docs Update Policy

When changing any of these areas, update the canonical docs in the same PR:

- Theme inventory or behavior: `docs/themes.md` (which also embeds the preview images)
- Preview regeneration workflow: `docs/previews.md`
- Config schema or defaults: `docs/configuration.md`
- Setup, install, auth, or recovery flow: `README.md`, `docs/setup.md`, or `docs/web-ui.md`
- Contributor workflow or architecture: `docs/development.md`, `docs/architecture.md`, or `CLAUDE.md`

## Testing

- Use `pytest` with mocks for external APIs and file I/O.
- Use `tmp_path` for temporary files.
- Do not make real network calls in tests.
- Add or update documentation checks when you introduce a new exhaustive list.
- Coverage is enforced at ≥90% via `pytest-cov` (`fail_under` in `pyproject.toml`); current coverage is ~99%. Run `make coverage` to see missing lines and an HTML report at `htmlcov/index.html`. New defensive branches should ship with tests.
- Theme changes shift the pixel-hash snapshots in `tests/snapshots/theme_pixel_hashes.json`. If the diff is intentional, regenerate with `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py` and commit the updated JSON alongside the source change. Adding a new theme also requires a fresh baseline — the coverage guard test fails without one.

## PR Checklist

- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] `make fmt` leaves no changes
- [ ] `make docs-check` passes when docs or user-facing behavior changed
- [ ] Tests were added or updated for behavior changes
- [ ] Canonical docs were updated for any user-facing change
