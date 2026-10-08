"""postcard.py — vintage dithered postcard theme.

A divided composition that reads like a piece of mail picked up off the
doormat.  The left two-thirds is a Floyd-Steinberg-dithered procedural
mountain-lake "view" keyed to the weather icon, with the sun following
the hour, so the scene shifts from dawn to dusk and from a clear
afternoon to a thunderstorm.  The right third is the
postcard's back: cursive greeting (the daily quote), a circular postmark
that doubles as the dateline, a stamp carrying the moon phase glyph, and
a stack of ruled "address" lines listing today's events.

Typography mirrors a 1950s souvenir card: **Playfair Display** italic for
the greeting, **Cinzel** small caps for the address rules and labels,
and a hand-lettered feel achieved by mixing weights against the dither.

On Inky the canvas opts into RGB (``prefer_color_on_inky=True``); the
postmark + stamp border pick up the inky-red accent while the scene
stays grayscale.  Waveshare quantizes the whole image to 1-bit via
Floyd-Steinberg, turning the greyscale scene into an engraving-style
dither.

Editing notes: the view is ``postcard_scene.py``, numpy-painted and seeded by
the date; the light is floored to the hour, keeping the theme out of
``TIME_DRIVEN``. Its exp / sin / pow go through ``math``-built tables (``_exp``,
``_sin``, ``_pow``), never numpy's per-CPU SIMD kernels, so the snapshot hash
holds across machines.
"""

from __future__ import annotations

from src.render.fonts import (
    cinzel_semibold,
    playfair_regular,
    playfair_semibold,
)
from src.render.theme import (
    INKY_BLACK,
    INKY_RED,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)


def postcard_theme() -> Theme:
    """Return the postcard (dithered scene + postcard back) theme."""
    return Theme(
        name="postcard",
        layout=ThemeLayout(
            # 2× supersampled canvas — the WaveshareBackend's LANCZOS resize
            # down to the display's native 800×480 acts as a free anti-alias
            # pass over every procedural curve + every text glyph before the
            # final Floyd-Steinberg quantize.
            canvas_w=1600,
            canvas_h=960,
            canvas_mode="L",
            preferred_quantization_mode="floyd_steinberg",
            prefer_color_on_inky=True,
            postcard=ComponentRegion(0, 0, 1600, 960),
            draw_order=["postcard"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=255,
            font_regular=playfair_regular,
            font_medium=playfair_regular,
            font_semibold=playfair_semibold,
            font_bold=playfair_semibold,
            font_title=playfair_semibold,
            font_section_label=cinzel_semibold,
            font_quote=playfair_regular,
            font_quote_author=cinzel_semibold,
            label_font_size=11,
            label_font_weight="semibold",
            accent_primary=INKY_RED,
            accent_secondary=INKY_BLACK,
            inky_palette=(INKY_RED, INKY_BLACK),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "postcard",
        postcard_theme,
        inky_palette=(INKY_RED, INKY_BLACK),
    )


_register()
