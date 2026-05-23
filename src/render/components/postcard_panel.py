"""Full-canvas dithered postcard component for the ``postcard`` theme.

The composition is a divided rectangle:

  ┌─────────────────────────────────┬──────────────────────────────────┐
  │                                 │  Greeting (Playfair italic)      │
  │   Procedural dithered scene     │  ────────────────────────────    │
  │   (sky + horizon + landscape    │  POSTMARK    [ STAMP w/ MOON ]   │
  │   + foreground), keyed to the   │                                  │
  │   weather icon and daypart.     │  TODAY  •  May 23, 2026          │
  │                                 │  9:00a  TEAM STANDUP             │
  │   Floyd-Steinberg-dithered      │  12:30p LUNCH WITH SARA          │
  │   greyscale gradients become    │  2:00p  DENTIST                  │
  │   engraving on Waveshare;       │  6:00p  YOGA — STUDIO 12         │
  │   stay grey on Inky RGB so the  │                                  │
  │   stamp's red accent reads.     │  "Wish you were here"            │
  │                                 │   — quote / signature            │
  └─────────────────────────────────┴──────────────────────────────────┘

Drawing happens at L-mode (8-bit greyscale) by default; on Inky RGB
canvases the same greyscale values are emitted as ``(v, v, v)`` triples
plus a warm red accent for the postmark and stamp border, so the eInk
panel's color story stays consistent with the rest of the dashboard.

The scene is generated entirely from PIL primitives — no external
asset paths — so the component is fully offline and deterministic for
a given date + weather icon.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime
from functools import lru_cache

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DashboardData
from src.render.components.info_panel import _quote_for_today
from src.render.moon import is_waxing, moon_illumination
from src.render.primitives import (
    draw_text_truncated,
    draw_text_wrapped,
    events_for_day,
    text_height,
    wrap_lines,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_RED, ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Geometry — postcard is split at SCENE_W; everything left of it is the
# dithered view, everything right is the postcard back.
# ---------------------------------------------------------------------------

SCENE_W = 480
BACK_X = SCENE_W
BACK_PAD_X = 20
BACK_PAD_Y = 18

# Centre of the scene — sun/moon, mountains etc. position relative to this.
_SCENE_CX = SCENE_W // 2
_HORIZON_Y_FRAC = 0.62


# ---------------------------------------------------------------------------
# Mode-aware colour helpers (mirrors halftone_panel)
# ---------------------------------------------------------------------------


def _grey(v: int, mode: str) -> int | tuple[int, int, int]:
    return v if mode == "L" else (v, v, v)


def _ink(mode: str) -> int | tuple[int, int, int]:
    return 0 if mode == "L" else (0, 0, 0)


def _accent_red(mode: str) -> int | tuple[int, int, int]:
    """Postmark / stamp-border accent.  Red on Inky, solid black on L mode.

    L mode collapses the accent to solid ink because mid-grey would dither
    into a noisy half-tone pattern after Floyd-Steinberg — fine for
    procedural illustration but illegible for small text and thin rules.
    """
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_RED]
    return 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_postcard(
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
    """Draw the full postcard (dithered scene + postcard back) into *region*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        image = draw._image  # type: ignore[attr-defined]

    x0, y0, w, h = region.x, region.y, region.w, region.h

    scene_rect = (x0, y0, x0 + SCENE_W, y0 + h)
    back_rect = (x0 + SCENE_W, y0, x0 + w, y0 + h)

    _draw_scene(image, scene_rect, data, today, now)
    _draw_back(
        draw,
        image,
        data,
        today,
        now,
        rect=back_rect,
        style=style,
        quote_refresh=quote_refresh,
    )
    _draw_center_crease(image, x0 + SCENE_W, y0, h)


# ---------------------------------------------------------------------------
# Scene dispatch (left panel)
# ---------------------------------------------------------------------------


def _scene_kind(icon: str | None) -> tuple[str, bool]:
    """Map an OWM icon code to ``(kind, is_night)``."""
    if not icon:
        return ("clear", False)
    code = icon[:2]
    is_night = icon[2:3] == "n"
    if code == "01":
        return ("clear", is_night)
    if code in ("02", "03"):
        return ("partly", is_night)
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
    return ("clear", is_night)


