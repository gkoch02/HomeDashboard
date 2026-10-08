"""Moonphase Inverted theme — light parchment/fairy-tale variant.

Identical layout and overlay to ``moonphase`` but with colors flipped:
black text on a white canvas for a hand-illustrated manuscript feel
and maximum eInk contrast.
"""

from __future__ import annotations

import dataclasses

from src.render.theme import Theme
from src.render.themes.moonphase import moonphase_theme


def moonphase_invert_theme() -> Theme:
    """Return the Moonphase Inverted theme: ``moonphase`` on a parchment plate."""
    base = moonphase_theme()
    # moonphase overrides the partial-refresh derivation for its dark plate; this
    # light one (~12% ink, threshold-quantized) derives partial refresh itself,
    # so the override is dropped rather than restated.
    layout = dataclasses.replace(base.layout, supports_partial_refresh=None)
    style = dataclasses.replace(base.style, fg=0, bg=255)
    return dataclasses.replace(base, name="moonphase_invert", layout=layout, style=style)


def _register() -> None:
    from src.render.theme import INKY_BLUE
    from src.render.themes.registry import register_theme

    # Navy for both accents: yellow type on the parchment plate barely reads.
    register_theme("moonphase_invert", moonphase_invert_theme, inky_palette=(INKY_BLUE, INKY_BLUE))


_register()
