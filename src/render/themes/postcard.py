"""postcard.py — vintage dithered postcard theme.

A divided composition that reads like a piece of mail picked up off the
doormat.  The left two-thirds is a Floyd-Steinberg-dithered procedural
"view" — sky, horizon, landscape silhouette, foreground — keyed to the
current weather icon and daypart so the scene shifts from dawn to dusk
and from a clear afternoon to a thunderstorm.  The right third is the
postcard's back: cursive greeting (the daily quote), a circular postmark
that doubles as the dateline, a stamp carrying the moon phase glyph, and
a stack of ruled "address" lines listing today's events.

Typography mirrors a 1950s souvenir card: **Playfair Display** italic for
the greeting, **Cinzel** small caps for the address rules and labels,
and a hand-lettered feel achieved by mixing weights against the dither.

On Inky the canvas opts into RGB (``prefer_color_on_inky=True``); the
postmark + stamp border pick up the inky-red accent while the scene
stays grayscale.  Waveshare quantizes the whole image to 1-bit via
Floyd-Steinberg, turning the procedural greyscale gradients into the
characteristic engraving-style dither.
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
            canvas_w=800,
            canvas_h=480,
            canvas_mode="L",
            preferred_quantization_mode="floyd_steinberg",
            prefer_color_on_inky=True,
            postcard=ComponentRegion(0, 0, 800, 480),
            # Hide all standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
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
