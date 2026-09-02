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

- Python 3.10+
- `git`
- `make`

---

## Core Commands

| Command | What it does |
|---|---|
| `make setup` | create venv, install deps, create config from template |
| `make dry` | render `output/latest.png` with dummy data |
| `make previews` | generate the monochrome Waveshare theme preview PNGs |
| `make previews-inky` | generate the Inky Spectra 6 theme preview PNGs |
| `make test` | run the full pytest suite |
| `make coverage` | run pytest with coverage; prints missing lines and writes `htmlcov/index.html` |
| `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py` | regenerate theme pixel-hash baselines after an intentional theme change (commit the updated `tests/snapshots/theme_pixel_hashes.json`) |
| `make lint` | run `ruff check src/ tests/ scripts/ tools/` |
| `make fmt` | run `ruff format src/ tests/ scripts/ tools/` |
| `make check` | validate `config/config.yaml` |
| `make docs-check` | validate markdown links and doc theme inventories |
| `make version` | print the app version |
| `make release-dry` | show what the next release would be — writes nothing |
| `make release` | cut a release: bump the version, date the changelog, commit, tag |

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
- Use `make previews` for the batch of monochrome Waveshare PNGs embedded in [Themes](themes.md).
- Use `make previews-inky` for the Spectra 6 PNGs embedded in [Inky Previews](inky-previews.md).
- See [Theme Previews](previews.md) for flags, the pinned render date, and single-theme renders.

---

## Releasing

The version lives in **one** place: `src/_version.py`. `pyproject.toml` reads it
via `[tool.setuptools.dynamic]`, so there is no second copy to keep in sync —
`pip install .` and `make version` resolve the same string.

Cut a release with one command:

```bash
make release-dry        # show the plan, write nothing
make release            # bump, date the changelog, commit, tag
git push -u origin HEAD && git push origin v<new-version>
```

`scripts/release.py` does four things that used to be four manual edits:

1. bumps `src/_version.py`
2. renames the `## [Unreleased]` changelog heading to `## [X.Y.Z] - <today>` and
   opens a fresh empty `## [Unreleased]` above it
3. commits both files as `Release X.Y.Z`
4. creates the annotated tag `vX.Y.Z`

It refuses to run on a dirty working tree, on an existing tag, or when the new
version would not be greater than the current one. Pushing stays manual.

If any of those steps fails partway — a rejecting pre-commit hook, a tag that
cannot be created — the script restores `src/_version.py`, `CHANGELOG.md` and
`HEAD` to their pre-release state before re-raising, so you can fix the cause
and simply re-run. Without that, a failure left the version bumped and the
`## [Unreleased]` block already rolled into a dated section, and the retry
failed with a misleading "the `## [Unreleased]` block is empty". The rollback
deliberately does not use `git reset --hard`: `--allow-dirty` means the tree
may hold unrelated work, so only the two files the script owns are rewritten
and unstaged.

### How the bump size is chosen

