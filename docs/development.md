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
- [Adding a fetcher / theme / component](#adding-a-fetcher--theme--component)
- [Aware-datetime discipline](#aware-datetime-discipline)

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
- caldav — used by `src/fetchers/calendar_caldav.py` when `google.caldav_url` is configured
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

---

## Adding a fetcher / theme / component

v5 introduced three plugin registries that turn the v4 multi-file recipes into one-file
drop-ins. Reach for these patterns when you're extending the dashboard rather than
modifying it.

### New fetcher

1. Create `src/fetchers/my_source.py` and implement a fetch function that takes the
   relevant config object (or the full `Config`) and returns a serialisable value.
2. At the bottom of the module, register the adapter:

   ```python
   from src.fetchers.registry import Fetcher, register_fetcher

   def _ser(value): ...      # value → JSON-able primitives
   def _deser(blob): ...     # JSON-able → value

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

3. Add `from src.fetchers import my_source as _my_source  # noqa: F401` to
   `src/fetchers/__init__.py` so the side-effect import fires on package load.
4. Extend `DashboardData` in `src/data/models.py` if a new top-level field is needed.

The `DataPipeline`, cache layer, circuit breaker, quota tracker, and staleness tracker
all iterate the registry — no edits to `data_pipeline.py` or `cache.py` are required.
See `src/fetchers/calendar_caldav.py` plus the `_register()` block at the bottom of
`src/fetchers/calendar.py` for the v5 reference.

### New theme

1. Create `src/render/themes/my_theme.py` exporting a `my_theme() -> Theme` factory.
2. At the bottom of the module:

   ```python
   def _register() -> None:
       from src.render.theme import INKY_BLUE, INKY_RED
       from src.render.themes.registry import register_theme

       register_theme("my_theme", my_theme, inky_palette=(INKY_BLUE, INKY_RED))

   _register()
   ```

3. Add the module to `src/render/themes/__init__.py` so it's imported on package load.
4. Regenerate the pixel-hash baseline:

   ```bash
   UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py
   ```

   Commit the updated `tests/snapshots/theme_pixel_hashes.json` alongside the source.

New themes are automatically eligible for the random rotation pool. To exclude one
(utility / diagnostic views), add its name to `_EXCLUDED_FROM_POOL` in
`src/render/random_theme.py`. To author a greyscale theme, set `canvas_mode="L"` in
`ThemeLayout` and use `fg=0, bg=255` in `ThemeStyle`.

### New component

1. Create `src/render/components/my_panel.py` with `draw_my_panel(draw, data, region, style, ...)`.
2. Add a `ComponentRegion` to `ThemeLayout` in `src/render/theme.py` if the new component
   is full-canvas (otherwise reuse one of the existing regions).
3. Register an adapter in either of two places:

   - inside `my_panel.py` itself with the decorator form:

     ```python
     from src.render.components.registry import register_component, RenderContext

     @register_component("my_panel")
     def _adapter(ctx: RenderContext) -> None:
         draw_my_panel(ctx.draw, ctx.data, region=ctx.layout.my_panel, style=ctx.style)
     ```

   - or as an entry in `src/render/components/_builtins.py` if you'd rather keep
     adapter wrappers centralised next to the existing 25.
4. Add `"my_panel"` to the relevant theme's `draw_order`. No edits to `canvas.py`.

### New web-editable config field

1. Add the field to the relevant dataclass in `src/config.py` and parse it in
   `load_config`.
2. Add a sample value to `config/config.example.yaml`.
3. Add a `FieldSpec` entry to the appropriate `SectionSpec` in `src/config_schema.py`.
   Mark `secret=True` for credentials. The `editable_field_paths()` allowlist used by
   the web UI regenerates from the schema automatically.
4. If the field affects validation, extend `validate_config` in `src/config.py`.

### New web endpoint

1. Create `src/web/routes/my_route.py` with a `Blueprint("my_route", __name__)`.
2. Register the blueprint in `src/web/app.py`.
3. Mutating endpoints must call `csrf_protect()` from `src.web.csrf`. Clients
   (templates, tests) echo the session's CSRF token in the `X-CSRF-Token` header.

See `src/web/routes/preview.py` as the v5 reference.

---

## Aware-datetime discipline

All persistent timestamps in production code go through `src/_time.py`:

| Helper | Returns |
|---|---|
| `now_utc()` | aware UTC datetime |
| `now_local(tz)` | aware datetime in *tz* (UTC if `tz` is None) |
| `to_aware(value, tz)` | attaches *tz* (or UTC) to a naive datetime; passes aware values through |
| `assert_aware(value)` | raises `ValueError` on a naive value, returns it otherwise |

`tools/check_naive_datetime.py` is an AST-based CI guard that fails on `datetime.now()`
(no args) or `datetime.utcnow()` outside `src/_time.py`. The guard is enforced in CI by
`tests/test_naive_datetime_guard.py`. Run it locally with:

```bash
python tools/check_naive_datetime.py
```

Lines that genuinely want naive local wall-clock time (file-name timestamps,
quiet-hours config comparisons, test fallbacks) carry an `# allow-naive-datetime`
trailing comment. The guard tolerates the comment landing on a continuation line
when `ruff format` wraps the call across multiple physical lines.
