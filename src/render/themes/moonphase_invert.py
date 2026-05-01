"""Moonphase Inverted theme — light parchment/fairy-tale variant.

Identical layout and overlay to ``moonphase`` but with colors flipped:
black text on a white canvas for a hand-illustrated manuscript feel
and maximum eInk contrast.
"""

from src.render.fonts import (
    cinzel_bold,
    playfair_medium,
    playfair_regular,
    regular,
    semibold,
)
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle
from src.render.themes.moonphase import _draw_moonphase_overlay


def moonphase_invert_theme() -> Theme:
    """Return the Moonphase Inverted theme — light canvas, parchment feel."""
    return Theme(
        name="moonphase_invert",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # All standard regions hidden
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            qotd=ComponentRegion(0, 0, 800, 400, visible=False),
            weather_full=ComponentRegion(0, 0, 800, 480, visible=False),
            fuzzyclock=ComponentRegion(0, 0, 800, 400, visible=False),
            diags=ComponentRegion(0, 0, 800, 480, visible=False),
            air_quality_full=ComponentRegion(0, 0, 800, 480, visible=False),
            # Full-canvas moonphase region
            moonphase_full=ComponentRegion(0, 0, 800, 480),
            draw_order=["moonphase_full"],
            overlay_fn=_draw_moonphase_overlay,
        ),
        style=ThemeStyle(
            fg=0,  # black on white — parchment / fairy-tale book
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            show_borders=False,
            font_regular=regular,
            font_medium=playfair_medium,
            font_semibold=semibold,
            font_bold=cinzel_bold,
            font_title=cinzel_bold,
            font_section_label=cinzel_bold,
            font_quote=playfair_regular,
            font_quote_author=playfair_regular,
            label_font_size=12,
            label_font_weight="bold",
        ),
    )


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_YELLOW
    from src.render.themes.registry import register_theme

    register_theme(
        "moonphase_invert", moonphase_invert_theme, inky_palette=(INKY_YELLOW, INKY_BLUE)
    )


_register()
