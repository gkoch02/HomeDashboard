"""wide_forecast theme — a weather strip for a 1360x480 panel.

The weather-first panoramic theme. Where ``weather`` stacks the forecast
beneath the current conditions on a landscape plate, this one lays them side
by side across the 10.85" panel's width: the conditions now as a hero block at
the left end, five forecast cards in a row, and a band beneath the cards for
alerts, air quality and the moon. See
``src/render/components/wide_forecast_panel.py`` for the plate itself.

DM Sans throughout, with the temperature numeral in DM Sans Bold. The colour
story is the one the four-ink panel can tell: red (primary) for the section
labels, today's chip and — via the alert accent — active alerts and an
unhealthy AQI; yellow (secondary) for the filled precipitation bars, where a
light fill behind a hairline outline reads well. On a monochrome panel the
bars fill with ink and the chip inverts, so nothing is lost.

The plate does not read the clock: its caption uses the data timestamp, and
an idle tick renders the same image.
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
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


def wide_forecast_theme() -> Theme:
    """Return the wide_forecast (panoramic weather strip) theme."""
    return Theme(
        name="wide_forecast",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            wide_forecast=ComponentRegion(0, 0, CANVAS_W, CANVAS_H),
            # Hide the standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 0, 0, visible=False),
            week_view=ComponentRegion(0, 0, 0, 0, visible=False),
            weather=ComponentRegion(0, 0, 0, 0, visible=False),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            today_view=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["wide_forecast"],
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
            accent_secondary=INKY_YELLOW,
            accent_alert=INKY_RED,
            inky_palette=(INKY_RED, INKY_YELLOW),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("wide_forecast", wide_forecast_theme, inky_palette=(INKY_RED, INKY_YELLOW))


_register()
