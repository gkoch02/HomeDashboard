"""wide_week theme — the standard dashboard reflowed for a 1360x480 panel.

The first of the panoramic themes, and the one that needs no new component.
The 10.85" Waveshare panel is 1360 px wide and 480 tall, nearly three times
as wide as it is high; the 800x480 week view stretched onto it is unreadable,
and fitted it is a letterboxed band with a third of the panel blank. This
theme draws the same header, week grid, weather, birthdays and quote at the
panel's native size instead, with the extra width spent where a week grid
wants it: seven columns of 128 px rather than 114, and a full-height rail
beside them stacking the three information panels top to bottom.

Registered with a red-and-black accent pair. The 10.85" panel has four inks —
black, white, yellow and red — and the two it lacks resolve to black at render
time, so a theme meant for it names only the two it has: red for the section
labels, the title and alerts, black for the glyphs and bullets. On a Spectra 6
panel the same pair applies, and on a monochrome one both fall back to ink.
"""

from __future__ import annotations

from src.render.theme import (
    INKY_BLACK,
    INKY_RED,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)

CANVAS_W = 1360
CANVAS_H = 480
HEADER_H = 44
WEEK_W = 900


def wide_week_theme() -> Theme:
    """Return the wide_week (panoramic week-view) theme."""
    rail_x = WEEK_W
    rail_w = CANVAS_W - WEEK_W
    body_y = HEADER_H
    body_h = CANVAS_H - HEADER_H
    weather_h = 196
    birthdays_h = 110
    return Theme(
        name="wide_week",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            header=ComponentRegion(0, 0, CANVAS_W, HEADER_H),
            week_view=ComponentRegion(0, body_y, WEEK_W, body_h),
            weather=ComponentRegion(rail_x, body_y, rail_w, weather_h),
            birthdays=ComponentRegion(rail_x, body_y + weather_h, rail_w, birthdays_h),
            info=ComponentRegion(
                rail_x,
                body_y + weather_h + birthdays_h,
                rail_w,
                body_h - weather_h - birthdays_h,
            ),
            today_view=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["header", "week_view", "weather", "birthdays", "info"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            accent_primary=INKY_RED,
            accent_secondary=INKY_BLACK,
            accent_alert=INKY_RED,
            inky_palette=(INKY_RED, INKY_BLACK),
            label_font_size=12,
            label_font_weight="semibold",
            spacing_scale=1.15,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("wide_week", wide_week_theme, inky_palette=(INKY_RED, INKY_BLACK))


_register()
