"""Fuzzy-clock Inverted theme.

Identical layout to ``fuzzyclock`` — full-screen natural-language clock phrase
with a compact weather banner across the bottom — but with the color scheme
flipped: white text on a black canvas instead of black on white.

Layout (800 × 480):
  ┌────────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │                                                                        │
  │                     half past seven                                    │
  │                                                                        │
  │                  Wednesday  ·  23 March                                │
  │                                                                        │
  │                                                                        │
  ├── thin rule ───────────────────────────────────────────────────────────┤
  │  ☀ 72°  Partly Cloudy   H:78° L:60°  Feels 70°  │  Mon ··· Tue ···  🌒│
  └────────────────────────────────────────────────────────────────────────┘

Font choice: DM Sans — same as ``fuzzyclock``.  The geometric shapes of this
screen-optimised sans-serif hold up well at large sizes when reversed out of
a dark background.
"""

from __future__ import annotations

import dataclasses

from src.render.theme import Theme
from src.render.themes.fuzzyclock import fuzzyclock_theme


def fuzzyclock_invert_theme() -> Theme:
    """Return the fuzzyclock Inverted theme: ``fuzzyclock`` with the polarity flipped."""
    base = fuzzyclock_theme()
    # Overrides the derivation (a 95% ink plate would decline): the phrase
    # changes every five minutes, so declining would mean ~200 full-waveform
    # flashes a day. Listed in OVERRIDES in tests/test_theme_partial_refresh.py.
    layout = dataclasses.replace(base.layout, supports_partial_refresh=True)
    style = dataclasses.replace(base.style, fg=1, bg=0)
    return dataclasses.replace(base, name="fuzzyclock_invert", layout=layout, style=style)


def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_YELLOW
    from src.render.themes.registry import register_theme

    register_theme(
        "fuzzyclock_invert", fuzzyclock_invert_theme, inky_palette=(INKY_YELLOW, INKY_BLUE)
    )


_register()
