"""Full-canvas Victorian-instrument-deck component for the ``weatherglass`` theme.

Layout (800×480 final; supersampled 2× to 1600×960 working canvas):

  ┌────────────────────────────────────────────────────────────────────┐
  │ MAY 27 · MMXXVI       ✦  WEATHERGLASS  ✦       NEW YORK            │
  │ ─────────────────────────────────────────────────────────────────  │
  │                                                                    │
  │  ┌──────┐         ╭────────────╮              ┌──────┐             │
  │  │ THER │         │  STORMY .. │              │ HYGRO│             │
  │  │ MOME │         │  ...  ↑    │              │ METER│             │
  │  │ TER  │         │  pivot     │              ├──────┤             │
  │  │ ║▓▓▓ │         │  BAROMETER │              │ UV.. │             │
  │  └──────┘         ╰────────────╯              └──────┘             │
  │  ─────────────────────────────────────────────────────────────────  │
  │  ╭───╮     ◜‾‾‾sun arc‾‾‾◝       ╭───╮       ╭───╮                 │
  │  │ N │  ☀  ↑ rise · ↓ set        │moon│       │AQI│                │
  │  ╰───╯                            ╰───╯       ╰───╯                │
  └────────────────────────────────────────────────────────────────────┘

Mode-aware drawing: the canvas is L-mode on Waveshare and RGB on Inky.
On L mode every shaded zone (thermometer cold zone, hygrometer comfort band,
UV readings below the current one, twilight on the horizon strip, the dial
bezels) is an engraved ruled tint — one-final-pixel rules from
``_ruled_fill`` — because the theme quantizes by threshold, which would snap
a mid-grey fill to solid black or paper. On RGB the same zones take
Spectra-6 colours directly (yellow brass, red mercury, blue cold, green
comfort).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageChops, ImageDraw

from src._io import atomic_write_json
from src.astronomy import sun_times
from src.data.models import AirQualityData, DashboardData, WeatherAlert, WeatherData
from src.render.artkit import grey as _grey
from src.render.artkit import ink as _ink
from src.render.moon import is_waxing, moon_illumination, moon_phase_name
from src.render.primitives import (
    deg_to_compass,
    draw_text_truncated,
    text_height,
    text_width,
    truncate_to_width,
    wind_unit,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import (
    INKY_BLUE,
    INKY_GREEN,
    INKY_RED,
    INKY_YELLOW,
    ComponentRegion,
    ThemeStyle,
)

# Supersample factor — must match the theme's canvas multiplier (2×).
# Every absolute pixel size below is multiplied by SS.

SS = 2

# Final-coord canvas (800×480) → working canvas dims.
_W = 800 * SS
_H = 480 * SS

# Layout bands.
_MAST_Y0 = 0
_MAST_Y1 = 64 * SS
_HERO_Y0 = 80 * SS
_HERO_Y1 = 360 * SS
_SEC_Y0 = 374 * SS
_SEC_Y1 = 466 * SS

# Hero instrument bounding boxes (final coords ×SS).
_THERMO_RECT = (20 * SS, _HERO_Y0, 200 * SS, _HERO_Y1)
_BARO_RECT = (220 * SS, _HERO_Y0, 580 * SS, _HERO_Y1)
_HYGRO_UV_RECT = (600 * SS, _HERO_Y0, 780 * SS, _HERO_Y1)

# Secondary instrument bounding boxes.
_WIND_RECT = (24 * SS, _SEC_Y0, 168 * SS, _SEC_Y1)
_SUN_RECT = (184 * SS, _SEC_Y0, 488 * SS, _SEC_Y1)
_MOON_RECT = (504 * SS, _SEC_Y0, 600 * SS, _SEC_Y1)
_AQI_RECT = (616 * SS, _SEC_Y0, 716 * SS, _SEC_Y1)


# Mode-aware colour helpers — brass/mercury collapse to solid ink on L mode
# so thin needles stay crisp through Floyd-Steinberg quantization.  Large
# fill bands (cold/comfort zones, wood grain) use mid-grey on L so they
# dither into engraving-style halftone.


def _brass(mode: str) -> int | tuple[int, int, int]:
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_YELLOW]
    return 0


def _mercury(mode: str) -> int | tuple[int, int, int]:
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_RED]
    return 0


def _cold(mode: str) -> int | tuple[int, int, int]:
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_BLUE]
    return 90


def _warm_good(mode: str) -> int | tuple[int, int, int]:
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_GREEN]
    return 70


# Type: Cinzel for engraved words, Literata Bold for every scale numeral and
# small reading — Cinzel's thin digits break up at 9–11 px after the 2× downsample.


def _label_font(style: ThemeStyle, px: int):
    fn = style.font_section_label or style.font_semibold
    return fn(px * SS)


def _numeral_font(style: ThemeStyle, px: int):
    return style.font_bold(px * SS)


def _value_font(style: ThemeStyle, px: int):
    fn = style.font_date_number or style.font_bold
    return fn(px * SS)


# Engraved tints. A mid-grey fill thresholds to solid black or vanishes, so
# on L mode a zone is shaded with ruled lines instead: horizontal rules one
# final pixel thick on even rows, which survive the 2× downsample exactly.
# On RGB the zone takes its palette colour.

RULE_DENSE = 2  # final-pixel pitch: every other row (≈50 % ink)
RULE_OPEN = 3  # every third row (≈33 % ink)


def _ruled_fill(draw: ImageDraw.ImageDraw, polygon, colour, mode: str, pitch: int) -> None:
    """Fill *polygon* with *colour* on RGB, or with horizontal rules on L mode."""
    if mode == "RGB":
        draw.polygon(polygon, fill=colour)
        return
    xs = [int(p[0]) for p in polygon]
    ys = [int(p[1]) for p in polygon]
    bx0, by0 = min(xs), min(ys)
    size = (max(xs) - bx0 + 1, max(ys) - by0 + 1)
    if size[0] <= 1 or size[1] <= 1:
        return
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon([(x - bx0, y - by0) for x, y in polygon], fill=255)
    rules = Image.new("L", size, 0)
    rd = ImageDraw.Draw(rules)
    step = pitch * SS
    first = (-by0) % step  # rows aligned to the canvas, not the zone
    for y in range(first, size[1], step):
        rd.rectangle((0, y, size[0], y + SS - 1), fill=255)
    rules.paste(0, (0, 0), ImageChops.invert(mask))
    draw._image.paste(_ink(mode), (bx0, by0), rules)  # type: ignore[attr-defined]


def _rect_poly(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _annulus_poly(
    cx: float, cy: float, r_in: float, r_out: float, a0: float, a1: float, steps: int = 48
) -> list[tuple[float, float]]:
    """Polygon for an annular sector; angles in degrees, maths convention (+y up)."""
    outer = []
    inner = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        outer.append((cx + math.cos(a) * r_out, cy - math.sin(a) * r_out))
        inner.append((cx + math.cos(a) * r_in, cy - math.sin(a) * r_in))
    return outer + inner[::-1]


# Pressure history — tiny rolling JSON file in state_dir.  The trend needle
# compares the current pressure against the oldest sample between 1 and 36
# hours old.  Any IO failure silently disables the trend needle.

_PRESSURE_FILE = "weatherglass_pressure_history.json"
_MAX_SAMPLES = 48
_MIN_APPEND_GAP = timedelta(minutes=30)
_TREND_MIN_AGE = timedelta(hours=1)
_TREND_MAX_AGE = timedelta(hours=36)


def _load_prev_pressure(
    state_dir: str | None, now: datetime
) -> tuple[float | None, datetime | None]:
    """Return ``(prev_hPa, ts)`` from the rolling history, or ``(None, None)``."""
    if not state_dir:
        return (None, None)
    path = Path(state_dir) / _PRESSURE_FILE
    try:
        if not path.exists():
            return (None, None)
        blob = json.loads(path.read_text())
    except (OSError, ValueError):
        return (None, None)
    samples = blob.get("samples") if isinstance(blob, dict) else None
    if not isinstance(samples, list):
        return (None, None)
    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    best: tuple[float, datetime] | None = None
    for entry in samples:
        if not isinstance(entry, dict):
            continue
        ts_raw = entry.get("ts")
        hpa = entry.get("hPa")
        if not isinstance(ts_raw, str) or not isinstance(hpa, (int, float)):
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = now_utc - ts.astimezone(timezone.utc)
        if _TREND_MIN_AGE <= age <= _TREND_MAX_AGE:
            if best is None or ts < best[1]:
                best = (float(hpa), ts)
    if best is None:
        return (None, None)
    return best


def _save_pressure_sample(state_dir: str | None, current_hpa: float | None, now: datetime) -> None:
    """Append the current pressure to the rolling history; trim + atomic write."""
    if not state_dir or current_hpa is None:
        return
    try:
        Path(state_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    path = Path(state_dir) / _PRESSURE_FILE
    samples: list[dict] = []
    try:
        if path.exists():
            blob = json.loads(path.read_text())
            if isinstance(blob, dict) and isinstance(blob.get("samples"), list):
                samples = [s for s in blob["samples"] if isinstance(s, dict)]
    except (OSError, ValueError):
        samples = []

    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    # Skip if last sample is too recent.
    if samples:
        last = samples[-1]
        last_ts = last.get("ts")
        if isinstance(last_ts, str):
            try:
                lts = datetime.fromisoformat(last_ts)
                if lts.tzinfo is None:
                    lts = lts.replace(tzinfo=timezone.utc)
                if now_utc - lts.astimezone(timezone.utc) < _MIN_APPEND_GAP:
                    return
            except ValueError:
                pass
    samples.append({"ts": now_utc.isoformat(), "hPa": float(current_hpa)})
    samples = samples[-_MAX_SAMPLES:]
    try:
        # The shared helper is the only sanctioned way to persist JSON state
        # here; it cleans up its own tempfile and re-raises, so the swallow
        # stays local — history bookkeeping must never break a render.
        atomic_write_json(path, {"samples": samples})
    except OSError:
        return


# Unit-aware scale ranges


def _temp_scale(units: str | None) -> tuple[float, float, str, list[float]]:
    """Return ``(lo, hi, symbol, major_ticks)`` for the thermometer scale."""
    if units == "metric":
        return (-20.0, 45.0, "°C", [-20, -10, 0, 10, 20, 30, 40])
    if units == "standard":
        return (253.0, 318.0, "K", [253, 263, 273, 283, 293, 303, 313])
    return (0.0, 110.0, "°F", [0, 20, 40, 60, 80, 100])


def _temp_comfort_band(units: str | None) -> tuple[float, float]:
    """Return ``(low, high)`` of the comfortable temperature zone."""
    if units == "metric":
        return (16.0, 24.0)
    if units == "standard":
        return (289.15, 297.15)
    return (60.0, 75.0)


def _temp_cold_threshold(units: str | None) -> float:
    if units == "metric":
        return 0.0
    if units == "standard":
        return 273.15
    return 32.0


def _temp_hot_threshold(units: str | None) -> float:
    if units == "metric":
        return 30.0
    if units == "standard":
        return 303.15
    return 85.0


def _wind_unit_label(units: str | None) -> str:
    """Kept for the tests that import it; the one rule lives in ``primitives.wind_unit``."""
    return wind_unit(SimpleNamespace(units=units))


def draw_weatherglass(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    state_dir: str | None = None,
) -> None:
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        image = draw._image  # type: ignore[attr-defined]

    mode = image.mode
    weather = data.weather
    air_quality = data.air_quality
    alerts: list[WeatherAlert] = weather.alerts if weather else []

    # Persist pressure now (before the trend lookup, but trend will only see
    # samples from prior runs since we only fire the lookup once).
    prev_pressure: float | None = None
    if weather is not None and weather.pressure is not None:
        prev_pressure, _ = _load_prev_pressure(state_dir, now)
        _save_pressure_sample(state_dir, weather.pressure, now)

    _draw_background(image, mode, style)
    _draw_masthead(draw, today, weather, mode, style)
    _draw_filigree_corners(draw, mode)

    _draw_thermometer(draw, _THERMO_RECT, weather, mode, style)
    _draw_barometer(draw, _BARO_RECT, weather, prev_pressure, mode, style)
    _draw_hygrometer_uv_stack(draw, _HYGRO_UV_RECT, weather, mode, style)

    _draw_wind_compass(draw, _WIND_RECT, weather, mode, style)
    _draw_sun_arc(draw, _SUN_RECT, weather, today, now, latitude, longitude, mode, style)
    _draw_moon_porthole(draw, _MOON_RECT, today, mode, style)
    _draw_aqi_or_nameplate(draw, _AQI_RECT, air_quality, today, mode, style)

    # Alert cartouche overlays everything else, including the masthead.
    if alerts:
        _draw_alert_cartouche(draw, alerts, mode, style)


# Background — parchment fill + subtle wood-grain cross-hatch


def _draw_background(image: Image.Image, mode: str, style: ThemeStyle) -> None:
    """Pure white field + a single clean outer frame line.

    Greyscale stripes / hairline shadows dither into noise on the 1-bit
    Waveshare backend, so we keep the field pristine and rely on negative
    space to define the instrument bench.
    """
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, _W, _H), fill=_grey(255, mode))
    inset = 6 * SS
    draw.rectangle(
        (inset, inset, _W - inset, _H - inset),
        outline=_ink(mode),
        width=SS,
    )


# Masthead — "WEATHERGLASS" wordmark + date + location


def _draw_masthead(
    draw: ImageDraw.ImageDraw,
    today: date,
    weather: WeatherData | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    ink = _ink(mode)
    brass = _brass(mode)

    pad_x = 28 * SS
    title_font = style.font_title(32 * SS) if style.font_title else style.font_bold(32 * SS)
    label_font = (
        style.font_section_label(14 * SS)
        if style.font_section_label
        else style.font_semibold(14 * SS)
    )

    title = "WEATHERGLASS"
    tb = draw.textbbox((0, 0), title, font=title_font)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    cx = _W // 2
    tx = cx - tw // 2 - tb[0]
    ty = _MAST_Y0 + (_MAST_Y1 - _MAST_Y0 - th) // 2 - tb[1]
    draw.text((tx, ty), title, font=title_font, fill=ink)

    # Brass star ornaments flanking the wordmark.
    star_y = _MAST_Y0 + (_MAST_Y1 - _MAST_Y0) // 2
    star_offset = tw // 2 + 18 * SS
    for sx in (cx - star_offset, cx + star_offset):
        _draw_compass_star(draw, sx, star_y, 7 * SS, brass)

    # Date on the left in small caps.
    date_text = today.strftime("%b %-d · %Y").upper()
    draw.text((pad_x, _MAST_Y0 + 22 * SS), date_text, font=label_font, fill=ink)

    # Location on the right in small caps — truncated if too long.
    if weather is not None and weather.location_name:
        loc_text = weather.location_name.upper()
        lw = text_width(draw, loc_text, label_font)
        max_loc_w = (cx - star_offset) - (pad_x + text_width(draw, date_text, label_font)) - 8 * SS
        draw_text_truncated(
            draw,
            (_W - pad_x - min(lw, max_loc_w), _MAST_Y0 + 22 * SS),
            loc_text,
            label_font,
            max_loc_w,
            fill=ink,
        )

    # Heavy + thin double rule under the masthead.
    rule_y = _MAST_Y1
    draw.line([(pad_x, rule_y), (_W - pad_x, rule_y)], fill=ink, width=2 * SS)
    draw.line(
        [(pad_x, rule_y + 5 * SS), (_W - pad_x, rule_y + 5 * SS)],
        fill=ink,
        width=SS,
    )


def _draw_compass_star(draw: ImageDraw.ImageDraw, cx: float, cy: int, r: int, fill) -> None:
    """Four-pointed compass-star ornament centred at (cx, cy)."""
    pts = [(cx, cy - r), (cx + r // 3, cy), (cx, cy + r), (cx - r // 3, cy)]
    draw.polygon(pts, fill=fill)
    pts2 = [(cx - r, cy), (cx, cy - r // 3), (cx + r, cy), (cx, cy + r // 3)]
    draw.polygon(pts2, fill=fill)


# Filigree corner ornaments


def _draw_filigree_corners(draw: ImageDraw.ImageDraw, mode: str) -> None:
    """Small arc curls in each of the 4 canvas corners."""
    ink = _ink(mode)
    inset = 14 * SS
    arc_r = 20 * SS
    for quadrant in range(4):
        # Quadrant 0 = top-left, 1 = top-right, 2 = bottom-right, 3 = bottom-left.
        if quadrant == 0:
            cx, cy = inset + arc_r, inset + arc_r
            start, end = 90, 180
        elif quadrant == 1:
            cx, cy = _W - inset - arc_r, inset + arc_r
            start, end = 0, 90
        elif quadrant == 2:
            cx, cy = _W - inset - arc_r, _H - inset - arc_r
            start, end = 270, 360
        else:
            cx, cy = inset + arc_r, _H - inset - arc_r
            start, end = 180, 270
        # Concentric arcs.
        for offset in range(0, 9 * SS, 3 * SS):
            r = arc_r - offset
            draw.arc(
                (cx - r, cy - r, cx + r, cy + r),
                start=start,
                end=end,
                fill=ink,
                width=SS,
            )
        # Small dot at the inner tip of the curl.
        tip_r = 2 * SS
        # Tip pointing toward canvas centre.
        if quadrant == 0:
            tx, ty = cx + arc_r - 8 * SS, cy + arc_r - 8 * SS
        elif quadrant == 1:
            tx, ty = cx - arc_r + 8 * SS, cy + arc_r - 8 * SS
        elif quadrant == 2:
            tx, ty = cx - arc_r + 8 * SS, cy - arc_r + 8 * SS
        else:
            tx, ty = cx + arc_r - 8 * SS, cy - arc_r + 8 * SS
        draw.ellipse((tx - tip_r, ty - tip_r, tx + tip_r, ty + tip_r), fill=ink)


# Instrument helpers — shared dial drawing primitives


def _draw_instrument_backplate(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    mode: str,
    radius: int = 6,
) -> None:
    """Single clean rounded rectangle — no inner hairline (it dithered noisily)."""
    x0, y0, x1, y1 = rect
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=radius * SS,
        fill=_grey(255, mode),
        outline=_ink(mode),
        width=2 * SS,
    )


def _draw_dial_rim(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    r_outer: int,
    r_inner: int,
    mode: str,
    *,
    hatch_step_deg: int = 6,  # kept for backwards compat; unused
) -> None:
    """Draw an instrument rim: brass on Inky, an engraved ruled bezel on L mode."""
    del hatch_step_deg  # legacy parameter
    ink = _ink(mode)
    if mode == "RGB":
        draw.ellipse(
            (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
            fill=_brass(mode),
        )
        draw.ellipse(
            (cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
            fill=_grey(255, mode),
        )
    elif r_outer - r_inner >= 8 * SS:
        _ruled_fill(
            draw, _annulus_poly(cx, cy, r_inner, r_outer, 0, 360, 96), None, mode, RULE_OPEN
        )
    # Outer + inner black rings (drawn last so they sit on top of the fill).
    draw.ellipse(
        (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
        outline=ink,
        width=2 * SS,
    )
    draw.ellipse(
        (cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
        outline=ink,
        width=2 * SS,
    )


# Thermometer


def _draw_thermometer(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    """Mercury thermometer with a zone strip; hero reading, feels-like and range at right."""
    _draw_instrument_backplate(draw, rect, mode)
    x0, y0, x1, y1 = rect
    ink = _ink(mode)
    mercury = _mercury(mode)

    units = weather.units if weather else "imperial"
    lo, hi, sym, major_ticks = _temp_scale(units)
    cold_t = _temp_cold_threshold(units)
    hot_t = _temp_hot_threshold(units)
    comf_lo, comf_hi = _temp_comfort_band(units)

    stem_w = 14 * SS
    stem_cx = x0 + 52 * SS
    stem_x0 = stem_cx - stem_w // 2
    stem_x1 = stem_cx + stem_w // 2
    stem_top = y0 + 18 * SS
    stem_bot = y0 + 186 * SS
    bulb_r = 15 * SS
    bulb_cy = stem_bot + bulb_r

    def ty_of(t: float) -> int:
        return _temp_to_y(t, lo, hi, stem_top, stem_bot)

    # Zone strip right of the stem: cold ruled, comfort open, hot solid —
    # three tones a 1-bit panel can hold apart. Inky takes palette colours.
    band_x0 = stem_x1 + 5 * SS
    band_x1 = band_x0 + 8 * SS
    cold_y = ty_of(cold_t)
    if cold_y < stem_bot:
        _ruled_fill(
            draw, _rect_poly(band_x0, cold_y, band_x1, stem_bot), _cold(mode), mode, RULE_DENSE
        )
    if mode == "RGB":
        draw.rectangle((band_x0, ty_of(comf_hi), band_x1, ty_of(comf_lo)), fill=_warm_good(mode))
    hot_y = ty_of(hot_t)
    if hot_y > stem_top:
        draw.rectangle((band_x0, stem_top, band_x1, hot_y), fill=mercury)
    draw.rectangle((band_x0, stem_top, band_x1, stem_bot), outline=ink, width=SS)
    if mode != "RGB":
        # Comfort zone bracketed by two ticks across the open strip.
        for edge in (ty_of(comf_hi), ty_of(comf_lo)):
            draw.rectangle((band_x0, edge - SS // 2, band_x1 + 3 * SS, edge + SS // 2), fill=ink)

    # Glass: stem pill and bulb, outlined heavily enough to survive the threshold.
    draw.rounded_rectangle(
        (stem_x0, stem_top, stem_x1, stem_bot + bulb_r // 2),
        radius=stem_w // 2,
        outline=ink,
        width=2 * SS,
        fill=_grey(255, mode),
    )
    draw.ellipse(
        (stem_cx - bulb_r, bulb_cy - bulb_r, stem_cx + bulb_r, bulb_cy + bulb_r),
        outline=ink,
        width=2 * SS,
        fill=_grey(255, mode),
    )

    # Scale on the left: numbered majors, a minor at every half step.
    tick_font = _numeral_font(style, 11)
    lh = text_height(tick_font)
    step = major_ticks[1] - major_ticks[0] if len(major_ticks) >= 2 else 0
    for t in major_ticks:
        ty = ty_of(t)
        draw.line([(stem_x0 - 9 * SS, ty), (stem_x0 - 2 * SS, ty)], fill=ink, width=2 * SS)
        label = f"{int(t)}"
        lw = text_width(draw, label, tick_font)
        draw.text((stem_x0 - 12 * SS - lw, ty - lh // 2 - SS), label, font=tick_font, fill=ink)
        for k in (1, 2, 3) if step else ():
            mt = t + step * k / 4
            if mt > hi:
                break
            length = 6 if k == 2 else 4
            my = ty_of(mt)
            draw.line([(stem_x0 - length * SS, my), (stem_x0 - 2 * SS, my)], fill=ink, width=SS)

    # Mercury: bulb plus column, inset inside the glass.
    reading = weather.current_temp if weather is not None else None
    if reading is not None:
        ty = max(stem_top + 2 * SS, min(ty_of(reading), stem_bot))
        inset = 4 * SS
        draw.ellipse(
            (
                stem_cx - bulb_r + inset,
                bulb_cy - bulb_r + inset,
                stem_cx + bulb_r - inset,
                bulb_cy + bulb_r - inset,
            ),
            fill=mercury,
        )
        draw.rectangle(
            (stem_x0 + inset, ty, stem_x1 - inset, bulb_cy),
            fill=mercury,
        )

    # Feels-like pointer: a solid wedge against the zone strip.
    feels = weather.feels_like if weather is not None else None
    if feels is not None:
        fy = max(stem_top, min(ty_of(feels), stem_bot))
        tip = band_x1 + 3 * SS
        draw.polygon(
            [(tip, fy), (tip + 9 * SS, fy - 6 * SS), (tip + 9 * SS, fy + 6 * SS)], fill=ink
        )

    # Right column: day's range on top, hero reading beside the bulb, feels-like under it.
    col_x0 = band_x1 + 16 * SS
    col_cx = (col_x0 + x1 - 6 * SS) // 2
    small = _label_font(style, 11)
    if weather is not None and weather.high is not None and weather.low is not None:
        num = _numeral_font(style, 17)
        for i, (word, val) in enumerate((("HIGH", weather.high), ("LOW", weather.low))):
            row_y = stem_top + 6 * SS + i * 50 * SS
            _text_centred(draw, col_cx, row_y, word, small, ink)
            _text_centred(draw, col_cx, row_y + 18 * SS, f"{round(val)}°", num, ink)
        draw.line(
            [(col_cx - 26 * SS, stem_top + 107 * SS), (col_cx + 26 * SS, stem_top + 107 * SS)],
            fill=ink,
            width=SS,
        )

    if reading is not None:
        val_font = _value_font(style, 38)
        vb = draw.textbbox((0, 0), f"{round(reading)}°", font=val_font)
        vy = bulb_cy - (vb[3] - vb[1]) // 2 - 10 * SS
        _text_centred(draw, col_cx, vy, f"{round(reading)}°", val_font, ink)
        if feels is not None:
            _text_centred(
                draw, col_cx, vy + (vb[3] - vb[1]) + 10 * SS, f"FEELS {round(feels)}°", small, ink
            )

    label_font = _label_font(style, 12)
    label = f"THERMOMETER · {sym}"
    lb = draw.textbbox((0, 0), label, font=label_font)
    _text_centred(draw, (x0 + x1) // 2, y1 - 10 * SS - (lb[3] - lb[1]), label, label_font, ink)


def _text_centred(draw: ImageDraw.ImageDraw, cx: float, top: float, text: str, font, fill) -> None:
    """Draw *text* horizontally centred on *cx* with its ink top at *top*."""
    tb = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (tb[2] - tb[0]) / 2 - tb[0], top - tb[1]), text, font=font, fill=fill)


def _temp_to_y(t: float, lo: float, hi: float, y_top: int, y_bot: int) -> int:
    """Map temperature value to a stem-y coordinate (hi at top, lo at bottom)."""
    if hi <= lo:
        return y_bot
    frac = (t - lo) / (hi - lo)
    frac = max(0.0, min(1.0, frac))
    return int(y_bot - frac * (y_bot - y_top))


# Barometer

# Barometer scale: 950..1050 hPa over a 270° aneroid sweep, maths convention
# (+y up): 950 at 225° (lower left), 1000 at the top, 1050 at -45° (lower
# right). The 90° gap at the bottom carries the reading and the nameplate.
_BARO_PRESSURE_LO = 950.0
_BARO_PRESSURE_HI = 1050.0
_BARO_START_DEG = 225.0
_BARO_SWEEP_DEG = 270.0

# Traditional banjo-barometer words at their inch-of-mercury positions
# (28.5, 29, 29.5, 30, 30.5 inHg).
_BARO_WORDS = (
    (965.0, "STORMY"),
    (982.0, "RAIN"),
    (999.0, "CHANGE"),
    (1016.0, "FAIR"),
    (1033.0, "VERY DRY"),
)
_TREND_THRESHOLD_HPA = 1.0


def _pressure_to_angle(p: float) -> float:
    """Map pressure (hPa) to dial angle in degrees (225 = low end, -45 = high end)."""
    p = max(_BARO_PRESSURE_LO, min(_BARO_PRESSURE_HI, p))
    frac = (p - _BARO_PRESSURE_LO) / (_BARO_PRESSURE_HI - _BARO_PRESSURE_LO)
    return _BARO_START_DEG - _BARO_SWEEP_DEG * frac


def _trend_word(current: float, previous: float | None) -> str | None:
    if previous is None:
        return None
    delta = current - previous
    if delta > _TREND_THRESHOLD_HPA:
        return f"RISING +{delta:.0f}"
    if delta < -_TREND_THRESHOLD_HPA:
        return f"FALLING {delta:.0f}"
    return "STEADY"


def _draw_barometer(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    prev_pressure: float | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    """Round aneroid barometer dial with optional trend needle."""
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) // 2
    # Top 26 px stay clear for the alert ribbon; the dial fills the rest.
    r_outer = (y1 - y0 - 26 * SS) // 2
    cy = y1 - r_outer - SS
    r_inner = r_outer - 10 * SS
    ink = _ink(mode)

    _draw_dial_rim(draw, cx, cy, r_outer, r_inner, mode)
    draw.ellipse(
        (
            cx - r_inner + 4 * SS,
            cy - r_inner + 4 * SS,
            cx + r_inner - 4 * SS,
            cy + r_inner - 4 * SS,
        ),
        outline=ink,
        width=SS,
    )

    def at(radius: float, deg: float) -> tuple[float, float]:
        a = math.radians(deg)
        return (cx + math.cos(a) * radius, cy - math.sin(a) * radius)

    # Scale: a tick every 2 hPa, longer every 10 with a numeral, a dot every 5.
    num_font = _numeral_font(style, 11)
    tick_out = r_inner - 4 * SS
    for p in range(int(_BARO_PRESSURE_LO), int(_BARO_PRESSURE_HI) + 1, 2):
        deg = _pressure_to_angle(p)
        major = p % 10 == 0
        length = 13 * SS if major else 6 * SS
        draw.line(
            [at(tick_out - length, deg), at(tick_out, deg)], fill=ink, width=2 * SS if major else SS
        )
        if major:
            nx, ny = at(tick_out - 24 * SS, deg)
            text = str(p)
            tb = draw.textbbox((0, 0), text, font=num_font)
            draw.text(
                (nx - (tb[2] - tb[0]) / 2 - tb[0], ny - (tb[3] - tb[1]) / 2 - tb[1]),
                text,
                font=num_font,
                fill=ink,
            )
    draw.arc(
        (cx - tick_out, cy - tick_out, cx + tick_out, cy + tick_out),
        start=-_BARO_START_DEG,
        end=_BARO_SWEEP_DEG - _BARO_START_DEG,
        fill=ink,
        width=SS,
    )

    word_font = _label_font(style, 11)
    word_radius = tick_out - 50 * SS
    for word_hpa, text in _BARO_WORDS:
        wx, wy = at(word_radius, _pressure_to_angle(word_hpa))
        tb = draw.textbbox((0, 0), text, font=word_font)
        draw.text(
            (wx - (tb[2] - tb[0]) / 2 - tb[0], wy - (tb[3] - tb[1]) / 2 - tb[1]),
            text,
            font=word_font,
            fill=ink,
        )

    pressure = weather.pressure if weather is not None else None
    if pressure is not None and prev_pressure is not None:
        delta = pressure - prev_pressure
        if delta > _TREND_THRESHOLD_HPA:
            trend_colour = _warm_good(mode)
        elif delta < -_TREND_THRESHOLD_HPA:
            trend_colour = _cold(mode)
        else:
            trend_colour = ink
        _draw_needle(
            draw,
            cx,
            cy,
            _pressure_to_angle(prev_pressure),
            tick_out - 16 * SS,
            trend_colour,
            mode,
            hollow=True,
        )
    if pressure is not None:
        _draw_needle(
            draw, cx, cy, _pressure_to_angle(pressure), tick_out - 2 * SS, ink, mode, hollow=False
        )

    pivot_r = 6 * SS
    draw.ellipse(
        (cx - pivot_r, cy - pivot_r, cx + pivot_r, cy + pivot_r),
        fill=_brass(mode),
        outline=ink,
        width=2 * SS,
    )

    # Bottom gap: reading, trend and the engraved nameplate.
    val_font = _value_font(style, 17)
    val_text = f"{round(pressure)} hPa" if pressure is not None else "—"
    _text_centred(draw, cx, cy + 30 * SS, val_text, val_font, ink)
    trend = _trend_word(pressure, prev_pressure) if pressure is not None else None
    if trend is not None:
        _text_centred(draw, cx, cy + 54 * SS, trend, _numeral_font(style, 11), ink)
    name_font = _label_font(style, 12)
    nb = draw.textbbox((0, 0), "BAROMETER", font=name_font)
    _text_centred(draw, cx, cy + r_inner - 22 * SS - (nb[3] - nb[1]), "BAROMETER", name_font, ink)


def _draw_needle(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    angle_deg: float,
    length: int,
    colour,
    mode: str,
    *,
    hollow: bool = False,
) -> None:
    """Tapered needle from (cx, cy) pointing at angle_deg (math convention, +y up).

    Hollow needles draw outline-only (for the secondary trend needle).
    """
    a = math.radians(angle_deg)
    tip_x = cx + math.cos(a) * length
    tip_y = cy - math.sin(a) * length
    # Tail offset opposite direction at small fraction of length.
    tail_len = length * 0.18
    tail_x = cx - math.cos(a) * tail_len
    tail_y = cy + math.sin(a) * tail_len
    # Perpendicular for the base width.
    base_w = max(2 * SS, length // 26)
    perp = (-math.sin(a) * base_w, -math.cos(a) * base_w)
    p1 = (cx + perp[0], cy + perp[1])
    p2 = (cx - perp[0], cy - perp[1])
    poly = [(tip_x, tip_y), p1, (tail_x, tail_y), p2]
    if hollow:
        draw.polygon(poly, outline=colour)
        # Make sure the outline is visible at SS=2.
        for i in range(len(poly)):
            a_pt = poly[i]
            b_pt = poly[(i + 1) % len(poly)]
            draw.line([a_pt, b_pt], fill=colour, width=SS)
    else:
        draw.polygon(poly, fill=colour)


# Hygrometer + UV bar (stacked right column)


def _draw_hygrometer_uv_stack(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    x0, y0, x1, y1 = rect
    mid_y = y0 + (y1 - y0) // 2 - 2 * SS
    hygro_rect = (x0, y0, x1, mid_y)
    uv_rect = (x0, mid_y + 4 * SS, x1, y1)
    _draw_hygrometer(draw, hygro_rect, weather, mode, style)
    _draw_uv_bar(draw, uv_rect, weather, mode, style)


def _draw_hygrometer(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    """Semi-circular dial: 0% (left) → 100% (right), needle to current humidity."""
    _draw_instrument_backplate(draw, rect, mode)
    x0, y0, x1, y1 = rect
    ink = _ink(mode)
    cx = (x0 + x1) // 2
    arc_top = y0 + 24 * SS
    # The arc occupies the upper portion of the card.  Centre the half-disc
    # so the diameter sits a third of the way down.
    r = min((x1 - x0) // 2 - 14 * SS, (y1 - y0) // 2 - 6 * SS)
    cy = arc_top + r

    # Comfort band shading (30-60% RH) — drawn as a thin annulus near the
    # rim rather than a full pie slice so it reads as an engraved tone band.
    band_inner = r - 14 * SS
    band_outer = r - 4 * SS
    # Comfort band (30–60 % RH) as an engraved tone band just inside the rim.
    _ruled_fill(
        draw,
        _annulus_poly(cx, cy, band_inner, band_outer, 180 - 60 * 1.8, 180 - 30 * 1.8, 24),
        _warm_good(mode),
        mode,
        RULE_DENSE,
    )

    # Arc outline + diameter line — heavy for legibility.
    draw.arc(
        (cx - r, cy - r, cx + r, cy + r),
        start=180,
        end=360,
        fill=ink,
        width=2 * SS,
    )
    draw.line([(cx - r, cy), (cx + r, cy)], fill=ink, width=2 * SS)

    # Ticks every 10 %, numbered every 20 %.
    tick_font = _numeral_font(style, 10)
    for pct in range(0, 101, 10):
        a = math.radians(180 - pct * 1.8)
        major = pct % 20 == 0
        tlen = (10 if major else 5) * SS
        draw.line(
            [
                (cx + math.cos(a) * (r - tlen), cy - math.sin(a) * (r - tlen)),
                (cx + math.cos(a) * r, cy - math.sin(a) * r),
            ],
            fill=ink,
            width=2 * SS if major else SS,
        )
        if not major:
            continue
        lx = cx + math.cos(a) * (r + 10 * SS)
        ly = cy - math.sin(a) * (r + 10 * SS)
        text = f"{pct}"
        tb = draw.textbbox((0, 0), text, font=tick_font)
        draw.text(
            (lx - (tb[2] - tb[0]) // 2 - tb[0], ly - (tb[3] - tb[1]) // 2 - tb[1]),
            text,
            font=tick_font,
            fill=ink,
        )

    # Needle — thicker tapered triangle for visibility.
    if weather is not None and weather.humidity is not None:
        deg = 180 - weather.humidity * 1.8
        a = math.radians(deg)
        tip_x = cx + math.cos(a) * (r - 18 * SS)
        tip_y = cy - math.sin(a) * (r - 18 * SS)
        perp_len = 3 * SS
        perp = (-math.sin(a) * perp_len, -math.cos(a) * perp_len)
        poly = [
            (tip_x, tip_y),
            (cx + perp[0], cy + perp[1]),
            (cx - perp[0], cy - perp[1]),
        ]
        draw.polygon(poly, fill=ink)
        # Pivot.
        pr = 4 * SS
        draw.ellipse(
            (cx - pr, cy - pr, cx + pr, cy + pr),
            fill=_brass(mode),
            outline=ink,
            width=2 * SS,
        )

    # Label + numeric readout below the arc.  The "HYGROMETER" label sits
    # close to the bottom of the card; the value floats just under the arc.
    label_font = (
        style.font_section_label(12 * SS)
        if style.font_section_label
        else style.font_semibold(12 * SS)
    )
    val_font = (
        style.font_date_number(20 * SS) if style.font_date_number else style.font_bold(20 * SS)
    )
    if weather is not None and weather.humidity is not None:
        val_text = f"{int(weather.humidity)}%"
    else:
        val_text = "—"
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    val_h = vb[3] - vb[1]
    label_text = "HYGROMETER"
    lb = draw.textbbox((0, 0), label_text, font=label_font)
    label_h = lb[3] - lb[1]
    # Anchor label at the bottom of the card.
    label_y = y1 - 8 * SS - label_h
    # Centre the value vertically between the arc baseline and the label.
    space_top = cy + 6 * SS
    space_bot = label_y - 4 * SS
    val_y = max(space_top, space_top + (space_bot - space_top - val_h) // 2)
    vx = cx - (vb[2] - vb[0]) // 2 - vb[0]
    draw.text((vx, val_y), val_text, font=val_font, fill=ink)
    lx = cx - (lb[2] - lb[0]) // 2 - lb[0]
    draw.text((lx, label_y), label_text, font=label_font, fill=ink)


def _draw_uv_bar(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    """Horizontal 12-cell solar index strip."""
    _draw_instrument_backplate(draw, rect, mode)
    x0, y0, x1, y1 = rect
    ink = _ink(mode)
    bar_x0 = x0 + 14 * SS
    bar_x1 = x1 - 14 * SS
    bar_y0 = y0 + 22 * SS
    bar_y1 = bar_y0 + 18 * SS
    n_cells = 12
    cell_w = (bar_x1 - bar_x0) / n_cells

    # Zone colours per EPA UV category — RGB only.  L mode just outlines the
    # cells and fills the ACTIVE cell solid black so reading + category are
    # both clear without dithering.
    def _cell_colour(i: int):
        if i <= 2:
            return _warm_good(mode)  # green: low (0–2)
        if i <= 5:
            return _brass(mode)  # yellow: moderate (3–5)
        if i <= 7:
            return _mercury(mode)  # red: high (6–7)
        return _ink(mode)  # black: very high / extreme (8+)

    active_idx = -1
    if weather is not None and weather.uv_index is not None:
        active_idx = max(0, min(n_cells - 1, int(weather.uv_index)))

    for i in range(n_cells):
        cx0 = bar_x0 + i * cell_w
        cx1 = bar_x0 + (i + 1) * cell_w
        if mode == "RGB":
            col = _cell_colour(i)
            draw.rectangle((cx0, bar_y0, cx1, bar_y1), fill=col, outline=ink, width=SS)
        else:
            # A gauge reading: cells below the reading ruled, the reading solid.
            if i < active_idx:
                _ruled_fill(draw, _rect_poly(cx0, bar_y0, cx1, bar_y1), None, mode, RULE_DENSE)
            fill = ink if i == active_idx else None
            draw.rectangle((cx0, bar_y0, cx1, bar_y1), fill=fill, outline=ink, width=SS)

    # Pointer triangle above the active cell.
    if active_idx >= 0:
        px = bar_x0 + (active_idx + 0.5) * cell_w
        py = bar_y0 - 4 * SS
        draw.polygon(
            [(px, py), (px - 6 * SS, py - 9 * SS), (px + 6 * SS, py - 9 * SS)],
            fill=ink,
        )

    # Numeric labels at the boundaries between EPA zones.
    tick_font = _numeral_font(style, 10)
    for v in (0, 3, 6, 8, 11):
        tx = bar_x0 + (v + 0.5) * cell_w
        draw.line([(tx, bar_y1 + SS), (tx, bar_y1 + 5 * SS)], fill=ink, width=SS)
        text = str(v)
        tb = draw.textbbox((0, 0), text, font=tick_font)
        draw.text(
            (tx - (tb[2] - tb[0]) // 2 - tb[0], bar_y1 + 6 * SS),
            text,
            font=tick_font,
            fill=ink,
        )

    # Label + numeric value below — label first (anchored to card bottom),
    # value above it.
    label_font = (
        style.font_section_label(12 * SS)
        if style.font_section_label
        else style.font_semibold(12 * SS)
    )
    if weather is not None and weather.uv_index is not None:
        val_text = f"{weather.uv_index:.1f} · {_uv_category(weather.uv_index)}"
    else:
        val_text = "—"
    val_font = _numeral_font(style, 15)
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    cx_card = (x0 + x1) // 2
    label_text = "SOLAR INDEX"
    lb = draw.textbbox((0, 0), label_text, font=label_font)
    label_y = y1 - 8 * SS - (lb[3] - lb[1])
    val_y = (bar_y1 + 20 * SS + label_y) // 2 - (vb[3] - vb[1]) // 2
    _text_centred(draw, cx_card, label_y, label_text, label_font, ink)
    _text_centred(draw, cx_card, val_y, val_text, val_font, ink)


def _uv_category(uv: float) -> str:
    """EPA UV index category name."""
    if uv < 3:
        return "LOW"
    if uv < 6:
        return "MODERATE"
    if uv < 8:
        return "HIGH"
    if uv < 11:
        return "VERY HIGH"
    return "EXTREME"


# Wind compass


def _draw_wind_compass(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    x0, y0, x1, y1 = rect
    ink = _ink(mode)
    # Reserve a caption band at the bottom for the wind-speed readout so the
    # direction needle owns the dial and never crosses the numerals.
    caption_h = 20 * SS
    dial_y1 = y1 - caption_h
    cx = (x0 + x1) // 2
    cy = (y0 + dial_y1) // 2
    r_outer = min((x1 - x0) // 2, (dial_y1 - y0) // 2) - 4 * SS
    r_inner = r_outer - 8 * SS

    _draw_dial_rim(draw, cx, cy, r_outer, r_inner, mode, hatch_step_deg=15)

    # Cardinal letters (N/E/S/W) and intermediate ticks.
    card_font = (
        style.font_section_label(11 * SS)
        if style.font_section_label
        else style.font_semibold(11 * SS)
    )
    # Maths angles: N=top=90°, E=right=0°, S=bottom=270°, W=left=180°.
    cardinals = [("N", 90, True), ("E", 0, False), ("S", 270, False), ("W", 180, False)]
    label_r = r_inner - 8 * SS
    for letter, deg, is_north in cardinals:
        a = math.radians(deg)
        lx = cx + math.cos(a) * label_r
        ly = cy - math.sin(a) * label_r
        tb = draw.textbbox((0, 0), letter, font=card_font)
        tw = tb[2] - tb[0]
        th = tb[3] - tb[1]
        draw.text(
            (lx - tw // 2 - tb[0], ly - th // 2 - tb[1]),
            letter,
            font=card_font,
            fill=ink,
        )
        if is_north:
            # Small brass arrow above the N marker.
            arrow_y = cy - r_outer - 1
            draw.polygon(
                [
                    (cx, arrow_y - 5 * SS),
                    (cx - 3 * SS, arrow_y + 1 * SS),
                    (cx + 3 * SS, arrow_y + 1 * SS),
                ],
                fill=_brass(mode),
                outline=ink,
            )

    # Intercardinal tick marks (NE/SE/SW/NW).
    for deg in (45, 135, 225, 315):
        a = math.radians(deg)
        x0t = cx + math.cos(a) * (r_inner - 4 * SS)
        y0t = cy - math.sin(a) * (r_inner - 4 * SS)
        x1t = cx + math.cos(a) * r_inner
        y1t = cy - math.sin(a) * r_inner
        draw.line([(x0t, y0t), (x1t, y1t)], fill=ink, width=SS)

    # Needle pointing IN the direction the wind is blowing TOWARD.
    # OWM wind_deg is the direction the wind is coming FROM, so we flip 180°
    # to get the arrow's pointing direction.  Compass angles: 0=N, 90=E,
    # 180=S, 270=W.  Convert to maths angle: math_deg = 90 - compass_deg.
    if (
        weather is not None
        and weather.wind_speed is not None
        and weather.wind_deg is not None
        and weather.wind_speed > 0
    ):
        compass_deg = (weather.wind_deg + 180.0) % 360.0
        math_deg = (90.0 - compass_deg) % 360.0
        _draw_needle(
            draw,
            cx,
            cy,
            math_deg,
            r_inner - 6 * SS,
            _mercury(mode),
            mode,
            hollow=False,
        )
        # Pivot.
        pr = 3 * SS
        draw.ellipse(
            (cx - pr, cy - pr, cx + pr, cy + pr),
            fill=_brass(mode),
            outline=ink,
            width=SS,
        )

    # Wind-speed caption centred in the band beneath the dial: big value +
    # small unit on one baseline.  Keeping it out of the dial lets the needle
    # point any bearing without crossing the numerals or the cardinal letters.
    units_label = _wind_unit_label(weather.units if weather else None)
    if weather is not None and weather.wind_deg is not None:
        units_label = f"{units_label} {deg_to_compass(weather.wind_deg)}"
    val_font = _value_font(style, 14)
    small_font = _label_font(style, 10)
    cap_cy = (dial_y1 + y1) // 2
    if weather is None or weather.wind_speed is None or weather.wind_speed <= 0:
        cb = draw.textbbox((0, 0), "CALM", font=val_font)
        draw.text(
            (cx - (cb[2] - cb[0]) // 2 - cb[0], cap_cy - (cb[1] + cb[3]) // 2),
            "CALM",
            font=val_font,
            fill=ink,
        )
    else:
        val_text = f"{int(round(weather.wind_speed))}"
        vb = draw.textbbox((0, 0), val_text, font=val_font)
        ub = draw.textbbox((0, 0), units_label, font=small_font)
        gap = 4 * SS
        total_w = (vb[2] - vb[0]) + gap + (ub[2] - ub[0])
        vx = cx - total_w // 2
        draw.text(
            (vx - vb[0], cap_cy - (vb[1] + vb[3]) // 2),
            val_text,
            font=val_font,
            fill=ink,
        )
        ux = vx + (vb[2] - vb[0]) + gap
        draw.text(
            (ux - ub[0], cap_cy - (ub[1] + ub[3]) // 2),
            units_label,
            font=small_font,
            fill=ink,
        )


# Sun arc + twilight band


def _draw_sun_arc(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    today: date,
    now: datetime,
    latitude: float | None,
    longitude: float | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    """24-hour horizon strip with twilight tints, and the sun's arc from rise to set."""
    _draw_instrument_backplate(draw, rect, mode)
    x0, y0, x1, y1 = rect
    ink = _ink(mode)
    pad = 16 * SS
    strip_x0 = x0 + pad
    strip_x1 = x1 - pad
    strip_w = strip_x1 - strip_x0
    strip_y0 = y0 + 52 * SS
    strip_y1 = strip_y0 + 8 * SS

    sun_info = None
    if latitude is not None and longitude is not None:
        try:
            sun_info = sun_times(today, latitude, longitude)
        except Exception:
            sun_info = None

    sr_dt = weather.sunrise if weather is not None else None
    ss_dt = weather.sunset if weather is not None else None
    if sr_dt is None and sun_info is not None:
        sr_dt = sun_info.sunrise
    if ss_dt is None and sun_info is not None:
        ss_dt = sun_info.sunset

    # The render clock carries the configured zone; computed sun times are UTC.
    local_tz = now.tzinfo
    if local_tz is None and sr_dt is not None:
        local_tz = sr_dt.tzinfo

    def _time_frac(dt: datetime | None) -> float | None:
        """Fraction of the local day elapsed at *dt* (0 = midnight)."""
        if dt is None:
            return None
        if local_tz is not None:
            dt = dt.replace(tzinfo=local_tz) if dt.tzinfo is None else dt.astimezone(local_tz)
        return (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400.0

    def _x_for(dt: datetime | None) -> int | None:
        frac = _time_frac(dt)
        return None if frac is None else int(strip_x0 + frac * strip_w)

    # Horizon strip: night solid, twilight ruled (darker phases denser), day open.
    draw.rectangle((strip_x0, strip_y0, strip_x1, strip_y1), fill=ink)
    if sun_info is not None:
        phases = (
            (sun_info.nautical_dawn, sun_info.sunrise, RULE_DENSE),
            (sun_info.civil_dawn, sun_info.sunrise, RULE_OPEN),
            (sun_info.sunset, sun_info.nautical_dusk, RULE_DENSE),
            (sun_info.sunset, sun_info.civil_dusk, RULE_OPEN),
        )
        for start, end, pitch in phases:
            sx, ex = _x_for(start), _x_for(end)
            if sx is None or ex is None or ex <= sx:
                continue
            draw.rectangle((sx, strip_y0 + SS, ex, strip_y1 - SS), fill=_grey(255, mode))
            _ruled_fill(draw, _rect_poly(sx, strip_y0, ex, strip_y1), _cold(mode), mode, pitch)
    sx_day, ex_day = _x_for(sr_dt), _x_for(ss_dt)
    has_day = False
    if sx_day is not None and ex_day is not None and ex_day > sx_day:
        has_day = True
        draw.rectangle((sx_day, strip_y0 + SS, ex_day, strip_y1 - SS), fill=_grey(255, mode))
    draw.rectangle((strip_x0, strip_y0, strip_x1, strip_y1), outline=ink, width=SS)
    for hour in (6, 12, 18):
        hx = strip_x0 + strip_w * hour // 24
        draw.line([(hx, strip_y1), (hx, strip_y1 + 4 * SS)], fill=ink, width=SS)

    # The sun's path: a half-ellipse standing on the strip from rise to set.
    arc_top = y0 + 12 * SS
    arc_base = strip_y0
    is_day = False
    now_frac = _time_frac(now)
    if has_day:
        assert sx_day is not None and ex_day is not None
        arc_cx = (sx_day + ex_day) / 2
        arc_rx = (ex_day - sx_day) / 2
        arc_ry = arc_base - arc_top
        draw.arc(
            (arc_cx - arc_rx, arc_base - arc_ry, arc_cx + arc_rx, arc_base + arc_ry),
            start=180,
            end=360,
            fill=ink,
            width=2 * SS,
        )
        sr_frac, ss_frac = _time_frac(sr_dt), _time_frac(ss_dt)
        if sr_frac is not None and ss_frac is not None and now_frac is not None:
            is_day = sr_frac <= now_frac <= ss_frac
            if is_day:
                t = (now_frac - sr_frac) / max(1e-6, ss_frac - sr_frac)
                theta = math.pi * (1.0 - t)
                gx = arc_cx + arc_rx * math.cos(theta)
                gy = arc_base - arc_ry * math.sin(theta)
    if not is_day:
        nx = _x_for(now)
        gx = nx if nx is not None else (strip_x0 + strip_x1) / 2
        gy = strip_y0 - 12 * SS

    glyph_r = 9 * SS
    if is_day:
        for deg in range(0, 360, 45):
            a = math.radians(deg)
            draw.line(
                [
                    (gx + math.cos(a) * (glyph_r + 3 * SS), gy + math.sin(a) * (glyph_r + 3 * SS)),
                    (gx + math.cos(a) * (glyph_r + 7 * SS), gy + math.sin(a) * (glyph_r + 7 * SS)),
                ],
                fill=_brass(mode),
                width=2 * SS,
            )
        draw.ellipse(
            (gx - glyph_r, gy - glyph_r, gx + glyph_r, gy + glyph_r),
            fill=_brass(mode),
            outline=ink,
            width=2 * SS,
        )
    else:
        draw.ellipse(
            (gx - glyph_r, gy - glyph_r, gx + glyph_r, gy + glyph_r),
            fill=_grey(255, mode),
            outline=ink,
            width=2 * SS,
        )
        cut = 4 * SS if is_waxing(today) else -4 * SS
        draw.ellipse((gx - glyph_r + cut, gy - glyph_r, gx + glyph_r + cut, gy + glyph_r), fill=ink)

    # Rise and set at the ends, the day's length between them.
    time_font = _numeral_font(style, 11)
    label_y = strip_y1 + 8 * SS
    if sr_dt is not None:
        draw.text(
            (strip_x0, label_y), f"Rise {_fmt_clock(sr_dt, local_tz)}", font=time_font, fill=ink
        )
    if ss_dt is not None:
        text = f"Set {_fmt_clock(ss_dt, local_tz)}"
        draw.text(
            (strip_x1 - text_width(draw, text, time_font), label_y), text, font=time_font, fill=ink
        )
    centre = "SOL · ARC"
    if sr_dt is not None and ss_dt is not None and ss_dt > sr_dt:
        minutes = int((ss_dt - sr_dt).total_seconds() // 60)
        centre = f"DAYLIGHT {minutes // 60}H {minutes % 60:02d}M"
    cfont = _label_font(style, 11)
    cb = draw.textbbox((0, 0), centre, font=cfont)
    draw.text(
        ((strip_x0 + strip_x1) / 2 - (cb[2] - cb[0]) / 2 - cb[0], label_y + SS),
        centre,
        font=cfont,
        fill=ink,
    )


def _fmt_clock(dt: datetime, tz) -> str:
    """Format a datetime as 'H:MMa' / 'H:MMp' in the given tz."""
    if tz is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.astimezone(tz)
    s = dt.strftime("%-I:%M%p").lower()
    return s.replace("am", "a").replace("pm", "p")


# Moon porthole


def _draw_moon_porthole(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    today: date,
    mode: str,
    style: ThemeStyle,
) -> None:
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) // 2
    cy = y0 + 30 * SS  # disc occupies upper portion; labels below
    r_outer = min((x1 - x0) // 2, 24 * SS)
    r_inner = r_outer - 5 * SS
    ink = _ink(mode)

    _draw_dial_rim(draw, cx, cy, r_outer, r_inner, mode, hatch_step_deg=15)

    # Procedural moon — bright disc with terminator clipping.
    illum = moon_illumination(today)  # 0..100
    waxing = is_waxing(today)

    # Bright disc — pure white; dark side — pure ink (collapses cleanly on L).
    bright = _grey(255, mode)
    dark = _ink(mode)
    disc_bbox = (cx - r_inner + SS, cy - r_inner + SS, cx + r_inner - SS, cy + r_inner - SS)
    draw.ellipse(disc_bbox, fill=bright)

    # Terminator: the dark side is always opposite the lit limb.
    # Waxing → lit on RIGHT (Northern hemisphere convention) → dark on LEFT.
    # Waning → lit on LEFT → dark on RIGHT.
    # The terminator curve is modelled by overlaying a vertical ellipse
    # whose width is proportional to |2f - 1|, in the colour of the OPPOSITE
    # side, narrowing the appropriate sliver.
    f = illum / 100.0
    f = max(0.0, min(1.0, f))
    if waxing:
        # Dark covers the LEFT half.
        draw.chord(disc_bbox, start=90, end=270, fill=dark)
    else:
        # Dark covers the RIGHT half.
        draw.chord(disc_bbox, start=270, end=90, fill=dark)
    if f < 0.5:
        # Less than half illuminated: encroach the dark side further into the
        # lit half by overlaying a dark ellipse, leaving only a thin lit crescent.
        ellipse_w = int((r_inner - SS) * (1.0 - 2.0 * f))
        overlay_colour = dark
    else:
        # More than half illuminated: encroach the bright side further into
        # the dark half, leaving only a thin dark crescent.
        ellipse_w = int((r_inner - SS) * (2.0 * f - 1.0))
        overlay_colour = bright
    if ellipse_w > 0:
        draw.ellipse(
            (cx - ellipse_w, cy - r_inner + SS, cx + ellipse_w, cy + r_inner - SS),
            fill=overlay_colour,
        )

    # Labels below the disc.
    name_font = (
        style.font_section_label(10 * SS)
        if style.font_section_label
        else style.font_semibold(10 * SS)
    )
    val_font = (
        style.font_date_number(12 * SS) if style.font_date_number else style.font_bold(12 * SS)
    )
    name_text = moon_phase_name(today).upper()
    val_text = f"{int(round(illum))}%"
    nb = draw.textbbox((0, 0), name_text, font=name_font)
    nx = cx - (nb[2] - nb[0]) // 2 - nb[0]
    name_y = cy + r_outer + 8 * SS
    draw.text((nx, name_y), name_text, font=name_font, fill=ink)
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    vx = cx - (vb[2] - vb[0]) // 2 - vb[0]
    draw.text((vx, name_y + (nb[3] - nb[1]) + 4 * SS), val_text, font=val_font, fill=ink)


# AQI badge / nameplate


def _aqi_ring_colour(aqi: int, mode: str):
    if aqi <= 50:
        return _warm_good(mode)
    if aqi <= 100:
        return _brass(mode)
    if aqi <= 150:
        return _mercury(mode)
    return _ink(mode)


def _draw_aqi_or_nameplate(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    air_quality: AirQualityData | None,
    today: date,
    mode: str,
    style: ThemeStyle,
) -> None:
    if air_quality is None:
        _draw_nameplate(draw, rect, today, mode, style)
        return
    _draw_aqi_badge(draw, rect, air_quality, mode, style)


def _draw_aqi_badge(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    aq: AirQualityData,
    mode: str,
    style: ThemeStyle,
) -> None:
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) // 2
    cy = y0 + 30 * SS
    r_outer = min((x1 - x0) // 2, 24 * SS)
    r_inner = r_outer - 5 * SS
    ink = _ink(mode)

    _draw_dial_rim(draw, cx, cy, r_outer, r_inner, mode, hatch_step_deg=15)

    # AQI category ring inside the brass rim — solid colour on RGB,
    # skipped entirely on L (the category appears as text below).
    ring_outer = r_inner - SS
    ring_inner = r_inner - 7 * SS
    if mode == "RGB":
        colour = _aqi_ring_colour(aq.aqi, mode)
        draw.ellipse(
            (cx - ring_outer, cy - ring_outer, cx + ring_outer, cy + ring_outer),
            fill=colour,
        )
        draw.ellipse(
            (cx - ring_inner, cy - ring_inner, cx + ring_inner, cy + ring_inner),
            fill=_grey(255, mode),
            outline=ink,
            width=2 * SS,
        )

    # Centre numeral — bigger and bolder.
    val_font = (
        style.font_date_number(16 * SS) if style.font_date_number else style.font_bold(16 * SS)
    )
    val_text = str(int(aq.aqi))
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    vx = cx - (vb[2] - vb[0]) // 2 - vb[0]
    vy = cy - (vb[3] - vb[1]) // 2 - vb[1]
    draw.text((vx, vy), val_text, font=val_font, fill=ink)

    label_font = (
        style.font_section_label(11 * SS)
        if style.font_section_label
        else style.font_semibold(11 * SS)
    )
    aqi_label = "AIR · AQI"
    cat = aq.category.upper() if aq.category else ""
    label_y = cy + r_outer + 8 * SS
    lb = draw.textbbox((0, 0), aqi_label, font=label_font)
    draw.text(
        (cx - (lb[2] - lb[0]) // 2 - lb[0], label_y),
        aqi_label,
        font=label_font,
        fill=ink,
    )
    if cat:
        cb = draw.textbbox((0, 0), cat, font=label_font)
        # Truncate if too wide.
        max_w = x1 - x0 - 4 * SS
        if cb[2] - cb[0] > max_w:
            # Use only the first word.
            cat = cat.split()[0]
            cb = draw.textbbox((0, 0), cat, font=label_font)
        draw.text(
            (cx - (cb[2] - cb[0]) // 2 - cb[0], label_y + (lb[3] - lb[1]) + 2 * SS),
            cat,
            font=label_font,
            fill=ink,
        )


def _draw_nameplate(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    today: date,
    mode: str,
    style: ThemeStyle,
) -> None:
    """Engraved nameplate occupying the AQI slot when air_quality is absent."""
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    ink = _ink(mode)
    brass = _brass(mode)

    # Oval brass cartouche.
    plate_w = (x1 - x0) - 8 * SS
    plate_h = (y1 - y0) - 24 * SS
    px0 = cx - plate_w // 2
    py0 = cy - plate_h // 2 - 4 * SS
    px1 = cx + plate_w // 2
    py1 = cy + plate_h // 2 - 4 * SS
    if mode == "RGB":
        draw.rounded_rectangle(
            (px0, py0, px1, py1),
            radius=8 * SS,
            fill=brass,
            outline=ink,
            width=2 * SS,
        )
    else:
        # On L mode, pure white plate with a thick black outline — no mid
        # grey fill that would dither into noise.
        draw.rounded_rectangle(
            (px0, py0, px1, py1),
            radius=8 * SS,
            fill=_grey(255, mode),
            outline=ink,
            width=2 * SS,
        )
    # Engraved inner outline.
    pad = 3 * SS
    draw.rounded_rectangle(
        (px0 + pad, py0 + pad, px1 - pad, py1 - pad),
        radius=6 * SS,
        outline=ink,
        width=SS,
    )

    # Title + year.
    label_font = (
        style.font_section_label(10 * SS)
        if style.font_section_label
        else style.font_semibold(10 * SS)
    )
    body_font = (
        style.font_section_label(13 * SS) if style.font_section_label else style.font_bold(13 * SS)
    )
    title_text = "WEATHERGLASS"
    year_text = today.strftime("%Y")
    tb = draw.textbbox((0, 0), title_text, font=label_font)
    draw.text(
        (cx - (tb[2] - tb[0]) // 2 - tb[0], py0 + 4 * SS),
        title_text,
        font=label_font,
        fill=ink,
    )
    yb = draw.textbbox((0, 0), year_text, font=body_font)
    draw.text(
        (cx - (yb[2] - yb[0]) // 2 - yb[0], py0 + plate_h // 2 - (yb[3] - yb[1]) // 2),
        year_text,
        font=body_font,
        fill=ink,
    )


# Alert cartouche overlay


def _draw_alert_cartouche(
    draw: ImageDraw.ImageDraw,
    alerts: list[WeatherAlert],
    mode: str,
    style: ThemeStyle,
) -> None:
    """Ribbon between the masthead and the barometer naming up to two alerts on one line."""
    text_events = [" · ".join(a.event for a in alerts[:2] if a.event)]
    if not text_events[0]:
        return
    ink = _ink(mode)
    mercury = _mercury(mode)
    body_font = (
        style.font_section_label(13 * SS) if style.font_section_label else style.font_bold(13 * SS)
    )

    # Compute width: fit the widest line + generous padding for the notches.
    text_lines = [t.upper() for t in text_events]
    widths = [text_width(draw, t, body_font) for t in text_lines]
    inner_w = max(widths) + 56 * SS
    band_h = 26 * SS
    max_w = (_BARO_RECT[2] - _BARO_RECT[0]) + 40 * SS
    inner_w = min(inner_w, max_w)
    cx = _W // 2
    y0 = _MAST_Y1 + 9 * SS
    y1 = y0 + band_h
    x0 = cx - inner_w // 2
    x1 = cx + inner_w // 2

    # Ribbon polygon with notched ends.
    notch = 12 * SS
    poly = [
        (x0 + notch, y0),
        (x1 - notch, y0),
        (x1, (y0 + y1) // 2),
        (x1 - notch, y1),
        (x0 + notch, y1),
        (x0, (y0 + y1) // 2),
    ]
    # Fill pure white + mercury outline (thick so it survives on L mode).
    draw.polygon(poly, fill=_grey(255, mode), outline=mercury)
    # Repeat the outline at slight thickness so it shows in L mode dither.
    for i in range(len(poly)):
        a_pt = poly[i]
        b_pt = poly[(i + 1) % len(poly)]
        draw.line([a_pt, b_pt], fill=mercury, width=2 * SS)

    text = truncate_to_width(draw, text_lines[0], body_font, inner_w - 40 * SS)
    tb = draw.textbbox((0, 0), text, font=body_font)
    draw.text(
        (cx - (tb[2] - tb[0]) // 2 - tb[0], (y0 + y1) // 2 - (tb[1] + tb[3]) // 2),
        text,
        font=body_font,
        fill=mercury,
    )

    # Small ink end-cap dots.
    cap_r = 2 * SS
    draw.ellipse((x0 - cap_r, (y0 + y1) // 2 - cap_r, x0 + cap_r, (y0 + y1) // 2 + cap_r), fill=ink)
    draw.ellipse((x1 - cap_r, (y0 + y1) // 2 - cap_r, x1 + cap_r, (y0 + y1) // 2 + cap_r), fill=ink)
