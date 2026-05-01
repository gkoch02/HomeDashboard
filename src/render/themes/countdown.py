"""countdown.py — Config-driven days-until tracker theme.

Shows up to 5 user-configured target dates as countdowns. A single event renders
as a hero (giant number), multiple events stack as a list with decreasing
size.  Fully offline: events come from ``countdown.events`` in ``config.yaml``
so there is no fetcher, cache, or breaker involvement.

  ┌──────────────────────────────────────────────────────────────┐
  │  COUNTING DOWN TO                                            │
  │                                                              │
  │                       ╔═══════╗                              │
  │                       ║  42   ║                              │
  │                       ╚═══════╝                              │
  │                        DAYS                                  │
  │                    PARIS TRIP                                │
  │                    June 4, 2026                              │
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def countdown_theme() -> Theme:
    """Return the countdown theme — full-canvas big-number days-until tracker."""
    return Theme(
        name="countdown",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            countdown=ComponentRegion(0, 0, 800, 480),
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["countdown"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            label_font_size=14,
            label_font_weight="bold",
            show_borders=False,
        ),
    )


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_RED
    from src.render.themes.registry import register_theme

    register_theme("countdown", countdown_theme, inky_palette=(INKY_RED, INKY_BLUE))


_register()
