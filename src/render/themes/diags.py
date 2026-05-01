"""Diagnostics theme — full-canvas text readout of all data sources.

No icons, no decorations.  Monospace data rows (ShareTechMono) with
DM Sans Bold section labels for legibility.
"""

from src.render.fonts import cyber_mono, dm_bold, dm_medium
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def diags_theme() -> Theme:
    """Return the diags theme."""
    return Theme(
        name="diags",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # All standard regions disabled — diags owns the full canvas.
            header=ComponentRegion(0, 0, 800, 28, visible=False),
            week_view=ComponentRegion(0, 0, 0, 0, visible=False),
            weather=ComponentRegion(0, 0, 0, 0, visible=False),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            diags=ComponentRegion(0, 0, 800, 480),
            draw_order=["diags"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            show_borders=False,
            # cyber_mono (ShareTechMono) for data rows via font_regular;
            # dm_bold for section labels via font_bold.
            font_regular=cyber_mono,
            font_medium=dm_medium,
            font_semibold=dm_medium,
            font_bold=dm_bold,
        ),
    )


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_GREEN
    from src.render.themes.registry import register_theme

    register_theme("diags", diags_theme, inky_palette=(INKY_GREEN, INKY_BLUE))


_register()
