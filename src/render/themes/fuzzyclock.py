"""Fuzzy-clock theme.

The full display is devoted to the current time expressed as a natural-language
phrase ("half past seven", "quarter to nine"), with a compact weather banner
running across the bottom.

Layout (800 × 480):
  ┌────────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │                                                                        │
  │                     half past seven                                    │
  │                                                                        │
  │                  Wednesday  ·  23 March                                │
  │                                                                        │
  │                                                                        │
  ├── thin rule ───────────────────────────────────────────────────────────┤
  │  ☀ 72°  Partly Cloudy   H:78° L:60°  Feels 70°  │  Mon ··· Tue ···  🌒│
  └────────────────────────────────────────────────────────────────────────┘

Font choice: DM Sans — a screen-optimised geometric sans-serif with excellent
legibility at large display sizes on eInk.

Update frequency: time phrases change at 5-minute boundaries, so the cron /
systemd timer should run every 5 minutes.  The image-hash comparison in
main.py ensures the eInk panel is only physically refreshed when the phrase
actually changes.
"""

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

BANNER_H = 80   # height of the bottom weather strip


def fuzzyclock_theme() -> Theme:
    """Return the fuzzyclock theme."""
    clock_h = 480 - BANNER_H   # 400 px for the clock face

    return Theme(
        name="fuzzyclock",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # Standard regions are hidden — not used by this theme
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 0, 800, clock_h, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            info=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, clock_h, visible=False),
            qotd=ComponentRegion(0, 0, 800, clock_h, visible=False),
            # Fuzzyclock main area: full canvas above the weather banner
            fuzzyclock=ComponentRegion(0, 0, 800, clock_h),
            # Weather banner: full width at the bottom
            weather=ComponentRegion(0, clock_h, 800, BANNER_H),
            draw_order=["fuzzyclock", "fuzzyclock_weather"],
        ),
        style=ThemeStyle(
            fg=0,   # black ink on white paper
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            label_font_size=11,
            label_font_weight="semibold",
        ),
    )
