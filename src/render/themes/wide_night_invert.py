"""wide_night_invert theme — wide_night with ground and ink swapped.

The same four marks, labels, spacing and hourly repaint limit as
``wide_night``, drawn in red on a black ground on the colour panels (black on
white on monochrome). The layout is ``wide_night``'s with a different
component in ``draw_order``, so the two plates cannot drift apart.

It keeps the dark-canvas style (``bg`` ink), so it declines partial refresh
like its sibling — on the colour panels the plate is solid black, and the
colour panels have no partial refresh anyway. On a monochrome panel the plate
is white and would survive the fast waveform, but a theme meant for the four-
ink strip is not worth an override for that. Kept out of the random rotation
for the same reason as ``wide_night``.
"""

from __future__ import annotations

import dataclasses

from src.render.theme import INKY_BLACK, INKY_RED, Theme
from src.render.themes.wide_night import wide_night_theme


def wide_night_invert_theme() -> Theme:
    """Return the wide_night_invert (red on black night mode) theme."""
    base = wide_night_theme()
    layout = dataclasses.replace(base.layout, draw_order=["wide_night_invert"])
    return dataclasses.replace(base, name="wide_night_invert", layout=layout)


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "wide_night_invert", wide_night_invert_theme, inky_palette=(INKY_RED, INKY_BLACK)
    )


_register()
