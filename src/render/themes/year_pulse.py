"""year_pulse.py — Big-picture year progress theme.

Zooms out from the usual weekly view to show where you are in the year:
a large year number, week number, day-of-year progress bar, and a countdown
list of upcoming calendar events and birthdays.

  ┌──────────────────────────────────────────────────────────────┐
  │ Home Dashboard                    Sunday, Apr 5  10:23am     │ 40px
  ├──────────────────────────────────────────────────────────────┤
  │                                                              │
  │   2026                                       Week 14        │
  │   ████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   │
  │   Day 95 of 365  ·  26% complete                           │
  │                                                              │
  │ ──────────────────────────────────────────────────────────  │
  │  COMING UP                                                   │
  │  → 3d    John's Birthday                                     │
  │  → 23d   Next Big Event                                      │
  │  → 47d   Product Launch                                      │
  │  → 89d   Jane's Birthday                                     │
  │                                                              │
  ├──────────────────────────────────────────────────────────────┤
  │ ☀ 72°F  Partly Cloudy   H:78° L:60°                        │ 80px
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from src.render.fonts import sg_bold, sg_medium, sg_regular
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

_HEADER_H = 40
_WEATHER_H = 100
_PULSE_H = 480 - _HEADER_H - _WEATHER_H  # 340


def year_pulse_theme() -> Theme:
    """Return the year-pulse big-picture theme."""
    return Theme(
        name="year_pulse",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            header=ComponentRegion(0, 0, 800, _HEADER_H),
            year_pulse=ComponentRegion(0, _HEADER_H, 800, _PULSE_H),
            weather=ComponentRegion(0, _HEADER_H + _PULSE_H, 800, _WEATHER_H),
            # Hide standard regions not used by this theme
            week_view=ComponentRegion(0, 0, 800, 320, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            info=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, 320, visible=False),
            draw_order=["header", "year_pulse", "weather"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            # Space Grotesk for a clean, modern data-dashboard feel
            font_regular=sg_regular,
            font_medium=sg_medium,
            font_semibold=sg_medium,  # SG has no dedicated semibold
            font_bold=sg_bold,
            label_font_size=10,
            label_font_weight="bold",
            component_labels={"year_pulse": "COMING UP"},
            show_borders=False,
            show_forecast_strip=False,
        ),
    )
