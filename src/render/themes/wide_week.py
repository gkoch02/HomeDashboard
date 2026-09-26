"""wide_week theme — the standard week view beside an editorial rail, 1360x480.

The week grid is the dashboard's signature, and this theme keeps it exactly as
the default theme draws it — day columns, spanning all-day bars, the month and
date block in the weekend's lower half — giving it the right-hand 920 px of the
strip (seven columns of ~131 px, wider than the 800x480 original's 114). The
440 px to its left is a rail laid out like a broadsheet column rather than a
stack of the standard panels: the weekday masthead, the weather now, what is on
or next, a short forecast beside the sky, birthdays and the day's quote. See
``src/render/components/wide_week_rail_panel.py``.

There is no header bar: the rail's masthead carries the "updated" stamp and the
stale mark the header used to, and the grid runs the panel's full height.

The rail's NOW/NEXT line is the one thing that reads the clock, and it moves
only when an event starts or ends. It can reach into next week on a Sunday, so
the theme fetches one extra day (``EXTRA_EVENT_DAYS``).

Registered with a red-and-black accent pair. The 10.85" panel has four inks —
black, white, yellow and red — and names only the two a light plate can carry
type in: red for the rail's section labels, the alert bar and the grid's
accents, black for everything else. On a monochrome panel both are ink.
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
RAIL_W = 440


def wide_week_theme() -> Theme:
    """Return the wide_week (week grid + editorial rail) theme."""
    week_w = CANVAS_W - RAIL_W
    return Theme(
        name="wide_week",
        layout=ThemeLayout(
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            wide_week_rail=ComponentRegion(0, 0, RAIL_W, CANVAS_H),
            week_view=ComponentRegion(RAIL_W, 0, week_w, CANVAS_H),
            header=ComponentRegion(0, 0, 0, 0, visible=False),
            weather=ComponentRegion(0, 0, 0, 0, visible=False),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(0, 0, 0, 0, visible=False),
            today_view=ComponentRegion(0, 0, 0, 0, visible=False),
            draw_order=["week_view", "wide_week_rail"],
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
