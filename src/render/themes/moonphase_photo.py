"""Moonphase-photo theme — a real lunar photograph occluded per phase.

Identical to :func:`src.render.themes.moonphase.moonphase_theme` (dark celestial
canvas, whimsical vine border) except the hero and filmstrip discs are a real
moon photograph (``assets/moon_full.png``) occluded by the phase terminator,
instead of the procedural solid disc.  Toggled by ``ThemeStyle.use_moon_photo``
so the default ``moonphase`` theme keeps its clean solid-disk look.

Falls back to the procedural disc automatically when the photo asset is absent.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from src.render.themes.moonphase import moonphase_theme

if TYPE_CHECKING:
    from src.render.theme import Theme


def moonphase_photo_theme() -> Theme:
    """Return the Moonphase-photo theme — moonphase layout with photo discs."""
    base = moonphase_theme()
    style = dataclasses.replace(base.style, use_moon_photo=True)
    return dataclasses.replace(base, name="moonphase_photo", style=style)


# ---------------------------------------------------------------------------
# Registry adapter
# ---------------------------------------------------------------------------


def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_YELLOW
    from src.render.themes.registry import register_theme

    register_theme("moonphase_photo", moonphase_photo_theme, inky_palette=(INKY_BLUE, INKY_YELLOW))


_register()