The size is inferred from the `### ...` headings in the `## [Unreleased]` block,
following [Keep a Changelog](https://keepachangelog.com/):

| Unreleased contains | Bump |
|---|---|
| `Added`, `Changed`, `Deprecated`, or `Removed` | minor |
| only `Fixed` and/or `Security` | patch |

**Major is never inferred.** "Is this breaking?" is not a question the headings
can answer, so it has to be asked for: `make release RELEASE_ARGS="--major"`.
Any bump can be forced the same way — `--minor`, `--patch`, or
`--version 6.0.0`. An empty `## [Unreleased]` block is an error rather than a
silent patch bump; write the entries first.

### The guard

`tests/test_version_consistency.py` fails the build when the release invariants
drift: `pyproject.toml` restating a literal version, `__version__` not being
semver, the newest changelog entry disagreeing with `__version__`, an undated
newest entry, or a missing `## [Unreleased]` heading. Forgetting to bump is
caught by CI instead of noticed three releases later. `tests/test_release_script.py`
covers the script itself — bump inference, the happy path, and each of the three
failure paths — by driving the real script against throwaway git repos.

---

## Project structure

```text
home-dashboard/
├── assets/previews/ # committed per-theme preview PNGs (docs/themes.md + docs/inky-previews.md)
├── config/          # example config, web config template, bundled quotes
├── deploy/          # systemd units and setup helpers
├── docs/            # operator and contributor docs
├── fonts/           # bundled fonts (see CLAUDE.md → Bundled fonts for the catalog)
├── output/          # runtime artefacts (latest.png, dry-run scratch capped at the newest
│                   #   20 dashboard_*.png, logs, image-hash marker)
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
`src/render/random_theme.py`.

Partial-refresh capability needs no declaration: `Theme.allows_partial_refresh` derives
it from the plate, declining when the theme dithers (`preferred_quantization_mode` of
`floyd_steinberg` / `ordered`, or a dithered `background_fn`) or its `ThemeStyle.bg` is
ink. `ThemeLayout.supports_partial_refresh` defaults to `None` and exists only to overrule
that; see [Adding a Theme](../CONTRIBUTING.md#adding-a-theme). To author a greyscale theme, set `canvas_mode="L"` in
`ThemeLayout` and use `fg=0, bg=255` in `ThemeStyle` (or invert that polarity to
`fg=255, bg=0` for a dark canvas — see `constellation_map` for the white-on-black
reference).

If the theme uses an OFL display font that isn't already in `fonts/`, drop the
`.ttf` and the upstream `OFL.txt` license file into `fonts/` (named
`<Family>-OFL.txt`, matching the flat layout there), add an accessor to
`src/render/fonts.py`, and reference it via `style.font_title` /
`style.font_section_label` / `style.font_date_number` (see `light_cycle`'s
Righteous numeral, `almanac`'s Astloch masthead, or `constellation_map`'s
Audiowide labels).

**Don't ship a font without its license** — `tests/test_font_licenses.py`
enforces this in both directions, and the rule is a licence condition rather
than housekeeping: OFL 1.1 §2 requires the license text to accompany any
redistribution, so a face bundled without its `OFL.txt` is a compliance failure
in every clone and `make deploy` rsync. The suite also reads each font's own
`name` table and fails a face that asserts no *licence* of its own — a licence
description (nameID 13), a licence URL (14), or a grant stated inside the
copyright string. That second check is the one that matters when evaluating a
font found on a design-portfolio site: a sibling license file only proves
someone put a file there, whereas the embedded record is the font's own claim
about its terms. A face that makes no claim cannot be redistributed under this
project's MIT grant, however good it looks.

Note the bar is a licence and not a copyright. `Copyright (c) 2025 Foo` with
both licence fields empty states who owns the font, not what anyone may do with
it, so it fails. Two bundled families legitimately land there — Astloch and
Tangerine are OFL upstream but ship builds that predate the convention of
filling nameID 13/14 — and each is listed in `GRANT_VERIFIED_UPSTREAM` in the
test module with the URL where the grant was read. Adding an entry means
checking upstream yourself; it is not a way to quiet a font you have not
verified.

Also add the family to the bundled-typeface table in the **Third-party content**
section of `LICENSE`. If it is variable, pin the weight explicitly in the
accessor — several variable fonts default to a thin axis instance (Oxanium's is
ExtraLight 200), and an unpinned accessor renders as near-invisible hairlines on
the panel.

**Removing a font needs one extra grep.** `scripts/build_banner.py` is a
standalone script that deliberately does not import `src/render/fonts.py`; it
loads its faces by bare filename, so it is the only place a deleted `.ttf` can
still be referenced after every accessor is gone. Nothing imports it and no test
runs it, so a dangling reference stays invisible until someone runs
`make banner`. Grep the whole tree for the filename, not just for its accessor,
and regenerate `assets/banner.png` if the banner's own faces changed.

If the theme should be embedded in the docs, regenerate both preview sets —
`make previews` for the Waveshare PNG that `docs/themes.md` embeds, and
`make previews-inky` for the color PNG that `docs/inky-previews.md` embeds.
`make docs-check` fails if either page is missing an entry for the new theme.
All preview PNGs live under `assets/previews/`.

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
     adapter wrappers centralised next to the existing built-in registrations.
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
