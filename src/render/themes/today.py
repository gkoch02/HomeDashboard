"""today theme — focused single-day dashboard.

Shows one day of data at a glance:
- Tall header (60px) with title and update time
- Large date panel (left 30%) + spacious event list (right 70%) in a 280px tall zone
- Standard bottom strip (140px) with weather, birthdays, and quote
"""

from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def today_theme() -> Theme:
    """A focused single-day theme: large date panel + spacious event list."""
    return Theme(
        name="today",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            header=ComponentRegion(0, 0, 800, 60),
            # week_view hidden — today_view replaces it
            week_view=ComponentRegion(0, 60, 800, 280, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280),
            weather=ComponentRegion(0, 340, 400, 140),
            birthdays=ComponentRegion(400, 340, 200, 140),
            info=ComponentRegion(600, 340, 200, 140),
            draw_order=["header", "today_view", "weather", "birthdays", "info"],
        ),
        style=ThemeStyle(
            invert_header=True,
            invert_today_col=True,
            invert_allday_bars=True,
            spacing_scale=1.3,
            label_font_size=12,
            label_font_weight="bold",
        ),
    )