def _draw_scene(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    data: DashboardData,
    today: date,
    now: datetime,
) -> None:
    icon = data.weather.current_icon if data.weather is not None else None
    kind, is_night = _scene_kind(icon)

    _draw_sky(image, rect, kind, is_night, today, now)
    if kind == "fog":
        _draw_fog_bands(image, rect, today)
    horizon_y = rect[1] + int((rect[3] - rect[1]) * _HORIZON_Y_FRAC)
    _draw_distant_mountains(image, rect, horizon_y, today)
    _draw_water(image, rect, horizon_y, kind)
    _draw_foreground_shore(image, rect, horizon_y, today)
    if kind in ("clear", "partly") and not is_night:
        _draw_sun(image, rect, horizon_y - 60, today)
    elif kind in ("clear", "partly") and is_night:
        _draw_stars(image, rect, horizon_y, today)
        _draw_moon(image, rect, horizon_y - 70, today)
    if kind == "partly" or kind == "overcast":
        _draw_clouds(image, rect, kind, today)
    if kind == "rain" or kind == "storm":
        _draw_clouds(image, rect, "overcast", today, dark=True)
        _draw_rain_streaks(image, rect, today, heavy=(kind == "storm"))
        if kind == "storm":
            _draw_lightning(image, rect)
    if kind == "snow":
        _draw_clouds(image, rect, "overcast", today)
        _draw_snowflakes(image, rect, today)
    if kind in ("clear", "partly") and not is_night:
        _draw_birds(image, rect, today)


# ---------------------------------------------------------------------------
# Sky — vertical gradient keyed to weather + daypart
# ---------------------------------------------------------------------------


def _daypart_palette(kind: str, is_night: bool, now: datetime) -> tuple[int, int]:
    """Return ``(top_value, bottom_value)`` greyscale tones for the sky.

    The icon's day/night flag wins over local-clock hour, since the dashboard
    can render against a different timezone than ``now.tz``.  Dawn and dusk
    soften the top of the sky relative to midday; overcast / storm / rain /
    snow / fog conditions compress the range so the sky reads as a heavy,
    neutral grey regardless of daypart.
    """
    hour = now.hour + now.minute / 60.0
    if is_night:
        base = (35, 95)
    elif 5.0 <= hour < 7.5:
        # Dawn — soft grey-white sky with a brighter eastern horizon.
        base = (180, 245)
    elif 17.0 <= hour < 19.5:
        # Dusk — top deepens, horizon catches a glow.
        base = (155, 235)
    else:
        # Default day — bright sky, slightly darker at the zenith.
        base = (218, 248)

    if kind == "overcast":
        return (max(base[0], 150), max(base[1], 195))
    if kind == "storm":
        return (110, 165)
    if kind == "rain":
        return (135, 190)
    if kind == "snow":
        return (175, 225)
    if kind == "fog":
        return (190, 220)
    return base


def _draw_sky(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    kind: str,
    is_night: bool,
    today: date,
    now: datetime,
) -> None:
    x0, y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - y0
    horizon_y = int(h * _HORIZON_Y_FRAC)
    top, bottom = _daypart_palette(kind, is_night, now)
    strip = Image.new("L", (1, h))
    for i in range(h):
        if i < horizon_y:
            t = i / max(1, horizon_y - 1)
            strip.putpixel((0, i), int(top + (bottom - top) * t))
        else:
            # Below the horizon the water gets its own gradient — but
            # painting the full strip first means horizon-aligned helpers
            # can rely on a clean base behind their own shading.
            strip.putpixel((0, i), bottom)
    full = strip.resize((w, h), Image.Resampling.NEAREST)
    if image.mode == "RGB":
        full = full.convert("RGB")
    image.paste(full, (x0, y0))


# ---------------------------------------------------------------------------
# Mountains, water, foreground silhouettes
# ---------------------------------------------------------------------------


