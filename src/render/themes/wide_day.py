"""wide_day theme — today as a timeline across a 1360x480 panel.

The panoramic theme that uses the strip's shape rather than tolerating it:
the 10.85" Waveshare panel is a band nearly three times as wide as it is
tall, and a band is the natural shape for a time axis. The middle of the plate
is today's hours running left to right with every timed event drawn as a bar
over its real span; the left end carries the date and the weather now, the
right end the next few events and the week's birthdays. See
``src/render/components/wide_day_panel.py`` for the plate itself.

Typography is DM Sans throughout — the plate carries a lot of small type in
bars and rails, and the screen-optimised cut holds up at 12–16 px — with the
hero day-of-month numeral in DM Sans Bold via ``font_date_number``.

The bar for the event in progress and the NOW marker take the alert accent:
red on the four-ink panel and on Spectra 6, ink on monochrome. Section labels
and the month line take the primary accent, also red; nothing on the plate
asks for yellow, so the registered pair is red and black.

This is a time-driven plate. The marker and the bar states follow the clock,
so the image changes every tick; on a colour panel, whose full refresh
flashes for twenty seconds, set ``display.min_refresh_interval_seconds`` to
space the writes out. The theme is listed in ``THEMES_NEEDING_TOMORROW``
because the UP NEXT rail reaches into tomorrow once today's events are done.
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
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


def wide_day_theme() -> Theme:
    """Return the wide_day (panoramic timeline) theme."""
    return Theme(
        name="wide_day",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            wide_day=ComponentRegion(0, 0, CANVAS_W, CANVAS_H),
            # Hide the standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 0, 0, visible=False),
            week_view=ComponentRegion(0, 0, 0, 0, visible=False),
            weather=ComponentRegion(0, 0, 0, 0, visible=False),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            today_view=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["wide_day"],
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
            font_date_number=dm_bold,
            label_font_size=14,
            label_font_weight="bold",
            accent_primary=INKY_RED,
            accent_secondary=INKY_BLACK,
            accent_alert=INKY_RED,
            inky_palette=(INKY_RED, INKY_BLACK),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("wide_day", wide_day_theme, inky_palette=(INKY_RED, INKY_BLACK))


_register()
