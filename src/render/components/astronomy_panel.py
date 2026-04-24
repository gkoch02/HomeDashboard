"""astronomy_panel.py — Full-canvas "sky tonight" panel.

Four-quadrant layout plus a dark-sky-window footer.  All data is computed
locally from ``src.astronomy`` + ``src.render.moon`` — no API calls, no fetcher.

  ┌─── HEADER: SKY TONIGHT ────────────────────────────────────┐
  │  ☀ SUN              │  🌙 MOON                             │
  │  Sunrise 6:05a      │  Phase: Waxing Gibbous               │
  │  Sunset  7:43p      │  Illumination: 76%                   │
  │  Day    13h 38m     │  Next Full: May 1                    │
  │  (+2m 28s)          │  Next New:  May 16                   │
  ├─────────────────────┼──────────────────────────────────────┤
  │  ✴ TWILIGHT         │  ✨ NEXT METEOR SHOWER               │
  │  Civil     8:12p    │  Eta Aquariids                       │
  │  Nautical  8:47p    │  Peak in 13 days                     │
  │  Astro     9:25p    │  ~50 per hour                        │
  ├─────────────────────┴──────────────────────────────────────┤
  │  🌌  DARK SKY: 9:25p tonight → 4:14a tomorrow (6h 49m)     │
  └────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from PIL import ImageDraw

from src.astronomy import (
    day_length,
    day_length_delta,
    next_meteor_shower,
    sun_times,
)
from src.data.models import DashboardData
from src.render.moon import (
    moon_illumination,
    moon_phase_age,
    moon_phase_glyph,
    moon_phase_name,
)
from src.render.primitives import (
    filled_rect,
    hline,
    text_height,
    text_width,
    vline,
)
from src.render.theme import ComponentRegion, ThemeStyle

_HEADER_H = 44
_ROW_H = 170
_FOOTER_H = 480 - _HEADER_H - _ROW_H * 2
_PAD = 16

_SYNODIC = 29.53059


def _fmt_time(dt: datetime | None, tz: tzinfo | None) -> str:
    """Format a UTC datetime as a local compact am/pm string, or '—' if None."""
    if dt is None:
        return "—"
    if tz is not None:
        dt = dt.astimezone(tz)
    s = dt.strftime("%-I:%M%p").lower()
    s = s.replace("am", "a").replace("pm", "p")
    return s


def _fmt_duration(td: timedelta | None) -> str:
    if td is None:
        return "—"
    total = int(td.total_seconds())
    hours, rem = divmod(abs(total), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m"


def _fmt_delta_seconds(td: timedelta | None) -> str:
    """Format a signed delta like '+2m 28s' or '-0m 53s'."""
    if td is None:
        return ""
    total = int(td.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    minutes, seconds = divmod(total, 60)
    return f"{sign}{minutes}m {seconds:02d}s today"


def _next_phase_date(today: date, target_fraction: float) -> date:
    """Return the date of the next occurrence of the given phase fraction.

    fraction 0.0 = new moon, 0.5 = full moon.  We use the synodic month
    progression and step forward day-by-day up to 40 days.
    """
    for i in range(0, 45):
        d = today + timedelta(days=i)
        age = moon_phase_age(d)
        # The "fraction" is age / SYNODIC.  We look for a crossing where the
        # day before was before the target and today is at or after.
        prev_age = moon_phase_age(d - timedelta(days=1))
        prev_frac = prev_age / _SYNODIC
        curr_frac = age / _SYNODIC
        target = target_fraction % 1.0
        # Handle wrap at the top of the synodic cycle.
        if prev_frac <= curr_frac:
            if prev_frac < target <= curr_frac:
                return d
        else:
            # Wrap case
            if target > prev_frac or target <= curr_frac:
                return d
    return today + timedelta(days=29)


def _draw_quadrant_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    style: ThemeStyle,
) -> int:
    font = style.label_font()
    draw.text((x, y), label, font=font, fill=style.primary_accent_fill())
    return y + text_height(font) + 6


def _draw_key_value_row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    value: str,
    style: ThemeStyle,
    *,
    label_width: int = 90,
    key_font_size: int = 13,
    value_font_size: int = 14,
) -> int:
    key_font = style.font_regular(key_font_size)
    val_font = style.font_semibold(value_font_size)
    draw.text((x, y), label, font=key_font, fill=style.fg)
    draw.text((x + label_width, y - 1), value, font=val_font, fill=style.fg)
    return y + max(text_height(key_font), text_height(val_font)) + 4


def _get_latlon(data: DashboardData) -> tuple[float, float] | None:
    """Best-effort extraction of latitude/longitude from available sources.

    For now the only source available to components is ``WeatherData`` — OWM
    returns sunrise/sunset directly, so we infer lat/lon from the configured
    ``timezone``-adjusted sunrise timestamp is impractical.  Callers should
    invoke with ``latitude``/``longitude`` explicitly; this helper returns
    ``None`` when no coordinates are known.
    """
    # DashboardData doesn't currently carry lat/lon; the caller plumbs them
    # via module-level access on WeatherData if present.  We return None here
    # to keep the panel agnostic — the drawer accepts explicit latitude/longitude.
    return None


def draw_astronomy(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """Draw the full-canvas astronomy panel inside *region*.

    When *latitude* / *longitude* are omitted the panel falls back to
    OWM-reported sunrise/sunset (if present in ``data.weather``) and hides
    the twilight section since it requires coordinate-based math.
    """
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    x0, y0, w, _h = region.x, region.y, region.w, region.h
    tz = now.tzinfo

    # Compute sun times from lat/lon when available; else use weather-supplied
    # sunrise/sunset (twilight section will display '—').
    has_coords = latitude is not None and longitude is not None
    if has_coords:
        t_today = sun_times(today, latitude, longitude)
        t_tomorrow = sun_times(today + timedelta(days=1), latitude, longitude)
        sunrise = t_today.sunrise
        sunset = t_today.sunset
        civil = t_today.civil_dusk
        nautical = t_today.nautical_dusk
        astro = t_today.astronomical_dusk
        astro_dawn_tomorrow = t_tomorrow.astronomical_dawn
        d_len = day_length(t_today)
        delta = day_length_delta(today, latitude, longitude)
    else:
        w_data = data.weather
        sunrise = w_data.sunrise if w_data else None
        sunset = w_data.sunset if w_data else None
        civil = nautical = astro = None
        astro_dawn_tomorrow = None
        if sunrise and sunset:
            d_len = sunset - sunrise
        else:
            d_len = None
        delta = None

    # ── Header bar ──────────────────────────────────────────────────────
    filled_rect(draw, (x0, y0, x0 + w - 1, y0 + _HEADER_H - 1), fill=style.fg)
    title_font = style.font_title(22) if style.font_title else style.font_bold(22)
    title = "SKY TONIGHT"
    draw.text(
        (x0 + _PAD, y0 + (_HEADER_H - text_height(title_font)) // 2 - 2),
        title,
        font=title_font,
        fill=style.bg,
    )
    sub_font = style.font_regular(13)
    sub = today.strftime("%A, %B %-d, %Y")
    sub_w = text_width(draw, sub, sub_font)
    draw.text(
        (x0 + w - sub_w - _PAD, y0 + (_HEADER_H - text_height(sub_font)) // 2 - 1),
        sub,
        font=sub_font,
        fill=style.bg,
    )

    # ── Row 1: SUN | MOON ────────────────────────────────────────────────
    row1_y = y0 + _HEADER_H
    row1_bot = row1_y + _ROW_H
    mid_x = x0 + w // 2
    hline(draw, row1_bot, x0, x0 + w - 1, fill=style.fg)
    vline(draw, mid_x, row1_y, row1_bot, fill=style.fg)

    # -- Sun quadrant --
    sx = x0 + _PAD
    sy = row1_y + 14
    sy = _draw_quadrant_label(draw, sx, sy, "SUN", style)
    sy = _draw_key_value_row(draw, sx, sy, "Sunrise", _fmt_time(sunrise, tz), style)
    sy = _draw_key_value_row(
        draw,
        sx,
        sy,
        "Solar noon",
        _fmt_time(sun_times(today, latitude, longitude).solar_noon if has_coords else None, tz),
        style,
    )
    sy = _draw_key_value_row(draw, sx, sy, "Sunset", _fmt_time(sunset, tz), style)
    sy = _draw_key_value_row(draw, sx, sy, "Day length", _fmt_duration(d_len), style)
    if delta is not None:
        delta_str = _fmt_delta_seconds(delta)
        small_font = style.font_regular(11)
        draw.text((sx, sy), delta_str, font=small_font, fill=style.fg)

    # -- Moon quadrant --
    mx = mid_x + _PAD
    my = row1_y + 14
    my = _draw_quadrant_label(draw, mx, my, "MOON", style)

    # Big glyph on the right side of the moon quadrant
    from src.render.fonts import weather_icon

    glyph_font = weather_icon(60)
    glyph = moon_phase_glyph(today)
    glyph_bb = draw.textbbox((0, 0), glyph, font=glyph_font)
    glyph_w = glyph_bb[2] - glyph_bb[0]
    glyph_h = glyph_bb[3] - glyph_bb[1]
    glyph_x = x0 + w - _PAD - glyph_w
    glyph_y = row1_y + (_ROW_H - glyph_h) // 2
    draw.text(
        (glyph_x - glyph_bb[0], glyph_y - glyph_bb[1]),
        glyph,
        font=glyph_font,
        fill=style.primary_accent_fill(),
    )

    my = _draw_key_value_row(draw, mx, my, "Phase", moon_phase_name(today), style)
    my = _draw_key_value_row(draw, mx, my, "Illum.", f"{moon_illumination(today):.0f}%", style)
    next_full = _next_phase_date(today, 0.5)
    next_new = _next_phase_date(today, 0.0)
    my = _draw_key_value_row(draw, mx, my, "Next full", next_full.strftime("%b %-d"), style)
    my = _draw_key_value_row(draw, mx, my, "Next new", next_new.strftime("%b %-d"), style)

    # ── Row 2: TWILIGHT | NEXT METEOR SHOWER ─────────────────────────────
    row2_y = row1_bot
    row2_bot = row2_y + _ROW_H
    hline(draw, row2_bot, x0, x0 + w - 1, fill=style.fg)
    vline(draw, mid_x, row2_y, row2_bot, fill=style.fg)

    # -- Twilight quadrant --
    tx = x0 + _PAD
    ty = row2_y + 14
    ty = _draw_quadrant_label(draw, tx, ty, "TWILIGHT (DUSK)", style)
    ty = _draw_key_value_row(draw, tx, ty, "Civil", _fmt_time(civil, tz), style)
    ty = _draw_key_value_row(draw, tx, ty, "Nautical", _fmt_time(nautical, tz), style)
    ty = _draw_key_value_row(draw, tx, ty, "Astronomical", _fmt_time(astro, tz), style)
    if not has_coords:
        warn_font = style.font_regular(10)
        draw.text(
            (tx, ty + 4),
            "Set weather lat/lon for twilight times",
            font=warn_font,
            fill=style.fg,
        )

    # -- Meteor shower quadrant --
    ex = mid_x + _PAD
    ey = row2_y + 14
    ey = _draw_quadrant_label(draw, ex, ey, "NEXT METEOR SHOWER", style)
    shower, days = next_meteor_shower(today)
    name_font = style.font_bold(22)
    draw.text((ex, ey), shower.name, font=name_font, fill=style.fg)
    ey += text_height(name_font) + 6
    peak_date = today + timedelta(days=days)
    peak_str = peak_date.strftime("%b %-d")
    if days == 0:
        countdown_str = f"Peak tonight ({peak_str})"
    elif days == 1:
        countdown_str = f"Peak in 1 day ({peak_str})"
    else:
        countdown_str = f"Peak in {days} days ({peak_str})"
    line_font = style.font_semibold(13)
    draw.text((ex, ey), countdown_str, font=line_font, fill=style.fg)
    ey += text_height(line_font) + 4
    rate_font = style.font_regular(13)
    draw.text(
        (ex, ey),
        f"~{shower.zhr} meteors per hour at peak",
        font=rate_font,
        fill=style.fg,
    )

    # ── Footer: Dark sky window ──────────────────────────────────────────
    fy = row2_bot
    label_font = style.label_font()
    draw.text(
        (x0 + _PAD, fy + 14),
        "DARK SKY WINDOW",
        font=label_font,
        fill=style.primary_accent_fill(),
    )
    detail_font = style.font_semibold(16)
    detail_y = fy + 14 + text_height(label_font) + 8
    if has_coords and astro is not None and astro_dawn_tomorrow is not None:
        window_len = astro_dawn_tomorrow - astro
        detail = (
            f"{_fmt_time(astro, tz)} tonight  →  "
            f"{_fmt_time(astro_dawn_tomorrow, tz)} tomorrow   "
            f"({_fmt_duration(window_len)})"
        )
    else:
        detail = "Coordinates needed to compute dark-sky window"
    draw.text((x0 + _PAD, detail_y), detail, font=detail_font, fill=style.fg)
