"""Quote-of-the-Day Inverted theme.

Identical layout to ``qotd`` — full-screen centered quote with a compact
weather banner across the bottom — but with the color scheme flipped:
white text on a black canvas instead of black on white.

Layout (800 × 480):
  ┌────────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │                                                                        │
  │          "The quote of the day, large and centered,                    │
  │           wrapping gracefully across as many lines                     │
  │           as it needs."                                                │
  │                                                  — Author Name         │
  │                                                                        │
  │                                                                        │
  ├── thin rule ───────────────────────────────────────────────────────────┤
  │  ☀ 72°  Partly Cloudy   H:78° L:60°  Feels 70°  │  Mon ··· Tue ···  🌒│
  └────────────────────────────────────────────────────────────────────────┘

Font choice: Playfair Display — same as ``qotd``.  The high-contrast strokes
of this transitional serif read especially well reversed out of a dark ground.
"""

from __future__ import annotations

import dataclasses

from src.render.theme import Theme
from src.render.themes.qotd import qotd_theme


def qotd_invert_theme() -> Theme:
    """Return the QOTD Inverted theme: ``qotd`` with the plate's polarity flipped."""
    base = qotd_theme()
    # The accents are unset: qotd's blue and green are chosen for a white plate.
    style = dataclasses.replace(base.style, fg=1, bg=0, accent_info=None, accent_primary=None)
    return dataclasses.replace(base, name="qotd_invert", style=style)


def _register() -> None:
    from src.render.theme import INKY_RED, INKY_YELLOW
    from src.render.themes.registry import register_theme

    register_theme("qotd_invert", qotd_invert_theme, inky_palette=(INKY_YELLOW, INKY_RED))


_register()
