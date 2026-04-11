"""Full-screen monthly calendar theme with an event-density heatmap."""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def monthly_theme() -> Theme:
    """Return the monthly wall-calendar heatmap theme."""
    return Theme(
        name="monthly",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            canvas_mode="1",
            prefer_color_on_inky=True,
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 0, 800, 320, visible=False),
            weather=ComponentRegion(0, 0, 300, 120, visible=False),
            birthdays=ComponentRegion(0, 0, 250, 120, visible=False),
            info=ComponentRegion(0, 0, 250, 120, visible=False),
            today_view=ComponentRegion(0, 0, 800, 280, visible=False),
            monthly=ComponentRegion(0, 0, 800, 480),
            draw_order=["monthly"],
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
            label_font_size=10,
            label_font_weight="semibold",
            show_borders=False,
        ),
    )
