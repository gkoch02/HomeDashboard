"""halftone_agenda.py — split-plate weather engraving + today's agenda.

The third arrangement of halftone's engraving vocabulary. ``halftone`` gives
the whole width to the illustration and reduces the calendar to a single NEXT
line; ``day_arc`` turns the artwork itself into a time axis. This variant cuts
the plate down the middle instead: art and weather on the left, the day's
events on the right, divided by a full-height ordered-Bayer rule.

The left pane carries the same procedural illustration as ``halftone`` —
rayed sun, phase-shaded moon, cumulus, stippled rain, lightning, snow or fog
banding, chosen from the OWM icon code — recomposed for a narrower,
nearly-square pane, with a typeset band beneath it holding the temperature
numeral, condition, high/low, sunrise, sunset, date and feels-like reading.

The right pane is the calendar, at the size a dedicated column allows: as many
of today's events as fit at a legible type size, with the dithering carrying
state — elapsed events perforated, the event in progress inverted, upcoming
ones crisp — and an "updated" caption in the bottom corner.

Typography follows the split. Righteous, halftone's single display voice,
carries the weather pane and the agenda's chrome; DM Sans sets the event rows,
which are small enough and numerous enough to want the screen-optimised cut
(the same division ``day_arc`` makes, for the same reason).

The agenda's DM Sans runs a weight heavier than the roles it fills — bold for
titles, semibold for times, medium for locations and the footer. Weight, not
size, is what makes ink read as black on an eInk panel: at 22 px Righteous
sets ~4.4 px stems while DM Sans SemiBold sets ~3.7 px, so matching the roles
one-for-one left the calendar side visibly greyer than the weather side.

On Inky the canvas is RGB (``prefer_color_on_inky=True``): yellow rings the
sun and moon, red fills the in-progress event bar. Everything else stays black
on paper so the engraving still reads as one.
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


def halftone_agenda_theme() -> Theme:
    """Return the halftone_agenda (split art / agenda plate) theme."""
    return Theme(
        name="halftone_agenda",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            canvas_mode="L",
            # Floyd-Steinberg turns the illustration's greyscale gradients into
            # the engraving-style dither this theme shares with halftone. The
            # agenda is unaffected: every glyph there is drawn in solid ink on
            # a solid paper underlay, and FS only diffuses intermediate values.
            preferred_quantization_mode="floyd_steinberg",
            prefer_color_on_inky=True,
            halftone_agenda=ComponentRegion(0, 0, 800, 480),
            # Hide all standard regions — this theme is full-canvas.
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            draw_order=["halftone_agenda"],
        ),
        style=ThemeStyle(
            # L-mode light canvas invariant: black ink on near-white field.
            fg=0,
            bg=255,
            # Role-based pairing: DM Sans for the agenda rows, Righteous for
            # every display element. See the module docstring.
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            # DM Sans Bold, not Righteous: the display face is reached through
            # font_title / font_section_label / font_date_number, which leaves
            # the bold role free for the agenda's heaviest rows. Righteous sets
            # ~4.4 px stems at 22 px and DM Sans Bold ~4.4 px at the same size,
            # so the two panes carry the same weight of ink on the panel.
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
        "halftone_agenda",
        halftone_agenda_theme,
        inky_palette=(INKY_YELLOW, INKY_RED),
    )


_register()
