"""Procedural moon-disc renderer for the moonphase theme.

Draws a clean lunar disc — a true phase terminator, a soft limb, and
earthshine on the unlit side — rather than the flat Weather-Icons font glyph
the theme used before.

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

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class MoonTones:
    """Tone palette for one moon disc, expressed in the target image mode.

    Each value is an ``int`` for ``"L"``/``"1"`` canvases or an ``(r, g, b)``
    tuple for ``"RGB"``.  ``lit`` is the sunlit limb, ``dark`` the earthshine
    on the unlit side, and ``edge`` the limb ring that outlines the whole disc.
    """

    lit: int | tuple[int, int, int]
    dark: int | tuple[int, int, int]
    edge: int | tuple[int, int, int]


def _draw_moon_core(
    d: ImageDraw.ImageDraw,
    r: int,
    age: float,
    synodic: float,
    tones: MoonTones,
    scale: int,
    show_edge: bool,
) -> None:
    """Draw the moon centred at (r, r) with radius *r* into draw *d*.

    *scale* is the supersample factor, used to size strokes so they stay
    proportional after downsampling.  When *show_edge* is true a limb ring
    outlines the full disc (so partial phases still read as a sphere); when
    false only the lit shape is drawn (bare crescent on the background).
    """
    cx = cy = r
    w = max(1, scale)

    # 1. Day side: fill the whole disc with the sunlit tone.  The night side is
    #    carved back out in step 3.
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tones.lit)

    # 2. Terminator geometry. phase 0 = new, 0.5 = full.  c = cos(phase angle);
    #    the terminator x is xt = xlim * c.  Waxing lights the right limb
    #    (x >= xt); waning the left (x <= -xt) — sign-correct across the cycle.
    phase = (age / synodic) % 1.0
    c = math.cos(2.0 * math.pi * phase)
    waxing = phase < 0.5

    # 3. Night side: paint the unlit region flat with earthshine so the dark
    #    limb stays faintly visible against the sky.
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
    if show_edge:
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
    show_edge: bool = True,
) -> None:
    """Paint a moon disc of *radius* centred at (cx, cy).

    When *image* is an ``"L"`` or ``"RGB"`` canvas the disc is rendered at 4×
    and LANCZOS-downsampled for a clean anti-aliased limb, then pasted through
    a circular mask so nothing outside the disc is touched.  On ``"1"`` canvases
    (or when no backing image is available) it is drawn flat at 1×.

    On ``"L"`` canvases the downsampled disc is Floyd-Steinberg-dithered to
    bilevel *here* so the surrounding theme can quantize with ``threshold``
    (keeping anti-aliased text crisp) while the moon still carries its smooth
    lit / earthshine gradient as stipple.  ``"RGB"`` (Inky) keeps full tone and
    defers to the panel's palette mapping.
    """
    image = image if image is not None else getattr(draw, "_image", None)
    mode = image.mode if image is not None else "L"

    if image is None or mode == "1" or radius < 4:
        _draw_moon_core(draw, radius, age, synodic, tones, scale=1, show_edge=show_edge)
        return

    scale = 4
    big = radius * scale
    size = big * 2
    sub = Image.new(mode, (size, size), tones.dark)
    sub_draw = ImageDraw.Draw(sub)
    _draw_moon_core(sub_draw, big, age, synodic, tones, scale=scale, show_edge=show_edge)
    sub = sub.resize((radius * 2, radius * 2), Image.LANCZOS)
    if mode == "L":
        # Pre-stipple the disc so a threshold global quantization preserves it.
        sub = sub.convert("1").convert("L")

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    mask = mask.resize((radius * 2, radius * 2), Image.LANCZOS)

    image.paste(sub, (cx - radius, cy - radius), mask)
