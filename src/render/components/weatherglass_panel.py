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

Mode-aware drawing: the canvas is L-mode (greyscale) on Waveshare and RGB
on Inky.  ``_brass``/``_mercury`` collapse to solid ink on L mode so thin
needles and small numerals stay crisp through Floyd-Steinberg quantization;
``_cold``/``_warm_good`` use mid-grey on L so large fill bands dither into
authentic engraving texture.  On RGB the helpers emit Spectra-6 palette
entries directly (yellow brass, red mercury, blue cold, green comfort).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from src.astronomy import sun_times
from src.data.models import AirQualityData, DashboardData, WeatherAlert, WeatherData
from src.render.moon import is_waxing, moon_illumination, moon_phase_name
from src.render.primitives import deg_to_compass, draw_text_truncated, text_height, text_width
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import (
    INKY_BLUE,
    INKY_GREEN,
    INKY_RED,
    INKY_YELLOW,
    ComponentRegion,
    ThemeStyle,
)

# ---------------------------------------------------------------------------
# Supersample factor — must match the theme's canvas multiplier (2×).
# Every absolute pixel size below is multiplied by SS.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Mode-aware colour helpers — brass/mercury collapse to solid ink on L mode
# so thin needles stay crisp through Floyd-Steinberg quantization.  Large
# fill bands (cold/comfort zones, wood grain) use mid-grey on L so they
# dither into engraving-style halftone.
# ---------------------------------------------------------------------------


def _grey(v: int, mode: str) -> int | tuple[int, int, int]:
    return v if mode == "L" else (v, v, v)


def _ink(mode: str) -> int | tuple[int, int, int]:
    return 0 if mode == "L" else (0, 0, 0)


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


