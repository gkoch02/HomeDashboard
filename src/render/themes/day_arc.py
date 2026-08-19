"""day_arc.py — calendar-forward dithered day plate.

The calendar-promoting sibling of ``halftone``. The top 200 px is a ribbon
that draws today as a left-to-right arc: a horizontal sky gradient keyed to
the real sunrise and sunset, the sun (or moon, after dark) riding a sine arc
at the current time's true horizontal position, and weather art around it.
The ribbon's baseline is a live time axis carrying hour ticks, a NOW caret and
one pip per timed event, so the artwork *is* the calendar rather than
competing with it.

Below a 6-px ordered-Bayer rule, the remaining 274 px is given to the day
itself: a full-height agenda on the left and a narrow rail on the right for
temperature, conditions and upcoming birthdays. Dithering carries meaning in
the agenda — elapsed events are perforated on a Bayer lattice, the event in
progress is inverted into a solid bar, and everything still to come is crisp.

Typography is split by role rather than by face. Righteous — halftone's single
display voice — carries the chrome (dateline, temperature numeral, section
labels, the TOMORROW chip), while DM Sans sets the agenda rows: this theme
puts far more small text on the plate than halftone does, and DM Sans is the
bundled screen-optimised cut that survives at 18 px.

On Inky the canvas is RGB (``prefer_color_on_inky=True``): yellow marks the
sun, the moon's limb and the daylight bar; red marks the NOW caret, the
in-progress event and birthday bullets. Everything else stays black on paper.
"""

from __future__ import annotations

from src.render.fonts import dm_medium, dm_regular, dm_semibold, righteous
from src.render.theme import (
    INKY_RED,
    INKY_YELLOW,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
)


def day_arc_theme() -> Theme:
    """Return the day_arc (day ribbon + promoted agenda) theme."""
    return Theme(
        name="day_arc",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            canvas_mode="L",
            # Floyd-Steinberg turns the ribbon's smooth horizontal gradient
            # into the engraving-style dither this theme shares with halftone.
            # It is harmless to the agenda's small type because every glyph is
            # drawn in solid ink over a solid paper underlay — FS only diffuses
            # intermediate values.
            preferred_quantization_mode="floyd_steinberg",
            prefer_color_on_inky=True,
            # The dithered sky ribbon is the plate: the fast waveform lightens it
            # in bands, and the axis strip under it goes with them.
            supports_partial_refresh=False,
            day_arc=ComponentRegion(0, 0, 800, 480),
            # Hide all standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["day_arc"],
        ),
        style=ThemeStyle(
            # L-mode light canvas invariant: black ink on near-white field.
            fg=0,
            bg=255,
            # Role-based pairing: DM Sans for the dense agenda body, Righteous
            # for every display element. See the module docstring.
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=righteous,
            font_title=righteous,
            font_section_label=righteous,
            font_date_number=righteous,
            label_font_size=13,
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
        "day_arc",
        day_arc_theme,
        inky_palette=(INKY_YELLOW, INKY_RED),
    )


_register()
