"""Moonphase Inverted theme — light parchment/fairy-tale variant.

Identical layout and overlay to ``moonphase`` but with colors flipped:
black text on a white canvas for a hand-illustrated manuscript feel
and maximum eInk contrast.
"""

from src.render.fonts import (
    cinzel_bold,
    cormorant_bold,
    cormorant_italic_semibold,
    cormorant_semibold,
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
            # Full-canvas moonphase region
            moonphase_full=ComponentRegion(0, 0, 800, 480),
            draw_order=["moonphase_full"],
            overlay_fn=_draw_moonphase_overlay,
            canvas_mode="L",
            preferred_quantization_mode="threshold",
            prefer_color_on_inky=True,
            # Keeps partial refresh, and the parchment polarity is why: unlike
            # `moonphase` this is a light canvas at ~12% ink, less than `default`,
            # and `threshold` quantization is a hard cut that lays down no dither
            # for the fast waveform to wash out. `canvas_mode="L"` alone is not a
            # reason to decline — it is the dithering quantizers that are.
        ),
        style=ThemeStyle(
            fg=0,  # black on white — parchment / fairy-tale book (L mode)
            bg=255,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            show_borders=False,
            font_regular=cormorant_semibold,
            font_medium=cormorant_semibold,
            font_semibold=cormorant_bold,
            font_bold=cinzel_bold,
            font_title=cinzel_bold,
            font_section_label=cinzel_bold,
            font_quote=cormorant_italic_semibold,
            font_quote_author=cinzel_bold,
            label_font_size=12,
            label_font_weight="bold",
        ),
    )


def _register() -> None:
    from src.render.theme import INKY_BLUE
    from src.render.themes.registry import register_theme

    # Navy for both accents: yellow type on the parchment plate barely reads.
    register_theme("moonphase_invert", moonphase_invert_theme, inky_palette=(INKY_BLUE, INKY_BLUE))


_register()
