"""naturalist.py — Victorian botanical-plate theme.

A 19th-century scientific-illustration plate, rendered procedurally with
Floyd-Steinberg crosshatching.  The hero is a single specimen branch
whose leaf density, posture, and surface treatment shift with the season
and current weather: bare twigs in winter, swelling buds in early spring,
full canopy in summer, sparse rust-toned canopy in autumn, weighted
limbs in snow, frost stippling in cold clear weather, and rain streaks
behind the foliage during precipitation.

Hand-lettered Cinzel labels with thin leader lines pin today's events,
moon phase, and sunrise/sunset to specific anatomical points on the
specimen — the way a botanical engraver would label a leaf, a node, or a
flower.  A blackletter masthead ("PLATE LXXIII — MAY MMXXVI") anchors the
top, and a Latin-style caption beneath the specimen carries the day's
quote in italics, with the author rendered in small caps.

Inky picks up red plate ornaments + leader-line dots against a black
specimen; Waveshare quantizes the same procedural greyscale to 1-bit via
Floyd-Steinberg, turning the leaf gradients and bark shading into
authentic engraving-style halftone.
"""

from __future__ import annotations

from src.render.fonts import (
    astloch_bold,
    cinzel_black,
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


def naturalist_theme() -> Theme:
    """Return the naturalist (Victorian botanical plate) theme."""
    return Theme(
        name="naturalist",
        layout=ThemeLayout(
            # 2× supersampled canvas — the WaveshareBackend's LANCZOS resize
            # down to the display's native 800×480 acts as a free anti-alias
            # pass over the engraved specimen + every text glyph before the
            # final Floyd-Steinberg quantize.
            canvas_w=1600,
            canvas_h=960,
            canvas_mode="L",
            preferred_quantization_mode="floyd_steinberg",
            prefer_color_on_inky=True,
            naturalist=ComponentRegion(0, 0, 1600, 960),
            # Hide all standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 1600, 80, visible=False),
            week_view=ComponentRegion(0, 80, 1600, 640, visible=False),
            weather=ComponentRegion(0, 720, 600, 240, visible=False),
            birthdays=ComponentRegion(600, 720, 500, 240, visible=False),
            info=ComponentRegion(1100, 720, 500, 240, visible=False),
            today_view=ComponentRegion(0, 120, 1600, 560, visible=False),
            draw_order=["naturalist"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=255,
            font_regular=playfair_regular,
            font_medium=playfair_regular,
            font_semibold=playfair_semibold,
            font_bold=playfair_semibold,
            # Astloch blackletter masthead; Cinzel for plate labels.
            font_title=astloch_bold,
            font_section_label=cinzel_black,
            font_quote=playfair_regular,
            font_quote_author=cinzel_semibold,
            label_font_size=11,
            label_font_weight="bold",
            accent_primary=INKY_RED,
            accent_secondary=INKY_BLACK,
            inky_palette=(INKY_RED, INKY_BLACK),
            show_borders=True,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "naturalist",
        naturalist_theme,
        inky_palette=(INKY_RED, INKY_BLACK),
    )


_register()
