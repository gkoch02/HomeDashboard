"""trends.py — stacked sparkline dashboard theme.

Five labeled time-series rows under a thin masthead:

  TEMP — 24h          : current + interpolated forecast across ±12 h
  AIR                 : current AQI marker on a 6-zone health scale
  DAYLIGHT — 7d       : day length for today and the next six days
  EVENTS — 14d        : per-day event count bars for the next two weeks
  MOON — 30d          : illumination curve across the next synodic month

Each row gets a Bayer-filled area under its curve, giving a clean halftone
density read on monochrome ink. The Inky variant draws series in blue with
a yellow today-marker; on Waveshare the same code paints black on white
and the final ``ordered`` quantize step yields a crisp dot pattern.

Typography is DM Sans throughout (data-viz neutrality) with Share Tech
Mono for the numeric right-hand annotations.
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import (
    INKY_BLUE,
    INKY_YELLOW,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)


def trends_theme() -> Theme:
    """Return the trends (stacked sparkline) theme."""
    return Theme(
        name="trends",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            canvas_mode="L",
            # Ordered Bayer keeps the area-fill dots regular; Floyd-Steinberg
            # noise would look like a scratched chart rather than a halftone.
            preferred_quantization_mode="ordered",
            prefer_color_on_inky=True,
            trends=ComponentRegion(0, 0, 800, 480),
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["trends"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=255,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            font_title=dm_bold,
            font_section_label=dm_semibold,
            label_font_size=10,
            label_font_weight="semibold",
            accent_primary=INKY_BLUE,
            accent_secondary=INKY_YELLOW,
            inky_palette=(INKY_BLUE, INKY_YELLOW),
            show_borders=True,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "trends",
        trends_theme,
        inky_palette=(INKY_BLUE, INKY_YELLOW),
    )


_register()
