"""Message theme.

Forgoes the calendar, birthdays, and info panel entirely.  The full display is
devoted to a large centered user-supplied message, with a compact weather banner
running across the bottom.

Layout (800 × 480):
  ┌────────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │                                                                        │
  │                  "The message text, large and                          │
  │                   centered, wrapping as needed."                       │
  │                                                                        │
  │                                                                        │
  ├── thin rule ───────────────────────────────────────────────────────────┤
  │  ☀ 72°  Partly Cloudy   H:78° L:60°  Feels 70°  │  Mon ··· Tue ···  🌒│
  └────────────────────────────────────────────────────────────────────────┘

Font choice: Space Grotesk — a proportional sans-serif with distinctive
letterforms (a, G, R, t) that give data-dashboard personality while
remaining highly legible at large sizes on eInk displays.

Usage:
    python src/main.py --dry-run --dummy --theme message --message "Hello!"
"""

from src.render.fonts import sg_bold, sg_medium, sg_regular
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

BANNER_H = 80  # height of the bottom weather strip


def message_theme() -> Theme:
    """Return the message theme."""
    msg_h = 480 - BANNER_H  # 400 px for the message text

    return Theme(
        name="message",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # Unused regions are hidden but kept with sensible defaults
            # so that the layout dataclass remains fully populated.
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 0, 800, msg_h, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            info=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, msg_h, visible=False),
            # Message main area: full canvas above the weather banner
            message=ComponentRegion(0, 0, 800, msg_h),
            # Weather banner: full width at the bottom
            weather=ComponentRegion(0, msg_h, 800, BANNER_H),
            draw_order=["message", "message_weather"],
        ),
        style=ThemeStyle(
            fg=0,  # black ink on white paper
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            # Space Grotesk: proportional sans with data-dashboard character.
            # No semibold weight bundled — bold is used for both bold and semibold.
            font_regular=sg_regular,
            font_medium=sg_medium,
            font_semibold=sg_bold,
            font_bold=sg_bold,
            label_font_size=11,
            label_font_weight="semibold",
        ),
    )


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_RED
    from src.render.themes.registry import register_theme

    register_theme("message", message_theme, inky_palette=(INKY_RED, INKY_BLUE))


_register()
