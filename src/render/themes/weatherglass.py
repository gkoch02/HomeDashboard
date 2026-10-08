"""weatherglass.py — Victorian weather-station instrument deck.

A full-canvas brass-and-mahogany panel of procedural analog gauges arranged
like an antique aneroid bench: a hero thermometer at left, a round barometer
dial at centre, a hygrometer + UV bar stack at right, and a row of smaller
instruments below — wind compass rose, sun arc with twilight bands, moon
porthole with a procedural terminator, and an optional AQI badge.

The composition reads top to bottom as masthead → three hero instruments
→ four secondary instruments, with engraved tick marks, hairline cross-hatch
ornaments, and filigree corner curls.  An alert ribbon sits between the
masthead and the barometer when weather alerts are active.

On Waveshare the L-mode canvas is supersampled 2× (1600×960); the backend's
LANCZOS resize anti-aliases every rim, tick and needle and the threshold
quantize snaps them to crisp ink, while shaded zones are engraved as ruled
tints that survive that step.  On Inky the canvas opts into
RGB so the brass rims pick up yellow, the mercury column + alert text
pick up red, the cold scale + falling-pressure trend needle pick up blue,
and the comfort band + rising-pressure trend needle pick up green.
"""

from __future__ import annotations

from src.render.fonts import (
    cinzel_black,
    cinzel_bold,
    literata_bold,
    literata_semibold,
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
            # Keeps partial refresh. The `threshold` mode above is chosen
            # precisely so the shaded zones snap to solid black instead of
            # dithering into speckle, which leaves ~8% ink of crisp line-work on
            # paper — nothing for the fast waveform to fade. It also redraws every
            # tick, so it is the theme that gains most from the fast path.
            weatherglass=ComponentRegion(0, 0, 1600, 960),
            draw_order=["weatherglass"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=255,
            # Literata (a screen serif with lining figures) sets every scale
            # numeral and small reading; Cinzel Bold the engraved words; Cinzel
            # Black the hero readings; Rye the Western-saloon masthead.
            font_regular=literata_semibold,
            font_medium=literata_semibold,
            font_semibold=literata_bold,
            font_bold=literata_bold,
            font_title=rye,
            font_section_label=cinzel_bold,
            font_date_number=cinzel_black,
            font_month_title=cinzel_black,
            font_quote=literata_semibold,
            font_quote_author=cinzel_bold,
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
