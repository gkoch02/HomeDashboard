"""Procedural lake-and-mountains view for the ``postcard`` theme.

The scene is painted as a float greyscale field (0 = ink, 255 = paper) with
numpy, then handed back as an ``"L"`` image for the Floyd-Steinberg quantize to
engrave.  Everything is keyed to three inputs:

* the **date** seeds the landscape, so the ridges, trees and clouds change
  daily but stay put for the rest of the day;
* the **weather icon** picks the conditions (clear, partly cloudy, overcast,
  rain, storm, snow, fog) and the icon's day/night flag;
* the **hour** places the sun on an arc between sunrise and sunset, so the
  scene runs from a low dawn glow through midday to a backlit golden hour.
  The hour is floored, so the image changes at most once an hour.

Depth comes from aerial perspective: four ridge layers fade toward the sky's
horizon tone with distance, and the lake mirrors everything above it with
rippled distortion.  The foreground banks and pines stay near-solid ink so the
composition holds its shape on a 1-bit panel.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from src.render.moon import is_waxing, moon_illumination

SS = 2  # supersample factor of the postcard canvas
HORIZON_FRAC = 0.60

# Fallback sun times (local hours) when the weather carries none.
_DEFAULT_SUNRISE = 6.5
_DEFAULT_SUNSET = 19.0
# Snow lies above this height, as a fraction of the sky above the horizon.
_SNOWLINE = 0.40
# Below this elevation (0..1 of the arc's peak) the light turns golden.
_GOLDEN_ALT = 0.18

# (zenith, horizon) tones per condition, for day / golden hour / night.
_SKY_TONES: dict[str, dict[str, tuple[float, float]]] = {
    "clear": {"day": (204, 248), "golden": (78, 252), "night": (8, 100)},
    "partly": {"day": (178, 246), "golden": (78, 250), "night": (10, 100)},
    "overcast": {"day": (176, 218), "golden": (150, 218), "night": (34, 92)},
    "rain": {"day": (92, 172), "golden": (80, 176), "night": (30, 112)},
    "storm": {"day": (50, 130), "golden": (46, 134), "night": (20, 96)},
    "snow": {"day": (168, 214), "golden": (150, 216), "night": (48, 104)},
    "fog": {"day": (206, 240), "golden": (196, 240), "night": (58, 108)},
}


@dataclass(frozen=True)
class Light:
    """Where the light comes from: daypart, sun position and elevation."""

    phase: str  # "day" | "golden" | "night"
    sun_x: float  # 0..1 across the scene; the sun rises on the left
    sun_alt: float  # 0..1 elevation, 0 at the horizon


def scene_kind(icon: str | None) -> tuple[str, bool]:
    """Map an OWM icon code to ``(kind, is_night)``."""
    if not icon:
        return ("clear", False)
    code = icon[:2]
    is_night = icon[2:3] == "n"
    kinds = {
        "01": "clear",
        "02": "partly",
        "03": "partly",
        "04": "overcast",
        "09": "rain",
        "10": "rain",
        "11": "storm",
        "13": "snow",
        "50": "fog",
    }
    return (kinds.get(code, "clear"), is_night)


def _hours(dt: datetime) -> float:
    return dt.hour + dt.minute / 60.0


def light_for(
    now: datetime,
    is_night: bool,
    sunrise: datetime | None = None,
    sunset: datetime | None = None,
) -> Light:
    """Return the scene's light for the hour holding *now*.

    The icon's night flag wins over the clock, since the dashboard can render
    in a different timezone than the weather station.  A day icon outside the
    sunrise–sunset span pins the sun to the nearer horizon.
    """
    if is_night:
        return Light("night", 0.7, 0.0)
    rise = _hours(sunrise) if sunrise is not None else _DEFAULT_SUNRISE
    down = _hours(sunset) if sunset is not None else _DEFAULT_SUNSET
    if down - rise < 1.0:
        rise, down = _DEFAULT_SUNRISE, _DEFAULT_SUNSET
    # Middle of the hour, so the hour's render is representative of all of it.
    t = now.hour + 0.5
    frac = min(1.0, max(0.0, (t - rise) / (down - rise)))
    alt = math.sin(math.pi * frac)
    phase = "golden" if alt < _GOLDEN_ALT else "day"
    return Light(phase, 0.14 + 0.72 * frac, alt)


# Deterministic transcendentals
#
# numpy dispatches exp / sin / pow to SIMD kernels chosen per CPU, which can
# differ in the last ulp between machines; after the dither one flipped pixel
# changes the snapshot hash.  These tables are built once with scalar ``math``
# and read through ``np.interp``, which is plain arithmetic.

_EXP_X = np.linspace(-40.0, 0.0, 40 * 512 + 1)
_EXP_Y = np.array([math.exp(v) for v in _EXP_X])
_SIN_X = np.linspace(0.0, 2 * math.pi, 8193)
_SIN_Y = np.array([math.sin(v) for v in _SIN_X])
_UNIT = np.linspace(0.0, 1.0, 4097)


def _exp(x: np.ndarray) -> np.ndarray:
    """``e**x`` for ``x <= 0`` (larger arguments clamp to 1)."""
    return np.interp(x, _EXP_X, _EXP_Y).astype(np.float32)


def _sin(x: np.ndarray) -> np.ndarray:
    return np.interp(np.mod(x, 2 * math.pi), _SIN_X, _SIN_Y).astype(np.float32)


@lru_cache(maxsize=8)
def _pow_table(p: float) -> np.ndarray:
    return np.array([v**p for v in _UNIT])


def _pow(x: np.ndarray, p: float) -> np.ndarray:
    """``x**p`` for ``x`` in 0..1."""
    return np.interp(x, _UNIT, _pow_table(p)).astype(np.float32)


def _dist(dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    return np.sqrt(dx * dx + dy * dy)


# Noise


def _fbm(
    rng: np.random.Generator,
    w: int,
    h: int,
    cells: tuple[int, int],
    octaves: int = 5,
    gain: float = 0.5,
) -> np.ndarray:
    """Fractal value noise in 0..1, *cells* ``(x, y)`` knots at the base octave."""
    total = np.zeros((h, w), dtype=np.float32)
    amp = 1.0
    cx, cy = cells
    for _ in range(octaves):
        grid = rng.random((cy + 1, cx + 1), dtype=np.float32)
        layer = Image.fromarray(grid, "F").resize((w, h), Image.Resampling.BICUBIC)
        total += amp * np.asarray(layer, dtype=np.float32)
        amp *= gain
        cx *= 2
        cy *= 2
    lo, hi = float(np.min(total)), float(np.max(total))
    return (total - lo) / max(1e-6, hi - lo)


def _noise_1d(
    rng: np.random.Generator, w: int, cells: int, octaves: int = 6, gain: float = 0.5
) -> np.ndarray:
    """Piecewise-linear fractal noise in -1..1; linear knots read as rock facets."""
    xs = np.arange(w, dtype=np.float32)
    total = np.zeros(w, dtype=np.float32)
    amp = 1.0
    norm = 0.0
    n = cells
    for _ in range(octaves):
        knots = rng.random(n + 1, dtype=np.float32) * 2.0 - 1.0
        total += amp * np.interp(xs, np.linspace(0, w - 1, n + 1), knots).astype(np.float32)
        norm += amp
        amp *= gain
        n *= 2
    return total / norm


def _smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _blur(a: np.ndarray, radius: float) -> np.ndarray:
    """Gaussian-blur a 0..1 mask (through an 8-bit plate, which Pillow can blur)."""
    img = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8), "L")
    return np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255.0


def _mask(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    m = Image.new("L", (w, h), 0)
    return m, ImageDraw.Draw(m)


def _as_alpha(m: Image.Image) -> np.ndarray:
    return np.asarray(m, dtype=np.float32) / 255.0


def _over(field: np.ndarray, tone: float | np.ndarray, alpha: np.ndarray) -> None:
    """Composite *tone* over *field* in place through *alpha* (0..1)."""
    field *= 1.0 - alpha
    field += alpha * tone


# Scene


def render_scene(
    w: int,
    h: int,
    *,
    kind: str,
    light: Light,
    today: date,
) -> Image.Image:
    """Paint the view and return it as an ``"L"`` image of ``(w, h)``."""
    rng = np.random.default_rng(today.toordinal())
    prng = random.Random(today.toordinal())
    hz = int(h * HORIZON_FRAC)
    night = light.phase == "night"
    tones = _SKY_TONES.get(kind, _SKY_TONES["clear"])[light.phase]
    sky_lit = kind in ("clear", "partly")
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # Even a rising sun clears the far ridge, so dawn and dusk show a disc.
    sun = (light.sun_x * w, hz - (0.34 + 0.50 * light.sun_alt) * hz)
    moon = (0.70 * w, hz * 0.30)

    field = _sky(w, h, hz, tones, yy, xx, kind, light, sun, moon)
    if sky_lit and night:
        _stars(field, rng, prng, w, hz, yy, xx)
    if sky_lit and not night:
        _sun_disc(field, sun, w, h, ring=light.phase == "day")
    elif sky_lit and night:
        _moon(field, rng, moon, today)
    _clouds(field, rng, w, hz, yy, kind, light, sun)

    horizon_tone = tones[1]
    ridge_ink = 12.0 if night or light.phase == "golden" else 34.0
    profiles = _mountains(field, rng, prng, w, hz, yy, xx, kind, light, horizon_tone, ridge_ink)
    if kind == "fog" or (light.phase == "golden" and kind in ("clear", "partly")):
        _valley_mist(field, rng, w, hz, yy, profiles, kind, horizon_tone)

    _lake(field, rng, prng, w, h, hz, yy, xx, kind, light, sun, moon)
    if sky_lit and not night:
        _sailboat(field, prng, w, hz, h)
    if kind == "storm":
        _lightning(field, prng, w, hz, profiles[1])
    _foreground(field, rng, prng, w, h, hz, kind, light)
    if kind in ("rain", "storm"):
        _rain(field, prng, w, h, heavy=kind == "storm")
    if kind == "snow":
        _snowfall(field, prng, w, h)
    if sky_lit and not night:
        _birds(field, prng, w, hz, sun)

    # Paper grain breaks Floyd-Steinberg's worm patterns on smooth gradients.
    field += rng.normal(0.0, 2.5, size=field.shape).astype(np.float32)
    # A soft vignette, like an old print's darkened corners.
    r2 = ((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) * 2.0
    field *= 1.0 - 0.10 * r2
    return Image.fromarray(np.clip(field, 0, 255).astype(np.uint8), "L")


def _sky(
    w: int,
    h: int,
    hz: int,
    tones: tuple[float, float],
    yy: np.ndarray,
    xx: np.ndarray,
    kind: str,
    light: Light,
    sun: tuple[float, float],
    moon: tuple[float, float],
) -> np.ndarray:
    """Vertical gradient that brightens fast near the horizon, plus glows."""
    zen, hor = tones
    s = np.clip(yy / hz, 0.0, 1.0)
    field = zen + (hor - zen) * _pow(s, 1.7)
    if kind in ("clear", "partly") and light.phase != "night":
        d = _dist(xx - sun[0], yy - sun[1])
        low = 1.0 - light.sun_alt
        field += (35 + 80 * low) * _exp(-d / (w * (0.10 + 0.12 * low)))
        if light.phase == "golden":
            # The band of bright air along the horizon on the sun's side.
            band = _exp(-np.clip(hz - yy, 0, None) / (hz * 0.22))
            side = _exp(-np.abs(xx - sun[0]) / (w * 0.55))
            field += 55 * band * side
    elif kind in ("clear", "partly"):
        d = _dist(xx - moon[0], yy - moon[1])
        field += 46 * _exp(-d / (w * 0.07))
    elif light.phase == "golden":
        # A pale seam of light under a cloud deck at dawn and dusk.
        field += 22 * _exp(-np.clip(hz - yy, 0, None) / (hz * 0.12))
    return field.astype(np.float32)


def _stars(
    field: np.ndarray,
    rng: np.random.Generator,
    prng: random.Random,
    w: int,
    hz: int,
    yy: np.ndarray,
    xx: np.ndarray,
) -> None:
    sky = (slice(0, hz), slice(0, w))
    # A faint Milky Way: mottled band on a diagonal.
    dist = np.abs((xx[sky] - 0.15 * w) * 0.55 - (yy[sky] - 0.05 * hz)) / w
    band = _exp(-((dist / 0.07) ** 2))
    mottle = _fbm(rng, w, hz, (8, 6), octaves=6)
    field[sky] += 34 * band * _smoothstep(0.35, 0.9, mottle)
    draw_m, d = _mask(w, hz)
    for _ in range(900):
        x = prng.uniform(4, w - 4)
        y = prng.uniform(4, hz - 6 * SS)
        # Haze near the horizon thins the stars out.
        if prng.random() > 1.0 - (y / hz) ** 2:
            continue
        r = prng.choice((0.6, 0.8, 1.0, 1.0, 1.4, 1.8)) * SS / 2
        v = prng.randint(150, 255)
        d.ellipse((x - r, y - r, x + r, y + r), fill=v)
    for _ in range(9):
        x = prng.uniform(30 * SS, w - 30 * SS)
        y = prng.uniform(20 * SS, hz * 0.6)
        arm = prng.uniform(5, 9) * SS
        d.line([(x - arm, y), (x + arm, y)], fill=255, width=1)
        d.line([(x, y - arm), (x, y + arm)], fill=255, width=1)
        d.ellipse((x - 1.5 * SS, y - 1.5 * SS, x + 1.5 * SS, y + 1.5 * SS), fill=255)
    a = _as_alpha(draw_m)
    field[sky] = np.maximum(field[sky], 255 * a)


def _sun_disc(field: np.ndarray, sun: tuple[float, float], w: int, h: int, *, ring: bool) -> None:
    r = 21 * SS
    sx, sy = sun
    m, d = _mask(w, h)
    d.ellipse((sx - r, sy - r, sx + r, sy + r), fill=255)
    ring_m, rd = _mask(w, h)
    # A fine engraved ring keeps the disc visible against a pale sky.
    rd.ellipse((sx - r, sy - r, sx + r, sy + r), outline=255, width=SS)
    _over(field, 255.0, _as_alpha(m))
    if ring:
        _over(field, 110.0, _as_alpha(ring_m))


def _moon(
    field: np.ndarray,
    rng: np.random.Generator,
    moon: tuple[float, float],
    today: date,
) -> None:
    r = 20 * SS
    disc = moon_disc(2 * r + 1, moon_illumination(today), is_waxing(today))
    arr = np.asarray(disc, dtype=np.float32)
    tone, alpha = arr[..., 0], arr[..., 1] / 255.0
    # Maria: darker mottling on the lit face.
    maria = tone * (0.80 + 0.20 * _fbm(rng, 2 * r + 1, 2 * r + 1, (3, 3), octaves=4))
    x0, y0 = int(moon[0]) - r, int(moon[1]) - r
    region = field[y0 : y0 + 2 * r + 1, x0 : x0 + 2 * r + 1]
    _over(region, maria, alpha)


@lru_cache(maxsize=32)
def moon_disc(d: int, illumination_pct: float, waxing: bool) -> Image.Image:
    """An ``"LA"`` moon of diameter *d* lit to *illumination_pct* on the waxing side."""
    out = Image.new("LA", (d, d), (0, 0))
    c = (d - 1) / 2.0
    radius = (d - 1) / 2.0
    phase = max(0.0, min(1.0, illumination_pct / 100.0))
    term_x = (1.0 - 2.0 * phase) * radius
    soft = 3.0 * SS
    px = out.load()
    assert px is not None
    for y in range(d):
        for x in range(d):
            dx, dy = x - c, y - c
            if dx * dx + dy * dy > radius * radius:
                continue
            signed = dx - term_x if waxing else -(dx + term_x)
            lit = (max(-1.0, min(1.0, signed / soft)) + 1.0) * 0.5
            px[x, y] = (int(48 + (250 - 48) * lit), 255)
    return out


def _clouds(
    field: np.ndarray,
    rng: np.random.Generator,
    w: int,
    hz: int,
    yy: np.ndarray,
    kind: str,
    light: Light,
    sun: tuple[float, float],
) -> None:
    sky = field[:hz]
    y = yy[:hz]
    night = light.phase == "night"
    if kind == "partly":
        dens, lit = _cumulus(rng, w, hz)
        top, base = (150.0, 50.0) if night else (255.0, 150.0)
        tone = base + (top - base) * lit
        if light.phase == "golden":
            tone = tone + 30 * _exp(-np.abs(np.arange(w) - sun[0]) / (w * 0.4))[None, :]
        _over(sky, tone, dens)
    elif kind in ("overcast", "snow"):
        n = _fbm(rng, w, hz, (2, 7), octaves=6)
        streaks = _smoothstep(0.30, 0.85, n)
        lo, hi = (30.0, 70.0) if night else (150.0, 228.0)
        _over(sky, lo + (hi - lo) * streaks, np.full_like(n, 0.80))
    elif kind in ("rain", "storm"):
        n = _fbm(rng, w, hz, (3, 4), octaves=6)
        dark = 24.0 if night else (38.0 if kind == "storm" else 70.0)
        light_v = 84.0 if night else (110.0 if kind == "storm" else 150.0)
        ceiling = 1.0 - _smoothstep(0.30 * hz, 0.78 * hz, y)
        tone = dark + (light_v - dark) * _smoothstep(0.25, 0.85, n)
        _over(sky, tone, 0.92 * ceiling)
    elif kind == "fog":
        n = _fbm(rng, w, hz, (2, 6), octaves=5)
        _over(sky, 240.0 if not night else 92.0, 0.5 * _smoothstep(0.3, 0.8, n))


def _cumulus(rng: np.random.Generator, w: int, hz: int) -> tuple[np.ndarray, np.ndarray]:
    """``(coverage, light)`` for a few cumulus, both 0..1.

    Each cloud is a heap of puffs; every puff is shaded as a sphere lit from
    above, and the higher (farther) puffs are laid down first so the nearer
    ones overlap them.  Those overlaps are what make a cumulus read as one.
    """
    alpha = np.zeros((hz, w), dtype=np.float32)
    light = np.zeros((hz, w), dtype=np.float32)
    n_clouds = int(rng.integers(3, 5))
    for k in range(n_clouds):
        cx = (k + 0.5 + rng.uniform(-0.25, 0.25)) / n_clouds * w
        base = rng.uniform(0.34, 0.50) * hz
        width = rng.uniform(0.16, 0.26) * w
        puffs = []
        for _ in range(int(rng.integers(9, 14))):
            u = rng.uniform(-0.5, 0.5)
            mid = 1.0 - abs(u) * 2.0
            r = (9 + 20 * mid) * rng.uniform(0.75, 1.15) * SS
            cy = base - r * (0.5 + 1.5 * mid * rng.uniform(0.2, 1.0))
            puffs.append((cy, cx + u * width, r))
        lo_x = int(max(0, cx - width))
        hi_x = int(min(w, cx + width))
        for cy, px, r in sorted(puffs):
            x0, x1 = int(max(0, px - r)), int(min(w, px + r + 1))
            y0, y1 = int(max(0, cy - r)), int(min(hz, cy + r + 1))
            if x0 >= x1 or y0 >= y1:
                continue
            gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
            dx, dy = (gx - px) / r, (gy - cy) / r
            inside = dx * dx + dy * dy <= 1.0
            # Bright crown, greying toward the puff's underside.
            shade = 1.0 - 0.75 * _smoothstep(-0.4, 1.0, dy)
            light[y0:y1, x0:x1] = np.where(inside, shade, light[y0:y1, x0:x1])
            alpha[y0:y1, x0:x1] = np.where(inside, 1.0, alpha[y0:y1, x0:x1])
        # Cumulus sit on a flat, shadowed base.
        alpha[int(base) :, lo_x:hi_x] = 0.0
    detail = _fbm(rng, w, hz, (24, 14), octaves=3)
    soft = _blur(alpha, 1.5 * SS)
    coverage = _smoothstep(0.30, 0.70, soft * (0.85 + 0.3 * detail))
    return coverage, light


def _mountains(
    field: np.ndarray,
    rng: np.random.Generator,
    prng: random.Random,
    w: int,
    hz: int,
    yy: np.ndarray,
    xx: np.ndarray,
    kind: str,
    light: Light,
    horizon_tone: float,
    ink: float,
) -> list[np.ndarray]:
    """Four ridges, far to near; return each ridge's crest y per column."""
    haze = {"fog": 0.30, "rain": 0.55, "storm": 0.60, "snow": 0.65, "overcast": 0.85}.get(kind, 1.0)
    # Low sun behind the range, or moonlight: the ridges read as silhouettes.
    backlit = light.phase in ("golden", "night")
    sun_dir = -1.0 if light.sun_x > 0.5 else 1.0
    # (peak height as a fraction of the sky, base knots, depth 0..1, rock texture)
    layers = [
        (0.62, 3, 0.50, True),
        (0.36, 5, 0.66, True),
        (0.17, 8, 0.80, False),
        (0.012, 0, 0.90, False),
    ]
    profiles: list[np.ndarray] = []
    for i, (peak, knots, depth, rocky) in enumerate(layers):
        if knots:
            # A low gain keeps the fine octaves from sawing the crest into teeth.
            n = (_noise_1d(rng, w, knots, gain=0.38) + 1.0) * 0.5
            # Lift the highs so a few summits stand clear of the range.
            crest = hz - peak * hz * (0.30 + 0.70 * _pow(n, 1.4))
        else:
            crest = np.full(w, hz - peak * hz, dtype=np.float32)
        crest = crest.astype(np.float32)
        inside = yy[:hz] >= crest[None, :]
        if not knots:
            # The far shore's treeline: a dense row of tiny spires.
            m, d = _mask(w, hz)
            x = 0.0
            while x < w:
                th = prng.uniform(4, 13) * SS
                tw = th * prng.uniform(0.28, 0.4)
                base = hz - prng.uniform(0, 3) * SS
                d.polygon([(x - tw, base), (x, base - th), (x + tw, base)], fill=255)
                x += prng.uniform(1.5, 5.0) * SS
            inside = inside | (_as_alpha(m) > 0.5)
        # Moonlight flattens the ridges into near-black silhouettes.
        v = min(1.0, depth * (1.8 if light.phase == "night" else 1.0)) * haze
        tone = horizon_tone + (ink - horizon_tone) * v
        depth_below = np.clip(yy[:hz] - crest[None, :], 0, None)
        span = max(1.0, peak * hz)
        layer = np.full((hz, w), tone, dtype=np.float32)
        # Mist pools at the foot of every ridge.
        layer += (horizon_tone - tone) * 0.30 * _smoothstep(0.0, 1.0, depth_below / span) * v
        if rocky:
            shade = _peak_shadow(crest, hz, xx[:hz], yy[:hz], sun_dir, prng)
            # Backlit ridges read as silhouettes; a cloud deck's diffuse light
            # leaves only a hint of the faces.
            lit = 0.3 if backlit else (1.0 if kind in ("clear", "partly") else 0.4)
            layer += (14 - 52 * shade) * lit * v
            rock = _fbm(rng, w, hz, (20, 14), octaves=4)
            layer += (rock - 0.5) * 26 * lit * v
            if i == 0 and kind != "fog":
                # Snow holds only above a fixed altitude, so only the summits
                # carry it; the couloirs drag fingers of it down the faces.
                couloirs = np.abs(_noise_1d(rng, w, 48, 3)) * 18 * SS
                snowline = hz - _SNOWLINE * hz + couloirs
                snow = (yy[:hz] < snowline[None, :]) & inside
                snow_v = 104.0 if light.phase == "night" else (196.0 if backlit else 250.0)
                if kind in ("rain", "storm"):
                    snow_v -= 50.0
                snow_tone = snow_v - 74 * shade * lit + (rock - 0.5) * 16
                layer = np.where(snow, snow_tone, layer)
        # An engraver's contour along the crest keeps each ridge legible
        # after the dither flattens neighbouring greys into one texture.
        contour = (depth_below > 0) & (depth_below < 1.5 * SS) & bool(knots)
        layer = np.where(contour, layer - 70 * max(v, 0.35), layer)
        _over(field[:hz], layer, inside.astype(np.float32))
        profiles.append(crest)
    return profiles


