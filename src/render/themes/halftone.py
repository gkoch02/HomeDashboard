"""halftone.py — procedural dithered weather-plate theme.

The hero region (top 320 px) is a procedurally-drawn illustration of the
current weather: a rayed sun with a halftone-graded sky for clear days,
overlapping ellipse clouds for the cloudy family, stippled rain or snow,
a sharp lightning bolt for thunderstorms, horizontal banding for fog,
or a moon disc with smooth terminator shading for clear nights. The
illustration is drawn entirely with PIL primitives onto an L-mode (8-bit
greyscale) canvas; the Waveshare backend then quantizes the gradients to
1-bit via Floyd-Steinberg, producing the engraving-style dither that is
the theme's whole point.

A 6-px ordered-Bayer rule separates the hero from a 154-px margin band
carrying the temperature numeral, condition, location, next event, and
the daily quote.

Typography evokes a 19th-century natural-history plate: Playfair Display
for the body and large temperature numeral, Cinzel small caps for labels
and the right-aligned location.

On Inky the canvas is RGB (``prefer_color_on_inky=True``) and the sun
and moon pick up a yellow accent; everything else stays monochrome
black so the engraving still reads as one.
"""

from __future__ import annotations

from src.render.fonts import righteous
from src.render.theme import (
    INKY_BLACK,
    INKY_YELLOW,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)


def halftone_theme() -> Theme:
    """Return the halftone (engraved weather plate) theme."""
    return Theme(
        name="halftone",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            canvas_mode="L",
            # Floyd-Steinberg turns the procedural greyscale gradients into
            # an organic engraving-style dither instead of a flat threshold.
            preferred_quantization_mode="floyd_steinberg",
            # Yellow sun/moon accents come through on Inky; Waveshare stays
            # bilevel via the final L→1 quantize step.
            prefer_color_on_inky=True,
            halftone=ComponentRegion(0, 0, 800, 480),
            # Hide all standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["halftone"],
        ),
        style=ThemeStyle(
            # L-mode light canvas invariant: black ink on near-white field.
            fg=0,
            bg=255,
            # Every typeset element uses Righteous (OFL) — a single-weight
            # geometric display sans whose thick, even strokes survive
            # Floyd-Steinberg dithering cleanly at every size. The unified
            # face also lets the engraved plate read as one voice instead
            # of mixing serif, small-caps, and sans body in the same band.
            font_regular=righteous,
            font_medium=righteous,
            font_semibold=righteous,
            font_bold=righteous,
            font_title=righteous,
            font_section_label=righteous,
            font_quote=righteous,
            font_quote_author=righteous,
            label_font_size=15,
            label_font_weight="semibold",
            accent_primary=INKY_BLACK,
            accent_secondary=INKY_YELLOW,
            inky_palette=(INKY_BLACK, INKY_YELLOW),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "halftone",
        halftone_theme,
        inky_palette=(INKY_BLACK, INKY_YELLOW),
    )


_register()
