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

3. Register the theme in `src/render/theme.py` by adding it to `_THEME_REGISTRY`.
4. If it should never appear in rotation, add it to `_EXCLUDED_FROM_POOL` in `src/render/random_theme.py`.
5. If the theme is user-facing, update:
   - `docs/themes.md`
   - `docs/color-themes.md` if it has a gallery preview
   - any theme lists in config or setup docs that are intended to be exhaustive
6. Generate previews and confirm they render cleanly:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme my_theme
```

For greyscale custom themes, set `ThemeLayout.canvas_mode = "L"` and use `fg=0, bg=255` in `ThemeStyle`.

## Adding a Fetcher or Data Source

1. Create the fetcher module in `src/fetchers/`.
2. Return typed data models from `src/data/models.py`.
3. Add cache serialization support in `src/fetchers/cache.py`.
4. Integrate the source into `src/data_pipeline.py`.
5. Extend `DashboardData` if the source becomes part of the render pipeline.
6. Add tests that mock all external I/O.
7. Update operator docs if the source introduces new config or new UI behavior.

## Adding a Config Option

1. Add the field to the relevant dataclass in `src/config.py`.
2. Parse the YAML key in `load_config()` if needed.
3. Add validation in `validate_config()` when invalid input should be surfaced clearly.
4. Update `config/config.example.yaml`.
5. Update `docs/configuration.md` if the field is operator-facing.
6. Update any setup or web UI docs that depend on that field.

## Docs Update Policy

When changing any of these areas, update the canonical docs in the same PR:

- Theme inventory or behavior: `docs/themes.md`
- Preview gallery content: `docs/color-themes.md`
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
