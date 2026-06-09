"""Shared helpers for the procedural art themes.

The dithered/engraved panels (``weatherglass``, ``postcard``, ``naturalist``,
``halftone``, ``almanac``) render on an ``"L"`` greyscale canvas on Waveshare
and an RGB canvas on Inky, so every colour they place must be expressed
per-mode. These helpers grew up copy-pasted in each panel; this module is the
single home for the genuinely shared ones.

Panels import them under their established private aliases, e.g.::

    from src.render.artkit import grey as _grey, ink as _ink
"""

from __future__ import annotations

from datetime import date

from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_RED


def grey(v: int, mode: str) -> int | tuple[int, int, int]:
    """Return *v* (0..255) as either an L-mode int or an RGB greyscale triple."""
    return v if mode == "L" else (v, v, v)


def ink(mode: str) -> int | tuple[int, int, int]:
    """Solid foreground ink (black)."""
    return 0 if mode == "L" else (0, 0, 0)


def accent_red(mode: str) -> int | tuple[int, int, int]:
    """Red accent on the Inky RGB canvas, solid black on L mode.

    L mode collapses the accent to solid ink because mid-grey would dither
    into a noisy half-tone pattern after Floyd-Steinberg — fine for
    procedural illustration but illegible for small text and thin rules.
    """
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_RED]
    return 0


def season(today: date) -> str:
    """Northern-hemisphere meteorological season: winter/spring/summer/autumn."""
    m = today.month
    if 3 <= m <= 5:
        return "spring"
    if 6 <= m <= 8:
        return "summer"
    if 9 <= m <= 11:
        return "autumn"
    return "winter"
