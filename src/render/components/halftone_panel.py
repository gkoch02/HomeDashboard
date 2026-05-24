"""Full-canvas dithered weather plate for the ``halftone`` theme.

The panel draws a procedural illustration that varies by weather icon code
into an 800×320 hero region, a 6-px ordered-Bayer rule, and a 154-px margin
band of typeset data below.

Drawing is L-mode by default (8-bit greyscale). When the canvas is RGB
(Inky panels with ``prefer_color_on_inky=True``), the greyscale tones are
emitted as ``(v, v, v)`` triples and the warm sun/moon highlight uses a
yellow accent. Floyd-Steinberg quantization (configured by the theme's
``preferred_quantization_mode``) turns the smooth greyscale gradients into
engraving-style halftone on Waveshare.

No external assets — every illustration is generated from PIL primitives.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime
from functools import lru_cache

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DashboardData
from src.render.fonts import weather_icon
from src.render.moon import is_waxing, moon_illumination
from src.render.primitives import draw_text_truncated
from src.render.quantize import _BAYER_4X4, INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_YELLOW, ComponentRegion, ThemeStyle

# Weather Icons font glyphs — Righteous itself has no ↑/↓ arrows, so the
# sunrise/sunset row borrows these two glyphs from the bundled Weather
# Icons font and centers them on the Righteous text midline.
_SUNRISE_GLYPH = "\uf051"  # wi-sunrise
_SUNSET_GLYPH = "\uf052"  # wi-sunset

# ---------------------------------------------------------------------------
# Region geometry
# ---------------------------------------------------------------------------

HERO_H = 296
RULE_H = 6
MARGIN_PAD_X = 28
TEMP_NUMERAL_SIZE = 128
# Fixed left-column reservation for the temperature numeral + caption.
# Sized to hold a 3-digit temp ("108°") at TEMP_NUMERAL_SIZE without
# overlapping the right-side text column, so the right column's available
# width doesn't shrink as the temp digit count grows.
TEMP_COL_W = 280

# Centre of the hero region — sun/moon and most cloud assemblies position
# themselves relative to this point.
_HERO_CX = 400
_HERO_CY = 156


# ---------------------------------------------------------------------------
# Mode-aware colour helpers
# ---------------------------------------------------------------------------


def _grey(v: int, mode: str) -> int | tuple[int, int, int]:
    """Return *v* (0..255) as either an L-mode int or an RGB greyscale triple."""
    return v if mode == "L" else (v, v, v)


def _accent_yellow(mode: str) -> int | tuple[int, int, int]:
    """Warm-light accent for sun/moon highlights.

    On RGB canvases this returns the Inky Spectra-6 yellow RGB tuple; on
    L-mode it collapses to a light grey so the highlight still reads.
    """
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_YELLOW]
    return 210


def _ink(mode: str) -> int | tuple[int, int, int]:
    """Solid foreground ink (black)."""
    return 0 if mode == "L" else (0, 0, 0)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_halftone(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full ``halftone`` plate into *region* of *image*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        # The production caller (``canvas.render_dashboard``) always passes
        # the backing image via ``RenderContext.image``. This branch only
        # fires for tests that build an ``ImageDraw.Draw`` directly without
        # forwarding the image — fall back to the private attribute rather
        # than crashing so those tests keep working.
        image = draw._image  # type: ignore[attr-defined]

    mode = image.mode
    x0, y0, w, h = region.x, region.y, region.w, region.h
    hero_rect = (x0, y0, x0 + w, y0 + HERO_H)
    rule_y0 = y0 + HERO_H
    margin_y0 = rule_y0 + RULE_H

    _draw_illustration(image, hero_rect, data, today, now)
    _draw_bayer_rule(image, x0, rule_y0, w, RULE_H, mode)
    _draw_margin_band(
        draw,
        image,
        data,
        today,
        now,
        x0=x0,
        y0=margin_y0,
        w=w,
        h=h - HERO_H - RULE_H,
        style=style,
    )


# ---------------------------------------------------------------------------
# Illustration dispatch
# ---------------------------------------------------------------------------


def _illustration_kind(icon: str | None) -> tuple[str, bool]:
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


def _draw_illustration(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
    data: DashboardData,
    today: date,
    now: datetime,
) -> None:
    icon = data.weather.current_icon if data.weather is not None else None
    kind, is_night = _illustration_kind(icon)

    if kind == "sun":
        _draw_sky(image, hero_rect, day=True)
        _draw_sun(image, hero_rect, cx=_HERO_CX, cy=_HERO_CY - 8, radius=92)
    elif kind == "moon":
        _draw_sky(image, hero_rect, day=False)
        _draw_stars(image, hero_rect, today)
        _draw_moon(image, hero_rect, today, cx=_HERO_CX, cy=_HERO_CY - 8, radius=92)
    elif kind == "partly_cloudy":
        _draw_sky(image, hero_rect, day=not is_night)
        if is_night:
            _draw_stars(image, hero_rect, today)
            _draw_moon(image, hero_rect, today, cx=_HERO_CX - 140, cy=_HERO_CY - 30, radius=70)
        else:
            _draw_sun(image, hero_rect, cx=_HERO_CX - 150, cy=_HERO_CY - 30, radius=78)
        _draw_cloud(image, hero_rect, cx=_HERO_CX + 90, cy=_HERO_CY + 10, scale=1.25)
    elif kind == "overcast":
        # Layered light cumulus stacked across the sky.
        _draw_sky(image, hero_rect, day=not is_night)
        _draw_cloud(image, hero_rect, cx=_HERO_CX - 220, cy=_HERO_CY - 40, scale=0.95)
        _draw_cloud(image, hero_rect, cx=_HERO_CX + 190, cy=_HERO_CY - 60, scale=0.9)
        _draw_cloud(image, hero_rect, cx=_HERO_CX, cy=_HERO_CY + 20, scale=1.35)
    elif kind == "rain":
        _draw_sky(image, hero_rect, day=not is_night)
        _draw_cloud(image, hero_rect, cx=_HERO_CX, cy=_HERO_CY - 50, scale=1.3, dark=True)
        _draw_precip(image, hero_rect, today, kind="rain")
    elif kind == "storm":
        # Mid-grey "broken sky" so the very dark storm cloud pops out.
        _draw_sky_stormy(image, hero_rect)
        _draw_cloud(image, hero_rect, cx=_HERO_CX, cy=_HERO_CY - 50, scale=1.4, dark=True)
        _draw_lightning(image, hero_rect, cx=_HERO_CX + 6, top_y=_HERO_CY - 8)
        _draw_precip(image, hero_rect, today, kind="rain", count=350)
    elif kind == "snow":
        _draw_sky(image, hero_rect, day=not is_night)
        _draw_cloud(image, hero_rect, cx=_HERO_CX, cy=_HERO_CY - 50, scale=1.25)
        _draw_precip(image, hero_rect, today, kind="snow")
    elif kind == "fog":
        _draw_fog(image, hero_rect, today)
    else:
        _draw_missing(image, hero_rect)


# ---------------------------------------------------------------------------
# Sky background
# ---------------------------------------------------------------------------


def _draw_sky(image: Image.Image, hero_rect: tuple[int, int, int, int], *, day: bool) -> None:
    """Paint a vertical greyscale gradient sky into *hero_rect*."""
    x0, y0, x1, y1 = hero_rect
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


def _draw_sky_stormy(image: Image.Image, hero_rect: tuple[int, int, int, int]) -> None:
    """Mid-grey turbulent sky for thunderstorm scenes (sky reads as 'broken cloud')."""
    x0, y0, x1, y1 = hero_rect
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


def _draw_fog(image: Image.Image, hero_rect: tuple[int, int, int, int], today: date) -> None:
    """Stack horizontal greyscale bands with slight jitter for fog conditions."""
    x0, y0, x1, y1 = hero_rect
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


def _draw_sun(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
    *,
    cx: int,
    cy: int,
    radius: int,
) -> None:
    """Draw radiating triangular rays, then a soft radial-gradient sun disc."""
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
    disc = _radial_gradient_disc(radius * 2 + 1, inner_v=255, outer_v=210)
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
            outline=_accent_yellow(mode),
            width=3,
        )


@lru_cache(maxsize=8)
def _radial_gradient_disc(d: int, inner_v: int, outer_v: int) -> Image.Image:
    """Return an LA-mode disc of diameter *d* with a radial greyscale gradient.

    Pixels outside the disc have alpha=0 so a pasted disc leaves the
    surrounding canvas untouched.
    """
    out = Image.new("LA", (d, d), (0, 0))
    cx = cy = (d - 1) / 2.0
    rad = (d - 1) / 2.0
    px = out.load()
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


def _draw_moon(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
    today: date,
    *,
    cx: int,
    cy: int,
    radius: int,
) -> None:
    illum = moon_illumination(today)
    disc = _moon_disc(radius * 2 + 1, illum, is_waxing(today))
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
            outline=_accent_yellow(mode),
            width=2,
        )


@lru_cache(maxsize=32)
def _moon_disc(d: int, illumination_pct: float, waxing: bool) -> Image.Image:
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


def _draw_stars(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
    today: date,
) -> None:
    """Scatter small bright pixels across the night sky, seeded daily."""
    x0, y0, x1, y1 = hero_rect
    draw = ImageDraw.Draw(image)
    rng = random.Random(today.toordinal() ^ 0xA17)
    mode = image.mode
    bright = _grey(245, mode)
    medium = _grey(200, mode)
    for _ in range(140):
        x = rng.randint(x0 + 6, x1 - 6)
        y = rng.randint(y0 + 6, y1 - 24)
        size = rng.choice((0, 0, 0, 1))
        fill = bright if size else medium
        if size == 0:
            draw.point((x, y), fill=fill)
        else:
            draw.rectangle((x, y, x + 1, y + 1), fill=fill)


# ---------------------------------------------------------------------------
# Clouds
# ---------------------------------------------------------------------------


def _draw_cloud(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
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
    # full width — same pattern as ``_draw_sky``. Much faster than a per-pixel
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


def _draw_precip(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
    today: date,
    *,
    kind: str,
    count: int = 260,
) -> None:
    """Scatter rain streaks or snow flakes below the cloud line."""
    x0, y0, x1, y1 = hero_rect
    draw = ImageDraw.Draw(image)
    rng = random.Random(today.toordinal() ^ 0xBEEF)
    mode = image.mode
    bottom = y1 - 18
    top = y0 + 130
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


def _draw_lightning(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
    *,
    cx: int,
    top_y: int,
) -> None:
    """Sharp inky lightning bolt zig-zagging downward from *(cx, top_y)*."""
    mode = image.mode
    draw = ImageDraw.Draw(image)
    h = (hero_rect[3] - 10) - top_y
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


def _draw_missing(image: Image.Image, hero_rect: tuple[int, int, int, int]) -> None:
    """Concentric arcs + 'NO SIGNAL' message when we have no weather data."""
    mode = image.mode
    # Mid-grey backdrop so the no-signal panel reads at the same density as
    # the populated weather plates.
    backdrop = Image.new("L", (hero_rect[2] - hero_rect[0], hero_rect[3] - hero_rect[1]), 160)
    if mode == "RGB":
        backdrop = backdrop.convert("RGB")
    image.paste(backdrop, (hero_rect[0], hero_rect[1]))
    draw = ImageDraw.Draw(image)
    cx = (hero_rect[0] + hero_rect[2]) // 2
    cy = (hero_rect[1] + hero_rect[3]) // 2
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
# Decorative Bayer rule
# ---------------------------------------------------------------------------


def _draw_bayer_rule(image: Image.Image, x0: int, y0: int, w: int, h: int, mode: str) -> None:
    """Engraving-style separator: a Bayer halftone strip bracketed by hairlines.

    The hairlines give a crisp top and bottom edge so the eye reads it as a
    decorative rule rather than as bleed-through from the hero illustration.
    """
    on = _ink(mode)
    px = image.load()
    # Top hairline (full-width, solid).
    for xx in range(w):
        px[x0 + xx, y0] = on
    # Bottom hairline.
    for xx in range(w):
        px[x0 + xx, y0 + h - 1] = on
    # Interior rows: Bayer dot pattern, slightly denser so it reads as ~60%.
    for yy in range(1, h - 1):
        y = y0 + yy
        for xx in range(w):
            t = _BAYER_4X4[yy & 3][xx & 3]
            if t < 144:
                px[x0 + xx, y] = on


# ---------------------------------------------------------------------------
# Margin band — typeset weather info + next event + daily quote
# ---------------------------------------------------------------------------


def _fmt_temp(t: float | None) -> str:
    if t is None:
        return "—"
    return f"{int(round(t))}°"


def _format_event_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").lstrip("0")


def _next_event_line(events: list[CalendarEvent], now: datetime) -> str | None:
    """Find the soonest non-all-day future event and format it for the margin."""
    if not events:
        return None
    now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
    candidates: list[tuple[datetime, CalendarEvent]] = []
    for e in events:
        if e.is_all_day:
            continue
        start = e.start.replace(tzinfo=None) if e.start.tzinfo is not None else e.start
        if start >= now_naive:
            candidates.append((start, e))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    start, event = candidates[0]
    when = _format_event_time(start)
    return f"NEXT — {when}  {event.summary}"


def _draw_margin_band(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    x0: int,
    y0: int,
    w: int,
    h: int,
    style: ThemeStyle,
) -> None:
    """Paint the typeset data band below the hero illustration.

    Two-band almanac layout: the temperature numeral anchors the left
    third; the right side stacks a "NOW" line (condition + H/L/feels)
    above a thin hairline rule, then a "TODAY" pair of lines
    (sunrise/sunset + date, then the next event).

        ┌──────────────────────────────────────────────────────────────┐
        │         │ PARTLY CLOUDY · H 48° · L 35° · FEELS 38°          │
        │   42°   │ ─────────────────────────────────────────────────  │
        │         │ ☀ 6:24 AM   ☼ 7:51 PM        MON · APR 6 · 2026    │
        │         │ NEXT — 9:00 AM  ·  Farmers Market                  │
        └──────────────────────────────────────────────────────────────┘
    """
    mode = image.mode
    # Paint a clean paper background so the dithered hero never bleeds in.
    paper = Image.new("L", (w, h), 255)
    if mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x0, y0))

    # Every margin-band glyph is drawn in solid ink. Mid-grey fills get
    # mangled by Floyd-Steinberg into a halftone pattern and become
    # illegible — visual hierarchy here is carried by size and weight,
    # not by colour.
    ink = _ink(mode)

    weather = data.weather

    # --- Temperature numeral, vertically centred in the full band. A
    # smaller "feels NN°" caption sits directly under it so the headline
    # weather summary on the right can stay tight without losing that
    # secondary reading.
    feels_caption = (
        f"feels {_fmt_temp(weather.feels_like)}"
        if weather and weather.feels_like is not None
        else ""
    )
    feels_font = style.font_semibold(20) if feels_caption else None
    feels_h = 0
    if feels_caption and feels_font is not None:
        fb = draw.textbbox((0, 0), feels_caption, font=feels_font)
        feels_h = (fb[3] - fb[1]) + 8  # 8 px gap above the caption

    # The temp numeral lives inside a fixed-width left column so the
    # right-side text column width is stable across 1-, 2-, and 3-digit
    # temperatures. Within that column the temp is left-aligned to the
    # outer margin.
    temp_font = style.font_title(TEMP_NUMERAL_SIZE)
    temp_text = _fmt_temp(weather.current_temp) if weather else "—"
    temp_bbox = draw.textbbox((0, 0), temp_text, font=temp_font)
    temp_visible_h = temp_bbox[3] - temp_bbox[1]
    temp_x = x0 + MARGIN_PAD_X - temp_bbox[0]
    # Vertically centre the temp + caption stack together so they read as
    # one block.
    stack_h = temp_visible_h + feels_h
    temp_y = y0 + (h - stack_h) // 2 - temp_bbox[1]
    draw.text((temp_x, temp_y), temp_text, font=temp_font, fill=ink)
    temp_w = temp_bbox[2] - temp_bbox[0]
    text_col_x = x0 + TEMP_COL_W
    text_col_right = x0 + w - MARGIN_PAD_X

    # Centre the feels-like caption horizontally under the temperature
    # numeral so it reads as a footnote to the headline number.
    if feels_caption and feels_font is not None:
        fb = draw.textbbox((0, 0), feels_caption, font=feels_font)
        cap_w = fb[2] - fb[0]
        temp_w = temp_bbox[2] - temp_bbox[0]
        cap_x = temp_x + (temp_w - cap_w) // 2 - fb[0]
        cap_y = temp_y + temp_bbox[1] + temp_visible_h + 8 - fb[1]
        draw.text((cap_x, cap_y), feels_caption, font=feels_font, fill=ink)

    # --- Three zones for the right-column text, each carrying one row:
    # NOW (above the rule), TODAY (sun times + date), NEXT (calendar).
    # The hairline rule splits NOW from the lower pair; the lower pair
    # is split evenly between TODAY and NEXT. Each row's text is
    # vertically centred within its zone so the band reads as three
    # deliberately-spaced rows rather than top-aligned text with
    # arbitrary gaps.
    rule_y = y0 + h // 3
    below_top = rule_y + 1
    below_split = below_top + (y0 + h - below_top) // 2
    now_zone = (y0, rule_y)
    today_zone = (below_top, below_split)
    next_zone = (below_split, y0 + h)

    def _centre_y(bbox: tuple[int, int, int, int], zone: tuple[int, int]) -> int:
        """Return the y to draw at so *bbox*'s visible ink centres in *zone*."""
        bb_h = bbox[3] - bbox[1]
        zone_mid = (zone[0] + zone[1]) // 2
        return zone_mid - bb_h // 2 - bbox[1]

    # --- NOW row: condition + H / L on one line. ``feels NN°`` lives
    # under the temperature numeral so this row can breathe at a larger
    # display size without overflowing on long condition strings (the
    # widest OWM phrase ``HEAVY INTENSITY RAIN`` plus triple-digit temps
    # still fits inside the 492 px right column at 25 pt).
    now_font = style.font_section_label(25)
    now_parts: list[str] = []
    if weather is not None:
        if weather.current_description:
            now_parts.append(weather.current_description.upper())
        now_parts.append(f"H {_fmt_temp(weather.high)}")
        now_parts.append(f"L {_fmt_temp(weather.low)}")
    else:
        now_parts.append("AWAITING DATA")
    now_text = "  ·  ".join(now_parts)
    nb = draw.textbbox((0, 0), now_text, font=now_font)
    max_now_w = text_col_right - text_col_x
    draw_text_truncated(
        draw,
        (text_col_x, _centre_y(nb, now_zone)),
        now_text,
        now_font,
        max_now_w,
        fill=ink,
    )

    # --- Hairline rule between the NOW zone and the lower pair.
    _draw_text_band_rule(image, text_col_x, rule_y, text_col_right - text_col_x, mode)

    # --- TODAY row: sunrise + sunset on the left, date on the right,
    # both vertically centred in the TODAY zone.
    today_font = style.font_semibold(22)
    if weather and (weather.sunrise or weather.sunset):
        rise_text = _format_event_time(weather.sunrise) if weather.sunrise else "—"
        set_text = _format_event_time(weather.sunset) if weather.sunset else "—"
        icon_font = weather_icon(28)
        glyph_pad = 5
        pair_gap = 20

        chunks = [
            (_SUNRISE_GLYPH, icon_font),
            (rise_text, today_font),
            (_SUNSET_GLYPH, icon_font),
            (set_text, today_font),
        ]
        measured = [(s, f, draw.textbbox((0, 0), s, font=f)) for s, f in chunks]
        pads = (glyph_pad, pair_gap, glyph_pad, 0)

        # All chunks share the same vertical midline — derived from the
        # TODAY zone's mid Y so the row sits centred regardless of which
        # chunk (icon vs text) happens to be tallest.
        row_mid = (today_zone[0] + today_zone[1]) // 2

        cursor = text_col_x
        for (s, f, bb), pad in zip(measured, pads):
            glyph_mid = (bb[1] + bb[3]) // 2
            draw.text((cursor - bb[0], row_mid - glyph_mid), s, font=f, fill=ink)
            cursor += (bb[2] - bb[0]) + pad

    date_font = style.font_section_label(22)
    date_text = today.strftime("%a · %b %-d · %Y").upper()
    db = draw.textbbox((0, 0), date_text, font=date_font)
    date_x = text_col_right - (db[2] - db[0]) - db[0]
    draw.text((date_x, _centre_y(db, today_zone)), date_text, font=date_font, fill=ink)

    # --- NEXT event, centred in the NEXT zone.
    next_line = _next_event_line(data.events, now)
    if next_line:
        event_font = style.font_semibold(24)
        eb = draw.textbbox((0, 0), next_line, font=event_font)
        max_w = text_col_right - text_col_x
        draw_text_truncated(
            draw,
            (text_col_x, _centre_y(eb, next_zone)),
            next_line,
            event_font,
            max_w,
            fill=ink,
        )


def _draw_text_band_rule(image: Image.Image, x0: int, y: int, w: int, mode: str) -> None:
    """Single-pixel dotted hairline matching the hero's Bayer rule motif.

    Pixels are drawn at the darker Bayer cells of the 4×4 matrix on a
    single row, giving a delicate halftone rule that pairs with the
    6-px engraved separator above.
    """
    on = _ink(mode)
    px = image.load()
    for xx in range(w):
        if _BAYER_4X4[0][xx & 3] < 128:
            px[x0 + xx, y] = on
