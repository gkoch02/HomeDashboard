# Retired themes

Themes taken out of the product but kept here so any of them can come back.
Nothing in this directory is imported, tested, linted, packaged or deployed as
part of the dashboard; the files are as they were on the day they were retired.

| Theme | Panel module(s) it needed | Tests |
|---|---|---|
| `agenda` | shared week-view components (still shipped) | — |
| `minimalist` | shared week-view components (still shipped) | — |
| `today` | `today_view` (still shipped; `old_fashioned` uses it) | `removed_from_test_themes.py` |
| `timeline` | `timeline_panel.py` | `test_timeline_theme.py`, `removed_from_test_themes.py` |
| `year_pulse` | `year_pulse_panel.py` | `test_year_pulse_theme.py`, `removed_from_test_themes.py` |
| `sunrise` | `sunrise_panel.py` | `test_sunrise_theme.py` |
| `tides` | `tides_panel.py` | `test_tides_theme.py`, `test_tides_panel.py` |
| `scorecard` | `scorecard_panel.py` | `test_scorecard_theme.py`, `test_scorecard_panel.py` |
| `naturalist` | `naturalist_panel.py` | `test_naturalist_theme.py` |

Layout:

- `src/render/themes/`, `src/render/components/` — the theme factories and the
  panels only they used, at the paths they had under `src/`.
- `tests/` — their dedicated test modules, the cases cut from
  `tests/test_themes.py`, and their pixel hashes
  (`tests/snapshots/theme_pixel_hashes.json`).
- `assets/previews/` — the monochrome and Inky preview images.
- `docs/themes.md` — their entries from `docs/themes.md` and
  `docs/inky-previews.md`.

While retired, each name is listed in `RETIRED_THEME_NAMES`
(`src/render/themes/registry.py`): a config, schedule entry or rule still
naming one renders `default` with a warning instead of failing every run.

## Restoring a theme

The quickest route is to revert the commit that retired them
(`git log --diff-filter=A -- retired/README.md`) and delete what you do not
want back. To restore one theme by hand:

1. `git mv` its theme module, panel module and tests from `retired/` back to
   the same paths under `src/` and `tests/`, and its two preview PNGs back to
   `assets/previews/`.
2. Add its side-effect import to `src/render/themes/__init__.py` and remove the
   name from `RETIRED_THEME_NAMES`.
3. For a full-canvas panel, re-add its `ComponentRegion` field to `ThemeLayout`
   in `src/render/theme.py`, and its panel module to the import list and its
   adapter to `src/render/components/_builtins.py` (both below).
4. `sunrise` and `tides` import `antonio_bold`; re-add it to
   `src/render/fonts.py` next to `antonio_semibold`:

   ```python
   def antonio_bold(size: int) -> ImageFont.FreeTypeFont:
       return _get_antonio(size, 700)
   ```

5. Put its hash back in `tests/snapshots/theme_pixel_hashes.json` (or
   regenerate with `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py`),
   and re-add it where the test suite lists themes by behaviour:
   `TIME_DRIVEN` in `tests/test_idle_tick_no_redraw.py` (`timeline`,
   `scorecard`, `sunrise`, `tides`) and `DECLINES_PARTIAL` in
   `tests/test_theme_partial_refresh.py` (`naturalist`).
6. Restore its entries in `docs/themes.md` and `docs/inky-previews.md` (from
   `docs/themes.md` here), the theme lists in `docs/themes.md` and
   `config/config.example.yaml`, and the count in `README.md`. Run
   `make docs-check`, `make lint` and `make test`.

### `ThemeLayout` fields (`src/render/theme.py`)

```python
    # Used by the ``timeline`` theme for the hourly day-view timeline.
    # Hidden by default so existing themes are not affected.
    timeline: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 40, 800, 360, visible=False)
    )
    # Used by the ``year_pulse`` theme for the year progress + countdowns area.
    # Hidden by default so existing themes are not affected.
    year_pulse: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 40, 800, 360, visible=False)
    )
    # Used by the ``sunrise`` theme for the sun-arc + split-schedule panel.
    sunrise: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``scorecard`` theme for the numeric KPI tile grid.
    scorecard: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``tides`` theme for alternating inverted horizontal bands.
    tides: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``naturalist`` theme for a Victorian botanical plate.
    naturalist: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
```

### Component adapters (`src/render/components/_builtins.py`)

```python
@register_component("timeline")
def _timeline(ctx: RenderContext) -> None:
    timeline_panel.draw_timeline(
        ctx.draw,
        ctx.data.events,
        ctx.today,
        ctx.now,
        region=ctx.layout.timeline,
        style=ctx.style,
    )


@register_component("year_pulse")
def _year_pulse(ctx: RenderContext) -> None:
    year_pulse_panel.draw_year_pulse(
        ctx.draw,
        ctx.data,
        ctx.today,
        region=ctx.layout.year_pulse,
        style=ctx.style,
    )


@register_component("sunrise")
def _sunrise(ctx: RenderContext) -> None:
    sunrise_panel.draw_sunrise(
        ctx.draw,
        ctx.data,
        ctx.today,
        ctx.now,
        region=ctx.layout.sunrise,
        style=ctx.style,
    )


@register_component("scorecard")
def _scorecard(ctx: RenderContext) -> None:
    scorecard_panel.draw_scorecard(
        ctx.draw,
        ctx.data,
        ctx.today,
        ctx.now,
        region=ctx.layout.scorecard,
        style=ctx.style,
        quote_refresh=ctx.quote_refresh,
        quotes_path=ctx.quotes_path,
    )


@register_component("tides")
def _tides(ctx: RenderContext) -> None:
    tides_panel.draw_tides(
        ctx.draw,
        ctx.data,
        ctx.today,
        ctx.now,
        region=ctx.layout.tides,
        style=ctx.style,
        quote_refresh=ctx.quote_refresh,
        quotes_path=ctx.quotes_path,
    )


@register_component("naturalist")
def _naturalist(ctx: RenderContext) -> None:
    naturalist_panel.draw_naturalist(
        ctx.draw,
        ctx.data,
        ctx.today,
        ctx.now,
        image=ctx.image,
        region=ctx.layout.naturalist,
        style=ctx.style,
        quote_refresh=ctx.quote_refresh,
        quotes_path=ctx.quotes_path,
    )
```
