"""wide_horizon theme — the next three days of sky, weather and plans on one axis.

The panoramic theme built for what the 1360x480 strip can do and an 800x480
plate cannot: a 72-hour time axis at a readable scale. The sky across the
strip is coloured by the sun's real altitude at every moment — day, twilight
and night following each other left to right — the forecast temperature runs
over it as one line, rain hangs beneath it, and the calendar's events sit
below on the same hours. See ``src/render/components/wide_horizon_panel.py``.

Type is **Big Shoulders Display** (condensed Chicago-signage grotesque) for
day names, temperatures and the hero reading, DM Sans for event titles and
small labels. On a colour panel the twilights are ordered dithers between
pairs of inks — pale yellow, orange, maroon — the temperature line and
today's name are red, and the sun and moon yellow; the registered Inky pair is
red and yellow.

The plate is drawn in pure inks (ordered dithers, unantialiased type), and
declares ``ordered`` quantization so a monochrome panel that scales it
re-screens its tones rather than thresholding a blurred dither to flat ink —
which also, correctly, derives it out of partial refresh: the fast waveform
fades dithered ink. ``EXTRA_EVENT_DAYS`` fetches the days the window reaches
past the Monday-anchored week.
"""

from __future__ import annotations

from src.render.fonts import (
    big_shoulders_black,
    big_shoulders_extrabold,
    dm_bold,
    dm_medium,
    dm_regular,
    dm_semibold,
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


def wide_horizon_theme() -> Theme:
    """Return the wide_horizon (72-hour panorama) theme."""
    return Theme(
        name="wide_horizon",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            canvas_mode="L",
            preferred_quantization_mode="ordered",
            prefer_color_on_inky=True,
            wide_horizon=ComponentRegion(0, 0, CANVAS_W, CANVAS_H),
            header=ComponentRegion(0, 0, 0, 0, visible=False),
            week_view=ComponentRegion(0, 0, 0, 0, visible=False),
            weather=ComponentRegion(0, 0, 0, 0, visible=False),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            today_view=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["wide_horizon"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=255,
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            font_title=big_shoulders_black,
            font_section_label=dm_bold,
            font_date_number=big_shoulders_black,
            font_month_title=big_shoulders_extrabold,
            label_font_size=13,
            accent_primary=INKY_RED,
            accent_secondary=INKY_YELLOW,
            inky_palette=(INKY_RED, INKY_YELLOW),
            show_borders=False,
        ),
    )


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("wide_horizon", wide_horizon_theme, inky_palette=(INKY_RED, INKY_YELLOW))


_register()
