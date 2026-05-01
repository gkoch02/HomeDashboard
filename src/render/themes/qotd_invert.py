"""Quote-of-the-Day Inverted theme.

Identical layout to ``qotd`` — full-screen centered quote with a compact
weather banner across the bottom — but with the color scheme flipped:
white text on a black canvas instead of black on white.

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

Font choice: Playfair Display — same as ``qotd``.  The high-contrast strokes
of this transitional serif read especially well reversed out of a dark ground.
"""

from src.render.fonts import (
    playfair_bold,
    playfair_medium,
    playfair_regular,
    playfair_semibold,
)
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

BANNER_H = 80  # height of the bottom weather strip


def qotd_invert_theme() -> Theme:
    """Return the QOTD Inverted theme."""
    quote_h = 480 - BANNER_H  # 400 px for the quote

    return Theme(
        name="qotd_invert",
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
            fg=1,  # white text on black canvas
            bg=0,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            # Playfair Display: high-contrast strokes read beautifully reversed out.
            font_regular=playfair_regular,
            font_medium=playfair_medium,
            font_semibold=playfair_semibold,
            font_bold=playfair_bold,
            label_font_size=11,
            label_font_weight="semibold",
        ),
    )


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.theme import INKY_RED, INKY_YELLOW
    from src.render.themes.registry import register_theme

    register_theme("qotd_invert", qotd_invert_theme, inky_palette=(INKY_YELLOW, INKY_RED))


_register()
