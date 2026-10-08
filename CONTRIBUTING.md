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
make lint         # ruff check src/ tests/ scripts/ tools/
make fmt          # ruff format src/ tests/ scripts/ tools/
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

The full recipe — module, registration, snapshot baseline, previews, catalog entries,
greyscale and partial-refresh rules, fonts — lives in
[Development → New theme](docs/development.md#new-theme).

## Adding a Fetcher or Data Source

v5 fetchers self-register via a `register_fetcher(...)` call. The cache layer,
circuit breaker, and quota tracker all iterate the registry, so `cache.py` needs no
edit; a new `DashboardData` field still needs its line in `DataPipeline.fetch()`.

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

- Theme inventory or behavior: `docs/themes.md` (which embeds the monochrome Waveshare
  previews) **and** `docs/inky-previews.md` (the Spectra 6 color catalog) — `make docs-check`
  holds both to the theme registry
- Preview regeneration workflow: `docs/previews.md`
- Config schema or defaults: `docs/configuration.md`
- Setup, install, auth, or recovery flow: `README.md`, `docs/setup.md`, or `docs/web-ui.md`
- Contributor workflow or architecture: `docs/development.md`, `docs/architecture.md`, or `CLAUDE.md`

## Testing

- Use `pytest` with mocks for external APIs and file I/O.
- Use `tmp_path` for temporary files.
- Do not make real network calls in tests.
- Add or update documentation checks when you introduce a new exhaustive list.
- Coverage is enforced at ≥94% via `pytest-cov` (`fail_under` in `pyproject.toml`); current coverage is ~98%. Run `make coverage` to see missing lines and an HTML report at `htmlcov/index.html`. New defensive branches should ship with tests.
- Theme changes shift the pixel-hash snapshots in `tests/snapshots/theme_pixel_hashes.json`. If the diff is intentional, regenerate with `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py` and commit the updated JSON alongside the source change. Adding a new theme also requires a fresh baseline — the coverage guard test fails without one.

## Releasing

Do not hand-edit the version. It lives only in `src/_version.py` (`pyproject.toml`
reads it dynamically), and releases are cut with:

```bash
make release-dry        # show the plan
make release            # bump, date the changelog, commit, tag
```

The bump size is inferred from the `## [Unreleased]` changelog block — a
`### Added`/`### Changed`/`### Deprecated`/`### Removed` section means minor,
`### Fixed`/`### Security` alone means patch, and major must be asked for with
`make release RELEASE_ARGS="--major"`. So the thing to keep current in a PR is
the **`## [Unreleased]` entry**; the version number follows from it at release
time. See [Releasing](docs/development.md#releasing).

## PR Checklist

Opening a PR seeds this from [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md),
which also covers the conditional steps (snapshots, previews, config, changelog).

- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] `make fmt` leaves no changes
- [ ] `python -m mypy src/` is clean
- [ ] `make docs-check` passes when docs or user-facing behavior changed
- [ ] Tests were added or updated for behavior changes
- [ ] Canonical docs were updated for any user-facing change
