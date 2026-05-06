"""almanac.py — Old-Farmer's-Almanac editorial theme.

Front-page composition: ornamental masthead, large editorial dateline, four
bordered sections in a 2×2 grid (Heavens / Sky / Week Ahead / Garden), and
a footer aphorism with author in small caps.

Typography is Playfair Display (body) + Cinzel (section labels and small caps)
for a 19th-century reference-book feel.  All data is already available
(weather, astronomy, moon, quote, events, birthdays) — no new fetcher needed.
"""

from __future__ import annotations

from src.render.fonts import (
    cinzel_black,
    cinzel_semibold,
    playfair_bold,
    playfair_medium,
    playfair_regular,
    playfair_semibold,
)
from src.render.theme import (
    INKY_BLACK,
    INKY_RED,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)


def almanac_theme() -> Theme:
    """Return the Almanac editorial theme."""
    return Theme(
        name="almanac",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            almanac=ComponentRegion(0, 0, 800, 480),
            # Hide standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["almanac"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            font_regular=playfair_regular,
            font_medium=playfair_medium,
            font_semibold=playfair_semibold,
            font_bold=playfair_bold,
            font_title=playfair_bold,
            font_section_label=cinzel_black,
            font_quote=playfair_regular,
            font_quote_author=cinzel_semibold,
            label_font_size=12,
            label_font_weight="bold",
            accent_primary=INKY_RED,
            accent_secondary=INKY_BLACK,
            inky_palette=(INKY_RED, INKY_BLACK),
            show_borders=True,
        ),
    )


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme("almanac", almanac_theme, inky_palette=(INKY_RED, INKY_BLACK))


_register()
