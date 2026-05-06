"""light_cycle_panel.py — 24-hour radial clock theme.

A full-canvas circular clock representing the entire day at a glance:

  * Outer rim: 24 hour ticks with major numerals at 00 / 06 / 12 / 18.
  * Twilight band ring: concentric arcs whose density encodes the day's
    light cycle — solid at deep night, sparse at civil twilight, empty
    during daylight. Arcs are computed from astronomical / nautical /
    civil twilight times via :mod:`src.astronomy`, with a graceful
    fallback to OWM-reported sunrise/sunset when latitude/longitude are
    unavailable.
  * Event ring: small radial dashes at each timed-event start position.
  * Center disc: today's date, day name, and weather summary.
  * Sun (or moon, when the sun is below the horizon) glyph at the
    current-time position on the rim, plus a needle running from centre
    to that point.
"""

from __future__ import annotations

import math
from datetime import date, datetime, tzinfo

from PIL import ImageDraw

from src.astronomy import sun_times
from src.data.models import DashboardData
from src.render.fonts import weather_icon
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_phase_glyph
from src.render.primitives import (
    events_for_day,
    text_height,
    text_width,
)
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

_CENTER_X = 400
_CENTER_Y = 222
_OUTER_R = 192  # rim of the clock face
_TICK_INNER_R = 180  # minor hour ticks start here
_MAJOR_TICK_INNER_R = 170  # major (every 6h) ticks start here
_HOUR_LABEL_R = 212  # numerals sit just outside the rim
_TWILIGHT_OUTER_R = 167
_TWILIGHT_INNER_R = 126
_EVENT_OUTER_R = 122
_EVENT_INNER_R = 110
_INNER_DISC_R = 104  # central content area radius
_GLYPH_R = 192  # sun/moon glyph sits just outside the rim


# ---------------------------------------------------------------------------
# Polar coordinate helpers
# ---------------------------------------------------------------------------


def _hour_to_pil_angle(hours: float) -> float:
    """Convert hour-of-day to a PIL angle in degrees.

    PIL's arc/pieslice convention: 0° at 3 o'clock, increasing clockwise
    through 90° (6 o'clock), 180° (9 o'clock), 270° (12 o'clock = top).
    A 24-hour clock with midnight at the top puts hour 0 at 270°.
    """
    return (270.0 + hours * 15.0) % 360.0


def _hour_to_radians(hours: float) -> float:
    return math.radians(_hour_to_pil_angle(hours))


def _polar(radius: float, hours: float) -> tuple[int, int]:
    """Return the (x, y) pixel for *hours* on the clock at *radius*."""
    rad = _hour_to_radians(hours)
    return (
        _CENTER_X + int(round(radius * math.cos(rad))),
        _CENTER_Y + int(round(radius * math.sin(rad))),
    )


