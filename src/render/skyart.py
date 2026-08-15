"""Procedural sky-illustration primitives shared by the dithered weather themes.

These routines grew up inside ``components/halftone_panel.py``; ``day_arc``
needs the same sun, moon, cloud, precipitation and Bayer-rule vocabulary, so
they live here rather than being copy-pasted a second time. This mirrors the
earlier extraction of :mod:`src.render.artkit`.

Everything is mode-aware. On an ``"L"`` canvas (Waveshare) tones are plain
0–255 ints and the theme's Floyd-Steinberg quantization turns the smooth
gradients into engraving-style halftone; on ``"RGB"`` (Inky panels with
``prefer_color_on_inky=True``) the same tones are emitted as ``(v, v, v)``
triples and the sun/moon pick up a warm yellow accent.

Two conventions worth knowing before adding to this module:

* Gradients are built as a 1-px strip and ``NEAREST``-resized to full size.
  A per-pixel nested loop is measurably slower on a Pi.
* Text is never drawn here. Mid-grey text is destroyed by Floyd-Steinberg;
  callers typeset in solid ink over a solid paper underlay.

No external assets — every illustration is generated from PIL primitives.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from datetime import date
from functools import lru_cache

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from src.render.artkit import grey as _grey
from src.render.artkit import ink as _ink
from src.render.moon import is_waxing, moon_illumination
from src.render.quantize import _BAYER_4X4, INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_YELLOW

Rect = tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# Mode-aware colour helpers
# ---------------------------------------------------------------------------


def accent_yellow(mode: str) -> int | tuple[int, int, int]:
    """Warm-light accent for sun/moon highlights.

    On RGB canvases this returns the Inky Spectra-6 yellow RGB tuple; on
    L-mode it collapses to a light grey so the highlight still reads.
    """
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_YELLOW]
    return 210


# ---------------------------------------------------------------------------
# Weather icon classification
# ---------------------------------------------------------------------------


def illustration_kind(icon: str | None) -> tuple[str, bool]:
    """Map an OWM icon code (e.g. ``"10d"``) to ``(kind, is_night)``.

    ``is_night`` is True when the icon's day/night suffix is ``"n"``; for
    the ``01`` family this also determines whether we draw the sun or the
    moon variant.
    """
    if not icon:
        return ("missing", False)
    code = icon[:2]
    day_night = icon[2:3] if len(icon) > 2 else "d"
    is_night = day_night == "n"
    if code == "01":
        return ("moon" if is_night else "sun", is_night)
    if code in ("02", "03"):
        return ("partly_cloudy", is_night)
    if code == "04":
        return ("overcast", is_night)
    if code in ("09", "10"):
        return ("rain", is_night)
    if code == "11":
        return ("storm", is_night)
    if code == "13":
        return ("snow", is_night)
    if code == "50":
        return ("fog", is_night)
    return ("missing", False)


# ---------------------------------------------------------------------------
# Sky backgrounds
# ---------------------------------------------------------------------------


def draw_sky(image: Image.Image, rect: Rect, *, day: bool) -> None:
    """Paint a vertical greyscale gradient sky into *rect*."""
    x0, y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - y0
    if day:
        # Darker at the zenith, lighter toward the horizon. Floyd-Steinberg
        # only registers as a visible halftone once the underlying value
        # drops well below mid-grey; 100–145 produces a dense engraving-style
        # texture that makes the sun rays (252) and cloud highlights (255)
        # pop as crisp white shapes against an unmistakably "shaded" sky.
        top, bottom = 100, 145
    else:
        # Dark sky for night scenes — value 35 is denser than 60 so the top
        # reads as "darker zenith" and the bottom is the horizon glow.
        top, bottom = 35, 70
    strip = Image.new("L", (1, h))
    for i in range(h):
        t = i / max(1, h - 1)
        strip.putpixel((0, i), int(top + (bottom - top) * t))
    full = strip.resize((w, h), Image.Resampling.NEAREST)
    if image.mode == "RGB":
        full = full.convert("RGB")
    image.paste(full, (x0, y0))


def draw_sky_stormy(image: Image.Image, rect: Rect) -> None:
    """Mid-grey turbulent sky for thunderstorm scenes (sky reads as 'broken cloud')."""
    x0, y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - y0
    strip = Image.new("L", (1, h))
    for i in range(h):
        t = i / max(1, h - 1)
        # 90 at top → 135 toward the horizon: a heavy, charged sky that
        # dithers to a dense halftone so the dark storm cloud + bolt still
        # read as the darkest elements on the plate.
        v = int(90 + (135 - 90) * t)
        strip.putpixel((0, i), v)
    full = strip.resize((w, h), Image.Resampling.NEAREST)
    if image.mode == "RGB":
        full = full.convert("RGB")
    image.paste(full, (x0, y0))


def draw_fog(image: Image.Image, rect: Rect, today: date) -> None:
    """Stack horizontal greyscale bands with slight jitter for fog conditions."""
    x0, y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - y0
    rng = random.Random(today.toordinal() ^ 0xF06)
    # Start from a denser mid-grey sky tone, alternate denser/lighter bands.
    # Values pulled down to 135–190 so fog dithers to a visible textured
    # halftone rather than nearly-white on eInk.
    base_tones = [150, 175, 135, 180, 160, 190, 145, 170]
    band_count = 8
    band_h = h // band_count
    for i in range(band_count):
        tone = base_tones[i % len(base_tones)] + rng.randint(-8, 8)
        tone = max(110, min(200, tone))
        # Jitter the band horizontally so seams between bands waver.
        offset = rng.randint(-30, 30)
        band = Image.new("L", (w + 60, band_h + 2), tone)
        if image.mode == "RGB":
            band = band.convert("RGB")
        image.paste(band, (x0 - 30 + offset, y0 + i * band_h))
    # Final fill for any leftover pixels at the bottom.
    tail_h = h - band_count * band_h
    if tail_h > 0:
        tail = Image.new("L", (w, tail_h), 165)
        if image.mode == "RGB":
            tail = tail.convert("RGB")
        image.paste(tail, (x0, y0 + band_count * band_h))


# ---------------------------------------------------------------------------
# Sun + rays
# ---------------------------------------------------------------------------


def draw_sun(
    image: Image.Image,
    rect: Rect,
    *,
    cx: int,
    cy: int,
    radius: int,
) -> None:
    """Draw radiating triangular rays, then a soft radial-gradient sun disc.

    Ray length is ``radius`` plus a fixed additive term, which suits a large
    hero disc. Callers drawing a small sun want proportional rays instead —
    see ``day_arc_panel._draw_sun_disc``.
    """
    mode = image.mode
    draw = ImageDraw.Draw(image)

    # Twelve rays at 30° intervals, alternating short/long lengths. Rays are
    # drawn brighter than the sky so they read as light radiating outward.
    ray_count = 12
    for i in range(ray_count):
        angle = (i / ray_count) * 2 * math.pi - math.pi / 2
        long_ray = i % 2 == 0
        length = radius + (90 if long_ray else 58)
        half_w = math.radians(7 if long_ray else 5)
        inner_r = radius + 4
        x_tip = cx + math.cos(angle) * length
        y_tip = cy + math.sin(angle) * length
        x_a = cx + math.cos(angle - half_w) * inner_r
        y_a = cy + math.sin(angle - half_w) * inner_r
        x_b = cx + math.cos(angle + half_w) * inner_r
        y_b = cy + math.sin(angle + half_w) * inner_r
        draw.polygon([(x_tip, y_tip), (x_a, y_a), (x_b, y_b)], fill=_grey(252, mode))

    # Sun disc with radial gradient: brilliant white centre fading to a soft
    # halftone edge that still reads as brighter than the sky background.
    disc = radial_gradient_disc(radius * 2 + 1, inner_v=255, outer_v=210)
    if mode == "RGB":
        disc_rgb = disc.convert("RGB")
        image.paste(disc_rgb, (cx - radius, cy - radius), disc.split()[1])
    else:
        image.paste(disc, (cx - radius, cy - radius), disc.split()[1])

    # Inky colour highlight: yellow ring just inside the disc edge.
    if mode == "RGB":
        ring_r = radius - 3
        draw.ellipse(
            (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
            outline=accent_yellow(mode),
            width=3,
        )


@lru_cache(maxsize=8)
def radial_gradient_disc(d: int, inner_v: int, outer_v: int) -> Image.Image:
    """Return an LA-mode disc of diameter *d* with a radial greyscale gradient.

    Pixels outside the disc have alpha=0 so a pasted disc leaves the
    surrounding canvas untouched.
    """
    out = Image.new("LA", (d, d), (0, 0))
    cx = cy = (d - 1) / 2.0
    rad = (d - 1) / 2.0
    px = out.load()
    assert px is not None
    for y in range(d):
        for x in range(d):
            dx = x - cx
            dy = y - cy
            r = math.hypot(dx, dy)
            if r > rad:
                continue
            t = r / rad if rad > 0 else 0.0
            # Slight ease so the centre stays bright across more of the disc.
            t = t * t
            v = int(inner_v + (outer_v - inner_v) * t)
            px[x, y] = (v, 255)
    return out


# ---------------------------------------------------------------------------
# Moon
# ---------------------------------------------------------------------------


def draw_moon(
    image: Image.Image,
    rect: Rect,
    today: date,
    *,
    cx: int,
    cy: int,
    radius: int,
) -> None:
    """Paste a phase-shaded moon disc at *(cx, cy)*, ringed in yellow on Inky."""
    illum = moon_illumination(today)
    disc = moon_disc(radius * 2 + 1, illum, is_waxing(today))
    mode = image.mode
    if mode == "RGB":
        disc_rgb = disc.convert("RGB")
        image.paste(disc_rgb, (cx - radius, cy - radius), disc.split()[1])
    else:
        image.paste(disc, (cx - radius, cy - radius), disc.split()[1])

    # Inky colour story: warm yellow ring picks the moon out of the dark sky.
    if mode == "RGB":
        draw = ImageDraw.Draw(image)
        ring_r = radius + 4
        draw.ellipse(
            (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
            outline=accent_yellow(mode),
            width=2,
        )


@lru_cache(maxsize=32)
def moon_disc(d: int, illumination_pct: float, waxing: bool) -> Image.Image:
    """Greyscale moon with smooth terminator shading.

    *illumination_pct* in 0..100; *waxing* picks which limb is lit.
    """
    out = Image.new("LA", (d, d), (0, 0))
    cx = cy = (d - 1) / 2.0
    R = (d - 1) / 2.0
    # Map illumination to terminator x: 0% → entirely dark, 100% → entirely lit.
    # The terminator is a vertical ellipse; we only need its x-intercept on the
    # centre row to drive the smooth-edge lighting.
    phase = max(0.0, min(1.0, illumination_pct / 100.0))
    term_x_rel = (1.0 - 2.0 * phase) * R  # +R = no lit, -R = fully lit
    soft_px = 5.0
    px = out.load()
    assert px is not None
    for y in range(d):
        for x in range(d):
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy > R * R:
                continue
            # Signed distance from the terminator: positive = lit side.
            if waxing:
                signed = dx - term_x_rel
            else:
                signed = -(dx + term_x_rel)
            t = max(-1.0, min(1.0, signed / soft_px))
            lit = (t + 1.0) * 0.5  # 0 = dark, 1 = lit
            v = int(70 + (245 - 70) * lit)
            px[x, y] = (v, 255)
    return out


def draw_stars(
    image: Image.Image,
    rect: Rect,
    today: date,
    *,
    count: int = 140,
    bottom_inset: int = 24,
) -> None:
    """Scatter small bright pixels across the night sky, seeded daily.

    The seed is derived from ``today.toordinal()`` rather than ``hash()`` so the
    field is identical across processes — pixel snapshots depend on it.
    """
    x0, y0, x1, y1 = rect
    draw = ImageDraw.Draw(image)
    rng = random.Random(today.toordinal() ^ 0xA17)
    mode = image.mode
    bright = _grey(245, mode)
    medium = _grey(200, mode)
    lo_y = y0 + 6
    hi_y = y1 - bottom_inset
    if hi_y <= lo_y:
        return
    for _ in range(count):
        x = rng.randint(x0 + 6, x1 - 6)
        y = rng.randint(lo_y, hi_y)
        size = rng.choice((0, 0, 0, 1))
        fill = bright if size else medium
        if size == 0:
            draw.point((x, y), fill=fill)
        else:
            draw.rectangle((x, y, x + 1, y + 1), fill=fill)


# ---------------------------------------------------------------------------
# Clouds
# ---------------------------------------------------------------------------


def draw_cloud(
    image: Image.Image,
    rect: Rect,
    *,
    cx: int,
    cy: int,
    scale: float = 1.0,
    dark: bool = False,
) -> None:
    """Composite a soft cloud (union of ellipses) at *(cx, cy)*.

    *dark* picks a heavier interior gradient (for rain-bearing clouds).
    """
    # Cloud silhouette: five overlapping ellipses sized off *scale*.
    base_w = int(220 * scale)
    base_h = int(120 * scale)
    pad = 8
    bw = base_w + pad * 2
    bh = base_h + pad * 2
    mask = Image.new("L", (bw, bh), 0)
    mdraw = ImageDraw.Draw(mask)
    s = scale
    lobes = [
        (int(50 * s), int(70 * s), int(38 * s)),
        (int(95 * s), int(45 * s), int(50 * s)),
        (int(140 * s), int(55 * s), int(48 * s)),
        (int(180 * s), int(75 * s), int(38 * s)),
        (int(110 * s), int(85 * s), int(46 * s)),
    ]
    for lx, ly, lr in lobes:
        mdraw.ellipse(
            (pad + lx - lr, pad + ly - lr, pad + lx + lr, pad + ly + lr),
            fill=255,
        )
    # Interior shading: top lighter (catching the light), bottom darker.
    if dark:
        # Rain/storm clouds — heavy, brooding.
        top, bottom = 95, 55
    else:
        # Fair-weather cumulus — bright at the top, denser halftone at the
        # underside. Keep values well above the sky tones so the cloud reads
        # as opaque against the dithered sky.
        top, bottom = 255, 175
    # Build the vertical gradient as a 1-px-wide strip then NEAREST-resize to
    # full width — same pattern as ``draw_sky``. Much faster than a per-pixel
    # nested loop, especially on a Pi.
    strip = Image.new("L", (1, bh))
    for y in range(bh):
        t = y / max(1, bh - 1)
        strip.putpixel((0, y), int(top + (bottom - top) * t))
    interior = strip.resize((bw, bh), Image.Resampling.NEAREST)
    if image.mode == "RGB":
        interior = interior.convert("RGB")

    top_left = (cx - bw // 2, cy - bh // 2)
    image.paste(interior, top_left, mask)


# ---------------------------------------------------------------------------
# Precipitation
# ---------------------------------------------------------------------------


def draw_precip(
    image: Image.Image,
    rect: Rect,
    today: date,
    *,
    kind: str,
    count: int = 260,
    top_inset: int = 130,
    bottom_inset: int = 18,
) -> None:
    """Scatter rain streaks or snow flakes below the cloud line."""
    x0, y0, x1, y1 = rect
    draw = ImageDraw.Draw(image)
    rng = random.Random(today.toordinal() ^ 0xBEEF)
    mode = image.mode
    bottom = y1 - bottom_inset
    top = y0 + top_inset
    if bottom <= top:
        return
    streak_fill = _grey(95, mode)
    # Snowflakes are drawn as solid ink stars against the light sky (engraving
    # convention) so they stay visible after Floyd-Steinberg quantization.
    flake_fill = _ink(mode)
    if kind == "rain":
        for _ in range(count):
            x = rng.randint(x0 + 6, x1 - 6)
            y = rng.randint(top, bottom)
            length = rng.randint(6, 14)
            slant = rng.choice((-3, -2, -1))
            draw.line([(x, y), (x + slant, y + length)], fill=streak_fill, width=1)
    else:  # snow
        for _ in range(int(count * 0.5)):
            x = rng.randint(x0 + 6, x1 - 6)
            y = rng.randint(top, bottom)
            r = rng.choice((1, 2, 2))
            # Centre dot.
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=flake_fill)
            if r >= 2:
                draw.line((x - r - 1, y, x + r + 1, y), fill=flake_fill, width=1)
                draw.line((x, y - r - 1, x, y + r + 1), fill=flake_fill, width=1)
                draw.line((x - r, y - r, x + r, y + r), fill=flake_fill, width=1)
                draw.line((x - r, y + r, x + r, y - r), fill=flake_fill, width=1)


def draw_lightning(
    image: Image.Image,
    rect: Rect,
    *,
    cx: int,
    top_y: int,
    bottom_inset: int = 10,
) -> None:
    """Sharp inky lightning bolt zig-zagging downward from *(cx, top_y)*."""
    mode = image.mode
    draw = ImageDraw.Draw(image)
    h = (rect[3] - bottom_inset) - top_y
    points = [
        (cx + 14, top_y),
        (cx - 6, top_y + int(h * 0.32)),
        (cx + 6, top_y + int(h * 0.40)),
        (cx - 14, top_y + int(h * 0.78)),
        (cx + 4, top_y + int(h * 0.52)),
        (cx - 4, top_y + int(h * 0.46)),
        (cx + 18, top_y + int(h * 0.10)),
    ]
    draw.polygon(points, fill=_ink(mode))


# ---------------------------------------------------------------------------
# "Missing" / no-signal fallback
# ---------------------------------------------------------------------------


def draw_missing(image: Image.Image, rect: Rect) -> None:
    """Concentric arcs standing in for an illustration when weather is absent."""
    mode = image.mode
    # Mid-grey backdrop so the no-signal panel reads at the same density as
    # the populated weather plates.
    backdrop = Image.new("L", (rect[2] - rect[0], rect[3] - rect[1]), 160)
    if mode == "RGB":
        backdrop = backdrop.convert("RGB")
    image.paste(backdrop, (rect[0], rect[1]))
    draw = ImageDraw.Draw(image)
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    # Arc tones must all sit clearly below the 160 backdrop so each ring
    # stays distinguishable; the original (200, 180, 160, 140, 120) set was
    # tuned for a 240 paper backdrop and collapsed against mid-grey.
    for r, tone in ((140, 120), (110, 100), (80, 80), (50, 60), (24, 40)):
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            outline=_grey(tone, mode),
            width=2,
        )


# ---------------------------------------------------------------------------
# Scene composition
# ---------------------------------------------------------------------------

# The scene below was composed for halftone's 800x296 hero, and every placement
# is still written in those coordinates. They are re-expressed as fractions of
# whatever rect is passed in, so the same composition survives a narrower
# plate. Element *sizes* scale separately via the ``scale`` argument, because a
# square-ish hero wants a disc nearly as large as the wide one even though
# every horizontal offset has to shrink with the width.
_NOMINAL_W = 800
_NOMINAL_H = 296


def draw_weather_scene(
    image: Image.Image,
    rect: Rect,
    icon: str | None,
    today: date,
    *,
    scale: float = 1.0,
) -> None:
    """Draw the full procedural weather illustration for *icon* into *rect*.

    Dispatches on :func:`illustration_kind` and composes the primitives above
    into one of eight scenes (sun, moon, partly cloudy, overcast, rain, storm,
    snow, fog), falling back to :func:`draw_missing` when there is no weather.

    *scale* multiplies element sizes only; offsets and counts are derived from
    *rect* so a plate of a different shape stays composed. Passing the nominal
    800x296 rect at ``scale=1.0`` reproduces the original placement exactly.
    """
    x0, y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - y0
    cx = x0 + w // 2
    cy = y0 + h // 2

    # Horizontal offsets sit on the midpoint between the rect's width fraction
    # and *scale*. Mapping them by width alone shrinks the gaps faster than the
    # elements they separate — on a half-width plate the partly-cloudy sun and
    # its cloud end up on top of each other — while scaling them like the
    # elements pushes the assembly off a plate narrower than the landscape
    # composition it was drawn for. The midpoint keeps the assembly on the
    # plate, and what overlap is left reads as the occlusion a partly-cloudy
    # sky wants anyway.
    x_scale = (w / _NOMINAL_W + scale) / 2

    def dx(v: float) -> int:
        """Horizontal offset *v* (nominal px) mapped onto this rect's width."""
        return round(v * x_scale)

    def dy(v: float) -> int:
        """Vertical offset *v* (nominal px) mapped onto this rect's height."""
        return round(v * h / _NOMINAL_H)

    def sz(v: float) -> int:
        """Element size *v* (nominal px) at the caller's *scale*."""
        return max(1, round(v * scale))

    # Scatter counts track area rather than width: half the plate wants half
    # the raindrops, not the same 260 crammed into it.
    density = (w * h) / (_NOMINAL_W * _NOMINAL_H)

    def n(v: float) -> int:
        return max(1, round(v * density))

    kind, is_night = illustration_kind(icon)

    if kind == "sun":
        draw_sky(image, rect, day=True)
        draw_sun(image, rect, cx=cx, cy=cy, radius=sz(92))
    elif kind == "moon":
        draw_sky(image, rect, day=False)
        draw_stars(image, rect, today, count=n(140), bottom_inset=dy(24))
        draw_moon(image, rect, today, cx=cx, cy=cy, radius=sz(92))
    elif kind == "partly_cloudy":
        draw_sky(image, rect, day=not is_night)
        if is_night:
            draw_stars(image, rect, today, count=n(140), bottom_inset=dy(24))
            draw_moon(image, rect, today, cx=cx - dx(140), cy=cy - dy(22), radius=sz(70))
        else:
            draw_sun(image, rect, cx=cx - dx(150), cy=cy - dy(22), radius=sz(78))
        draw_cloud(image, rect, cx=cx + dx(90), cy=cy + dy(18), scale=1.25 * scale)
    elif kind == "overcast":
        # Layered light cumulus stacked across the sky.
        draw_sky(image, rect, day=not is_night)
        draw_cloud(image, rect, cx=cx - dx(220), cy=cy - dy(32), scale=0.95 * scale)
        draw_cloud(image, rect, cx=cx + dx(190), cy=cy - dy(52), scale=0.9 * scale)
        draw_cloud(image, rect, cx=cx, cy=cy + dy(28), scale=1.35 * scale)
    elif kind == "rain":
        draw_sky(image, rect, day=not is_night)
        draw_cloud(image, rect, cx=cx, cy=cy - dy(42), scale=1.3 * scale, dark=True)
        draw_precip(
            image, rect, today, kind="rain", count=n(260), top_inset=dy(130), bottom_inset=dy(18)
        )
    elif kind == "storm":
        # Mid-grey "broken sky" so the very dark storm cloud pops out.
        draw_sky_stormy(image, rect)
        draw_cloud(image, rect, cx=cx, cy=cy - dy(42), scale=1.4 * scale, dark=True)
        draw_lightning(image, rect, cx=cx + dx(6), top_y=cy, bottom_inset=dy(10))
        draw_precip(
            image, rect, today, kind="rain", count=n(350), top_inset=dy(130), bottom_inset=dy(18)
        )
    elif kind == "snow":
        draw_sky(image, rect, day=not is_night)
        draw_cloud(image, rect, cx=cx, cy=cy - dy(42), scale=1.25 * scale)
        draw_precip(
            image, rect, today, kind="snow", count=n(260), top_inset=dy(130), bottom_inset=dy(18)
        )
    elif kind == "fog":
        draw_fog(image, rect, today)
    else:
        draw_missing(image, rect)


