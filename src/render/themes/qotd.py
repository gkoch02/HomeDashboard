"""Quote-of-the-Day theme.

Forgoes the calendar, birthdays, and info panel entirely.  The full display is
devoted to a single beautifully typeset quote, with a compact weather banner
running across the bottom.

Layout (800 × 480):
  ┌────────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │                                                                        │
  │          "The quote of the day, large and centered,                    │
  │           wrapping gracefully across as many lines                     │
  │           as it needs."                                                │
  │                                                  — Author Name         │
  │                                                                        │
  │                                                                        │
  ├── thin rule ───────────────────────────────────────────────────────────┤
  │  ☀ 72°  Partly Cloudy   H:78° L:60°  Feels 70°  │  Mon ··· Tue ···  🌒│
  └────────────────────────────────────────────────────────────────────────┘

Font choice: Playfair Display — a refined transitional serif with high
contrast strokes that evoke classic editorial typography.  Legible at large
sizes on eInk displays.
"""

from src.render.fonts import (
    playfair_bold,
    playfair_medium,
    playfair_regular,
    playfair_semibold,
)
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

BANNER_H = 80  # height of the bottom weather strip

# Inky Spectra 6 palette indices used by src.render.canvas.
_INKY_BLUE = 4
_INKY_GREEN = 5


def qotd_theme() -> Theme:
    """Return the QOTD theme."""
    quote_h = 480 - BANNER_H  # 400 px for the quote

    return Theme(
        name="qotd",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # Unused regions are hidden but kept with sensible defaults
            # so that the layout dataclass remains fully populated.
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 0, 800, quote_h, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            info=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, quote_h, visible=False),
            # QOTD main area: full canvas above the weather banner
            qotd=ComponentRegion(0, 0, 800, quote_h),
            # Weather banner: full width at the bottom
            weather=ComponentRegion(0, quote_h, 800, BANNER_H),
            draw_order=["qotd", "qotd_weather"],
        ),
        style=ThemeStyle(
            fg=0,  # black ink on white paper
            bg=1,
            accent_info=_INKY_GREEN,
            accent_primary=_INKY_BLUE,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            # Playfair Display: the definitive legible decorative serif.
            font_regular=playfair_regular,
            font_medium=playfair_medium,
            font_semibold=playfair_semibold,
            font_bold=playfair_bold,
            label_font_size=11,
            label_font_weight="semibold",
        ),
    )