def _draw_distant_mountains(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    horizon_y: int,
    today: date,
) -> None:
    """Two ridge layers behind the horizon — fainter and farther one in back."""
    x0, _y0, x1, _y1 = rect
    mode = image.mode
    draw = ImageDraw.Draw(image)
    rng = random.Random(today.toordinal() ^ 0x4D43)

    # Far ridge — gentle grey silhouette.
    far_tone = _grey(155, mode)
    far_points: list[tuple[int, int]] = []
    far_points.append((x0, horizon_y))
    span = x1 - x0
    step = 20
    x = x0
    while x <= x1:
        amplitude = rng.randint(8, 26)
        y = horizon_y - amplitude
        far_points.append((x, y))
        x += step + rng.randint(-4, 4)
    far_points.append((x1, horizon_y))
    far_points.append((x1, horizon_y + 2))
    far_points.append((x0, horizon_y + 2))
    draw.polygon(far_points, fill=far_tone)

    # Near ridge — slightly taller, slightly darker.
    near_tone = _grey(95, mode)
    near_points = [(x0, horizon_y)]
    # Build a small palette of "peaks" to sample from.
    n_peaks = 4
    peak_width = span / n_peaks
    for i in range(n_peaks):
        # Start of peak base
        bx = int(x0 + i * peak_width)
        near_points.append((bx, horizon_y))
        # Peak summit
        peak_h = rng.randint(28, 60)
        peak_x = int(bx + peak_width * 0.5 + rng.randint(-12, 12))
        near_points.append((peak_x, horizon_y - peak_h))
    near_points.append((x1, horizon_y))
    near_points.append((x1, horizon_y + 4))
    near_points.append((x0, horizon_y + 4))
    draw.polygon(near_points, fill=near_tone)


def _draw_water(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    horizon_y: int,
    kind: str,
) -> None:
    """Vertical greyscale gradient with horizontal ripple lines."""
    x0, _y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - horizon_y
    mode = image.mode
    if h <= 0:
        return
    # Slightly darker than the sky for clear/partly conditions; rain-style
    # conditions compress the range so the water reads heavy and turbid.
    if kind in ("rain", "storm"):
        top, bottom = 110, 160
    elif kind == "snow":
        top, bottom = 200, 235
    elif kind == "fog":
        top, bottom = 205, 220
    elif kind == "overcast":
        top, bottom = 180, 215
    else:
        top, bottom = 165, 215
    strip = Image.new("L", (1, h))
    for i in range(h):
        t = i / max(1, h - 1)
        strip.putpixel((0, i), int(top + (bottom - top) * t))
    full = strip.resize((w, h), Image.Resampling.NEAREST)
    if mode == "RGB":
        full = full.convert("RGB")
    image.paste(full, (x0, horizon_y))

    # Subtle horizontal ripple lines — fewer near the horizon, more density
    # toward the foreground for a perspective hint.
    draw = ImageDraw.Draw(image)
    ripple_fill = _grey(95, mode)
    n_ripples = 12
    for i in range(n_ripples):
        t = i / max(1, n_ripples - 1)
        y = horizon_y + int(t * t * (h - 6)) + 3
        # Stagger left/right gaps so it looks like rippling water.
        gaps = 5 + i % 4
        seg_w = (w - 40) // gaps
        x = x0 + 20 + (i * 9) % 24
        for g in range(gaps):
            sx = x + g * seg_w
            sw = max(8, seg_w - 12 - (g % 3) * 4)
            draw.line([(sx, y), (sx + sw, y)], fill=ripple_fill, width=1)


def _draw_foreground_shore(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    horizon_y: int,
    today: date,
) -> None:
    """A dark, organic shore curve anchored at the bottom of the scene."""
    x0, _y0, x1, y1 = rect
    mode = image.mode
    draw = ImageDraw.Draw(image)
    rng = random.Random(today.toordinal() ^ 0xF0E1)
    shore_top = y1 - 70
    if shore_top <= horizon_y:
        return
    # Build a wavy top edge.
    points: list[tuple[int, int]] = []
    step = 14
    x = x0
    while x <= x1:
        amp = rng.randint(2, 9)
        y = shore_top + rng.randint(-amp, amp)
        points.append((x, y))
        x += step
    points.append((x1, shore_top))
    points.append((x1, y1))
    points.append((x0, y1))
    draw.polygon(points, fill=_grey(30, mode))

    # Add a few darker pebble/reed accents on the shore.
    pebble_fill = _ink(mode)
    for _ in range(18):
        px = rng.randint(x0 + 10, x1 - 10)
        py = rng.randint(shore_top + 6, y1 - 6)
        r = rng.choice((1, 1, 2))
        draw.ellipse((px - r, py - r, px + r, py + r), fill=pebble_fill)
    # A few thin reed strokes.
    for _ in range(7):
        rx = rng.randint(x0 + 20, x1 - 20)
        rh = rng.randint(14, 28)
        draw.line([(rx, shore_top - rh), (rx, shore_top + 4)], fill=pebble_fill, width=1)