def _peak_shadow(
    crest: np.ndarray,
    hz: int,
    xx: np.ndarray,
    yy: np.ndarray,
    sun_dir: float,
    prng: random.Random,
) -> np.ndarray:
    """1 on each summit's face turned from the light, 0 on the lit face.

    Every summit gets a spine running from its top down to the horizon; the
    face on the side away from the light is in shadow.  That light/shadow
    split per peak is how an engraver models a range, and it survives 1-bit.
    """
    w = crest.shape[0]
    k = max(3, w // 9)
    # Moving average by running sum: sequential, so it adds up the same everywhere.
    run = np.cumsum(np.pad(crest.astype(np.float64), (k // 2, k - 1 - k // 2), mode="edge"))
    smooth = (run[k - 1 :] - np.concatenate(([0.0], run[:-k]))) / k
    peaks = [i for i in range(1, w - 1) if smooth[i] < smooth[i - 1] and smooth[i] <= smooth[i + 1]]
    peaks = [
        int(max(0, p - k // 2) + np.argmin(crest[max(0, p - k // 2) : p + k // 2])) for p in peaks
    ]
    shade = np.zeros_like(xx)
    if not peaks:
        return shade
    bounds = [0]
    for a, b in zip(peaks, peaks[1:]):
        bounds.append(int(a + np.argmax(crest[a:b])) if b > a else a)
    bounds.append(w)
    for p, lo, hi in zip(peaks, bounds, bounds[1:]):
        py = float(crest[p])
        # The spine leans into the shadow side, so each shadow face is a wedge
        # that narrows toward the foot of the peak.
        far_edge = hi if sun_dir > 0 else lo
        lean = (far_edge - p) * prng.uniform(0.25, 0.55)
        frac = np.clip((yy[:, lo:hi] - py) / max(1.0, hz - py), 0.0, 1.0)
        spine = p + lean * frac
        away = (xx[:, lo:hi] - spine) * sun_dir > 0
        # The modelling fades into haze toward the foot of the range.
        fade = _exp(-np.clip(yy[:, lo:hi] - py, 0, None) / (0.55 * max(1.0, hz - py)))
        shade[:, lo:hi] = away * fade
    return shade


def _valley_mist(
    field: np.ndarray,
    rng: np.random.Generator,
    w: int,
    hz: int,
    yy: np.ndarray,
    profiles: list[np.ndarray],
    kind: str,
    horizon_tone: float,
) -> None:
    """Soft horizontal mist banks lying between the ridges."""
    n = _fbm(rng, w, hz, (3, 14), octaves=5)
    strength = 0.85 if kind == "fog" else 0.45
    for crest in profiles[1:3]:
        base = float(np.median(crest)) + (hz - float(np.median(crest))) * 0.55
        band = _exp(-(((yy[:hz] - base) / (hz * 0.07)) ** 2))
        _over(field[:hz], min(250.0, horizon_tone + 8), strength * band * _smoothstep(0.3, 0.75, n))


def _lake(
    field: np.ndarray,
    rng: np.random.Generator,
    prng: random.Random,
    w: int,
    h: int,
    hz: int,
    yy: np.ndarray,
    xx: np.ndarray,
    kind: str,
    light: Light,
    sun: tuple[float, float],
    moon: tuple[float, float],
) -> None:
    """Mirror the sky and ridges, break the mirror with ripples, add glitter."""
    rows = h - hz
    r = np.arange(rows, dtype=np.float32)
    t = r / max(1, rows - 1)
    rough = {"rain": 3.0, "storm": 4.5, "snow": 1.6, "fog": 0.8, "overcast": 1.4}.get(kind, 1.0)
    amp = (0.6 + 9.0 * _pow(t, 1.5)) * SS * rough
    phases = rng.uniform(0, 2 * math.pi, rows).astype(np.float32)
    wavelen = (18 + 70 * t) * SS
    cols = np.arange(w, dtype=np.float32)
    dx = amp[:, None] * _sin(2 * math.pi * cols[None, :] / wavelen[:, None] + phases[:, None])
    src_x = np.clip((cols[None, :] + dx).astype(np.int32), 0, w - 1)
    src_y = np.clip(hz - 1 - (r * 1.05).astype(np.int32), 0, hz - 1)
    refl = field[src_y[:, None], src_x]
    water_v = {"rain": 95.0, "storm": 70.0, "fog": 222.0, "snow": 150.0}.get(kind, 0.0)
    if light.phase == "night":
        water_v = 30.0 if kind != "fog" else 80.0
    mix = {"fog": 0.55, "rain": 0.45, "storm": 0.45, "snow": 0.25}.get(kind, 0.18)
    if water_v == 0.0:
        water_v = float(np.median(field[hz - 10 : hz]))
    refl = refl * (1 - mix) * 0.9 + water_v * mix - 16
    # Ripple streaks: long, thin, denser toward the viewer.
    streak = _fbm(rng, w, rows, (5, max(8, rows // (3 * SS))), octaves=3)
    k = (0.25 + t[:, None]) * 34 * min(rough, 2.0)
    refl += (streak - 0.5) * k
    field[hz:] = refl
    # Glitter path under the sun or moon.
    src = None
    if kind in ("clear", "partly"):
        src = moon if light.phase == "night" else sun
    if src is not None:
        spread = (6 + 70 * t) * SS
        path = _exp(-(((cols[None, :] - src[0]) / spread[:, None]) ** 2))
        glint = _fbm(rng, w, rows, (40, max(8, rows // (2 * SS))), octaves=2)
        strength = 1.0 if light.phase != "day" else 0.75
        sparkle = (glint > 1.0 - 0.55 * path * strength).astype(np.float32)
        top = 250.0 if light.phase != "night" else 228.0
        _over(field[hz:], top, sparkle * 0.95)
    # A crisp waterline where the far shore meets the lake.
    field[hz : hz + SS] = np.minimum(field[hz : hz + SS], field[hz - 1] - 12)


def _sailboat(field: np.ndarray, prng: random.Random, w: int, hz: int, h: int) -> None:
    bx = prng.uniform(0.56, 0.70) * w
    by = hz + prng.uniform(0.05, 0.08) * h
    m, d = _mask(w, h)
    hull_w, mast = 13 * SS, 24 * SS
    d.polygon(
        [
            (bx - hull_w, by - 3 * SS),
            (bx + hull_w, by - 3 * SS),
            (bx + hull_w * 0.7, by),
            (bx - hull_w * 0.75, by),
        ],
        fill=255,
    )
    d.polygon([(bx, by - 4 * SS), (bx, by - mast), (bx + hull_w * 0.85, by - 4 * SS)], fill=255)
    d.polygon(
        [(bx - SS, by - 5 * SS), (bx - SS, by - mast * 0.8), (bx - hull_w * 0.7, by - 5 * SS)],
        fill=255,
    )
    a = _as_alpha(m)
    # The reflection hangs under the hull, broken into bands by the ripples.
    refl = np.zeros_like(a)
    base = int(by)
    span = min(base - int(by - mast) + 1, h - base)
    refl[base : base + span] = a[base - 1 : base - span - 1 : -1][:span]
    bands = ((np.arange(h) // (2 * SS)) % 3 != 0).astype(np.float32)[:, None]
    _over(field, 60.0, refl * bands * 0.6)
    _over(field, 14.0, a)


def _lightning(field: np.ndarray, prng: random.Random, w: int, hz: int, ridge: np.ndarray) -> None:
    x = prng.uniform(0.45, 0.75) * w
    end_y = float(ridge[int(min(w - 1, max(0, x)))]) + 4 * SS
    pts = _bolt(prng, (x, hz * 0.18), (x + prng.uniform(-40, 40) * SS, end_y), 26 * SS)
    m, d = _mask(w, field.shape[0])
    d.line(pts, fill=255, width=3 * SS, joint="curve")
    for _ in range(3):
        i = prng.randint(len(pts) // 5, len(pts) * 3 // 5)
        bx, by = pts[i]
        branch = _bolt(
            prng,
            (bx, by),
            (bx + prng.uniform(-70, 70) * SS, by + prng.uniform(40, 90) * SS),
            14 * SS,
        )
        d.line(branch, fill=255, width=SS, joint="curve")
    a = _as_alpha(m)
    glow = _blur(a, 16 * SS)
    field += 150 * glow / max(1e-6, float(glow.max()))
    _over(field, 255.0, a)


def _bolt(
    prng: random.Random, a: tuple[float, float], b: tuple[float, float], jitter: float
) -> list[tuple[float, float]]:
    """Midpoint-displaced polyline from *a* to *b*."""
    pts = [a, b]
    for _ in range(5):
        nxt = [pts[0]]
        for p, q in zip(pts, pts[1:]):
            mx = (p[0] + q[0]) / 2 + prng.uniform(-jitter, jitter)
            nxt += [(mx, (p[1] + q[1]) / 2), q]
        pts = nxt
        jitter *= 0.55
    return pts


def _foreground(
    field: np.ndarray,
    rng: np.random.Generator,
    prng: random.Random,
    w: int,
    h: int,
    hz: int,
    kind: str,
    light: Light,
) -> None:
    """Banks that rise at both edges, with pines framing the left side."""
    snowy = kind == "snow"
    fade = 0.55 if kind == "fog" else 1.0
    xs = np.arange(w, dtype=np.float32) / w
    top = (
        h * 0.93
        - h * 0.20 * _exp(-((xs / 0.30) ** 2))
        - h * 0.10 * _exp(-(((1 - xs) / 0.16) ** 2))
        + _noise_1d(rng, w, 10, 5) * 7 * SS
    )
    yy = np.arange(h, dtype=np.float32)[:, None]
    land = (yy >= top[None, :]).astype(np.float32)
    if snowy:
        ground = 222.0 + (_fbm(rng, w, h, (40, 20), octaves=3) - 0.5) * 30
    else:
        tex = _fbm(rng, w, h, (90, 14), octaves=3)
        ground = 16.0 + 40 * _smoothstep(0.62, 0.95, tex)
    land_tone = ground if fade == 1.0 else ground * fade + 200 * (1 - fade)
    _over(field, land_tone, land)

    ink_v = 6.0 if fade == 1.0 else 120.0
    far_v = 40.0 if fade == 1.0 else 170.0
    m_far, d_far = _mask(w, h)
    m_near, d_near = _mask(w, h)
    snow_m, d_snow = _mask(w, h)
    # Right bank: a few small pines, set back.
    for _ in range(prng.randint(3, 5)):
        x = prng.uniform(0.84, 0.99) * w
        base = float(top[int(min(w - 1, x))]) + 2 * SS
        _pine(d_far, d_snow if snowy else None, prng, x, base, prng.uniform(0.10, 0.20) * h)
    # Left bank: the framing cluster, tallest at the edge.
    for i in range(prng.randint(6, 8)):
        x = prng.uniform(0.0, 0.30) * w
        height = h * (0.62 - 1.4 * (x / w)) * prng.uniform(0.65, 1.0)
        base = float(top[int(min(w - 1, x))]) + 4 * SS
        draw = d_near if height > 0.30 * h else d_far
        _pine(draw, d_snow if snowy else None, prng, x, base, max(0.12 * h, height))
    # Grass tufts along the bank's edge.
    for _ in range(140):
        x = prng.uniform(0, w)
        base = float(top[int(min(w - 1, x))]) + SS
        for _ in range(3):
            lean = prng.uniform(-4, 4) * SS
            d_near.line(
                [(x, base), (x + lean, base - prng.uniform(4, 13) * SS)], fill=255, width=SS
            )
    _over(field, far_v, _as_alpha(m_far))
    _over(field, ink_v, _as_alpha(m_near))
    if snowy:
        _over(field, 236.0, _as_alpha(snow_m))


def _pine(
    d: ImageDraw.ImageDraw,
    d_snow: ImageDraw.ImageDraw | None,
    prng: random.Random,
    x: float,
    base: float,
    height: float,
) -> None:
    """A ragged spruce: drooping branch tiers that narrow toward the spire."""
    trunk_h = height * 0.10
    d.line([(x, base), (x, base - height)], fill=255, width=max(SS, int(height / 70)))
    step = max(2.5 * SS, height / 26)
    crown = height - trunk_h
    max_w = height * prng.uniform(0.17, 0.23)
    y = base - trunk_h
    while y > base - height + step:
        t = (base - trunk_h - y) / crown
        for side in (-1, 1):
            reach = max_w * (1 - t) ** 1.1 * prng.uniform(0.55, 1.15) + SS
            droop = step * prng.uniform(0.3, 0.9)
            tip = (x + side * reach, y + droop)
            d.polygon(
                [
                    (x, y - step * 1.4),
                    (x + side * reach * 0.55, y - step * 0.2),
                    tip,
                    (x + side * reach * 0.45, y + step * 0.35),
                    (x, y + step * 0.3),
                ],
                fill=255,
            )
            if d_snow is not None:
                d_snow.line(
                    [(x + side * reach * 0.15, y - step * 0.9), (tip[0], tip[1] - step * 0.35)],
                    fill=255,
                    width=SS,
                )
        y -= step * prng.uniform(0.75, 1.1)
    d.polygon(
        [(x - step * 0.6, y + step), (x, base - height - step), (x + step * 0.6, y + step)],
        fill=255,
    )


def _rain(field: np.ndarray, prng: random.Random, w: int, h: int, *, heavy: bool) -> None:
    m, d = _mask(w, h)
    slant = 0.22
    for _ in range(1500 if heavy else 950):
        x = prng.uniform(-0.2 * h * slant, w)
        y = prng.uniform(0, h)
        length = prng.uniform(10, 26) * SS
        d.line([(x, y), (x + length * slant, y + length)], fill=prng.randint(120, 255), width=1)
    a = _as_alpha(m) * (0.5 if heavy else 0.4)
    # Streaks read light against the dark sky and dark against pale water.
    tone = np.where(field < 128, 200.0, 70.0)
    _over(field, tone, a)


def _snowfall(field: np.ndarray, prng: random.Random, w: int, h: int) -> None:
    m, d = _mask(w, h)
    for _ in range(1100):
        x, y = prng.uniform(0, w), prng.uniform(0, h)
        r = prng.choice((0.8, 1.0, 1.0, 1.3, 1.7, 2.6)) * SS
        d.ellipse((x - r, y - r, x + r, y + r), fill=255)
    a = _as_alpha(m)
    # Dark rims keep the flakes legible where they cross the pale sky.
    rim = np.clip(_blur(a, 1.5 * SS) * 1.6 - a, 0, 1)
    _over(field, 120.0, rim * 0.5)
    _over(field, 255.0, a)


def _birds(
    field: np.ndarray, prng: random.Random, w: int, hz: int, sun: tuple[float, float]
) -> None:
    m, d = _mask(w, field.shape[0])
    cx = prng.uniform(0.45, 0.8) * w
    cy = prng.uniform(0.18, 0.32) * hz
    for _ in range(prng.randint(3, 5)):
        x = cx + prng.uniform(-60, 60) * SS
        y = cy + prng.uniform(-25, 25) * SS
        span = prng.uniform(5, 8) * SS
        d.arc((x - span, y - span / 2, x, y + span / 2), 200, 330, fill=255, width=SS)
        d.arc((x, y - span / 2, x + span, y + span / 2), 210, 340, fill=255, width=SS)
    _over(field, 20.0, _as_alpha(m))
