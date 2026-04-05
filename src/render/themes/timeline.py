"""timeline.py — Hourly day-view timeline theme.

Displays today's schedule as event blocks on a vertical hourly grid, making
free time and busy periods immediately obvious at a glance.

  ┌──────────────────────────────────────────────────────────────┐
  │ Home Dashboard                    Sunday, Apr 5  10:23am     │ 40px
  ├──────────────────────────────────────────────────────────────┤
  │      │                                                        │
  │  8am │                                                        │
  │  9am │ ▓▓▓▓▓▓▓▓▓▓▓ Team Standup                             │
  │ 10am │                                                        │
  │ 12pm │ · · · · · · (current-time dashed line)                │
  │  1pm │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ Product Review                      │
  │  2pm │                                                        │
  │  3pm │ ▓▓▓▓▓▓▓ 1:1 with Manager                             │
  │  9pm │                                                        │
  ├──────────────────────────────────────────────────────────────┤
  │ ☀ 72°F  Partly Cloudy   H:78° L:60°   Feels: 68°           │ 80px
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

_HEADER_H = 40
_WEATHER_H = 100
_TIMELINE_H = 480 - _HEADER_H - _WEATHER_H  # 340


def timeline_theme() -> Theme:
    """Return the hourly timeline theme."""
    return Theme(
        name="timeline",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            header=ComponentRegion(0, 0, 800, _HEADER_H),
            timeline=ComponentRegion(0, _HEADER_H, 800, _TIMELINE_H),
            weather=ComponentRegion(0, _HEADER_H + _TIMELINE_H, 800, _WEATHER_H),
            # Hide standard regions not used by this theme
            week_view=ComponentRegion(0, 0, 800, 320, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            info=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, 320, visible=False),
            draw_order=["header", "timeline", "weather"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=True,
            invert_today_col=False,
            invert_allday_bars=True,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            label_font_size=10,
            label_font_weight="semibold",
            show_borders=True,
            show_forecast_strip=False,
        ),
    )
