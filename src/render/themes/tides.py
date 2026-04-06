"""tides.py — Alternating inverted horizontal bands theme.

Full-width bands flowing top to bottom, alternating black-on-white and
white-on-black.  Shows ALL data sources in a single view with a striking
zebra-stripe visual that exploits eInk's crisp contrast.

  ▓▓▓ SUNDAY  APRIL 5  2026          ten past ten     ▓▓▓  42px
      9a Standup · 11a Review · 2p Workshop · 6:30p Din     50px
  ▓▓▓ ☀ 72°  Partly Cloudy  H:78° L:60°  Feels: 68° ▓▓▓  40px
      MON 74/58 ☁  TUE 80/63 ☀  WED 76/61  THU 71/55      55px
  ▓▓▓ AQI 42 Good  PM2.5: 8.2  ↑6:12a ↓7:48p  🌙63% ▓▓▓  36px
      🎂 Sarah (30) 14d · Mike (45) 38d · Jan 67d           36px
  ▓▓▓ "Dwell on the beauty of life."  — Marcus Aurelius▓▓▓  80px
      pi4b · 3d 7h up · load 0.42 · 72% RAM · 45°C         rest
"""

from __future__ import annotations

from src.render.fonts import nucore_condensed, regular
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def tides_theme() -> Theme:
    """Return the tides alternating-bands theme."""
    return Theme(
        name="tides",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            tides=ComponentRegion(0, 0, 800, 480),
            # Hide standard regions
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 0, 800, 320, visible=False),
            weather=ComponentRegion(0, 0, 800, 120, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            info=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, 320, visible=False),
            draw_order=["tides"],
        ),
        style=ThemeStyle(
            font_regular=regular,
            font_title=nucore_condensed,
            font_section_label=nucore_condensed,
            show_borders=False,
        ),
    )
