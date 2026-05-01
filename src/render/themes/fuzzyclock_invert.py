"""Fuzzy-clock Inverted theme.

Identical layout to ``fuzzyclock`` — full-screen natural-language clock phrase
with a compact weather banner across the bottom — but with the color scheme
flipped: white text on a black canvas instead of black on white.

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

Font choice: DM Sans — same as ``fuzzyclock``.  The geometric shapes of this
screen-optimised sans-serif hold up well at large sizes when reversed out of
a dark background.
"""

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

BANNER_H = 80  # height of the bottom weather strip


def fuzzyclock_invert_theme() -> Theme:
    """Return the fuzzyclock Inverted theme."""
    clock_h = 480 - BANNER_H  # 400 px for the clock face

    return Theme(
        name="fuzzyclock_invert",
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
            fg=1,  # white text on black canvas
            bg=0,
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


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_YELLOW
    from src.render.themes.registry import register_theme

    register_theme(
        "fuzzyclock_invert", fuzzyclock_invert_theme, inky_palette=(INKY_YELLOW, INKY_BLUE)
    )


_register()
