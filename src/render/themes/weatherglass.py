"""weatherglass.py — Victorian weather-station instrument deck.

A full-canvas brass-and-mahogany panel of procedural analog gauges arranged
like an antique aneroid bench: a hero thermometer at left, a round barometer
dial at centre, a hygrometer + UV bar stack at right, and a row of smaller
instruments below — wind compass rose, sun arc with twilight bands, moon
porthole with a procedural terminator, and an optional AQI badge.

The composition reads top to bottom as masthead → three hero instruments
→ four secondary instruments, with engraved tick marks, hairline cross-hatch
ornaments, and filigree corner curls.  An alert cartouche overlays the
masthead when weather alerts are active.

On Waveshare the L-mode canvas is supersampled 2× (1600×960) and the
backend's LANCZOS resize + Floyd-Steinberg quantize turn the gradients
into authentic engraving-style halftone.  On Inky the canvas opts into
RGB so the brass rims pick up yellow, the mercury column + alert text
pick up red, the cold scale + falling-pressure trend needle pick up blue,
and the comfort band + rising-pressure trend needle pick up green.
"""

from __future__ import annotations

from src.render.fonts import (
    cinzel_black,
    cinzel_semibold,
    playfair_regular,
    playfair_semibold,
    rye,
)
from src.render.theme import (
    INKY_RED,
    INKY_YELLOW,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)


def weatherglass_theme() -> Theme:
    """Return the weatherglass (Victorian instrument deck) theme."""
    return Theme(
        name="weatherglass",
        layout=ThemeLayout(
            # 2× supersampled canvas — LANCZOS downsample to 800×480 acts as
            # a free anti-alias pass over every dial rim, tick mark, needle,
            # and engraved label. The final 1-bit step uses threshold (not
            # Floyd-Steinberg) so the antialiased edges snap to crisp solid
            # black instead of dithering into speckle — every shaded zone is
            # already hand-stippled, so no fill relies on the dither pass.
            canvas_w=1600,
            canvas_h=960,
            canvas_mode="L",
            preferred_quantization_mode="threshold",
            prefer_color_on_inky=True,
            weatherglass=ComponentRegion(0, 0, 1600, 960),
            # Hide all standard regions — this theme owns the full canvas.
            header=ComponentRegion(0, 0, 1600, 80, visible=False),
            week_view=ComponentRegion(0, 80, 1600, 640, visible=False),
            weather=ComponentRegion(0, 720, 600, 240, visible=False),
            birthdays=ComponentRegion(600, 720, 500, 240, visible=False),
            info=ComponentRegion(1100, 720, 500, 240, visible=False),
            today_view=ComponentRegion(0, 120, 1600, 560, visible=False),
            draw_order=["weatherglass"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=255,
            font_regular=playfair_regular,
            font_medium=playfair_regular,
            font_semibold=playfair_semibold,
            font_bold=playfair_semibold,
            # Rye Western-saloon masthead; Cinzel for engraved dial labels
            # and high-contrast instrument numerals (Cinzel Black has the
            # full glyph coverage we need — NuCore's metrics are degenerate
            # for pure-digit strings and degree-sign rendering).
            font_title=rye,
            font_section_label=cinzel_semibold,
            font_date_number=cinzel_black,
            font_month_title=cinzel_black,
            font_quote=playfair_regular,
            font_quote_author=cinzel_semibold,
            label_font_size=11,
            label_font_weight="semibold",
            # Brass + mercury is the dominant palette pair on Inky.
            accent_primary=INKY_YELLOW,
            accent_secondary=INKY_RED,
            inky_palette=(INKY_YELLOW, INKY_RED),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "weatherglass",
        weatherglass_theme,
        inky_palette=(INKY_YELLOW, INKY_RED),
    )


_register()
