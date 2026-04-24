"""astronomy.py — Full-canvas "sky tonight" theme.

Displays sunrise/sunset/twilight times, moon phase, day-length delta, the next
upcoming meteor shower, and the astronomical dark-sky window.  All data is
computed locally — no external API calls.

Four-quadrant layout with a wide dark-sky footer.  Uses DM Sans for a clean
data-dashboard feel that complements the moonphase theme (which is expressive
and atmospheric) rather than duplicating it.
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle


def astronomy_theme() -> Theme:
    """Return the astronomy "sky tonight" theme."""
    return Theme(
        name="astronomy",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            astronomy=ComponentRegion(0, 0, 800, 480),
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["astronomy"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=True,
            invert_today_col=False,
            invert_allday_bars=False,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            font_title=dm_bold,
            font_section_label=dm_bold,
            label_font_size=11,
            label_font_weight="bold",
            show_borders=True,
        ),
    )
