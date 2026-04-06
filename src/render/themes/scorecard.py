"""scorecard.py — Numeric KPI grid theme.

Every data source becomes a big hero number in a 4-column tile grid.
Introduces computed metrics (% of day remaining, sunset countdown).

  ┌──────────────────────────────────────────────────────────────┐
  │ S C O R E C A R D               SUN  APR 5   10:23 AM      │ 40px
  ├──────────┬──────────┬──────────┬─────────────────────────────┤
  │    3     │   72°    │  AQI 42  │  W14 · 2026               │
  │ EVENTS   │ OUTDOOR  │ AIR      │  26% of year              │ 130px
  ├──────────┼──────────┼──────────┼─────────────────────────────┤
  │   47%    │  3:22p   │   14d    │   52°C                    │
  │ DAY LEFT │ SUNSET   │ BIRTHDAY │  CPU TEMP                 │ 130px
  ├──────────┴──────────┼──────────┴─────────────────────────────┤
  │  )) )) )) ))        │ "The only way to do great work…"     │
  │  WAXING GIBBOUS     │                    — Steve Jobs       │ 140px
  └─────────────────────┴──────────────────────────────────────┘
"""

from __future__ import annotations

from src.render.fonts import sg_bold, sg_medium, sg_regular
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def scorecard_theme() -> Theme:
    """Return the scorecard numeric KPI grid theme."""
    return Theme(
        name="scorecard",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            scorecard=ComponentRegion(0, 0, 800, 480),
            # Hide standard regions
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 0, 800, 320, visible=False),
            weather=ComponentRegion(0, 0, 800, 120, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            info=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, 320, visible=False),
            draw_order=["scorecard"],
        ),
        style=ThemeStyle(
            font_regular=sg_regular,
            font_medium=sg_medium,
            font_bold=sg_bold,
            font_title=sg_bold,
            font_section_label=sg_bold,
            show_borders=True,
        ),
    )
