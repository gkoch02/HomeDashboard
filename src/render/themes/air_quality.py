"""Full-screen air quality theme.

Devotes the entire 800×480 canvas to a rich environmental health display
built around the PurpleAir sensor data.  The layout is divided into four
horizontal zones:

  1. AQI hero (large number + category) + 6-zone health scale bar  — top 38%
  2. Particulate matter row (PM1.0 / PM2.5 / PM10)                 — 15%
  3. Ambient sensor cards (temperature, humidity, pressure)         — 21%
  4. Weather + 4-day forecast strip                                 — bottom 27%

Font: Space Grotesk — a proportional sans-serif derived from Space Mono that
retains the monospace family's quirky letterforms (a, G, R, t) for
data-dashboard personality while remaining cleanly legible at all sizes.
"""

from src.render.fonts import sg_bold, sg_medium, sg_regular
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def air_quality_theme() -> Theme:
    """Return the full-screen air quality theme."""
    return Theme(
        name="air_quality",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # All standard regions hidden — air_quality_full draws everything
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
            # Full-screen air quality region
            air_quality_full=ComponentRegion(0, 0, 800, 480),
            draw_order=["air_quality_full"],
        ),
        style=ThemeStyle(
            fg=0,   # black on white — optimal eInk contrast
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            show_borders=False,      # whitespace-defined layout
            font_regular=sg_regular,
            font_medium=sg_medium,
            font_semibold=sg_bold,   # no SemiBold weight in bundled cut; use Bold
            font_bold=sg_bold,
            label_font_size=10,
            label_font_weight="semibold",
        ),
    )