# ---------------------------------------------------------------------------
# Sun / moon / stars / clouds / weather effects
# ---------------------------------------------------------------------------


def _draw_sun(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    cy: int,
    today: date,
) -> None:
    """Draw a sun disc with a defined dark ring + rays so it reads against bright sky."""
    x0, y0, x1, _y1 = rect
    cx = x0 + (x1 - x0) // 3  # left third of scene
    radius = 32
    mode = image.mode
    draw = ImageDraw.Draw(image)
    # Eight engraving-style rays — short triangular spokes that read clearly
    # against a bright sky once Floyd-Steinberg has done its work.
    for i in range(16):
        a = (i / 16.0) * 2 * math.pi - math.pi / 2
        long_ray = i % 2 == 0
        length = radius + (28 if long_ray else 14)
        half_w = math.radians(4 if long_ray else 2)
        inner_r = radius + 2
        x_tip = cx + math.cos(a) * length
        y_tip = cy + math.sin(a) * length
        x_a = cx + math.cos(a - half_w) * inner_r
        y_a = cy + math.sin(a - half_w) * inner_r
        x_b = cx + math.cos(a + half_w) * inner_r
        y_b = cy + math.sin(a + half_w) * inner_r
        draw.polygon([(x_tip, y_tip), (x_a, y_a), (x_b, y_b)], fill=_ink(mode))
    # Sun disc — pale interior with a defined dark outline ring.
    disc = _radial_gradient_disc(radius * 2 + 1, inner_v=255, outer_v=215)
    target_xy = (cx - radius, cy - radius)
    if mode == "RGB":
        image.paste(disc.convert("RGB"), target_xy, disc.split()[1])
    else:
        image.paste(disc, target_xy, disc.split()[1])
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=_ink(mode),
        width=2,
    )


@lru_cache(maxsize=8)
def _radial_gradient_disc(d: int, inner_v: int, outer_v: int) -> Image.Image:
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
            t = (r / rad) if rad > 0 else 0.0
            t = t * t
            v = int(inner_v + (outer_v - inner_v) * t)
            px[x, y] = (v, 255)
    return out


def _draw_moon(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    cy: int,
    today: date,
) -> None:
    x0, _y0, x1, _y1 = rect
    cx = x0 + (x1 - x0) // 3
    radius = 32
    illum = moon_illumination(today)
    disc = _moon_disc(radius * 2 + 1, illum, is_waxing(today))
    target_xy = (cx - radius, cy - radius)
    mode = image.mode
    if mode == "RGB":
        image.paste(disc.convert("RGB"), target_xy, disc.split()[1])
    else:
        image.paste(disc, target_xy, disc.split()[1])


@lru_cache(maxsize=32)
def _moon_disc(d: int, illumination_pct: float, waxing: bool) -> Image.Image:
    out = Image.new("LA", (d, d), (0, 0))
    cx = cy = (d - 1) / 2.0
    R = (d - 1) / 2.0
    phase = max(0.0, min(1.0, illumination_pct / 100.0))
    term_x_rel = (1.0 - 2.0 * phase) * R
    soft_px = 4.0
    px = out.load()
    for y in range(d):
        for x in range(d):
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy > R * R:
                continue
            if waxing:
                signed = dx - term_x_rel
            else:
                signed = -(dx + term_x_rel)
            t = max(-1.0, min(1.0, signed / soft_px))
            lit = (t + 1.0) * 0.5
            v = int(70 + (245 - 70) * lit)
            px[x, y] = (v, 255)
    return out


def _draw_stars(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    horizon_y: int,
    today: date,
) -> None:
    x0, y0, x1, _y1 = rect
    draw = ImageDraw.Draw(image)
    rng = random.Random(today.toordinal() ^ 0xA17E)
    mode = image.mode
    for _ in range(70):
        x = rng.randint(x0 + 4, x1 - 4)
        y = rng.randint(y0 + 8, horizon_y - 20)
        bright = rng.choice((220, 240, 255, 200))
        draw.point((x, y), fill=_grey(bright, mode))


