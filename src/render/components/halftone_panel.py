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
from src.render.components.info_panel import _quote_for_today
from src.render.moon import moon_illumination, moon_phase_age
from src.render.primitives import draw_text_truncated, draw_text_wrapped, text_height, wrap_lines
from src.render.quantize import _BAYER_4X4, INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_YELLOW, ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Region geometry
# ---------------------------------------------------------------------------

HERO_H = 296
RULE_H = 6
MARGIN_PAD_X = 28
TEMP_NUMERAL_SIZE = 96

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
    quote_refresh: str = "daily",
) -> None:
    """Draw the full ``halftone`` plate into *region* of *image*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        # Component must have pixel access for radial gradients. The canvas
        # always supplies one in production; tests that build a draw object
        # directly should pass the backing image too.
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
        quote_refresh=quote_refresh,
    )


# ---------------------------------------------------------------------------
# Illustration dispatch
# ---------------------------------------------------------------------------


def _illustration_kind(icon: str | None) -> str:
    """Map an OWM icon code (e.g. ``"10d"``) to an illustration kind."""
    if not icon:
        return "missing"
    code = icon[:2]
    day_night = icon[2:3] if len(icon) > 2 else "d"
    if code == "01":
        return "moon" if day_night == "n" else "sun"
    if code in ("02", "03"):
        return "partly_cloudy"
    if code == "04":
        return "overcast"
    if code in ("09", "10"):
        return "rain"
    if code == "11":
        return "storm"
    if code == "13":
        return "snow"
    if code == "50":
        return "fog"
    return "missing"


def _draw_illustration(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
    data: DashboardData,
    today: date,
    now: datetime,
) -> None:
    icon = data.weather.current_icon if data.weather is not None else None
    kind = _illustration_kind(icon)
    is_night = bool(icon) and len(icon) > 2 and icon[2] == "n"

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
        # Light, slightly darker at the top, brighter toward the horizon.
        # Values in the 218–245 range give a sparse halftone that reads as
        # near-white on eInk while still letting the sun and clouds register
        # against it.
        top, bottom = 218, 245
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
        # 140 at top → 180 toward the horizon: a heavy, charged sky.
        v = int(140 + (180 - 140) * t)
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
    # Start from a neutral mid-grey sky tone, alternate denser/lighter bands.
    base_tones = [190, 215, 175, 220, 200, 230, 185, 210]
    band_count = 8
    band_h = h // band_count
    for i in range(band_count):
        tone = base_tones[i % len(base_tones)] + rng.randint(-8, 8)
        tone = max(140, min(240, tone))
        # Jitter the band horizontally so seams between bands waver.
        offset = rng.randint(-30, 30)
        band = Image.new("L", (w + 60, band_h + 2), tone)
        if image.mode == "RGB":
            band = band.convert("RGB")
        image.paste(band, (x0 - 30 + offset, y0 + i * band_h))
    # Final fill for any leftover pixels at the bottom.
    tail_h = h - band_count * band_h
    if tail_h > 0:
        tail = Image.new("L", (w, tail_h), 205)
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
    age = moon_phase_age(today)
    # First half of the synodic month is waxing (lit from the right limb).
    from src.render.moon import _SYNODIC_MONTH

    waxing = age < _SYNODIC_MONTH / 2
    disc = _moon_disc(radius * 2 + 1, illum, waxing)
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
        # Fair-weather cumulus — bright at the top, soft halftone at the
        # underside. Keep values well above the sky tones so the cloud reads
        # as opaque against the dithered sky.
        top, bottom = 255, 195
    interior = Image.new("L", (bw, bh))
    for y in range(bh):
        t = y / max(1, bh - 1)
        v = int(top + (bottom - top) * t)
        for x in range(bw):
            interior.putpixel((x, y), v)
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
    # Light paper backdrop.
    backdrop = Image.new("L", (hero_rect[2] - hero_rect[0], hero_rect[3] - hero_rect[1]), 240)
    if mode == "RGB":
        backdrop = backdrop.convert("RGB")
    image.paste(backdrop, (hero_rect[0], hero_rect[1]))
    draw = ImageDraw.Draw(image)
    cx = (hero_rect[0] + hero_rect[2]) // 2
    cy = (hero_rect[1] + hero_rect[3]) // 2
    for r, tone in ((140, 200), (110, 180), (80, 160), (50, 140), (24, 120)):
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
    s = dt.strftime("%-I:%M %p").lstrip("0")
    return s.replace(" AM", " AM").replace(" PM", " PM")


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
    quote_refresh: str,
) -> None:
    """Paint the typeset data band below the hero illustration.

    Two-column layout, anchored to the top of the band:

        ┌─────────────────────────────────────────────────────────────┐
        │ 42°    PARTLY CLOUDY              SATURDAY · MAY 23 · 2026  │
        │        H 48° · L 35° · feels 38°    sun ↑ 6:24   sun ↓ 7:51 │
        │        Next  9:00 AM Farmers Market                         │
        │                                                             │
        │ "It's not what you look at … "        — Henry David Thoreau │
        └─────────────────────────────────────────────────────────────┘
    """
    mode = image.mode
    # Paint a clean paper background so the dithered hero never bleeds in.
    paper = Image.new("L", (w, h), 255)
    if mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x0, y0))

    ink = _ink(mode)
    secondary = _grey(85, mode)

    weather = data.weather

    # --- Temperature numeral, anchored to the top-left of the band
    temp_font = style.font_title(TEMP_NUMERAL_SIZE)
    temp_text = _fmt_temp(weather.current_temp) if weather else "—"
    temp_bbox = draw.textbbox((0, 0), temp_text, font=temp_font)
    temp_x = x0 + MARGIN_PAD_X - temp_bbox[0]
    temp_y = y0 + 4 - temp_bbox[1]
    draw.text((temp_x, temp_y), temp_text, font=temp_font, fill=ink)
    temp_right = temp_x + (temp_bbox[2] - temp_bbox[0])
    text_col_x = temp_right + 22

    # --- Condition (small caps) to the right of the temperature numeral
    condition_font = style.font_section_label(18)
    condition_text = (weather.current_description or "").upper() if weather else "AWAITING DATA"
    if condition_text:
        cb = draw.textbbox((0, 0), condition_text, font=condition_font)
        cy = y0 + 14 - cb[1]
        draw.text(
            (text_col_x - cb[0], cy),
            condition_text,
            font=condition_font,
            fill=ink,
        )

    # --- Stats line under the condition
    stats_font = style.font_regular(15)
    parts: list[str] = []
    if weather is not None:
        parts.append(f"H {_fmt_temp(weather.high)}")
        parts.append(f"L {_fmt_temp(weather.low)}")
        if weather.feels_like is not None:
            parts.append(f"feels {_fmt_temp(weather.feels_like)}")
    stats_text = "  ·  ".join(parts) if parts else ""
    if stats_text:
        sb = draw.textbbox((0, 0), stats_text, font=stats_font)
        draw.text(
            (text_col_x - sb[0], y0 + 46 - sb[1]),
            stats_text,
            font=stats_font,
            fill=secondary,
        )

    # --- Next event line — below stats
    next_line = _next_event_line(data.events, now)
    if next_line:
        event_font = style.font_regular(15)
        eb = draw.textbbox((0, 0), next_line, font=event_font)
        ey = y0 + 74 - eb[1]
        # Limit to the available width before the right-column starts.
        max_w = (x0 + w - MARGIN_PAD_X - 260) - text_col_x
        if max_w > 80:
            draw_text_truncated(
                draw,
                (text_col_x, ey),
                next_line,
                event_font,
                max_w,
                fill=ink,
            )

    # --- Right-aligned location/date (small caps), anchored to the top-right
    location_font = style.font_section_label(15)
    location_text = (
        (weather.location_name or "").upper()
        if weather and weather.location_name
        else today.strftime("%A · %B %-d · %Y").upper()
    )
    lb = draw.textbbox((0, 0), location_text, font=location_font)
    loc_x = x0 + w - MARGIN_PAD_X - (lb[2] - lb[0]) - lb[0]
    loc_y = y0 + 14 - lb[1]
    draw.text((loc_x, loc_y), location_text, font=location_font, fill=ink)

    # When the OWM location is set, fall back to a date line below it.
    if weather and weather.location_name:
        date_font = stats_font
        date_text = today.strftime("%A · %B %-d · %Y").upper()
        db = draw.textbbox((0, 0), date_text, font=date_font)
        dx = x0 + w - MARGIN_PAD_X - (db[2] - db[0]) - db[0]
        draw.text((dx, y0 + 40 - db[1]), date_text, font=date_font, fill=secondary)
        sun_y = y0 + 66
    else:
        sun_y = y0 + 42

    # --- Sunrise / sunset line right-aligned
    if weather and (weather.sunrise or weather.sunset):
        rise = _format_event_time(weather.sunrise) if weather.sunrise else "—"
        setp = _format_event_time(weather.sunset) if weather.sunset else "—"
        sun_text = f"sun ↑ {rise}   sun ↓ {setp}"
        sb = draw.textbbox((0, 0), sun_text, font=stats_font)
        sx = x0 + w - MARGIN_PAD_X - (sb[2] - sb[0]) - sb[0]
        sy = sun_y - sb[1]
        draw.text((sx, sy), sun_text, font=stats_font, fill=secondary)

    # --- Daily quote at the bottom; wraps to two lines so the larger font
    # still has room to breathe. Author sits right-aligned beneath.
    quote = _quote_for_today(today, refresh=quote_refresh, now=now)
    quote_font = style.font_quote(15) if style.font_quote else style.font_regular(15)
    author_font = (
        style.font_quote_author(12) if style.font_quote_author else style.font_semibold(12)
    )
    quote_text = f"“{quote['text']}”"
    author_text = f"— {quote['author']}"
    quote_w = w - MARGIN_PAD_X * 2 - 12
    line_h = text_height(quote_font)
    lines = wrap_lines(quote_text, quote_font, quote_w)[:2]
    line_spacing = 2
    # Reserve space for author + bottom padding, then place the quote block
    # directly above it.
    author_bb = draw.textbbox((0, 0), author_text, font=author_font)
    author_h = author_bb[3] - author_bb[1]
    bottom_pad = 6
    block_h = line_h * len(lines) + line_spacing * max(0, len(lines) - 1)
    ay = y0 + h - bottom_pad - author_h - author_bb[1]
    qy = y0 + h - bottom_pad - author_h - 4 - block_h
    draw_text_wrapped(
        draw,
        (x0 + MARGIN_PAD_X, qy),
        quote_text,
        quote_font,
        quote_w,
        max_lines=2,
        line_spacing=line_spacing,
        fill=ink,
    )
    ax = x0 + w - MARGIN_PAD_X - (author_bb[2] - author_bb[0]) - author_bb[0]
    draw.text((ax, ay), author_text, font=author_font, fill=secondary)
