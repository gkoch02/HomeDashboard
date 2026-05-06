"""constellation_map.py — full-canvas star-chart theme.

Dark-canvas star map projected for the user's location and the current
moment (or tonight's solar midnight, when it's still daylight).  Renders
~45 named stars from a curated Bright Star subset, joined into the seven
most recognisable northern constellations, plus the moon at its current
altitude / azimuth.

Typography is Cinzel (star and constellation labels) + DM Sans (margin
data) so the chart reads like a printed sky atlas.  All sky-position
math runs out of :mod:`src.astronomy` — no API calls.
"""

from __future__ import annotations

from src.render.fonts import audiowide, dm_medium, dm_regular
from src.render.theme import (
    INKY_BLUE,
    INKY_YELLOW,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)


def constellation_map_theme() -> Theme:
    """Return the constellation-map theme."""
    return Theme(
        name="constellation_map",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            canvas_mode="L",
            constellation_map=ComponentRegion(0, 0, 800, 480),
            # Hide standard regions — full-canvas view.
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["constellation_map"],
            # Light up on Inky as a real colour piece (yellow accents on
            # black, blue constellation lines) — Waveshare stays bilevel.
            prefer_color_on_inky=True,
        ),
        style=ThemeStyle(
            # Dark canvas: white stars on a black sky.  L-mode invariant
            # ``fg=0/bg=255`` is reversed deliberately here; the resolve
            # helpers in canvas.py handle either polarity.
            fg=255,
            bg=0,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_bold=dm_medium,
            # Audiowide: a single-weight OFL retro-futuristic display sans
            # with tall, even strokes — reads as an "observatory" face and
            # stays legible at the small sizes the chart uses for star,
            # constellation, and cardinal labels against the dark sky.
            font_section_label=audiowide,
            font_title=audiowide,
            label_font_size=11,
            label_font_weight="regular",
            # accent_primary / accent_secondary are intentionally left
            # unset.  On Inky, ``inky_palette`` plus the resolve helpers in
            # ``canvas.py`` map them to YELLOW (constellation labels) and
            # BLUE (constellation lines + altitude rings) automatically.
            # On Waveshare 1-bit, the ``primary_accent_fill()`` /
            # ``secondary_accent_fill()`` helpers fall through to ``fg``,
            # giving us a clean monochrome chart with no palette-index
            # leakage into grayscale values.
            inky_palette=(INKY_YELLOW, INKY_BLUE),
            show_borders=False,
        ),
    )


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "constellation_map",
        constellation_map_theme,
        inky_palette=(INKY_YELLOW, INKY_BLUE),
    )


_register()
