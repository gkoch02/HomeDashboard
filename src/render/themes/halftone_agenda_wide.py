"""halftone_agenda_wide — the split-plate agenda drawn for a 1360x480 strip.

``halftone_agenda`` reaches the 10.85" panel either stretched, which pulls the
engraving wide and the agenda type with it, or fitted, which leaves a third of
the strip blank. This theme draws the same plate at the strip's own size, in
three panes: the illustration and weather band at the left, today's agenda at
half again its usual width in the middle, and a rail at the right for the data
the 800x480 plate has no room for — alerts, the next day's events, the
forecast, birthdays, air quality and the moon. See
``src/render/components/halftone_agenda_wide_panel.py`` for the plate.

The style is ``halftone_agenda``'s own — L-mode canvas, Floyd-Steinberg for the
engraving, Righteous for display type, DM Sans one weight up for the rows, and
the yellow-and-red Inky pair — so a household running both sees one theme on
two panels. On the four-ink 10.85" panel the same two accents are the ones it
has: yellow rings the sun, marks each timed event and sets the "updated"
stamp; red marks all-day events, the dateline, the alert bar and a birthday
today.

Two days past today are fetched for it (``EXTRA_EVENT_DAYS``): the agenda
rolls to tomorrow after dark, and the rail then shows the day after that.
"""

from __future__ import annotations

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold, righteous
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


def halftone_agenda_wide_theme() -> Theme:
    """Return the halftone_agenda_wide (panoramic split-plate agenda) theme."""
    return Theme(
        name="halftone_agenda_wide",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            canvas_mode="L",
            preferred_quantization_mode="floyd_steinberg",
            prefer_color_on_inky=True,
            halftone_agenda_wide=ComponentRegion(0, 0, CANVAS_W, CANVAS_H),
            header=ComponentRegion(0, 0, 0, 0, visible=False),
            week_view=ComponentRegion(0, 0, 0, 0, visible=False),
            weather=ComponentRegion(0, 0, 0, 0, visible=False),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            today_view=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["halftone_agenda_wide"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=255,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            font_title=righteous,
            font_section_label=righteous,
            font_date_number=righteous,
            label_font_size=14,
            label_font_weight="semibold",
            accent_primary=INKY_YELLOW,
            accent_secondary=INKY_RED,
            inky_palette=(INKY_YELLOW, INKY_RED),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "halftone_agenda_wide",
        halftone_agenda_wide_theme,
        inky_palette=(INKY_YELLOW, INKY_RED),
    )


_register()