def _bbox(radius: float) -> tuple[int, int, int, int]:
    """Return the bounding box for a circle of *radius* centred on the clock."""
    return (
        _CENTER_X - int(radius),
        _CENTER_Y - int(radius),
        _CENTER_X + int(radius),
        _CENTER_Y + int(radius),
    )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _to_local_naive(dt: datetime, tz: tzinfo | None) -> datetime:
    """Strip tzinfo, converting to *tz* first when both *dt* and *tz* are aware."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz) if tz is not None else dt.astimezone()
        dt = dt.replace(tzinfo=None)
    return dt


def _hours_of_day(dt: datetime, today: date, tz: tzinfo | None) -> float | None:
    """Return *dt* as fractional hours-of-day on *today*, clamped to [0, 24].

    Returns ``None`` for datetimes that fall on neither today nor an adjacent
    day — those can't be plotted on a single 24h dial.
    """
    if dt is None:
        return None
    naive = _to_local_naive(dt, tz)
    delta_days = (naive.date() - today).days
    if delta_days < -1 or delta_days > 1:
        return None
    hours = naive.hour + naive.minute / 60.0 + naive.second / 3600.0 + delta_days * 24.0
    return max(0.0, min(24.0, hours))


# ---------------------------------------------------------------------------
# Twilight bands
# ---------------------------------------------------------------------------


def _resolve_sun_times(
    today: date,
    weather_sunrise: datetime | None,
    weather_sunset: datetime | None,
    latitude: float | None,
    longitude: float | None,
    tz: tzinfo | None,
) -> tuple[float | None, float | None, list[tuple[float, float, int]]]:
    """Resolve today's twilight bands.

    Returns ``(sunrise_hr, sunset_hr, bands)`` where each band is
    ``(start_hr, end_hr, density)`` covering a portion of the 24-hour dial.

    *density* is the number of concentric arcs to draw inside the twilight
    annulus. Higher = denser shading. Conventions:
        4 = night (deep / no-twilight darkness)
        3 = astronomical twilight
        2 = nautical twilight
        1 = civil twilight
        0 = daylight (caller skips drawing)

    When latitude/longitude are unavailable the function falls back to the
    OWM-reported sunrise/sunset and emits a single-density night band
    covering the dark hours.
    """
    if latitude is not None and longitude is not None and (latitude, longitude) != (0.0, 0.0):
        st = sun_times(today, latitude, longitude)
        events = [
            ("astro_dawn", _hours_of_day(st.astronomical_dawn, today, tz)),
            ("naut_dawn", _hours_of_day(st.nautical_dawn, today, tz)),
            ("civil_dawn", _hours_of_day(st.civil_dawn, today, tz)),
            ("sunrise", _hours_of_day(st.sunrise, today, tz)),
            ("sunset", _hours_of_day(st.sunset, today, tz)),
            ("civil_dusk", _hours_of_day(st.civil_dusk, today, tz)),
            ("naut_dusk", _hours_of_day(st.nautical_dusk, today, tz)),
            ("astro_dusk", _hours_of_day(st.astronomical_dusk, today, tz)),
        ]
        # If any are None (polar day/night) fall back to the simpler model.
        if all(v is not None for _, v in events):
            sunrise_hr = events[3][1]
            sunset_hr = events[4][1]
            ad, nd, cd, sr, ss, cdk, ndk, adk = (v for _, v in events)
            bands: list[tuple[float, float, int]] = [
                (0.0, ad, 4),  # midnight → astronomical dawn = night
                (ad, nd, 3),  # astronomical twilight (morning)
                (nd, cd, 2),  # nautical twilight (morning)
                (cd, sr, 1),  # civil twilight (morning)
                # daylight (sr → ss) = no band drawn
                (ss, cdk, 1),  # civil twilight (evening)
                (cdk, ndk, 2),  # nautical twilight (evening)
                (ndk, adk, 3),  # astronomical twilight (evening)
                (adk, 24.0, 4),  # astronomical dusk → midnight = night
            ]
            return sunrise_hr, sunset_hr, bands

    # Fallback: use weather sunrise/sunset only — single dark band before
    # sunrise and after sunset.
    sr_hr = _hours_of_day(weather_sunrise, today, tz) if weather_sunrise else None
    ss_hr = _hours_of_day(weather_sunset, today, tz) if weather_sunset else None
    if sr_hr is None or ss_hr is None:
        return None, None, []
    return sr_hr, ss_hr, [(0.0, sr_hr, 4), (ss_hr, 24.0, 4)]


# Angular spacing between radial dashes for each phase, in degrees.
# Smaller spacing = denser band. None = solid fill (deep night).
_PHASE_DASH_SPACING_DEG: dict[int, float | None] = {
    4: None,  # night — solid fill
    3: 1.5,  # astronomical twilight — very dense dashes
    2: 3.0,  # nautical twilight — medium dashes
    1: 5.0,  # civil twilight — sparse dashes
}


def _draw_twilight_band(
    draw: ImageDraw.ImageDraw,
    start_hr: float,
    end_hr: float,
    density: int,
    fill,
    bg,
) -> None:
    """Draw one twilight band inside the twilight annulus.

    Density 4 = solid filled annular wedge.  Densities 1–3 are radial-dash
    fields whose spacing decreases with darkness — sparse for civil twilight,
    very dense for astronomical twilight.
    """
    if density <= 0 or end_hr <= start_hr:
        return
    start_angle = _hour_to_pil_angle(start_hr)
    end_angle = _hour_to_pil_angle(end_hr)
    spacing = _PHASE_DASH_SPACING_DEG.get(density, 5.0)

    if spacing is None:
        # Solid filled annular wedge: outer pie filled, then inner pie stamps bg.
        draw.pieslice(_bbox(_TWILIGHT_OUTER_R), start_angle, end_angle, fill=fill)
        draw.pieslice(_bbox(_TWILIGHT_INNER_R), start_angle, end_angle, fill=bg)
        return

    # Radial dashes: a short line from inner to outer radius at each step.
    # Use the unwrapped (start, end) since the caller already split at midnight.
    span = end_angle - start_angle
    if span < 0:
        span += 360.0
    n = max(1, int(span // spacing))
    step = span / n
    for i in range(n + 1):
        a = math.radians((start_angle + i * step) % 360.0)
        x0 = _CENTER_X + int(round(_TWILIGHT_INNER_R * math.cos(a)))
        y0 = _CENTER_Y + int(round(_TWILIGHT_INNER_R * math.sin(a)))
        x1 = _CENTER_X + int(round(_TWILIGHT_OUTER_R * math.cos(a)))
        y1 = _CENTER_Y + int(round(_TWILIGHT_OUTER_R * math.sin(a)))
        draw.line([(x0, y0), (x1, y1)], fill=fill, width=1)


# ---------------------------------------------------------------------------
# Tick marks + numerals
# ---------------------------------------------------------------------------


def _draw_hour_ticks(draw: ImageDraw.ImageDraw, fill) -> None:
    """Draw 24 minor ticks on the rim, with 4 longer ticks at 00/06/12/18."""
    for hour in range(24):
        is_major = hour % 6 == 0
        inner = _MAJOR_TICK_INNER_R if is_major else _TICK_INNER_R
        x0, y0 = _polar(inner, hour)
        x1, y1 = _polar(_OUTER_R, hour)
        draw.line([(x0, y0), (x1, y1)], fill=fill, width=2 if is_major else 1)


def _draw_hour_labels(
    draw: ImageDraw.ImageDraw,
    style: ThemeStyle,
    fill,
) -> None:
    """Draw the 00 / 06 / 12 / 18 numerals just outside the rim."""
    label_font = (style.font_section_label or style.font_bold)(18)
    for hour, text in ((0, "00"), (6, "06"), (12, "12"), (18, "18")):
        x, y = _polar(_HOUR_LABEL_R, hour)
        tw = text_width(draw, text, label_font)
        th = text_height(label_font)
        draw.text((x - tw // 2, y - th // 2 - 1), text, font=label_font, fill=fill)


# ---------------------------------------------------------------------------
# Events ring
# ---------------------------------------------------------------------------


def _draw_event_ticks(
    draw: ImageDraw.ImageDraw,
    events: list,
    today: date,
    tz: tzinfo | None,
    fill,
    accent,
) -> int:
    """Draw small radial dashes for each timed event. Returns count drawn."""
    drawn = 0
    for ev in events:
        if ev.is_all_day:
            continue
        start = ev.start
        if not isinstance(start, datetime):
            continue
        hr = _hours_of_day(start, today, tz)
        if hr is None:
            continue
        x0, y0 = _polar(_EVENT_INNER_R, hr)
        x1, y1 = _polar(_EVENT_OUTER_R, hr)
        draw.line([(x0, y0), (x1, y1)], fill=accent, width=2)
        # A dot at the inner end so the mark reads even when fill matches bg
        draw.ellipse(
            (x0 - 2, y0 - 2, x0 + 2, y0 + 2),
            fill=accent,
            outline=fill,
        )
        drawn += 1
    return drawn


# ---------------------------------------------------------------------------
# Center content
# ---------------------------------------------------------------------------


def _draw_center_disc(
    draw: ImageDraw.ImageDraw,
    today: date,
    now: datetime,
    weather,
    style: ThemeStyle,
) -> None:
    """Render day-of-week, big date numeral, month, and weather summary."""
    fg = style.fg
    bg = style.bg
    font_bold = style.font_bold
    font_medium = style.font_medium
    font_regular = style.font_regular

    # Background disc — clear out anything from rings that bled inward.
    draw.ellipse(_bbox(_INNER_DISC_R), fill=bg, outline=style.primary_accent_fill())

    # Day-of-week, top of disc
    dow = now.strftime("%A").upper()
    dow_font = font_medium(13)
    dow_w = text_width(draw, dow, dow_font)
    draw.text(
        (_CENTER_X - dow_w // 2, _CENTER_Y - 70),
        dow,
        font=dow_font,
        fill=style.primary_accent_fill(),
    )

    # Big date numeral, centred
    day_str = str(today.day)
    day_font = (style.font_date_number or font_bold)(72)
    day_w = text_width(draw, day_str, day_font)
    day_h = text_height(day_font)
    draw.text(
        (_CENTER_X - day_w // 2, _CENTER_Y - day_h // 2 - 6),
        day_str,
        font=day_font,
        fill=fg,
    )

    # Month name below numeral
    month = today.strftime("%B").upper()
    month_font = font_medium(12)
    month_w = text_width(draw, month, month_font)
    draw.text(
        (_CENTER_X - month_w // 2, _CENTER_Y + 28),
        month,
        font=month_font,
        fill=fg,
    )

    # Weather summary at the bottom of the disc
    if weather is not None:
        temp_str = f"{weather.current_temp:.0f}°"
        if weather.high is not None and weather.low is not None:
            temp_str += f"   H {weather.high:.0f}°  L {weather.low:.0f}°"
        wx_font = font_regular(11)
        wx_w = text_width(draw, temp_str, wx_font)
        draw.text(
            (_CENTER_X - wx_w // 2, _CENTER_Y + 52),
            temp_str,
            font=wx_font,
            fill=fg,
        )


# ---------------------------------------------------------------------------
# Sun/moon glyph + needle
# ---------------------------------------------------------------------------


def _draw_now_glyph_and_needle(
    draw: ImageDraw.ImageDraw,
    now: datetime,
    today: date,
    sunrise_hr: float | None,
    sunset_hr: float | None,
    style: ThemeStyle,
) -> None:
    """Draw the needle pointing to current time and the sun/moon glyph at the rim."""
    now_naive = _to_local_naive(now, now.tzinfo)
    now_hr = now_naive.hour + now_naive.minute / 60.0 + now_naive.second / 3600.0

    # Needle: a tapered triangle running from the inner disc out to the rim.
    accent = style.secondary_accent_fill()
    needle_inner = _INNER_DISC_R + 2
    needle_outer = _OUTER_R - 8
    rad = _hour_to_radians(now_hr)
    # Perpendicular direction for the base of the triangle
    perp = rad + math.pi / 2
    base_w = 4
    bx0 = _CENTER_X + int(round(needle_inner * math.cos(rad) + base_w * math.cos(perp)))
    by0 = _CENTER_Y + int(round(needle_inner * math.sin(rad) + base_w * math.sin(perp)))
    bx1 = _CENTER_X + int(round(needle_inner * math.cos(rad) - base_w * math.cos(perp)))
    by1 = _CENTER_Y + int(round(needle_inner * math.sin(rad) - base_w * math.sin(perp)))
    tx = _CENTER_X + int(round(needle_outer * math.cos(rad)))
    ty = _CENTER_Y + int(round(needle_outer * math.sin(rad)))
    draw.polygon([(bx0, by0), (tx, ty), (bx1, by1)], fill=accent, outline=style.fg)

    # Glyph: sun when daytime, moon when night
    is_day = sunrise_hr is not None and sunset_hr is not None and sunrise_hr <= now_hr <= sunset_hr
    if is_day:
        glyph = OWM_ICON_MAP.get("01d", FALLBACK_ICON)
        glyph_fill = style.primary_accent_fill()
    else:
        glyph = moon_phase_glyph(today)
        glyph_fill = style.fg
    glyph_font = weather_icon(30)
    gx, gy = _polar(_GLYPH_R + 22, now_hr)
    bbox = draw.textbbox((0, 0), glyph, font=glyph_font)
    gw, gh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Clear a small disc behind the glyph so it reads against the twilight band
    halo_r = max(gw, gh) // 2 + 5
    draw.ellipse(
        (gx - halo_r, gy - halo_r, gx + halo_r, gy + halo_r),
        fill=style.bg,
        outline=style.fg,
    )
    draw.text(
        (gx - gw // 2 - bbox[0], gy - gh // 2 - bbox[1]),
        glyph,
        font=glyph_font,
        fill=glyph_fill,
    )


# ---------------------------------------------------------------------------
# Header + footer strips
# ---------------------------------------------------------------------------


def _draw_header_strip(
    draw: ImageDraw.ImageDraw,
    region: ComponentRegion,
    today: date,
    weather,
    style: ThemeStyle,
) -> None:
    title_font = (style.font_title or style.font_bold)(15)
    label_font = (style.font_section_label or style.font_bold)(11)
    fg = style.fg

    title = "LIGHT  CYCLE"
    draw.text(
        (region.x + 18, region.y + 12),
        title,
        font=title_font,
        fill=style.primary_accent_fill(),
    )

    if weather is not None and weather.location_name:
        loc = weather.location_name.upper()
        loc_w = text_width(draw, loc, label_font)
        draw.text(
            (region.x + region.w - loc_w - 18, region.y + 16),
            loc,
            font=label_font,
            fill=fg,
        )


def _draw_footer_legend(
    draw: ImageDraw.ImageDraw,
    region: ComponentRegion,
    sunrise_hr: float | None,
    sunset_hr: float | None,
    event_count: int,
    style: ThemeStyle,
) -> None:
    """Bottom strip: sunrise/sunset times + today's event count."""
    fy = region.y + region.h - 28
    label_font = (style.font_section_label or style.font_bold)(10)
    val_font = style.font_semibold(13)
    fg = style.fg

    def _fmt(hr: float | None) -> str:
        if hr is None:
            return "—"
        h = int(hr) % 24
        m = int(round((hr - int(hr)) * 60)) % 60
        suffix = "a" if h < 12 else "p"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d}{suffix}"

    items = [
        ("RISE", _fmt(sunrise_hr)),
        ("SET", _fmt(sunset_hr)),
        ("EVENTS", str(event_count)),
    ]
    # Render evenly spaced across the canvas
    slot_w = region.w // len(items)
    for i, (label, value) in enumerate(items):
        cx = region.x + slot_w * i + slot_w // 2
        lw = text_width(draw, label, label_font)
        vw = text_width(draw, value, val_font)
        draw.text(
            (cx - lw // 2, fy),
            label,
            font=label_font,
            fill=style.primary_accent_fill(),
        )
        draw.text(
            (cx - vw // 2, fy + 12),
            value,
            font=val_font,
            fill=fg,
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_light_cycle(
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
    """Render the full-canvas Light Cycle radial 24-hour clock."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    fg = style.fg
    weather = data.weather
    tz = now.tzinfo

    # Header strip
    _draw_header_strip(draw, region, today, weather, style)

    # Outer rim circle
    draw.ellipse(_bbox(_OUTER_R), outline=fg, width=2)

    # Twilight bands
    weather_sunrise = weather.sunrise if weather else None
    weather_sunset = weather.sunset if weather else None
    sunrise_hr, sunset_hr, bands = _resolve_sun_times(
        today, weather_sunrise, weather_sunset, latitude, longitude, tz
    )
    for start_hr, end_hr, density in bands:
        _draw_twilight_band(draw, start_hr, end_hr, density, style.fg, style.bg)

    # Subtle inner + outer guide circles framing the twilight ring
    draw.ellipse(_bbox(_TWILIGHT_OUTER_R), outline=fg, width=1)
    draw.ellipse(_bbox(_TWILIGHT_INNER_R), outline=fg, width=1)

    # Hour ticks + labels
    _draw_hour_ticks(draw, fg)
    _draw_hour_labels(draw, style, fg)

    # Event ring
    timed_events = events_for_day(data.events, today)
    event_count = _draw_event_ticks(
        draw, timed_events, today, tz, fg, style.secondary_accent_fill()
    )

    # Center disc (drawn after rings so it masks anything that bled inward)
    _draw_center_disc(draw, today, now, weather, style)

    # Now-glyph + needle on top of everything
    _draw_now_glyph_and_needle(draw, now, today, sunrise_hr, sunset_hr, style)

    # Footer legend
    _draw_footer_legend(draw, region, sunrise_hr, sunset_hr, event_count, style)
