"""wide_ephemeris_light theme — the Ephemeris plate on a paper ground.

The same strip, agenda, conditions and outlook as ``wide_ephemeris``, set in
black on white. Yellow type does not read on paper, so the gold is only ever a
fill here: the slab under way is yellow with black type, the current hour is a
yellow column standing behind the strip in place of the gold line, and the
wordmark goes black over a yellow rule. Alerts stay red. On monochrome the
under-way slab is solid black with white type and the hour is a black line.

The layout is ``wide_ephemeris``'s with a different component in
``draw_order``, so the two plates cannot drift apart. Unlike its sibling the
ground is paper, so on a monochrome panel it derives *into* partial refresh.
"""

from __future__ import annotations

import dataclasses

from src.render.theme import INKY_RED, INKY_YELLOW, Theme
from src.render.themes.wide_ephemeris import wide_ephemeris_theme


def wide_ephemeris_light_theme() -> Theme:
    """Return the wide_ephemeris_light (Ephemeris on paper) theme."""
    base = wide_ephemeris_theme()
    layout = dataclasses.replace(base.layout, draw_order=["wide_ephemeris_light"])
    style = dataclasses.replace(base.style, fg=0, bg=255)
    return dataclasses.replace(base, name="wide_ephemeris_light", layout=layout, style=style)


def _register() -> None:
    from src.render.themes.registry import register_theme

    register_theme(
        "wide_ephemeris_light", wide_ephemeris_light_theme, inky_palette=(INKY_YELLOW, INKY_RED)
    )


_register()