# ---------------------------------------------------------------------------
# Decorative Bayer rule + screening
# ---------------------------------------------------------------------------


def draw_bayer_rule(
    image: Image.Image,
    x0: int,
    y0: int,
    w: int,
    h: int,
    mode: str,
    *,
    orientation: str = "horizontal",
) -> None:
    """Engraving-style separator: a Bayer halftone strip bracketed by hairlines.

    The hairlines give the strip two crisp edges so the eye reads it as a
    decorative rule rather than as bleed-through from the hero illustration.
    They run along the long edges: top and bottom for a horizontal rule, left
    and right when *orientation* is ``"vertical"`` (``halftone_agenda`` divides
    its two panes with one). The dot lattice is indexed off canvas coordinates
    either way, so a vertical rule aligns with the horizontal ones it meets.
    """
    on = _ink(mode)
    px = image.load()
    assert px is not None
    if orientation == "vertical":
        for yy in range(h):
            px[x0, y0 + yy] = on
            px[x0 + w - 1, y0 + yy] = on
        x_range = range(1, w - 1)
        y_range = range(h)
    else:
        for xx in range(w):
            px[x0 + xx, y0] = on
            px[x0 + xx, y0 + h - 1] = on
        x_range = range(w)
        y_range = range(1, h - 1)
    # Interior: Bayer dot pattern, slightly denser so it reads as ~60%.
    for yy in y_range:
        y = y0 + yy
        for xx in x_range:
            t = _BAYER_4X4[yy & 3][xx & 3]
            if t < 144:
                px[x0 + xx, y] = on


