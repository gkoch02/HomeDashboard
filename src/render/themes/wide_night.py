"""wide_night theme — a near-empty night plate for the 1360x480 panel.

The panoramic theme for after dark: four marks — the moon's phase, the
temperature, the air-quality index and the weather glyph — spaced evenly
across the strip on its midline, and nothing else. On the four-ink panel the
ground is solid red and the marks are black ink; on a monochrome panel, which
has no red, it is a black ground with the marks knocked out in white. See
``src/render/components/wide_night_panel.py``.

The style is declared as a dark-canvas plate (``fg`` paper, ``bg`` ink), the
convention the ``*_invert`` themes use: that is what the monochrome fallback
draws, it pads a letterboxed plate in the dark ground, and it derives the
theme out of partial refresh — the whole plate is one solid fill, which the
fast waveform lays down as charcoal. The panel reads the red from the primary
accent.

Kept out of the random rotation: a plate that shows almost nothing is meant
to be put up at night on purpose, through ``theme_schedule`` or a
``theme_rules`` ``daypart: night`` rule, not drawn by chance at noon.
``repaint_slot_hours=1`` holds the panel to one write per clock hour, so a
temperature or AQI change does not set off a twenty-second red flash in a
dark room every fetch.
"""

from __future__ import annotations

from src.render.fonts import jura_bold, jura_semibold
from src.render.theme import (
    INKY_BLACK,
    INKY_RED,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)

CANVAS_W = 1360
CANVAS_H = 480


def wide_night_theme() -> Theme:
    """Return the wide_night (panoramic night mode) theme."""
    return Theme(
        name="wide_night",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            repaint_slot_hours=1,
            wide_night=ComponentRegion(0, 0, CANVAS_W, CANVAS_H),
            # Hide the standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 0, 0, visible=False),
            week_view=ComponentRegion(0, 0, 0, 0, visible=False),
            weather=ComponentRegion(0, 0, 0, 0, visible=False),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            today_view=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["wide_night"],
        ),
        style=ThemeStyle(
            fg=1,
            bg=0,
            # One face for the whole plate.
            font_regular=jura_semibold,
            font_medium=jura_semibold,
            font_semibold=jura_semibold,
            # The tracked labels under each mark.
            font_bold=jura_bold,
            font_date_number=jura_semibold,
            accent_primary=INKY_RED,
            accent_secondary=INKY_BLACK,
            inky_palette=(INKY_RED, INKY_BLACK),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("wide_night", wide_night_theme, inky_palette=(INKY_RED, INKY_BLACK))


_register()
