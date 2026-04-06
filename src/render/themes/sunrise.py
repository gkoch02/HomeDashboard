"""sunrise.py — Sun-arc daylight dashboard theme.

Displays a semicircular sun arc showing the sun's position between sunrise
and sunset, with today's events split into "daylight" and "evening" columns.

  ┌──────────────────────────────────────────────────────────────┐
  │ Home Dashboard              Sunday, Apr 5  10:23am   72°F   │ 36px
  ├──────────────────────────────────────────────────────────────┤
  │              ·  ·  SUN ARC  ·  ·                            │
  │           ·          ☀ (positioned)        ·                │
  │  6:12a ─ ─ ─ ─ HORIZON LINE ─ ─ ─ ─ 7:48p                 │ 170px
  │▓▓▓▓▓▓▓▓▓▓▓▓▓ GROUND (stippled) ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
  ├────────────────────────┬─────────────────────────────────────┤
  │ DAYLIGHT               │ TONIGHT                            │
  │  9a  Standup           │  6:30p  Dinner                     │
  │  11a Review            │  8p     Read                       │ 194px
  │  2p  Workshop          │                                    │
  │  4p  1:1               │  🌙 Waxing Gibbous  63%           │
  ├────────────────────────┴─────────────────────────────────────┤
  │ ☀ 72° Partly Cloudy  H:78 L:60  AQI 42  Day 95/365        │ 80px
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from src.render.fonts import nucore_condensed, regular
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

_HEADER_H = 36
_ARC_H = 170
_FOOTER_H = 80
_SCHEDULE_H = 480 - _HEADER_H - _ARC_H - _FOOTER_H  # 194


def sunrise_theme() -> Theme:
    """Return the sunrise sun-arc daylight theme."""
    return Theme(
        name="sunrise",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            sunrise=ComponentRegion(0, 0, 800, 480),
            # Hide standard regions not used by this theme
            header=ComponentRegion(0, 0, 800, _HEADER_H, visible=False),
            week_view=ComponentRegion(0, 0, 800, 320, visible=False),
            weather=ComponentRegion(0, 0, 800, 120, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            info=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, 320, visible=False),
            draw_order=["sunrise"],
        ),
        style=ThemeStyle(
            font_title=nucore_condensed,
            font_section_label=nucore_condensed,
            font_regular=regular,
            invert_header=True,
            show_borders=True,
        ),
    )
