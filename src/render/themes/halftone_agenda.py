"""halftone_agenda.py — split-plate weather engraving + today's agenda.

The third arrangement of halftone's engraving vocabulary: art and weather on
the left, the day's events on the right, divided by a full-height
ordered-Bayer rule. The left pane carries the same procedural illustration as
``halftone`` — chosen from the OWM icon code, recomposed for a narrower,
nearly-square pane — with a typeset band beneath it (temperature numeral,
condition, high/low, sunrise, sunset, date, feels-like).

The right pane sets as many of today's events as fit at a legible size, each
row carrying its start and end time, in the treatment its state calls for —
elapsed perforated, in progress inverted, next up accented. Those need the
full waveform, and the plate's own dithering derives it out of partial
refresh (``Theme.allows_partial_refresh``).

Typography follows the split: Righteous for the weather pane and the agenda's
chrome, DM Sans for the event rows, one weight heavier than the roles it
fills (bold titles, semibold times, medium locations) so that at 22 px its
stems match Righteous's ~4.4 px and the calendar side reads as black as the
weather side.

On Inky the canvas is RGB (``prefer_color_on_inky=True``): yellow rings the
sun and moon, red marks the running event's bar and the next-up tick. On
Waveshare both accents collapse to ink.

Editing notes: Imports ``agenda_day`` from ``day_arc_panel`` rather than copying it; sun
times are normalised once in ``_sun_times``; ``TEMP_PT = 78`` and the ``inline_range`` /
``stacks_time`` rules are pinned by tests.
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
