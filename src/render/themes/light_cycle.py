"""light_cycle.py — Full-canvas radial 24-hour clock theme.

A dial on the left shows the whole day at once: the light band's tone tracks
the sky (solid night, engraved rings through twilight, open daylight), today's
events sit as arcs over their durations, and the sun rides the band at the
current time. The column on the right carries the numbers — sunrise, sunset,
day length and its change since yesterday, the current weather, today's agenda.

  ┌──────────────────────────────────────────────────────────────┐
  │              00                   LIGHT CYCLE                │
  │        ╭───────────╮              ─────────────────────────  │
  │      ╱ ▓▓▓ night ▓▓▓ ╲            SUNRISE  SUNSET  DAYLIGHT  │
  │     │ ≡  ┌───────┐  ≡ │           6:31a    7:26p   12h 54m   │
  │  18 │    │MONDAY │    │ 06        ─────────────────────────  │
  │     │ ◜  │   6   │  ◝ │           ☁ 42°  Partly cloudy       │
  │      ╲   │ APRIL │   ╱            ─────────────────────────  │
  │        ╰──── ☀ ────╯              TODAY · 2 EVENTS           │
  │              12                   ■ 2p   1:1 with Alex       │
  └──────────────────────────────────────────────────────────────┘

On Inky the daylight span fills with yellow and the twilight rings turn blue;
all type stays black, since yellow type on the Spectra white does not read.

Editing notes: Pure math from ``src/astronomy.py`` and ``src/render/moon.py``; it has no
fetcher.
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold, righteous
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
            # Righteous (OFL display sans) for the hero day-of-month numeral —
            # heavier strokes than DM Sans Bold so the digit reads cleanly at
            # 70+ pt against the inner disc.
            font_date_number=righteous,
            label_font_size=11,
            label_font_weight="bold",
            accent_primary=INKY_YELLOW,
            accent_secondary=INKY_BLUE,
            inky_palette=(INKY_YELLOW, INKY_BLUE),
            show_borders=True,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("light_cycle", light_cycle_theme, inky_palette=(INKY_YELLOW, INKY_BLUE))


_register()
