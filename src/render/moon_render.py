"""Procedural moon-disc renderer for the moonphase theme.

Draws a believable lunar disc — a true phase terminator, maria (dark seas),
a scatter of craters, a soft limb, and earthshine on the unlit side — rather
than the flat Weather-Icons font glyph the theme used before.

The renderer is mode-aware:

* ``"L"`` (Waveshare greyscale path) — smooth shading that the backend later
  dithers to 1-bit.
* ``"RGB"`` (Inky colour path) — a warm-yellow lit limb and a cool earthshine.
* ``"1"`` (unit-test / bilevel canvases) — drawn flat at 1× with no supersample.

Geometry is pure and deterministic: the same date + radius always yields the
same disc, so theme pixel-snapshot tests stay stable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class MoonTones:
    """Tone palette for one moon disc, expressed in the target image mode.

    Each value is an ``int`` for ``"L"``/``"1"`` canvases or an ``(r, g, b)``
    tuple for ``"RGB"``.  ``lit`` is the sunlit limb, ``dark`` the earthshine
    on the unlit side, ``maria`` the dark seas, ``crater`` crater detail, and
    ``edge`` the limb ring that outlines the whole disc.
    """

    lit: int | tuple[int, int, int]
    dark: int | tuple[int, int, int]
    maria: int | tuple[int, int, int]
    crater: int | tuple[int, int, int]
    edge: int | tuple[int, int, int]


# Maria (dark lunar seas) as ellipses in unit-disc coordinates: (cx, cy, rx, ry)
# with the disc spanning -1..1, +x right, +y down.  Loosely matches the
# near-side layout (Imbrium upper-left, Serenitatis/Tranquillitatis centre,
# Crisium right, Procellarum down the left limb) so the moon reads as *the*
# Moon rather than a generic blotch.  Hand-placed, not survey-accurate.
_MARIA: tuple[tuple[float, float, float, float], ...] = (
    (-0.34, -0.40, 0.30, 0.24),  # Mare Imbrium
    (0.04, -0.16, 0.20, 0.20),  # Mare Serenitatis
    (0.22, 0.10, 0.20, 0.22),  # Mare Tranquillitatis
    (0.52, -0.06, 0.16, 0.20),  # Mare Crisium
    (-0.56, 0.04, 0.18, 0.34),  # Oceanus Procellarum
    (0.10, 0.40, 0.16, 0.16),  # Mare Nectaris / Fecunditatis
    (-0.16, 0.30, 0.14, 0.16),  # Mare Nubium
)

# Craters as (cx, cy, r) in unit-disc coordinates — bright rims with darker
# floors.  Tycho sits low-centre (the ray system origin); Copernicus mid-left.
_CRATERS: tuple[tuple[float, float, float], ...] = (
    (-0.02, 0.62, 0.07),  # Tycho
    (-0.28, 0.10, 0.05),  # Copernicus
    (-0.46, -0.30, 0.04),  # Plato
    (0.40, 0.42, 0.04),  # Stevinus-ish
    (0.30, -0.44, 0.035),
)


def _blend(
    a: int | tuple[int, int, int],
    b: int | tuple[int, int, int],
    t: float,
) -> int | tuple[int, int, int]:
    """Linear blend ``a→b`` by ``t`` in [0,1], preserving int / tuple form."""
    if isinstance(a, tuple):
        b_t = b if isinstance(b, tuple) else (b, b, b)
        return tuple(int(round(a[i] + (b_t[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]
    b_i = b if isinstance(b, int) else int(sum(b) / 3)
    return int(round(a + (b_i - a) * t))


def _draw_moon_core(
    d: ImageDraw.ImageDraw,
    r: int,
    age: float,
    synodic: float,
    tones: MoonTones,
    scale: int,
) -> None:
    """Draw the moon centred at (r, r) with radius *r* into draw *d*.

    *scale* is the supersample factor, used to size strokes so they stay
    proportional after downsampling.
    """
    cx = cy = r
    w = max(1, scale)

    # 1. Day side: fill the whole disc with the sunlit tone, then lay in the
    #    surface texture (maria + craters) as if it were full.  We carve the
    #    night side back out in step 3, so detail only ever shows where lit.
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tones.lit)

    sea = tones.maria
    sea_soft = _blend(tones.maria, tones.lit, 0.45)
    for mx, my, rx, ry in _MARIA:
        ex, ey = cx + mx * r, cy + my * r
        erx, ery = rx * r, ry * r
        d.ellipse([ex - erx, ey - ery, ex + erx, ey + ery], fill=sea)
        d.ellipse(
            [ex - erx * 0.62, ey - ery * 0.62, ex + erx * 0.62, ey + ery * 0.62],
            fill=sea_soft,
        )

    floor = _blend(tones.crater, tones.maria, 0.30)
    for kx, ky, kr in _CRATERS:
        ex, ey = cx + kx * r, cy + ky * r
        er = max(1.0, kr * r)
        d.ellipse([ex - er, ey - er, ex + er, ey + er], fill=floor)
        d.ellipse([ex - er, ey - er, ex + er, ey + er], outline=tones.crater, width=w)

    # 2. Terminator geometry. phase 0 = new, 0.5 = full.  c = cos(phase angle);
    #    the terminator x is xt = xlim * c.  Waxing lights the right limb
    #    (x >= xt); waning the left (x <= -xt) — sign-correct across the cycle.
    phase = (age / synodic) % 1.0
    c = math.cos(2.0 * math.pi * phase)
    waxing = phase < 0.5

    # 3. Night side: paint the unlit region flat with earthshine so the dark
    #    limb stays faintly visible against the sky but carries no bright seas.
    for yy in range(-r, r + 1):
        xlim = math.sqrt(max(0.0, r * r - yy * yy))
        xt = xlim * c
        if waxing:
            nx0, nx1 = -xlim, xt  # unlit is left of the terminator
        else:
            nx0, nx1 = -xt, xlim  # unlit is right of the terminator
        if nx1 - nx0 >= 1.0:
            d.line(
                [(cx + int(round(nx0)), cy + yy), (cx + int(round(nx1)), cy + yy)],
                fill=tones.dark,
                width=1,
            )

    # 4. Limb ring — outlines the disc so it reads on any background.
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=tones.edge, width=w)


def render_moon_disc(
    image: Image.Image | None,
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    age: float,
    tones: MoonTones,
    *,
    synodic: float = 29.53059,
) -> None:
    """Paint a moon disc of *radius* centred at (cx, cy).

    When *image* is an ``"L"`` or ``"RGB"`` canvas the disc is rendered at 4×
    and LANCZOS-downsampled for a clean anti-aliased limb, then pasted through
    a circular mask so nothing outside the disc is touched.  On ``"1"`` canvases
    (or when no backing image is available) it is drawn flat at 1×.
    """
    image = image if image is not None else getattr(draw, "_image", None)
    mode = image.mode if image is not None else "L"

    if image is None or mode == "1" or radius < 4:
        _draw_moon_core(draw, radius, age, synodic, tones, scale=1)
        return

    scale = 4
    big = radius * scale
    size = big * 2
    sub = Image.new(mode, (size, size), tones.dark)
    sub_draw = ImageDraw.Draw(sub)
    _draw_moon_core(sub_draw, big, age, synodic, tones, scale=scale)
    sub = sub.resize((radius * 2, radius * 2), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    mask = mask.resize((radius * 2, radius * 2), Image.LANCZOS)

    image.paste(sub, (cx - radius, cy - radius), mask)
