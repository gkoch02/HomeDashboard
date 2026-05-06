"""light_cycle.py — Full-canvas radial 24-hour clock theme.

A circular dial visualises the entire day at a glance: twilight bands ring
the rim, calendar events appear as radial dashes inside that ring, and a
needle plus sun (or moon) glyph mark the current moment.  Center disc
holds today's date and weather summary.

  ┌──────────────────────────────────────────────────────────────┐
  │  LIGHT  CYCLE                                  PORTLAND, OR  │
  │                          ╱─── 00 ───╲                        │
  │                       ·  · twilight ·  ·                     │
  │                    ·         ▓ NIGHT ▓        ·              │
  │                   ·   ┌───────────┐         ☀              │
  │   18 ── ── ── ── ─┤   │  THURSDAY │ ── ── ── ── 06 ── ──    │
  │                   ·   │     27    │         ·              │
  │                    ·  │   APRIL   │        ·               │
  │                       │ 72° H78 L60│                        │
  │                       └───────────┘                         │
  │                          ╲─── 12 ───╱                        │
  │                                                              │
  │     RISE              SET             EVENTS                 │
  │     6:24a             7:51p            5                     │
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import (
    INKY_BLUE,
    INKY_YELLOW,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)


def light_cycle_theme() -> Theme:
    """Return the Light Cycle radial 24-hour clock theme."""
    return Theme(
        name="light_cycle",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            light_cycle=ComponentRegion(0, 0, 800, 480),
            # Hide standard regions not used by this theme
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["light_cycle"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            font_title=dm_bold,
            font_section_label=dm_bold,
            label_font_size=11,
            label_font_weight="bold",
            accent_primary=INKY_YELLOW,
            accent_secondary=INKY_BLUE,
            inky_palette=(INKY_YELLOW, INKY_BLUE),
            show_borders=True,
        ),
    )


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("light_cycle", light_cycle_theme, inky_palette=(INKY_YELLOW, INKY_BLUE))


_register()