# ---------------------------------------------------------------------------
# Pressure history — tiny rolling JSON file in state_dir.  The trend needle
# compares the current pressure against the oldest sample between 1 and 36
# hours old.  Any IO failure silently disables the trend needle.
# ---------------------------------------------------------------------------

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
    payload = json.dumps({"samples": samples})
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=".weatherglass_pressure_", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(payload)
            os.replace(tmp_name, path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    except OSError:
        return


# ---------------------------------------------------------------------------
# Unit-aware scale ranges
# ---------------------------------------------------------------------------


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
    if units == "metric":
        return "m/s"
    if units == "standard":
        return "m/s"
    return "mph"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Background — parchment fill + subtle wood-grain cross-hatch
# ---------------------------------------------------------------------------


def _draw_background(image: Image.Image, mode: str, style: ThemeStyle) -> None:
    """Fill canvas with parchment and stipple light wood-grain striations."""
    draw = ImageDraw.Draw(image)
    # Base fill — slightly warm parchment for the wood-frame feel.
    draw.rectangle((0, 0, _W, _H), fill=_grey(244, mode))
    # Faint horizontal grain across the full canvas.  Hairline rules,
    # near-paper tone so Floyd-Steinberg dithers them into a soft texture.
    grain = _grey(228, mode)
    for y in range(8 * SS, _H, 18 * SS):
        draw.line([(0, y), (_W, y)], fill=grain, width=SS)
    # A heavier stripe at the masthead/instrument bench boundary.
    draw.line(
        [(0, _HERO_Y1 + 6 * SS), (_W, _HERO_Y1 + 6 * SS)],
        fill=_grey(180, mode),
        width=SS,
    )
    # Solid outer frame line — 6px in from each edge.
    inset = 6 * SS
    draw.rectangle(
        (inset, inset, _W - inset, _H - inset),
        outline=_ink(mode),
        width=SS,
    )
    # Inner hairline frame — engraved feel.
    inset2 = 10 * SS
    draw.rectangle(
        (inset2, inset2, _W - inset2, _H - inset2),
        outline=_grey(120, mode),
        width=SS,
    )


# ---------------------------------------------------------------------------
# Masthead — "WEATHERGLASS" wordmark + date + location
# ---------------------------------------------------------------------------


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
    title_font = style.font_title(28 * SS) if style.font_title else style.font_bold(28 * SS)
    label_font = (
        style.font_section_label(11 * SS)
        if style.font_section_label
        else style.font_semibold(11 * SS)
    )

    # Title centred.
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


def _draw_compass_star(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill) -> None:
    """Four-pointed compass-star ornament centred at (cx, cy)."""
    pts = [(cx, cy - r), (cx + r // 3, cy), (cx, cy + r), (cx - r // 3, cy)]
    draw.polygon(pts, fill=fill)
    pts2 = [(cx - r, cy), (cx, cy - r // 3), (cx + r, cy), (cx, cy + r // 3)]
    draw.polygon(pts2, fill=fill)


# ---------------------------------------------------------------------------
# Filigree corner ornaments
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Instrument helpers — shared dial drawing primitives
# ---------------------------------------------------------------------------


def _draw_instrument_backplate(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    mode: str,
    radius: int = 6,
) -> None:
    """Backplate for boxed instruments: parchment fill + ink outline + corner ticks."""
    x0, y0, x1, y1 = rect
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=radius * SS,
        fill=_grey(250, mode),
        outline=_ink(mode),
        width=SS,
    )
    # Subtle inner hairline.
    pad = 4 * SS
    draw.rounded_rectangle(
        (x0 + pad, y0 + pad, x1 - pad, y1 - pad),
        radius=max(0, (radius - 2) * SS),
        outline=_grey(160, mode),
        width=SS,
    )


def _draw_dial_rim(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    r_outer: int,
    r_inner: int,
    mode: str,
    *,
    hatch_step_deg: int = 6,
) -> None:
    """Draw a brass-style rim: outer ring + inner ring + radial hairlines."""
    brass = _brass(mode)
    ink = _ink(mode)
    # Outer rim outline.
    draw.ellipse(
        (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
        outline=ink,
        width=SS,
    )
    # Annulus fill — on RGB this is brass yellow, on L it's a mid-grey so
    # the dithered rim reads as engraved metal.
    if mode == "RGB":
        # Paint the full disc then carve out the inner face.
        draw.ellipse(
            (cx - r_outer + SS, cy - r_outer + SS, cx + r_outer - SS, cy + r_outer - SS),
            fill=brass,
        )
        draw.ellipse(
            (cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
            fill=_grey(250, mode),
            outline=ink,
            width=SS,
        )
    else:
        # L mode: paint the inner face white then overlay a hatched annulus.
        draw.ellipse(
            (cx - r_outer + SS, cy - r_outer + SS, cx + r_outer - SS, cy + r_outer - SS),
            fill=_grey(150, mode),
        )
        draw.ellipse(
            (cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
            fill=_grey(250, mode),
            outline=ink,
            width=SS,
        )
    # Radial hairlines.
    for deg in range(0, 360, hatch_step_deg):
        a = math.radians(deg)
        x0 = cx + math.cos(a) * r_inner
        y0 = cy + math.sin(a) * r_inner
        x1 = cx + math.cos(a) * r_outer
        y1 = cy + math.sin(a) * r_outer
        draw.line([(x0, y0), (x1, y1)], fill=ink, width=SS)


def _rotate_text_paste(
    image: Image.Image,
    text: str,
    font,
    fill,
    angle_deg: float,
    centre: tuple[int, int],
    radial_offset: int,
) -> None:
    """Render text on a transparent strip, rotate, and paste at radius=radial_offset.

    The text reads outward from the rim — the angle is the direction the text
    points (0° = right, 90° = down, etc).
    """
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = 4 * SS
    # Render to an L-mode strip and treat any non-zero pixel as the fill region.
    strip = Image.new("L", (tw + 2 * pad, th + 2 * pad), 0)
    sd = ImageDraw.Draw(strip)
    sd.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=255)
    rotated = strip.rotate(-angle_deg, resample=Image.BICUBIC, expand=True)
    rw, rh = rotated.size
    cx, cy = centre
    a = math.radians(angle_deg)
    px = cx + math.cos(a) * radial_offset - rw // 2
    py = cy + math.sin(a) * radial_offset - rh // 2
    # Build a mask and paste the fill color through it.
    if image.mode == "RGB":
        coloured = Image.new("RGB", rotated.size, fill if isinstance(fill, tuple) else (0, 0, 0))
        image.paste(coloured, (int(px), int(py)), rotated)
    else:
        coloured = Image.new("L", rotated.size, fill if isinstance(fill, int) else 0)
        image.paste(coloured, (int(px), int(py)), rotated)


# ---------------------------------------------------------------------------
# Thermometer
# ---------------------------------------------------------------------------


def _draw_thermometer(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    """Vertical mercury thermometer with hero numeral on the right side."""
    _draw_instrument_backplate(draw, rect, mode)
    x0, y0, x1, y1 = rect
    ink = _ink(mode)
    mercury = _mercury(mode)

    units = weather.units if weather else "imperial"
    lo, hi, sym, major_ticks = _temp_scale(units)
    cold_t = _temp_cold_threshold(units)
    hot_t = _temp_hot_threshold(units)
    comf_lo, comf_hi = _temp_comfort_band(units)

    # Stem positioned to the LEFT of card centre so the right half can carry
    # the hero numeral.  Bulb at the bottom of the stem; label across the
    # bottom of the card; the numeral sits beside the bulb.
    stem_w = 12 * SS
    stem_cx = x0 + 50 * SS  # left-of-centre
    stem_x0 = stem_cx - stem_w // 2
    stem_x1 = stem_cx + stem_w // 2
    stem_top = y0 + 20 * SS
    stem_bot = y0 + 215 * SS
    bulb_r = 14 * SS
    bulb_cy = stem_bot + bulb_r + 2 * SS

    # Narrow zone fills on the FAR right edge of the stem.  Drawn as a
    # vertical accent strip — colour-blocked on Inky, stippled on L mode.
    band_x0 = stem_x1 + 4 * SS
    band_x1 = stem_x1 + 12 * SS
    if band_x1 > band_x0:
        # Cold band (≤ cold_t).
        cold_y = _temp_to_y(cold_t, lo, hi, stem_top, stem_bot)
        if cold_y < stem_bot:
            _fill_zone(draw, (band_x0, cold_y, band_x1, stem_bot), _cold(mode), mode)
        # Comfort band.
        comf_y1 = _temp_to_y(comf_hi, lo, hi, stem_top, stem_bot)
        comf_y0 = _temp_to_y(comf_lo, lo, hi, stem_top, stem_bot)
        _fill_zone(draw, (band_x0, comf_y1, band_x1, comf_y0), _warm_good(mode), mode)
        # Hot band (≥ hot_t).
        hot_y = _temp_to_y(hot_t, lo, hi, stem_top, stem_bot)
        if hot_y > stem_top:
            _fill_zone(draw, (band_x0, stem_top, band_x1, hot_y), _mercury(mode), mode)
        # Outline the strip so it reads as a discrete element.
        draw.rectangle((band_x0, stem_top, band_x1, stem_bot), outline=ink, width=SS)

    # Stem pill outline.
    draw.rounded_rectangle(
        (stem_x0, stem_top, stem_x1, stem_bot),
        radius=stem_w // 2,
        outline=ink,
        width=SS,
        fill=_grey(255, mode),
    )

    # Bulb outline.
    draw.ellipse(
        (stem_cx - bulb_r, bulb_cy - bulb_r, stem_cx + bulb_r, bulb_cy + bulb_r),
        outline=ink,
        width=SS,
        fill=_grey(255, mode),
    )

    # Tick marks + numerals on the LEFT side of the stem.
    tick_font = (
        style.font_section_label(7 * SS) if style.font_section_label else style.font_regular(7 * SS)
    )
    for t in major_ticks:
        ty = _temp_to_y(t, lo, hi, stem_top, stem_bot)
        if ty < stem_top - 2 or ty > stem_bot + 2:
            continue
        draw.line(
            [(stem_x0 - 8 * SS, ty), (stem_x0 - 2 * SS, ty)],
            fill=ink,
            width=SS,
        )
        label = f"{int(t)}"
        lw = text_width(draw, label, tick_font)
        lh = text_height(tick_font)
        draw.text(
            (stem_x0 - 10 * SS - lw, ty - lh // 2),
            label,
            font=tick_font,
            fill=ink,
        )
    # Minor ticks halfway between each pair of majors.
    if len(major_ticks) >= 2:
        step = major_ticks[1] - major_ticks[0]
        for t in major_ticks:
            mid = t + step / 2
            if mid > hi:
                continue
            ty = _temp_to_y(mid, lo, hi, stem_top, stem_bot)
            if ty < stem_top or ty > stem_bot:
                continue
            draw.line(
                [(stem_x0 - 4 * SS, ty), (stem_x0 - 2 * SS, ty)],
                fill=ink,
                width=SS,
            )

    # Mercury column.
    if weather is not None and weather.current_temp is not None:
        temp = weather.current_temp
        ty = _temp_to_y(temp, lo, hi, stem_top, stem_bot)
        ty = max(stem_top + SS, min(ty, stem_bot - SS))
        # Bulb filled.
        draw.ellipse(
            (
                stem_cx - bulb_r + SS,
                bulb_cy - bulb_r + SS,
                stem_cx + bulb_r - SS,
                bulb_cy + bulb_r - SS,
            ),
            fill=mercury,
        )
        # Stem column.
        draw.rounded_rectangle(
            (stem_x0 + SS, ty, stem_x1 - SS, stem_bot),
            radius=(stem_w - 2 * SS) // 2,
            fill=mercury,
        )

    # Feels-like marker — hollow triangle pointing at the stem.
    if weather is not None and weather.feels_like is not None:
        fy = _temp_to_y(weather.feels_like, lo, hi, stem_top, stem_bot)
        fy = max(stem_top, min(fy, stem_bot))
        tri = [
            (band_x1 + 4 * SS, fy),
            (band_x1 + 12 * SS, fy - 5 * SS),
            (band_x1 + 12 * SS, fy + 5 * SS),
        ]
        draw.polygon(tri, outline=ink, fill=_grey(255, mode))

    # Hero numeric value — placed in the RIGHT HALF of the card, beside the
    # bulb.  Uses font_date_number (Cinzel Black at this theme).
    if weather is not None and weather.current_temp is not None:
        val_font = (
            style.font_date_number(26 * SS) if style.font_date_number else style.font_bold(26 * SS)
        )
        val_text = f"{int(round(weather.current_temp))}°"
        vb = draw.textbbox((0, 0), val_text, font=val_font)
        vw = vb[2] - vb[0]
        vh = vb[3] - vb[1]
        # Centre the numeral in the right column (between band_x1 and x1).
        right_col_cx = (band_x1 + x1) // 2 + 6 * SS
        vx = right_col_cx - vw // 2 - vb[0]
        vy = bulb_cy - vh // 2 - vb[1]
        draw.text((vx, vy), val_text, font=val_font, fill=ink)

    # Feels-like text below the hero numeral.
    if weather is not None and weather.feels_like is not None:
        small_font = (
            style.font_section_label(8 * SS)
            if style.font_section_label
            else style.font_regular(8 * SS)
        )
        flike_text = f"FEELS  {int(round(weather.feels_like))}°"
        fb = draw.textbbox((0, 0), flike_text, font=small_font)
        right_col_cx = (band_x1 + x1) // 2 + 6 * SS
        fx = right_col_cx - (fb[2] - fb[0]) // 2 - fb[0]
        fy = bulb_cy + bulb_r + 12 * SS
        draw.text((fx, fy), flike_text, font=small_font, fill=_grey(80, mode))

    # Label across the bottom of the card.
    label_font = (
        style.font_section_label(9 * SS)
        if style.font_section_label
        else style.font_semibold(9 * SS)
    )
    label = f"THERMOMETER · {sym}"
    lb = draw.textbbox((0, 0), label, font=label_font)
    cx = (x0 + x1) // 2
    lx = cx - (lb[2] - lb[0]) // 2 - lb[0]
    ly = y1 - 12 * SS - (lb[3] - lb[1])
    draw.text((lx, ly), label, font=label_font, fill=ink)


def _temp_to_y(t: float, lo: float, hi: float, y_top: int, y_bot: int) -> int:
    """Map temperature value to a stem-y coordinate (hi at top, lo at bottom)."""
    if hi <= lo:
        return y_bot
    frac = (t - lo) / (hi - lo)
    frac = max(0.0, min(1.0, frac))
    return int(y_bot - frac * (y_bot - y_top))


def _fill_zone(
    draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], colour, mode: str
) -> None:
    """Fill a zone band with stippling on L mode, solid fill on RGB."""
    x0, y0, x1, y1 = rect
    if x1 <= x0 or y1 <= y0:
        return
    if mode == "RGB":
        draw.rectangle((x0, y0, x1, y1), fill=colour)
        return
    # L mode: stipple at the colour's tone for an engraved feel.
    tone = colour if isinstance(colour, int) else 0
    step = 3 * SS
    for y in range(int(y0), int(y1), step):
        for x in range(int(x0) + ((y // step) % 2) * (step // 2), int(x1), step):
            draw.point((x, y), fill=tone)


# ---------------------------------------------------------------------------
# Barometer
# ---------------------------------------------------------------------------

# Barometer scale: pressure 950..1050 hPa mapped to dial angle 180°..0°.
# 180° = far left ("STORMY"), 90° = top ("CHANGE"), 0° = far right ("VERY DRY").
_BARO_PRESSURE_LO = 950.0
_BARO_PRESSURE_HI = 1050.0


def _pressure_to_angle(p: float) -> float:
    """Map pressure (hPa) to dial angle in degrees (180=left, 0=right)."""
    p = max(_BARO_PRESSURE_LO, min(_BARO_PRESSURE_HI, p))
    frac = (p - _BARO_PRESSURE_LO) / (_BARO_PRESSURE_HI - _BARO_PRESSURE_LO)
    # Top hemisphere only: angle goes 180° → 0° as pressure rises.
    return 180.0 * (1.0 - frac)


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
    cy = (y0 + y1) // 2 - 8 * SS  # nudge up so the bottom legend has room
    r_outer = min((x1 - x0), (y1 - y0)) // 2 - 12 * SS
    r_inner = r_outer - 12 * SS
    ink = _ink(mode)

    _draw_dial_rim(draw, cx, cy, r_outer, r_inner, mode)

    # Tick marks: 60 around the full circle, longer/heavier every 5th.
    for i in range(60):
        deg = i * 6
        a = math.radians(deg)
        if i % 5 == 0:
            tlen = 9 * SS
            w = SS
        else:
            tlen = 4 * SS
            w = SS
        x0t = cx + math.cos(a) * (r_inner - tlen)
        y0t = cy + math.sin(a) * (r_inner - tlen)
        x1t = cx + math.cos(a) * (r_inner - SS)
        y1t = cy + math.sin(a) * (r_inner - SS)
        draw.line([(x0t, y0t), (x1t, y1t)], fill=ink, width=w)

    # Engraved zone labels around the upper half.
    label_font = (
        style.font_section_label(11 * SS)
        if style.font_section_label
        else style.font_semibold(11 * SS)
    )
    # The angles use canvas coords where 180° = left, 90° = top, 0° = right.
    # Pillow ellipse arcs start at 3 o'clock and go clockwise — we mirror our
    # math here so labels appear at the conventional positions.
    label_radius = r_inner - 24 * SS
    zones = [
        (180.0, "STORMY"),
        (135.0, "RAIN"),
        (90.0, "CHANGE"),
        (45.0, "FAIR"),
        (0.0, "VERY DRY"),
    ]
    for deg_angle, text in zones:
        # In our "math" convention, 180 = left, 0 = right.  We pass the angle
        # in PIL's coord convention (y grows down) by negating sin → no:
        # actually, ImageDraw uses the standard convention where +x = 0°,
        # and we want labels above the centre, so we use -math.sin().
        a = math.radians(deg_angle)
        # We want labels above the centre (upper half of the dial), so use
        # the Cartesian convention where +y goes up.  PIL uses +y down, so we
        # negate y in placement.
        lx_centre = cx + math.cos(a) * label_radius
        ly_centre = cy - math.sin(a) * label_radius
        tb = draw.textbbox((0, 0), text, font=label_font)
        tw = tb[2] - tb[0]
        th = tb[3] - tb[1]
        draw.text(
            (lx_centre - tw // 2 - tb[0], ly_centre - th // 2 - tb[1]),
            text,
            font=label_font,
            fill=ink,
        )

    # Numeric scale labels every 20 hPa from 960..1040.
    num_font = (
        style.font_section_label(7 * SS) if style.font_section_label else style.font_regular(7 * SS)
    )
    num_radius = r_inner - 10 * SS
    for p in (960, 980, 1000, 1020, 1040):
        # Pressure → math-angle: 180° = STORMY (low), 0° = VERY DRY (high).
        frac = (p - _BARO_PRESSURE_LO) / (_BARO_PRESSURE_HI - _BARO_PRESSURE_LO)
        deg = 180.0 * (1.0 - frac)
        a = math.radians(deg)
        nx = cx + math.cos(a) * num_radius
        ny = cy - math.sin(a) * num_radius
        text = str(p)
        tb = draw.textbbox((0, 0), text, font=num_font)
        tw = tb[2] - tb[0]
        th = tb[3] - tb[1]
        draw.text(
            (nx - tw // 2 - tb[0], ny - th // 2 - tb[1]),
            text,
            font=num_font,
            fill=_grey(80, mode),
        )

    # Trend needle (secondary, hollow) — drawn first so the main needle
    # overlaps it visually.
    if weather is not None and weather.pressure is not None and prev_pressure is not None:
        delta = weather.pressure - prev_pressure
        if delta > 1.0:
            trend_colour = _warm_good(mode)
        elif delta < -1.0:
            trend_colour = _cold(mode)
        else:
            trend_colour = ink
        _draw_needle(
            draw,
            cx,
            cy,
            _pressure_to_angle(prev_pressure),
            r_inner - 18 * SS,
            trend_colour,
            mode,
            hollow=True,
        )

    # Primary needle.
    if weather is not None and weather.pressure is not None:
        _draw_needle(
            draw,
            cx,
            cy,
            _pressure_to_angle(weather.pressure),
            r_inner - 8 * SS,
            ink,
            mode,
            hollow=False,
        )

    # Pivot — small brass disc.
    pivot_r = 5 * SS
    draw.ellipse(
        (cx - pivot_r, cy - pivot_r, cx + pivot_r, cy + pivot_r),
        fill=_brass(mode),
        outline=ink,
        width=SS,
    )

    # Centre cartouche — pressure value beneath the pivot.
    val_font = (
        style.font_date_number(11 * SS) if style.font_date_number else style.font_bold(11 * SS)
    )
    if weather is not None and weather.pressure is not None:
        val_text = f"{int(round(weather.pressure))} hPa"
    else:
        val_text = "—"
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    vx = cx - (vb[2] - vb[0]) // 2 - vb[0]
    vy = cy + pivot_r + 14 * SS
    draw.text((vx, vy), val_text, font=val_font, fill=ink)

    # "BAROMETER" word OUTSIDE the rim, in the space between the dial and
    # the bottom edge of the card.
    bot_font = (
        style.font_section_label(10 * SS)
        if style.font_section_label
        else style.font_semibold(10 * SS)
    )
    bot_text = "BAROMETER"
    bb = draw.textbbox((0, 0), bot_text, font=bot_font)
    bx = cx - (bb[2] - bb[0]) // 2 - bb[0]
    by = cy + r_outer + 8 * SS
    draw.text((bx, by), bot_text, font=bot_font, fill=ink)


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
    base_w = max(SS, length // 32)
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


# ---------------------------------------------------------------------------
# Hygrometer + UV bar (stacked right column)
# ---------------------------------------------------------------------------


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
    if mode == "RGB":
        n_steps = 24
        a_lo = math.radians(180 - 0.3 * 180)  # 30% = 126°
        a_hi = math.radians(180 - 0.6 * 180)  # 60% = 72°
        pts_outer = []
        pts_inner = []
        for i in range(n_steps + 1):
            t = i / n_steps
            a = a_lo + (a_hi - a_lo) * t
            pts_outer.append((cx + math.cos(a) * band_outer, cy - math.sin(a) * band_outer))
            pts_inner.append((cx + math.cos(a) * band_inner, cy - math.sin(a) * band_inner))
        poly = pts_outer + list(reversed(pts_inner))
        draw.polygon(poly, fill=_warm_good(mode))
    else:
        # L mode: stipple the comfort band annulus into the dial face.
        for h in range(30, 61, 2):
            a = math.radians(180 - h * 1.8)
            for rd in range(band_inner, band_outer, 2 * SS):
                x = cx + math.cos(a) * rd
                y = cy - math.sin(a) * rd
                draw.point((x, y), fill=_warm_good(mode))

    # Arc outline + diameter line.
    draw.arc(
        (cx - r, cy - r, cx + r, cy + r),
        start=180,
        end=360,
        fill=ink,
        width=SS,
    )
    draw.line([(cx - r, cy), (cx + r, cy)], fill=ink, width=SS)

    # Tick marks every 10%.
    tick_font = (
        style.font_section_label(7 * SS) if style.font_section_label else style.font_regular(7 * SS)
    )
    for pct in range(0, 101, 10):
        # Humidity → angle: 0% = 180° (left), 100% = 0° (right).
        deg = 180 - pct * 1.8
        a = math.radians(deg)
        major = pct % 25 == 0
        tlen = 8 * SS if major else 4 * SS
        x0t = cx + math.cos(a) * (r - tlen)
        y0t = cy - math.sin(a) * (r - tlen)
        x1t = cx + math.cos(a) * r
        y1t = cy - math.sin(a) * r
        draw.line([(x0t, y0t), (x1t, y1t)], fill=ink, width=SS)
        if major:
            lx = cx + math.cos(a) * (r + 8 * SS)
            ly = cy - math.sin(a) * (r + 8 * SS)
            text = f"{pct}"
            tb = draw.textbbox((0, 0), text, font=tick_font)
            draw.text(
                (lx - (tb[2] - tb[0]) // 2 - tb[0], ly - (tb[3] - tb[1]) // 2 - tb[1]),
                text,
                font=tick_font,
                fill=ink,
            )

    # Needle.
    if weather is not None and weather.humidity is not None:
        deg = 180 - weather.humidity * 1.8
        a = math.radians(deg)
        tip_x = cx + math.cos(a) * (r - 14 * SS)
        tip_y = cy - math.sin(a) * (r - 14 * SS)
        # Tapered triangle from pivot at (cx, cy) to the tip.
        perp_len = 2 * SS
        perp = (-math.sin(a) * perp_len, -math.cos(a) * perp_len)
        poly = [
            (tip_x, tip_y),
            (cx + perp[0], cy + perp[1]),
            (cx - perp[0], cy - perp[1]),
        ]
        draw.polygon(poly, fill=ink)
        # Pivot.
        pr = 3 * SS
        draw.ellipse(
            (cx - pr, cy - pr, cx + pr, cy + pr),
            fill=_brass(mode),
            outline=ink,
            width=SS,
        )

    # Label + numeric readout below the arc.  The "HYGROMETER" label sits
    # close to the bottom of the card; the value floats just under the arc.
    label_font = (
        style.font_section_label(9 * SS)
        if style.font_section_label
        else style.font_semibold(9 * SS)
    )
    val_font = (
        style.font_date_number(15 * SS) if style.font_date_number else style.font_bold(15 * SS)
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
    bar_x0 = x0 + 10 * SS
    bar_x1 = x1 - 10 * SS
    bar_y0 = y0 + 18 * SS
    bar_y1 = bar_y0 + 14 * SS
    n_cells = 12
    cell_w = (bar_x1 - bar_x0) / n_cells

    # Zone colours per cell index (0..11).  Each cell gets a fill keyed to
    # the EPA UV index categories.
    def _cell_colour(i: int):
        if i <= 2:
            return _warm_good(mode)
        if i <= 5:
            return _grey(150, mode)
        if i <= 7:
            return _brass(mode)
        if i <= 10:
            return _mercury(mode)
        return _ink(mode)

    for i in range(n_cells):
        cx0 = bar_x0 + i * cell_w
        cx1 = bar_x0 + (i + 1) * cell_w
        col = _cell_colour(i)
        if mode == "RGB":
            draw.rectangle((cx0, bar_y0, cx1, bar_y1), fill=col, outline=ink)
        else:
            # Stipple fill so cells differentiate after FS dither.
            _fill_zone(draw, (cx0 + SS, bar_y0 + SS, cx1 - SS, bar_y1 - SS), col, mode)
            draw.rectangle((cx0, bar_y0, cx1, bar_y1), outline=ink, width=SS)

    # Pointer triangle above the active cell.
    if weather is not None and weather.uv_index is not None:
        idx = max(0, min(n_cells - 1, int(weather.uv_index)))
        px = bar_x0 + (idx + 0.5) * cell_w
        py = bar_y0 - 3 * SS
        draw.polygon(
            [(px, py), (px - 4 * SS, py - 7 * SS), (px + 4 * SS, py - 7 * SS)],
            fill=ink,
        )

    # Tick marks for major levels (0, 3, 6, 8, 11) below the bar.
    tick_font = (
        style.font_section_label(7 * SS) if style.font_section_label else style.font_regular(7 * SS)
    )
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
        style.font_section_label(9 * SS)
        if style.font_section_label
        else style.font_semibold(9 * SS)
    )
    val_font = (
        style.font_date_number(11 * SS) if style.font_date_number else style.font_bold(11 * SS)
    )
    if weather is not None and weather.uv_index is not None:
        val_text = f"{weather.uv_index:.1f}"
    else:
        val_text = "—"
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    cx_card = (x0 + x1) // 2
    label_text = "SOLAR INDEX"
    lb = draw.textbbox((0, 0), label_text, font=label_font)
    label_y = y1 - 8 * SS - (lb[3] - lb[1])
    val_y = label_y - 6 * SS - (vb[3] - vb[1])
    draw.text(
        (cx_card - (lb[2] - lb[0]) // 2 - lb[0], label_y),
        label_text,
        font=label_font,
        fill=ink,
    )
    draw.text(
        (cx_card - (vb[2] - vb[0]) // 2 - vb[0], val_y),
        val_text,
        font=val_font,
        fill=ink,
    )


# ---------------------------------------------------------------------------
# Wind compass
# ---------------------------------------------------------------------------


def _draw_wind_compass(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    weather: WeatherData | None,
    mode: str,
    style: ThemeStyle,
) -> None:
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    r_outer = min((x1 - x0) // 2, (y1 - y0) // 2) - 4 * SS
    r_inner = r_outer - 8 * SS
    ink = _ink(mode)

    _draw_dial_rim(draw, cx, cy, r_outer, r_inner, mode, hatch_step_deg=15)

    # Cardinal letters (N/E/S/W) and intermediate ticks.
    card_font = (
        style.font_section_label(8 * SS)
        if style.font_section_label
        else style.font_semibold(8 * SS)
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
            r_inner - 12 * SS,
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

    # Centre numeric readout.
    units_label = _wind_unit_label(weather.units if weather else None)
    val_font = (
        style.font_date_number(11 * SS) if style.font_date_number else style.font_bold(11 * SS)
    )
    small_font = (
        style.font_section_label(7 * SS) if style.font_section_label else style.font_regular(7 * SS)
    )
    if weather is None or weather.wind_speed is None or weather.wind_speed <= 0:
        val_text = "CALM"
        unit_text = ""
    else:
        val_text = f"{int(round(weather.wind_speed))}"
        unit_text = units_label
    # Place readout BELOW the centre so the needle has space.
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    val_y = cy + 8 * SS
    draw.text(
        (cx - (vb[2] - vb[0]) // 2 - vb[0], val_y),
        val_text,
        font=val_font,
        fill=ink,
    )
    if unit_text:
        ub = draw.textbbox((0, 0), unit_text, font=small_font)
        draw.text(
            (cx - (ub[2] - ub[0]) // 2 - ub[0], val_y + (vb[3] - vb[1]) + SS),
            unit_text,
            font=small_font,
            fill=ink,
        )
    # Compass abbreviation top — small.
    if weather is not None and weather.wind_deg is not None and weather.wind_speed:
        comp_text = deg_to_compass(weather.wind_deg)
        cb = draw.textbbox((0, 0), comp_text, font=small_font)
        draw.text(
            (cx - (cb[2] - cb[0]) // 2 - cb[0], cy - r_inner + 2 * SS),
            comp_text,
            font=small_font,
            fill=_grey(80, mode),
        )


# ---------------------------------------------------------------------------
# Sun arc + twilight band
# ---------------------------------------------------------------------------


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
    """Horizontal half-ellipse showing the sun's path; twilight bands if lat/lon."""
    _draw_instrument_backplate(draw, rect, mode)
    x0, y0, x1, y1 = rect
    ink = _ink(mode)
    pad = 16 * SS
    arc_x0 = x0 + pad
    arc_x1 = x1 - pad
    arc_w = arc_x1 - arc_x0
    arc_h = (y1 - y0) - 30 * SS  # leave room for labels below
    arc_cy = y0 + arc_h
    arc_cx = (arc_x0 + arc_x1) // 2
    arc_r_x = arc_w // 2
    arc_r_y = max(8 * SS, arc_h - 18 * SS)

    # Day/night band: shade from "sunrise x" to "sunset x" along the arc baseline.
    # If we have lat/lon, fetch detailed sun_times for the twilight bands.
    sun_info = None
    if latitude is not None and longitude is not None:
        try:
            sun_info = sun_times(today, latitude, longitude)
        except Exception:
            sun_info = None

    # Determine sunrise/sunset for the day, prefer OWM-reported, fall back
    # to computed sun_info.
    sr_dt = None
    ss_dt = None
    if weather is not None:
        sr_dt = weather.sunrise
        ss_dt = weather.sunset
    if sr_dt is None and sun_info is not None:
        sr_dt = sun_info.sunrise
    if ss_dt is None and sun_info is not None:
        ss_dt = sun_info.sunset

    # Local timezone for time→x mapping: prefer the timezone of sunrise/sunset.
    local_tz = None
    if sr_dt is not None and sr_dt.tzinfo is not None:
        local_tz = sr_dt.tzinfo
    elif now.tzinfo is not None:
        local_tz = now.tzinfo

    def _time_frac(dt: datetime) -> float | None:
        """Map a datetime to a fraction along the arc baseline (0..1 = midnight..midnight)."""
        if dt is None:
            return None
        if local_tz is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_tz)
            else:
                dt = dt.astimezone(local_tz)
        seconds = dt.hour * 3600 + dt.minute * 60 + dt.second
        return seconds / 86400.0

    def _x_for(dt: datetime | None) -> int | None:
        frac = _time_frac(dt)
        if frac is None:
            return None
        return int(arc_x0 + frac * arc_w)

    # Twilight bands (only when lat/lon set).
    if sun_info is not None:
        # Build a list of (start_dt, end_dt, tone) bands for the lower strip.
        # Tones progressively lighter from astronomical dawn outward to day.
        bands: list[tuple[datetime | None, datetime | None, int]] = [
            (sun_info.astronomical_dawn, sun_info.nautical_dawn, 40),
            (sun_info.nautical_dawn, sun_info.civil_dawn, 90),
            (sun_info.civil_dawn, sun_info.sunrise, 160),
            (sun_info.sunrise, sun_info.sunset, 230),
            (sun_info.sunset, sun_info.civil_dusk, 160),
            (sun_info.civil_dusk, sun_info.nautical_dusk, 90),
            (sun_info.nautical_dusk, sun_info.astronomical_dusk, 40),
        ]
        strip_y0 = arc_cy + 2 * SS
        strip_y1 = strip_y0 + 8 * SS
        # Background "night" tone.
        draw.rectangle((arc_x0, strip_y0, arc_x1, strip_y1), fill=_grey(20, mode))
        for s, e, tone in bands:
            sx = _x_for(s)
            ex = _x_for(e)
            if sx is None or ex is None or ex <= sx:
                continue
            draw.rectangle((sx, strip_y0, ex, strip_y1), fill=_grey(tone, mode))
    elif sr_dt is not None and ss_dt is not None:
        # Single flat day/night band.
        strip_y0 = arc_cy + 2 * SS
        strip_y1 = strip_y0 + 8 * SS
        draw.rectangle((arc_x0, strip_y0, arc_x1, strip_y1), fill=_grey(20, mode))
        sx = _x_for(sr_dt)
        ex = _x_for(ss_dt)
        if sx is not None and ex is not None and ex > sx:
            draw.rectangle((sx, strip_y0, ex, strip_y1), fill=_grey(230, mode))

    # Arc curve — half-ellipse from west horizon to east horizon.
    draw.arc(
        (arc_cx - arc_r_x, arc_cy - arc_r_y, arc_cx + arc_r_x, arc_cy + arc_r_y),
        start=180,
        end=360,
        fill=_grey(100, mode),
        width=SS,
    )

    # Sun/moon glyph at the current time position.
    nx = _x_for(now)
    if nx is None:
        nx = arc_cx
    # Compute y on the arc curve: x is relative to arc_cx, so
    # y = arc_cy - arc_r_y * sin(angle) where angle ∈ [0°, 180°].
    rel = (nx - arc_cx) / max(1, arc_r_x)
    rel = max(-1.0, min(1.0, rel))
    arc_angle = math.acos(rel)  # 0 at right horizon → π at left horizon
    ny = arc_cy - arc_r_y * math.sin(arc_angle)
    # Is the sun above the horizon now?
    is_day = False
    if sr_dt is not None and ss_dt is not None:
        sr_frac = _time_frac(sr_dt)
        ss_frac = _time_frac(ss_dt)
        now_frac = _time_frac(now)
        if sr_frac is not None and ss_frac is not None and now_frac is not None:
            is_day = sr_frac <= now_frac <= ss_frac
    glyph_r = 9 * SS
    if is_day:
        draw.ellipse(
            (nx - glyph_r, ny - glyph_r, nx + glyph_r, ny + glyph_r),
            fill=_brass(mode),
            outline=ink,
            width=SS,
        )
        # Tiny rays.
        for deg in range(0, 360, 45):
            a = math.radians(deg)
            x0r = nx + math.cos(a) * (glyph_r + 2 * SS)
            y0r = ny + math.sin(a) * (glyph_r + 2 * SS)
            x1r = nx + math.cos(a) * (glyph_r + 5 * SS)
            y1r = ny + math.sin(a) * (glyph_r + 5 * SS)
            draw.line([(x0r, y0r), (x1r, y1r)], fill=_brass(mode), width=SS)
    else:
        # Night glyph — crescent: white disc with a slightly offset dark
        # disc cut out.  Position the cut based on waxing/waning.
        draw.ellipse(
            (nx - glyph_r, ny - glyph_r, nx + glyph_r, ny + glyph_r),
            fill=_grey(245, mode),
            outline=ink,
            width=SS,
        )
        cut_offset = 4 * SS if is_waxing(today) else -4 * SS
        draw.ellipse(
            (
                nx - glyph_r + cut_offset,
                ny - glyph_r,
                nx + glyph_r + cut_offset,
                ny + glyph_r,
            ),
            fill=_grey(40, mode),
        )

    # Sunrise / sunset numeric labels at the horizons.
    label_font = (
        style.font_section_label(8 * SS) if style.font_section_label else style.font_regular(8 * SS)
    )
    if sr_dt is not None:
        sr_text = _fmt_clock(sr_dt, local_tz)
        sb = draw.textbbox((0, 0), sr_text, font=label_font)
        draw.text(
            (arc_x0 + 2 * SS, arc_cy + 14 * SS),
            sr_text,
            font=label_font,
            fill=ink,
        )
    if ss_dt is not None:
        ss_text = _fmt_clock(ss_dt, local_tz)
        sb = draw.textbbox((0, 0), ss_text, font=label_font)
        sw = sb[2] - sb[0]
        draw.text(
            (arc_x1 - 2 * SS - sw - sb[0], arc_cy + 14 * SS),
            ss_text,
            font=label_font,
            fill=ink,
        )
    # "SUN" centre label.
    centre_label_font = (
        style.font_section_label(9 * SS)
        if style.font_section_label
        else style.font_semibold(9 * SS)
    )
    sun_text = "SOL · ARC"
    cb = draw.textbbox((0, 0), sun_text, font=centre_label_font)
    draw.text(
        (arc_cx - (cb[2] - cb[0]) // 2 - cb[0], arc_cy + 14 * SS),
        sun_text,
        font=centre_label_font,
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


# ---------------------------------------------------------------------------
# Moon porthole
# ---------------------------------------------------------------------------


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

    # Bright disc.
    bright = _grey(248, mode)
    dark = _grey(40, mode)
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
        style.font_section_label(7 * SS)
        if style.font_section_label
        else style.font_semibold(7 * SS)
    )
    val_font = style.font_date_number(9 * SS) if style.font_date_number else style.font_bold(9 * SS)
    name_text = moon_phase_name(today).upper()
    val_text = f"{int(round(illum))}%"
    nb = draw.textbbox((0, 0), name_text, font=name_font)
    nx = cx - (nb[2] - nb[0]) // 2 - nb[0]
    name_y = cy + r_outer + 8 * SS
    draw.text((nx, name_y), name_text, font=name_font, fill=ink)
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    vx = cx - (vb[2] - vb[0]) // 2 - vb[0]
    draw.text((vx, name_y + (nb[3] - nb[1]) + 2 * SS), val_text, font=val_font, fill=ink)


# ---------------------------------------------------------------------------
# AQI badge / nameplate
# ---------------------------------------------------------------------------


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

    # AQI coloured inner ring (annulus inside r_inner).
    ring_outer = r_inner - SS
    ring_inner = r_inner - 7 * SS
    colour = _aqi_ring_colour(aq.aqi, mode)
    if mode == "RGB":
        draw.ellipse(
            (cx - ring_outer, cy - ring_outer, cx + ring_outer, cy + ring_outer),
            fill=colour,
        )
        draw.ellipse(
            (cx - ring_inner, cy - ring_inner, cx + ring_inner, cy + ring_inner),
            fill=_grey(248, mode),
            outline=ink,
            width=SS,
        )
    else:
        # Stippled ring on L mode.
        for deg in range(0, 360, 4):
            a = math.radians(deg)
            for rd in range(ring_inner, ring_outer, 2 * SS):
                draw.point(
                    (cx + math.cos(a) * rd, cy + math.sin(a) * rd),
                    fill=colour,
                )
        draw.ellipse(
            (cx - ring_inner, cy - ring_inner, cx + ring_inner, cy + ring_inner),
            fill=_grey(248, mode),
            outline=ink,
            width=SS,
        )

    # Centre numeral.
    val_font = (
        style.font_date_number(11 * SS) if style.font_date_number else style.font_bold(11 * SS)
    )
    val_text = str(int(aq.aqi))
    vb = draw.textbbox((0, 0), val_text, font=val_font)
    vx = cx - (vb[2] - vb[0]) // 2 - vb[0]
    vy = cy - (vb[3] - vb[1]) // 2 - vb[1]
    draw.text((vx, vy), val_text, font=val_font, fill=ink)

    # Labels below.
    label_font = (
        style.font_section_label(8 * SS)
        if style.font_section_label
        else style.font_semibold(8 * SS)
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
            width=SS,
        )
    else:
        draw.rounded_rectangle(
            (px0, py0, px1, py1),
            radius=8 * SS,
            fill=_grey(180, mode),
            outline=ink,
            width=SS,
        )
    # Engraved inner outline.
    pad = 3 * SS
    draw.rounded_rectangle(
        (px0 + pad, py0 + pad, px1 - pad, py1 - pad),
        radius=6 * SS,
        outline=ink,
        width=SS,
    )

    # Roman-numeral year + month.
    label_font = (
        style.font_section_label(8 * SS)
        if style.font_section_label
        else style.font_semibold(8 * SS)
    )
    body_font = (
        style.font_section_label(10 * SS) if style.font_section_label else style.font_bold(10 * SS)
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


# ---------------------------------------------------------------------------
# Alert cartouche overlay
# ---------------------------------------------------------------------------


def _draw_alert_cartouche(
    draw: ImageDraw.ImageDraw,
    alerts: list[WeatherAlert],
    mode: str,
    style: ThemeStyle,
) -> None:
    """Ribbon-shaped overlay carrying up to 2 alert event names."""
    text_events = [a.event for a in alerts[:2] if a.event]
    if not text_events:
        return
    ink = _ink(mode)
    mercury = _mercury(mode)
    body_font = (
        style.font_section_label(10 * SS) if style.font_section_label else style.font_bold(10 * SS)
    )

    # Compute width: fit the widest line + generous padding for the notches.
    text_lines = [t.upper() for t in text_events]
    widths = [text_width(draw, t, body_font) for t in text_lines]
    inner_w = max(widths) + 48 * SS
    band_h = 14 * SS * len(text_lines) + 14 * SS
    max_w = _W - 80 * SS
    inner_w = min(inner_w, max_w)
    cx = _W // 2
    y0 = _MAST_Y1 + 8 * SS
    y1 = y0 + band_h
    x0 = cx - inner_w // 2
    x1 = cx + inner_w // 2

    # Ribbon polygon with notched ends.
    notch = 10 * SS
    poly = [
        (x0 + notch, y0),
        (x1 - notch, y0),
        (x1, (y0 + y1) // 2),
        (x1 - notch, y1),
        (x0 + notch, y1),
        (x0, (y0 + y1) // 2),
    ]
    # Fill (parchment) + mercury outline.
    draw.polygon(poly, fill=_grey(248, mode), outline=mercury)
    # Repeat the outline at slight thickness so it shows in L mode dither.
    for i in range(len(poly)):
        a_pt = poly[i]
        b_pt = poly[(i + 1) % len(poly)]
        draw.line([a_pt, b_pt], fill=mercury, width=2 * SS)

    # Text lines.
    line_h = 14 * SS
    base_y = y0 + (band_h - len(text_lines) * line_h) // 2
    max_text_w = inner_w - 36 * SS
    for i, text in enumerate(text_lines):
        tb = draw.textbbox((0, 0), text, font=body_font)
        tw = tb[2] - tb[0]
        if tw > max_text_w:
            draw_text_truncated(
                draw,
                (cx - max_text_w // 2, base_y + i * line_h),
                text,
                body_font,
                max_text_w,
                fill=mercury,
            )
        else:
            draw.text(
                (cx - tw // 2 - tb[0], base_y + i * line_h),
                text,
                font=body_font,
                fill=mercury,
            )

    # Small ink end-cap dots.
    cap_r = 2 * SS
    draw.ellipse((x0 - cap_r, (y0 + y1) // 2 - cap_r, x0 + cap_r, (y0 + y1) // 2 + cap_r), fill=ink)
    draw.ellipse((x1 - cap_r, (y0 + y1) // 2 - cap_r, x1 + cap_r, (y0 + y1) // 2 + cap_r), fill=ink)
