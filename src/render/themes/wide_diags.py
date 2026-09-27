"""wide_diags theme — the diags readout beside an ink and dither test plate.

The panoramic diagnostics view for the 1360x480 strip. The left 800 px are
the ``diags`` readout exactly as the 800x480 theme draws it; the right 560 px
are a swatch plate (``src/render/components/wide_diags_panel.py``): each ink
the panel has, every pair of inks mixed in ordered-dither steps, fine test
textures, and a gradient the display backend diffuses itself — for checking
what a panel, and the pipeline in front of it, can actually show.

The style is the ``diags`` one with the accent roles left unset, so on a
colour panel they resolve to its palette and the swatch plate can read the ink
set off them. The plate is exact inks drawn at native size; ``ordered``
quantization makes a scaled monochrome panel re-screen the dithers rather than
threshold a blurred checkerboard to flat ink, and — like any dithered plate —
derives the theme out of partial refresh. Excluded from the random rotation,
like ``diags``.
"""

from __future__ import annotations

from src.render.fonts import cyber_mono, dm_bold, dm_medium
from src.render.theme import (
    INKY_BLUE,
    INKY_GREEN,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)

CANVAS_W = 1360
CANVAS_H = 480
DIAGS_W = 800


def wide_diags_theme() -> Theme:
    """Return the wide_diags (diagnostics + swatch plate) theme."""
    return Theme(
        name="wide_diags",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            preferred_quantization_mode="ordered",
            diags=ComponentRegion(0, 0, DIAGS_W, CANVAS_H),
            wide_diags=ComponentRegion(DIAGS_W, 0, CANVAS_W - DIAGS_W, CANVAS_H),
            header=ComponentRegion(0, 0, 0, 0, visible=False),
            week_view=ComponentRegion(0, 0, 0, 0, visible=False),
            weather=ComponentRegion(0, 0, 0, 0, visible=False),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            today_view=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["diags", "wide_diags"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            show_borders=False,
            font_regular=cyber_mono,
            font_medium=dm_medium,
            font_semibold=dm_medium,
            font_bold=dm_bold,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    # diags' own pair: the left pane shares this style, so any other pair would
    # recolour its headings and it would no longer be the diags readout.
    register_theme("wide_diags", wide_diags_theme, inky_palette=(INKY_GREEN, INKY_BLUE))


_register()