def _draw_clouds(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    kind: str,
    today: date,
    *,
    dark: bool = False,
) -> None:
    """Two to four overlapping cloud ellipses up in the sky band."""
    x0, y0, x1, _y1 = rect
    horizon_y = y0 + int((rect[3] - rect[1]) * _HORIZON_Y_FRAC)
    rng = random.Random(today.toordinal() ^ 0xC10D)
    if kind == "overcast":
        n_clouds = 4
        scale = 1.05
    else:
        n_clouds = 2
        scale = 0.95
    # Vertical band: keep clouds clear of the top and horizon by a margin so
    # they never clip against the canvas edge.
    band_top = y0 + 50
    band_bot = horizon_y - 60
    for _ in range(n_clouds):
        cx = rng.randint(x0 + 80, x1 - 80)
        cy = rng.randint(band_top, max(band_top + 10, band_bot))
        _draw_one_cloud(image, cx, cy, scale=scale * rng.uniform(0.8, 1.2), dark=dark)


def _draw_one_cloud(
    image: Image.Image,
    cx: int,
    cy: int,
    *,
    scale: float = 1.0,
    dark: bool = False,
) -> None:
    """Composite a soft cloud (union of ellipses) centred at *(cx, cy)*."""
    base_w = int(140 * scale)
    base_h = int(60 * scale)
    pad = 6
    bw = base_w + pad * 2
    bh = base_h + pad * 2
    mask = Image.new("L", (bw, bh), 0)
    mdraw = ImageDraw.Draw(mask)
    s = scale
    lobes = [
        (int(30 * s), int(40 * s), int(22 * s)),
        (int(60 * s), int(25 * s), int(28 * s)),
        (int(95 * s), int(32 * s), int(26 * s)),
        (int(115 * s), int(45 * s), int(20 * s)),
        (int(70 * s), int(50 * s), int(24 * s)),
    ]
    for lx, ly, lr in lobes:
        mdraw.ellipse(
            (pad + lx - lr, pad + ly - lr, pad + lx + lr, pad + ly + lr),
            fill=255,
        )
    if dark:
        top, bottom = 95, 55
    else:
        top, bottom = 250, 200
    strip = Image.new("L", (1, bh))
    for y in range(bh):
        t = y / max(1, bh - 1)
        strip.putpixel((0, y), int(top + (bottom - top) * t))
    interior = strip.resize((bw, bh), Image.Resampling.NEAREST)
    if image.mode == "RGB":
        interior = interior.convert("RGB")
    image.paste(interior, (cx - bw // 2, cy - bh // 2), mask)


def _draw_rain_streaks(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    today: date,
    *,
    heavy: bool = False,
) -> None:
    x0, y0, x1, y1 = rect
    horizon_y = y0 + int((y1 - y0) * _HORIZON_Y_FRAC)
    draw = ImageDraw.Draw(image)
    mode = image.mode
    rng = random.Random(today.toordinal() ^ 0xBEEF)
    count = 360 if heavy else 220
    streak_fill = _grey(85 if heavy else 110, mode)
    for _ in range(count):
        x = rng.randint(x0 + 4, x1 - 4)
        y = rng.randint(y0 + 20, horizon_y - 4)
        length = rng.randint(6, 12)
        slant = rng.choice((-3, -2, -1))
        draw.line([(x, y), (x + slant, y + length)], fill=streak_fill, width=1)


def _draw_snowflakes(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    today: date,
) -> None:
    x0, y0, x1, y1 = rect
    horizon_y = y0 + int((y1 - y0) * _HORIZON_Y_FRAC)
    draw = ImageDraw.Draw(image)
    mode = image.mode
    rng = random.Random(today.toordinal() ^ 0x5577)
    fill = _ink(mode)
    for _ in range(150):
        x = rng.randint(x0 + 4, x1 - 4)
        y = rng.randint(y0 + 14, horizon_y - 4)
        r = rng.choice((1, 1, 2))
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _draw_lightning(
    image: Image.Image,
    rect: tuple[int, int, int, int],
) -> None:
    x0, y0, x1, y1 = rect
    horizon_y = y0 + int((y1 - y0) * _HORIZON_Y_FRAC)
    cx = x0 + (x1 - x0) // 2
    top = y0 + 60
    h = horizon_y - top
    draw = ImageDraw.Draw(image)
    mode = image.mode
    points = [
        (cx + 10, top),
        (cx - 4, top + int(h * 0.30)),
        (cx + 6, top + int(h * 0.38)),
        (cx - 10, top + int(h * 0.76)),
        (cx + 4, top + int(h * 0.50)),
        (cx - 4, top + int(h * 0.44)),
        (cx + 14, top + int(h * 0.10)),
    ]
    draw.polygon(points, fill=_ink(mode))


def _draw_fog_bands(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    today: date,
) -> None:
    x0, y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - y0
    rng = random.Random(today.toordinal() ^ 0xF06A)
    band_count = 6
    band_h = max(1, h // band_count // 2)
    for i in range(band_count):
        tone = rng.randint(185, 230)
        y = y0 + int(i * (h / band_count)) + rng.randint(-4, 4)
        band = Image.new("L", (w + 60, band_h + 2), tone)
        if image.mode == "RGB":
            band = band.convert("RGB")
        image.paste(band, (x0 - 30 + rng.randint(-20, 20), y))


def _draw_birds(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    today: date,
) -> None:
    """Three or four tiny v-shapes drifting in the upper sky."""
    x0, y0, x1, _y1 = rect
    horizon_y = y0 + int((rect[3] - rect[1]) * _HORIZON_Y_FRAC)
    draw = ImageDraw.Draw(image)
    mode = image.mode
    rng = random.Random(today.toordinal() ^ 0xB19D)
    fill = _ink(mode)
    n = rng.randint(3, 5)
    for _ in range(n):
        bx = rng.randint(x0 + 40, x1 - 40)
        by = rng.randint(y0 + 30, max(y0 + 35, horizon_y - 80))
        span = rng.randint(6, 10)
        draw.line([(bx - span, by + span // 2), (bx, by)], fill=fill, width=1)
        draw.line([(bx, by), (bx + span, by + span // 2)], fill=fill, width=1)


# ---------------------------------------------------------------------------
# Centre crease — vertical line between scene + back
# ---------------------------------------------------------------------------


def _draw_center_crease(
    image: Image.Image,
    x: int,
    y0: int,
    h: int,
) -> None:
    """A thin dashed centre line — the crease where the postcard would fold.

    A two-pixel white gutter sits between the dithered scene and the crease
    so the crease reads cleanly against the dark side too.
    """
    mode = image.mode
    draw = ImageDraw.Draw(image)
    # White gutter band (3 px wide) so the crease reads cleanly against the
    # dark dithered scene.
    gutter = _grey(255, mode)
    draw.rectangle((x - 3, y0, x - 1, y0 + h), fill=gutter)
    # Solid hairline on the boundary.
    draw.line([(x, y0), (x, y0 + h)], fill=_ink(mode), width=1)
    # Dashed inner shadow on the postcard-back side, suggests the printed edge.
    shadow = _grey(150, mode)
    yy = y0 + 6
    while yy < y0 + h - 6:
        draw.line([(x + 2, yy), (x + 2, yy + 5)], fill=shadow, width=1)
        yy += 9


# ---------------------------------------------------------------------------
# Postcard back (right panel)
# ---------------------------------------------------------------------------


def _events_today(events: list[CalendarEvent], today: date) -> list[CalendarEvent]:
    """Today's events, sorted (all-day first, then by start)."""
    return events_for_day(events, today)


def _fmt_event_time(dt: datetime) -> str:
    """Compact am/pm time, lowercase: e.g. ``9a``, ``2:30p``."""
    if dt.minute == 0:
        s = dt.strftime("%-I%p")
    else:
        s = dt.strftime("%-I:%M%p")
    return s.lower().replace("am", "a").replace("pm", "p")


def _draw_back(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    rect: tuple[int, int, int, int],
    style: ThemeStyle,
    quote_refresh: str,
) -> None:
    """Paint the right-panel postcard back: greeting, postmark, stamp, agenda, quote."""
    mode = image.mode
    x0, y0, x1, y1 = rect
    # Clean paper background so the dithered scene never bleeds in.
    paper = Image.new("L", (x1 - x0, y1 - y0), 255)
    if mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x0, y0))

    ink = _ink(mode)
    red = _accent_red(mode)

    inner_x0 = x0 + BACK_PAD_X
    inner_x1 = x1 - BACK_PAD_X
    inner_w = inner_x1 - inner_x0

    # --- Greeting (Playfair regular, solid ink so it doesn't fuzz after dither).
    greeting_font = style.font_semibold(20) if style.font_semibold else style.font_bold(20)
    greeting = "Greetings from today —"
    draw.text((inner_x0, y0 + BACK_PAD_Y), greeting, font=greeting_font, fill=ink)

    # --- Postmark (circular stamp) + Stamp (rectangular, with moon glyph)
    stamp_top = y0 + 64
    _draw_postmark(image, draw, inner_x0, stamp_top, today, mode=mode, red=red, ink=ink)
    _draw_stamp(
        image, draw, inner_x1 - 90, stamp_top, today, mode=mode, red=red, ink=ink, style=style
    )

    # --- Dividing rule under the stamps — solid black for a crisp boundary.
    rule_y = stamp_top + 94
    draw.line([(inner_x0, rule_y), (inner_x1, rule_y)], fill=ink, width=1)

    # --- Address-line agenda (today's events)
    label_font = style.font_section_label(13)
    label = f"TODAY  ·  {today.strftime('%a %b %-d').upper()}"
    draw.text((inner_x0, rule_y + 6), label, font=label_font, fill=ink)

    agenda_top = rule_y + 30
    events = _events_today(data.events, today)
    _draw_address_lines(
        draw,
        events,
        x0=inner_x0,
        y0=agenda_top,
        w=inner_w,
        style=style,
        ink=ink,
        red=red,
        mode=mode,
    )

    # --- Quote at the bottom — solid ink, larger Playfair body for legibility.
    quote = _quote_for_today(today, refresh=quote_refresh, now=now)
    quote_font = style.font_quote(15) if style.font_quote else style.font_regular(15)
    author_font = (
        style.font_quote_author(12) if style.font_quote_author else style.font_semibold(12)
    )
    quote_text = f"“{quote['text']}”"
    author_text = f"— {quote['author']}"
    quote_w = inner_w
    line_h = text_height(quote_font)
    lines = wrap_lines(quote_text, quote_font, quote_w)[:3]
    line_spacing = 2
    author_bb = draw.textbbox((0, 0), author_text, font=author_font)
    author_h = author_bb[3] - author_bb[1]
    bottom_pad = 12
    block_h = line_h * len(lines) + line_spacing * max(0, len(lines) - 1)
    ay = y1 - bottom_pad - author_h - author_bb[1]
    qy = y1 - bottom_pad - author_h - 4 - block_h
    draw_text_wrapped(
        draw,
        (inner_x0, qy),
        quote_text,
        quote_font,
        quote_w,
        max_lines=3,
        line_spacing=line_spacing,
        fill=ink,
    )
    ax = inner_x1 - (author_bb[2] - author_bb[0]) - author_bb[0]
    draw.text((ax, ay), author_text, font=author_font, fill=red)


def _draw_postmark(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    today: date,
    *,
    mode: str,
    red,
    ink,
) -> None:
    """Circular postmark with date text in two arcs."""
    r = 32
    cx, cy = x + r, y + r
    # Concentric red rings — two outer, one inner.
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=red, width=2)
    inner_r = r - 6
    draw.ellipse(
        (cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r),
        outline=red,
        width=1,
    )
    # Three wavy "cancellation" lines extending right from the postmark.
    wave_top = cy - 6
    wave_w = 96
    for i, dy in enumerate((-6, 0, 6)):
        # Slightly different phase each line for that "rolling cancel" look.
        wy = wave_top + dy + 6
        # Draw a sequence of short segments forming a sine wave.
        prev = None
        for j in range(0, wave_w, 3):
            xv = cx + r + 4 + j
            yv = int(wy + math.sin((j + i * 4) * 0.25) * 2)
            if prev is not None:
                draw.line([prev, (xv, yv)], fill=red, width=1)
            prev = (xv, yv)

    # Date inside the postmark — day numeral (big) over month abbrev (small caps).
    from src.render import fonts as _fonts

    day_font = _fonts.cinzel_bold(22)
    month_font = _fonts.cinzel_semibold(12)
    month_txt = today.strftime("%b").upper()
    day_txt = today.strftime("%-d")
    db = draw.textbbox((0, 0), day_txt, font=day_font)
    mb = draw.textbbox((0, 0), month_txt, font=month_font)
    dx = cx - (db[2] - db[0]) // 2 - db[0]
    dy = cy - (db[3] - db[1]) // 2 - db[1] - 2
    draw.text((dx, dy), day_txt, font=day_font, fill=red)
    mx = cx - (mb[2] - mb[0]) // 2 - mb[0]
    my = cy + (db[3] - db[1]) // 2 - 2
    draw.text((mx, my), month_txt, font=month_font, fill=red)


def _draw_stamp(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    today: date,
    *,
    mode: str,
    red,
    ink,
    style: ThemeStyle,
) -> None:
    """Rectangular postage stamp with perforated edges + moon glyph + illumination %."""
    w = 86
    h = 96
    # Outer perforation: a series of tiny ellipses around the edge.
    pitch = 6
    for px in range(x, x + w + 1, pitch):
        draw.ellipse((px - 2, y - 3, px + 2, y + 1), fill=red)
        draw.ellipse((px - 2, y + h - 1, px + 2, y + h + 3), fill=red)
    for py in range(y, y + h + 1, pitch):
        draw.ellipse((x - 3, py - 2, x + 1, py + 2), fill=red)
        draw.ellipse((x + w - 1, py - 2, x + w + 3, py + 2), fill=red)
    # Inner stamp border.
    pad = 5
    inner = (x + pad, y + pad, x + w - pad, y + h - pad)
    draw.rectangle(inner, outline=red, width=2)

    # Moon glyph centred in the upper portion.
    from src.render import fonts as _fonts
    from src.render.moon import moon_illumination, moon_phase_glyph

    glyph_font = _fonts.weather_icon(42)
    glyph = moon_phase_glyph(today)
    gb = draw.textbbox((0, 0), glyph, font=glyph_font)
    cx = x + w // 2
    gx = cx - (gb[2] - gb[0]) // 2 - gb[0]
    gy = y + 10 - gb[1]
    draw.text((gx, gy), glyph, font=glyph_font, fill=ink)

    # Bottom: illumination percent (always short) in solid Cinzel caps so it
    # stays legible after Floyd-Steinberg.
    illum = moon_illumination(today)
    pct_font = _fonts.cinzel_bold(14)
    pct = f"{int(round(illum))}%"
    pb = draw.textbbox((0, 0), pct, font=pct_font)
    px_ = cx - (pb[2] - pb[0]) // 2 - pb[0]
    py_ = y + h - pad - (pb[3] - pb[1]) - 4 - pb[1]
    draw.text((px_, py_), pct, font=pct_font, fill=ink)


def _draw_address_lines(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    *,
    x0: int,
    y0: int,
    w: int,
    style: ThemeStyle,
    ink,
    red,
    mode: str,
) -> None:
    """Stack of address lines: time gutter + summary + ruled underline.

    Body text is solid ink and the underline rules are a darker mid-grey
    (60) — barely affected by Floyd-Steinberg quantization but visually
    softer than the body text so the rules read as "address lines" rather
    than as primary content.
    """
    time_font = style.font_section_label(14)
    body_font = style.font_semibold(17) if style.font_semibold else style.font_regular(17)
    rule_fill = _grey(60, mode)
    line_h = 30
    max_rows = 5
    rows = events[:max_rows]

    if not rows:
        for i in range(4):
            ly = y0 + i * line_h + 22
            draw.line([(x0, ly), (x0 + w, ly)], fill=rule_fill, width=1)
        empty_label = "( nothing scheduled )"
        draw.text((x0, y0 + 2), empty_label, font=body_font, fill=ink)
        return

    gutter_w = 70
    for i, ev in enumerate(rows):
        ly = y0 + i * line_h
        rule_y = ly + line_h - 4
        draw.line([(x0, rule_y), (x0 + w, rule_y)], fill=rule_fill, width=1)
        if ev.is_all_day:
            time_txt = "ALL DAY"
        else:
            time_txt = _fmt_event_time(ev.start).upper()
        draw.text((x0, ly + 4), time_txt, font=time_font, fill=red)
        draw_text_truncated(
            draw,
            (x0 + gutter_w, ly + 2),
            ev.summary,
            body_font,
            w - gutter_w,
            fill=ink,
        )
    extra = len(events) - len(rows)
    if extra > 0:
        ly = y0 + len(rows) * line_h
        draw.text((x0, ly + 2), f"+{extra} more", font=body_font, fill=ink)
