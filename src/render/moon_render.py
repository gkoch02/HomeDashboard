"""Moon-disc renderer for the moonphase themes.

Two backends share the same phase geometry:

* **Procedural** (default) — a clean lunar disc with a true phase terminator, a
  soft limb, and earthshine on the unlit side.  Used by ``moonphase`` /
  ``moonphase_invert``.
* **Photo occlusion** (opt-in via ``use_photo=True``) — a real moon photograph
  bundled at ``assets/moon_full.png`` is occluded by the phase terminator: the
  sunlit region shows the photo, the unlit region keeps a faint earthshine copy
  of the same texture.  Used by the ``moonphase_photo`` theme.  Falls back to
  the procedural disc when the asset is missing.

Both backends are mode-aware:

* ``"L"`` (Waveshare greyscale path) — shading the backend later dithers to 1-bit.
* ``"RGB"`` (Inky colour path) — the procedural disc uses a warm-yellow lit limb
  and a cool earthshine; the photo renders as realistic greyscale.
* ``"1"`` (unit-test / bilevel canvases) — drawn flat at 1× with no supersample.

Geometry is pure and deterministic: the same date + radius always yields the
same disc, so theme pixel-snapshot tests stay stable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

# Bundled real-moon photograph, occluded per phase when ``use_photo`` is set.
# Absent in a bare checkout, so the photo theme falls back to the procedural disc.
_MOON_PHOTO_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "moon_full.png"

# Brightness the earthshine (unlit-side) texture is faded toward the background.
_EARTHSHINE_FACTOR = 0.16


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


def _tone_luminance(value: int | tuple[int, int, int]) -> float:
    """Normalize an ``"L"``/``"1"``/RGB tone to a 0..1 luminance."""
    if isinstance(value, tuple):
        return sum(value) / 3 / 255
    if value <= 1:  # "1" bilevel mode
        return float(value)
    return value / 255


@lru_cache(maxsize=4)
def _load_moon_photo(path: str) -> Image.Image | None:
    """Load and centre-square-crop the bundled moon photo, or None if missing.

    The result is an ``"L"`` square whose lunar disc fills the frame, so a later
    resize to ``(2r, 2r)`` maps disc → disc and the renderer's circular mask
    lines up with the photographed limb.  Cached per path so repeated discs in a
    single render don't re-decode the file.
    """
    try:
        img = Image.open(path).convert("L")
    except (FileNotFoundError, OSError):
        return None
    w, h = img.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return img.crop((left, top, left + s, top + s))


def moon_photo_available(path: str | None = None) -> bool:
    """True when a usable moon photograph is bundled (or present at *path*)."""
    return _load_moon_photo(str(path or _MOON_PHOTO_PATH)) is not None


def _lit_span(xlim: float, c: float, waxing: bool) -> tuple[float, float]:
    """Return the sunlit ``[x0, x1]`` span of one scanline (disc-centred coords).

    Mirrors the terminator convention in :func:`_draw_moon_core`: ``xt = xlim*c``
    is the terminator x; waxing lights the right limb (``x >= xt``), waning the
    left (``x <= -xt``).  An empty span (new moon) collapses to a zero-width slot.
    """
    xt = xlim * c
    return (xt, xlim) if waxing else (-xlim, -xt)


def _build_lit_mask(size: int, age: float, synodic: float) -> Image.Image:
    """Build an ``"L"`` mask: 255 over the sunlit disc region, 0 over the unlit."""
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    r = size / 2.0
    phase = (age / synodic) % 1.0
    c = math.cos(2.0 * math.pi * phase)
    waxing = phase < 0.5
    for yy in range(size):
        dy = yy - r + 0.5
        xlim = math.sqrt(max(0.0, r * r - dy * dy))
        x0, x1 = _lit_span(xlim, c, waxing)
        if x1 - x0 >= 0.75:
            md.line([(r + x0, yy), (r + x1, yy)], fill=255, width=1)
    return mask


def _render_photo_disc(
    image: Image.Image,
    cx: int,
    cy: int,
    radius: int,
    age: float,
    synodic: float,
    mode: str,
    dark_canvas: bool,
    photo: Image.Image,
) -> None:
    """Occlude the real moon photo by the phase terminator and paste it.

    The sunlit region shows the photograph; the unlit region keeps a dimmed
    (earthshine) copy of the same texture so the dark limb stays faintly visible.
    Rendered at 4× and LANCZOS-downsampled for a clean terminator, then pasted
    through a circular mask.  On a light (``moonphase_invert``-style) canvas the
    photo is luminance-inverted so the lit side reads as dark engraving.
    """
    scale = 4
    size = radius * 2 * scale
    base = photo.resize((size, size), Image.Resampling.LANCZOS)
    if not dark_canvas:
        base = ImageOps.invert(base)

    if dark_canvas:
        earth = base.point(lambda p: int(p * _EARTHSHINE_FACTOR))
    else:  # fade toward white parchment instead of black sky
        earth = base.point(lambda p: 255 - int((255 - p) * _EARTHSHINE_FACTOR))

    disc = Image.composite(base, earth, _build_lit_mask(size, age, synodic))
    disc = disc.resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)
    if mode == "L":
        # Pre-dither so a threshold global quantization keeps the crater detail.
        disc = disc.convert("1").convert("L")
    sub = disc.convert("RGB") if mode == "RGB" else disc

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    mask = mask.resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)
    image.paste(sub, (cx - radius, cy - radius), mask)


def _draw_moon_core(
    d: ImageDraw.ImageDraw,
    r: int,
    age: float,
    synodic: float,
    tones: MoonTones,
    scale: int,
    show_edge: bool,
    center: tuple[int, int] | None = None,
) -> None:
    """Draw the moon with radius *r* into draw *d*, centred at *center*.

    *center* defaults to ``(r, r)`` (the supersample sub-image case); the
    bilevel fallback passes the real destination centre so the disc lands in
    the moon row rather than the top-left corner.

    *scale* is the supersample factor, used to size strokes so they stay
    proportional after downsampling.  When *show_edge* is true a limb ring
    outlines the full disc (so partial phases still read as a sphere); when
    false only the lit shape is drawn (bare crescent on the background).
    """
    cx, cy = center if center is not None else (r, r)
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
    use_photo: bool = False,
    dark_canvas: bool | None = None,
    photo_path: str | None = None,
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

    When *use_photo* is true and a real moon photograph is bundled
    (``assets/moon_full.png``, or *photo_path*) it is occluded by the phase
    terminator instead of the disc being drawn procedurally; the procedural path
    remains the fallback when the asset is missing.  *dark_canvas* selects the
    photo's polarity (bright moon on a dark sky vs. dark engraving on a light
    parchment); when omitted it is inferred from *tones*.
    """
    image = image if image is not None else getattr(draw, "_image", None)
    mode = image.mode if image is not None else "L"

    if use_photo and image is not None and mode in ("L", "RGB") and radius >= 4:
        photo = _load_moon_photo(str(photo_path or _MOON_PHOTO_PATH))
        if photo is not None:
            if dark_canvas is None:
                dark_canvas = _tone_luminance(tones.lit) >= _tone_luminance(tones.dark)
            _render_photo_disc(image, cx, cy, radius, age, synodic, mode, dark_canvas, photo)
            return

    if image is None or mode == "1" or radius < 4:
        _draw_moon_core(
            draw, radius, age, synodic, tones, scale=1, show_edge=show_edge, center=(cx, cy)
        )
        return

    scale = 4
    big = radius * scale
    size = big * 2
    sub = Image.new(mode, (size, size), tones.dark)
    sub_draw = ImageDraw.Draw(sub)
    _draw_moon_core(sub_draw, big, age, synodic, tones, scale=scale, show_edge=show_edge)
    sub = sub.resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)
    if mode == "L":
        # Pre-stipple the disc so a threshold global quantization preserves it.
        sub = sub.convert("1").convert("L")

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    mask = mask.resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)

    image.paste(sub, (cx - radius, cy - radius), mask)
