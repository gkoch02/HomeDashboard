"""wide_ephemeris theme — HomeDashboardTV's Ephemeris, re-cut for the 1360x480 strip.

What is ahead, in the TV app's HUD dress: the next day as a strip (temperature,
rain, daylight and the calendar's events in lanes, a gold line at the current
hour), then the agenda, the conditions now and the outlook, on a dark ground.
See ``src/render/components/wide_ephemeris_panel.py``.

Type is the TV's faces, set heavier for the panel: **Michroma** for the
wordmark and the reading now, **Saira** at weight 900 (800 on the light plate)
for everything else. The registered Inky pair is yellow (the
gold) and red (alerts); on the four-ink 10.85" panel the same inks are native.

The plate is drawn in pure inks with no dithered tones, so it declares
``threshold`` quantization. Its ground is ink, so it derives out of partial
refresh, which the colour panels lack anyway. ``repaint_slot_hours=1`` matches
the strip's hourly step and keeps each weather fetch from costing a colour
flash; the "synced" time can therefore be up to an hour behind.

Editing notes: the strip is anchored to the hour holding now (``Window.at``), so
the theme stays out of ``TIME_DRIVEN``; anything new drawn from the clock must
snap to that hour too. Michroma's degree sign is a full ring, so readings set
it in Saira. Michroma is Latin-only and only ever sets digits and the wordmark.
"""

from __future__ import annotations

from src.render.fonts import (
    michroma,
    saira_condensed,
    saira_condensed_bold,
)
from src.render.theme import (
    INKY_RED,
    INKY_YELLOW,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)

CANVAS_W = 1360
CANVAS_H = 480


def wide_ephemeris_theme() -> Theme:
    """Return the wide_ephemeris (Ephemeris HUD) theme."""
    return Theme(
        name="wide_ephemeris",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            canvas_mode="L",
            preferred_quantization_mode="threshold",
            prefer_color_on_inky=True,
            repaint_slot_hours=1,
            wide_ephemeris=ComponentRegion(0, 0, CANVAS_W, CANVAS_H),
            draw_order=["wide_ephemeris"],
        ),
        style=ThemeStyle(
            fg=255,
            bg=0,
            font_regular=saira_condensed,
            font_medium=saira_condensed,
            font_semibold=saira_condensed,
            font_bold=saira_condensed_bold,
            font_title=michroma,
            font_section_label=saira_condensed_bold,
            font_date_number=michroma,
            font_month_title=michroma,
            accent_primary=INKY_YELLOW,
            accent_secondary=INKY_RED,
            inky_palette=(INKY_YELLOW, INKY_RED),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("wide_ephemeris", wide_ephemeris_theme, inky_palette=(INKY_YELLOW, INKY_RED))


_register()
