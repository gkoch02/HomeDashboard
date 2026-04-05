"""newspaper.py — Broadsheet newspaper layout theme.

A modern broadsheet layout with three distinct zones:

  ┌──────────────────────────────────────────────────────────────┐
  │ THE DASHBOARD              [inverted masthead]  Apr 5, 2026  │ 60px
  │══════════════════════════════════════════════════════════════│
  │                                │                             │
  │  TODAY'S AGENDA                │  WEATHER                    │
  │  9:00–10:00  Team Standup      │  ☀ 72°F  Partly Cloudy     │
  │  ...                           │  ...                        │
  │                                │─────────────────────────── │
  │                                │  WORDS OF WISDOM            │
  │                                │  "Quote of the day..."      │
  │                                │        — Author             │
  └────────────────────────────────┴─────────────────────────────┘

Left column (530px): Today's events as newspaper articles.
Right column (270px): Weather panel (top) + quote panel (bottom).
Decorative overlay: double-rule below masthead, vertical column separator.
"""

from __future__ import annotations

from PIL import ImageDraw

from src.render.fonts import (
    cinzel_black,
    cinzel_bold,
    playfair_bold,
    playfair_medium,
    playfair_regular,
    playfair_semibold,
)
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

# Layout constants
_MASTHEAD_H = 60
_LEFT_W = 530
_RIGHT_W = 270  # 800 - 530
_WEATHER_H = 220
_CONTENT_H = 480 - _MASTHEAD_H  # 420

# Split right column: weather on top, quote on bottom
_QUOTE_H = _CONTENT_H - _WEATHER_H  # 200


def _newspaper_overlay(
    draw: ImageDraw.ImageDraw, layout: ThemeLayout, style: ThemeStyle
) -> None:
    """Draw the double rule below the masthead and the vertical column separator."""
    # Double rule immediately below the masthead
    y1 = _MASTHEAD_H
    y2 = y1 + 3
    draw.line([(0, y1), (800, y1)], fill=style.fg, width=2)
    draw.line([(0, y2), (800, y2)], fill=style.fg, width=1)

    # Vertical column separator
    sep_x = _LEFT_W
    draw.line([(sep_x, _MASTHEAD_H + 4), (sep_x, 479)], fill=style.fg, width=1)


def newspaper_theme() -> Theme:
    """Return the newspaper broadsheet theme."""
    return Theme(
        name="newspaper",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # Masthead (repurposes the header region — taller than default)
            header=ComponentRegion(0, 0, 800, _MASTHEAD_H),
            # Left column: today's events as articles
            newspaper_events=ComponentRegion(0, _MASTHEAD_H, _LEFT_W, _CONTENT_H),
            # Right column top: weather panel
            weather=ComponentRegion(_LEFT_W, _MASTHEAD_H, _RIGHT_W, _WEATHER_H),
            # Right column bottom: quote panel
            info=ComponentRegion(_LEFT_W, _MASTHEAD_H + _WEATHER_H, _RIGHT_W, _QUOTE_H),
            # Hide standard regions not used by this theme
            week_view=ComponentRegion(0, 0, 800, 320, visible=False),
            birthdays=ComponentRegion(0, 0, 800, 40, visible=False),
            today_view=ComponentRegion(0, 0, 800, 320, visible=False),
            draw_order=["header", "newspaper_events", "weather", "info"],
            overlay_fn=_newspaper_overlay,
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=True,
            invert_today_col=False,
            invert_allday_bars=True,
            # Masthead title in Cinzel Black for that broadsheet feel
            font_title=cinzel_black,
            # Body text in Playfair Display (classic newspaper serif)
            font_regular=playfair_regular,
            font_medium=playfair_medium,
            font_semibold=playfair_semibold,
            font_bold=playfair_bold,
            font_quote=playfair_regular,
            font_quote_author=playfair_regular,
            # Section labels in Cinzel Bold (small caps feel)
            font_section_label=cinzel_bold,
            label_font_size=9,
            label_font_weight="bold",
            component_labels={
                "newspaper_events": "TODAY'S AGENDA",
                "weather": "WEATHER",
                "info": "WORDS OF WISDOM",
            },
            show_borders=True,
        ),
    )