def bayer_screen(w: int, h: int, phase_x: int, phase_y: int, threshold: int) -> Image.Image:
    """Return a ``w×h`` L-mode mask of the 4×4 Bayer lattice at *threshold*.

    255 where the cell passes the threshold, 0 where it doesn't. The phase is
    taken from canvas coordinates so adjacent screened regions line up into one
    continuous halftone field instead of visibly seaming.
    """
    base = np.array(_BAYER_4X4, dtype=np.int16)
    passing = ((base < threshold).astype(np.uint8)) * 255
    ys = (np.arange(h, dtype=np.int64) + phase_y) & 3
    xs = (np.arange(w, dtype=np.int64) + phase_x) & 3
    return Image.fromarray(passing[np.ix_(ys, xs)], mode="L")


def screened_paste(
    image: Image.Image,
    box: Rect,
    render: Callable[[ImageDraw.ImageDraw], None],
    *,
    threshold: int = 96,
) -> None:
    """Draw via *render* offscreen, then stamp it through a Bayer screen.

    *box* is ``(x, y, w, h)`` in canvas coordinates. ``render`` receives a draw
    handle on a white L-mode tile of that size and should draw in black.

    Used by ``day_arc`` to mark elapsed events: the row is typeset solid and
    then perforated here, so it reads as faded from across the room while
    staying legible up close. Doing it this way — rather than drawing the text
    in mid-grey and letting Floyd-Steinberg handle it — is deliberate on two
    counts. FS diffuses error across glyph boundaries and turns small type to
    mush, while a fixed ordered lattice degrades every glyph identically; and
    the RGB (Inky) path never runs FS at all, so a mid-grey row would screen on
    one backend and not the other. The output here is pure ink-or-nothing, so
    FS passes it through untouched and the Inky palette mapping is unambiguous.

    *threshold* is the Bayer cut in 0–240: higher removes more ink. The default
    of 96 retains roughly 60% of the original coverage.
    """
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return
    tile = Image.new("L", (w, h), 255)
    render(ImageDraw.Draw(tile))
    # Ink mask: every pixel the caller darkened, including antialiased edges.
    ink_mask = tile.point(lambda v: 255 if v < 128 else 0)
    mask = ImageChops.multiply(ink_mask, bayer_screen(w, h, x, y, threshold))
    image.paste(Image.new(image.mode, (w, h), _ink(image.mode)), (x, y), mask)
