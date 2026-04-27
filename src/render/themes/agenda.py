"""agenda theme — high-visibility week-view calendar.

A signage-grade weekly calendar designed to be read from across a room:
- Tall 50px header with the dashboard title in heavy DM Sans Bold
- Dominant 350px 7-day week_view grid with strong contrast
- Slim 80px strip at the bottom with weather + birthdays only (no quote)
- DM Sans family throughout, bumped weights for headers / date / labels
- Red Inky accent (dashboard title / section labels / alerts)
"""

from src.render import fonts
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def agenda_theme() -> Theme:
    """High-visibility week-view theme: bold DM Sans + dominant calendar grid."""
    inky_red = 3  # mirror of canvas._INKY_RED
    return Theme(
        name="agenda",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            header=ComponentRegion(0, 0, 800, 50),
            week_view=ComponentRegion(0, 50, 800, 350),
            weather=ComponentRegion(0, 400, 480, 80),
            birthdays=ComponentRegion(480, 400, 320, 80),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["header", "week_view", "weather", "birthdays"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            accent_primary=inky_red,
            accent_alert=inky_red,
            font_regular=fonts.dm_regular,
            font_medium=fonts.dm_medium,
            font_semibold=fonts.dm_semibold,
            font_bold=fonts.dm_bold,
            font_title=fonts.dm_bold,
            font_date_number=fonts.dm_bold,
            font_month_title=fonts.dm_bold,
            font_section_label=fonts.dm_bold,
            invert_header=True,
            invert_today_col=True,
            invert_allday_bars=True,
            show_borders=True,
            show_forecast_strip=False,
            spacing_scale=1.3,
            label_font_size=13,
            label_font_weight="bold",
        ),
    )
