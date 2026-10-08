"""light_cycle_panel.py — 24-hour radial clock theme.

The day as one dial, with the details beside it:

  * Dial (left): 24 hour ticks with numerals at 00 / 06 / 12 / 18; a light
    band whose tone encodes the sky — solid at night, engraved concentric
    rings for astronomical / nautical / civil twilight (denser = darker),
    open in daylight; today's timed events as arcs spanning their duration
    (hollow once they have ended); the sun (or moon) riding the light band
    at the current time, with a needle from the centre.
  * Centre disc: day name, the day-of-month numeral, month.
  * Info column (right): sunrise, sunset and day length with its change
    since yesterday; the current weather; today's agenda.

Twilight comes from :mod:`src.astronomy` when coordinates are configured,
falling back to the OWM sunrise / sunset otherwise. On a colour panel the
daylight span is filled with the primary accent and the twilight rings take
the secondary; type is never set in an accent, since yellow on the Spectra
white is unreadable.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, tzinfo

from PIL import ImageDraw

from src.astronomy import sun_times
from src.data.models import DashboardData
from src.render.artkit import hours_of_day as _hours_of_day
from src.render.artkit import to_local_naive as _to_local_naive
from src.render.fonts import weather_icon
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_phase_glyph
from src.render.primitives import (
    draw_text_truncated,
    events_for_day,
    fmt_deg,
    fmt_time,
    text_height,
    text_width,
    usable_coords,
)
from src.render.theme import ComponentRegion, ThemeStyle

# Dial geometry

_CENTER_X = 262
_CENTER_Y = 240
_OUTER_R = 196  # rim of the clock face
_TICK_INNER_R = 187  # minor hour ticks start here
_MAJOR_TICK_INNER_R = 178  # major (every 6h) ticks start here
_HOUR_LABEL_R = 213  # numerals sit just outside the rim
_TWILIGHT_OUTER_R = 174
_TWILIGHT_INNER_R = 140
_EVENT_OUTER_R = 132
_EVENT_LANE_W = 9  # two lanes inward from _EVENT_OUTER_R, 2 px apart
_INNER_DISC_R = 104  # central content area radius

# Info column

_COL_X0 = 500
_COL_X1 = 784


# Polar coordinate helpers


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


# Twilight bands


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
    coords = usable_coords(latitude, longitude)
    if coords is not None:
        st = sun_times(today, *coords)
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
            ad, nd, cd, sr, ss, cdk, ndk, adk = (v for _, v in events if v is not None)
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


# Pitch, in pixels, of the concentric rings that shade each twilight phase:
# a tighter pitch reads darker. Night (4) is solid.
_PHASE_RING_PITCH: dict[int, int | None] = {
    4: None,  # night — solid fill
    3: 2,  # astronomical twilight
    2: 3,  # nautical twilight
    1: 5,  # civil twilight
}


def _draw_twilight_band(
    draw: ImageDraw.ImageDraw,
    start_hr: float,
    end_hr: float,
    density: int,
    fill,
    bg,
) -> None:
    """Shade one phase of the light band between *start_hr* and *end_hr*.

    Density 4 is a solid annular wedge; 1–3 are concentric one-pixel rings
    whose pitch tightens as the sky darkens — an engraver's tint, which holds
    its tone on a 1-bit panel where a dither would speckle.
    """
    if density <= 0 or end_hr <= start_hr:
        return
    start_angle = _hour_to_pil_angle(start_hr)
    end_angle = _hour_to_pil_angle(end_hr)
    pitch = _PHASE_RING_PITCH.get(density, 5)
    if pitch is None:
        draw.pieslice(_bbox(_TWILIGHT_OUTER_R), start_angle, end_angle, fill=fill)
        draw.pieslice(_bbox(_TWILIGHT_INNER_R), start_angle, end_angle, fill=bg)
        return
    for radius in range(_TWILIGHT_INNER_R + pitch, _TWILIGHT_OUTER_R, pitch):
        draw.arc(_bbox(radius), start_angle, end_angle, fill=fill)


def _fill_daylight(draw: ImageDraw.ImageDraw, sunrise_hr: float, sunset_hr: float, fill, bg):
    """Fill the daylight span of the light band (colour panels only)."""
    if sunset_hr <= sunrise_hr:
        return
    start, end = _hour_to_pil_angle(sunrise_hr), _hour_to_pil_angle(sunset_hr)
    draw.pieslice(_bbox(_TWILIGHT_OUTER_R), start, end, fill=fill)
    draw.pieslice(_bbox(_TWILIGHT_INNER_R), start, end, fill=bg)


def _draw_horizon_marks(draw: ImageDraw.ImageDraw, hours: list[float], fill) -> None:
    """A heavy radial rule across the light band at sunrise and sunset."""
    for hr in hours:
        draw.line(
            [_polar(_TWILIGHT_INNER_R - 3, hr), _polar(_TWILIGHT_OUTER_R + 3, hr)],
            fill=fill,
            width=3,
        )


# Tick marks + numerals


def _draw_hour_ticks(draw: ImageDraw.ImageDraw, fill) -> None:
    """24 hour ticks on the rim (longer at 00/06/12/18) and quarter-hour pips."""
    for quarter in range(96):
        hour = quarter / 4
        if quarter % 4:
            draw.line([_polar(_OUTER_R - 4, hour), _polar(_OUTER_R, hour)], fill=fill)
            continue
        is_major = quarter % 24 == 0
        inner = _MAJOR_TICK_INNER_R if is_major else _TICK_INNER_R
        draw.line(
            [_polar(inner, hour), _polar(_OUTER_R, hour)], fill=fill, width=3 if is_major else 2
        )


def _draw_hour_labels(
    draw: ImageDraw.ImageDraw,
    style: ThemeStyle,
    fill,
) -> None:
    """Draw the 00 / 06 / 12 / 18 numerals just outside the rim."""
    label_font = (style.font_section_label or style.font_bold)(18)
    for hour, text in ((0, "00"), (6, "06"), (12, "12"), (18, "18")):
        x, y = _polar(_HOUR_LABEL_R, hour)
        bb = draw.textbbox((0, 0), text, font=label_font)
        draw.text(
            (x - (bb[2] - bb[0]) / 2 - bb[0], y - (bb[3] - bb[1]) / 2 - bb[1]),
            text,
            font=label_font,
            fill=fill,
        )


# Events ring


def _event_spans(events: list, today: date, tz: tzinfo | None) -> list[tuple[float, float]]:
    """``(start_hr, end_hr)`` for each timed event on *today*; all-day events have none."""
    spans = []
    for ev in events:
        if ev.is_all_day or not isinstance(ev.start, datetime):
            continue
        start = _hours_of_day(ev.start, today, tz)
        if start is None:
            continue
        end = _hours_of_day(ev.end, today, tz) if isinstance(ev.end, datetime) else None
        # A sliver at least 10 minutes wide, so a zero-length event still shows.
        end = max(end if end is not None else start, start + 1 / 6)
        spans.append((start, min(end, 24.0)))
    return spans


def _pack_lanes(spans: list[tuple[float, float]]) -> list[int]:
    """Lane 0 unless the span overlaps the last one placed there; then lane 1."""
    lane_end = [-1.0, -1.0]
    lanes = []
    for start, end in spans:
        lane = 0 if start >= lane_end[0] else 1
        lane_end[lane] = max(lane_end[lane], end)
        lanes.append(lane)
    return lanes


def _draw_event_arcs(
    draw: ImageDraw.ImageDraw,
    spans: list[tuple[float, float]],
    now_hr: float,
    fill,
    bg,
) -> int:
    """Draw each event as an arc over its duration; ended events are hollow."""
    for (start, end), lane in zip(spans, _pack_lanes(spans)):
        outer = _EVENT_OUTER_R - lane * (_EVENT_LANE_W + 2)
        a0, a1 = _hour_to_pil_angle(start), _hour_to_pil_angle(end)
        draw.arc(_bbox(outer), a0, a1, fill=fill, width=_EVENT_LANE_W)
        if end <= now_hr:
            inset = 1.6  # degrees, so the hollow keeps its end caps
            if (a1 - a0) % 360 > 2 * inset:
                draw.arc(_bbox(outer - 2), a0 + inset, a1 - inset, fill=bg, width=_EVENT_LANE_W - 4)
    return len(spans)


# Center content


def _draw_center_disc(
    draw: ImageDraw.ImageDraw,
    today: date,
    style: ThemeStyle,
) -> None:
    """Day-of-week above the date numeral, month below, centred on the dial."""
    fg = style.fg
    draw.ellipse(_bbox(_INNER_DISC_R), fill=style.bg, outline=fg, width=2)
    draw.ellipse(_bbox(_INNER_DISC_R - 5), outline=fg)

    day_str = str(today.day)
    day_font = (style.font_date_number or style.font_bold)(84)
    day_bbox = draw.textbbox((0, 0), day_str, font=day_font)
    day_h = day_bbox[3] - day_bbox[1]
    draw.text(
        (
            _CENTER_X - (day_bbox[2] - day_bbox[0]) / 2 - day_bbox[0],
            _CENTER_Y - day_h / 2 - day_bbox[1] + 2,
        ),
        day_str,
        font=day_font,
        fill=fg,
    )
    gap = 10
    label_font = style.font_bold(14)
    for text, above in (
        (today.strftime("%A").upper(), True),
        (today.strftime("%B").upper(), False),
    ):
        tb = draw.textbbox((0, 0), text, font=label_font)
        th = tb[3] - tb[1]
        ty = _CENTER_Y - day_h / 2 - gap - th if above else _CENTER_Y + day_h / 2 + gap + 2
        draw.text(
            (_CENTER_X - (tb[2] - tb[0]) / 2 - tb[0], ty - tb[1]), text, font=label_font, fill=fg
        )


# Sun/moon glyph + needle


def _now_hours(now: datetime) -> float:
    now_naive = _to_local_naive(now, now.tzinfo)
    return now_naive.hour + now_naive.minute / 60.0 + now_naive.second / 3600.0


def _draw_now_glyph_and_needle(
    draw: ImageDraw.ImageDraw,
    now_hr: float,
    today: date,
    sunrise_hr: float | None,
    sunset_hr: float | None,
    style: ThemeStyle,
) -> None:
    """Needle from the disc to the light band, and the sun or moon riding the band."""
    band_r = (_TWILIGHT_INNER_R + _TWILIGHT_OUTER_R) / 2
    halo_r = 19

    rad = _hour_to_radians(now_hr)
    perp = rad + math.pi / 2
    base_r = _INNER_DISC_R + 1
    tip_r = band_r - halo_r - 1
    base_w = 5
    base = (_CENTER_X + base_r * math.cos(rad), _CENTER_Y + base_r * math.sin(rad))
    draw.polygon(
        [
            (base[0] + base_w * math.cos(perp), base[1] + base_w * math.sin(perp)),
            (_CENTER_X + tip_r * math.cos(rad), _CENTER_Y + tip_r * math.sin(rad)),
            (base[0] - base_w * math.cos(perp), base[1] - base_w * math.sin(perp)),
        ],
        fill=style.secondary_accent_fill(),
        outline=style.fg,
    )

    is_day = sunrise_hr is not None and sunset_hr is not None and sunrise_hr <= now_hr <= sunset_hr
    glyph = OWM_ICON_MAP.get("01d", FALLBACK_ICON) if is_day else moon_phase_glyph(today)
    # By day the halo takes the primary accent (yellow on colour, paper on mono)
    # and the glyph stays ink, so it reads on either.
    halo_fill = style.primary_accent_fill() if is_day else style.bg
    if halo_fill == style.fg:
        halo_fill = style.bg
    gx = _CENTER_X + band_r * math.cos(rad)
    gy = _CENTER_Y + band_r * math.sin(rad)
    draw.ellipse(
        (gx - halo_r, gy - halo_r, gx + halo_r, gy + halo_r),
        fill=halo_fill,
        outline=style.fg,
        width=2,
    )
    glyph_font = weather_icon(24)
    bbox = draw.textbbox((0, 0), glyph, font=glyph_font)
    draw.text(
        (gx - (bbox[2] - bbox[0]) / 2 - bbox[0], gy - (bbox[3] - bbox[1]) / 2 - bbox[1]),
        glyph,
        font=glyph_font,
        fill=style.fg,
    )


# Info column


def _fmt_hours(hr: float | None) -> str:
    """``6:31a`` for fractional hours-of-day; an em dash for none."""
    if hr is None:
        return "—"
    # Round to the minute before splitting so 23:59:30 carries into the hour.
    total_minutes = int(round(hr * 60.0)) % (24 * 60)
    h, m = divmod(total_minutes, 60)
    suffix = "a" if h < 12 else "p"
    return f"{h % 12 or 12}:{m:02d}{suffix}"


def _day_length_change(
    today: date, latitude: float | None, longitude: float | None
) -> timedelta | None:
    """Today's day length minus yesterday's, or ``None`` without coordinates."""
    coords = usable_coords(latitude, longitude)
    if coords is None:
        return None
    spans = []
    for day in (today - timedelta(days=1), today):
        st = sun_times(day, *coords)
        if st.sunrise is None or st.sunset is None:
            return None
        spans.append(st.sunset - st.sunrise)
    return spans[1] - spans[0]


def _fmt_change(delta: timedelta) -> str:
    seconds = int(round(delta.total_seconds()))
    sign = "+" if seconds >= 0 else "−"
    minutes, secs = divmod(abs(seconds), 60)
    return f"{sign}{minutes}m {secs:02d}s"


def _column_label(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, style) -> None:
    draw.text((x, y), text, font=(style.font_section_label or style.font_bold)(11), fill=style.fg)


def _draw_sun_section(
    draw: ImageDraw.ImageDraw,
    y: int,
    sunrise_hr: float | None,
    sunset_hr: float | None,
    change: timedelta | None,
    style: ThemeStyle,
) -> int:
    """Sunrise / sunset / day length as a three-up row. Returns the next free y."""
    value_font = style.font_bold(24)
    slot = (_COL_X1 - _COL_X0) // 3
    length = None
    if sunrise_hr is not None and sunset_hr is not None and sunset_hr > sunrise_hr:
        minutes = int(round((sunset_hr - sunrise_hr) * 60))
        length = f"{minutes // 60}h {minutes % 60:02d}m"
    cells = (
        ("SUNRISE", _fmt_hours(sunrise_hr)),
        ("SUNSET", _fmt_hours(sunset_hr)),
        ("DAYLIGHT", length or "—"),
    )
    for i, (label, value) in enumerate(cells):
        x = _COL_X0 + i * slot
        _column_label(draw, x, y, label, style)
        draw.text((x, y + 16), value, font=value_font, fill=style.fg)
    if change is not None:
        # Right-aligned under DAYLIGHT; it may run back under SUNSET, which is empty there.
        caption = f"{_fmt_change(change)} vs yesterday"
        font = style.font_medium(11)
        draw.text(
            (_COL_X1 - text_width(draw, caption, font), y + 46), caption, font=font, fill=style.fg
        )
    return y + 66


def _draw_weather_section(draw: ImageDraw.ImageDraw, y: int, weather, style: ThemeStyle) -> int:
    """Icon, current temperature, condition and range. Returns the next free y."""
    if weather is None:
        return y
    icon = OWM_ICON_MAP.get(weather.current_icon, FALLBACK_ICON)
    icon_font = weather_icon(38)
    ib = draw.textbbox((0, 0), icon, font=icon_font)
    draw.text((_COL_X0 - ib[0], y + 4 - ib[1]), icon, font=icon_font, fill=style.fg)
    temp_x = _COL_X0 + (ib[2] - ib[0]) + 14
    temp_font = style.font_bold(40)
    temp = fmt_deg(weather.current_temp)
    tb = draw.textbbox((0, 0), temp, font=temp_font)
    draw.text((temp_x - tb[0], y + 2 - tb[1]), temp, font=temp_font, fill=style.fg)
    text_x = temp_x + (tb[2] - tb[0]) + 16
    desc = (weather.current_description or "").capitalize()
    draw_text_truncated(
        draw, (text_x, y + 2), desc, style.font_semibold(15), _COL_X1 - text_x, fill=style.fg
    )
    if weather.high is not None and weather.low is not None:
        draw.text(
            (text_x, y + 23),
            f"H {fmt_deg(weather.high)}   L {fmt_deg(weather.low)}",
            font=style.font_medium(14),
            fill=style.fg,
        )
    return y + 56


def _draw_agenda(
    draw: ImageDraw.ImageDraw,
    y: int,
    bottom: int,
    events: list,
    now: datetime,
    style: ThemeStyle,
) -> None:
    """Today's events, one per row; a hollow marker once an event has ended."""
    count = len(events)
    label = "TODAY" if not count else f"TODAY · {count} EVENT{'S' if count != 1 else ''}"
    _column_label(draw, _COL_X0, y, label, style)
    y += 22
    if not events:
        draw.text((_COL_X0, y), "Nothing scheduled", font=style.font_medium(15), fill=style.fg)
        return
    row_h = 30
    time_font = style.font_semibold(15)
    title_font = style.font_medium(17)
    now_naive = _to_local_naive(now, now.tzinfo)
    time_w = 62
    for idx, ev in enumerate(events):
        # While events follow, keep a row free for the "+N more" line.
        needed = row_h if idx == count - 1 else 2 * row_h
        if y + needed > bottom:
            draw.text((_COL_X0, y), f"+{count - idx} more", font=time_font, fill=style.fg)
            return
        # Event times are naive local, like the render clock once localised.
        ended = not ev.is_all_day and isinstance(ev.end, datetime) and ev.end <= now_naive
        cy = y + text_height(title_font) // 2 + 1
        box = (_COL_X0, cy - 4, _COL_X0 + 8, cy + 4)
        if ended:
            draw.rectangle(box, outline=style.fg)
        else:
            draw.rectangle(box, fill=style.fg)
        when = "all day" if ev.is_all_day else fmt_time(ev.start)
        draw.text((_COL_X0 + 16, y), when, font=time_font, fill=style.fg)
        title_x = _COL_X0 + 16 + time_w
        draw_text_truncated(
            draw, (title_x, y), ev.summary, title_font, _COL_X1 - title_x, fill=style.fg
        )
        y += row_h


def _draw_column_heading(draw: ImageDraw.ImageDraw, weather, style: ThemeStyle) -> None:
    title = "LIGHT CYCLE"
    if weather is not None and weather.location_name:
        title = f"{title} · {weather.location_name.upper()}"
    draw_text_truncated(
        draw, (_COL_X0, 22), title, style.font_bold(13), _COL_X1 - _COL_X0, fill=style.fg
    )
    draw.line([(_COL_X0, 44), (_COL_X1, 44)], fill=style.fg, width=2)


def _rule(draw: ImageDraw.ImageDraw, y: int, style: ThemeStyle) -> None:
    draw.line([(_COL_X0, y), (_COL_X1, y)], fill=style.fg)


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
    now_hr = _now_hours(now)
    is_colour = style.primary_accent_fill() != fg

    # Light band
    weather_sunrise = weather.sunrise if weather else None
    weather_sunset = weather.sunset if weather else None
    sunrise_hr, sunset_hr, bands = _resolve_sun_times(
        today, weather_sunrise, weather_sunset, latitude, longitude, tz
    )
    if is_colour and sunrise_hr is not None and sunset_hr is not None:
        _fill_daylight(draw, sunrise_hr, sunset_hr, style.primary_accent_fill(), style.bg)
    ring_fill = style.secondary_accent_fill()
    for start_hr, end_hr, density in bands:
        _draw_twilight_band(
            draw, start_hr, end_hr, density, fg if density == 4 else ring_fill, style.bg
        )
    draw.ellipse(_bbox(_TWILIGHT_OUTER_R), outline=fg)
    draw.ellipse(_bbox(_TWILIGHT_INNER_R), outline=fg)
    if sunrise_hr is not None and sunset_hr is not None:
        _draw_horizon_marks(draw, [sunrise_hr, sunset_hr], fg)

    # Rim
    draw.ellipse(_bbox(_OUTER_R), outline=fg, width=3)
    _draw_hour_ticks(draw, fg)
    _draw_hour_labels(draw, style, fg)

    # Events
    todays = events_for_day(data.events, today)
    _draw_event_arcs(draw, _event_spans(todays, today, tz), now_hr, fg, style.bg)

    _draw_center_disc(draw, today, style)
    _draw_now_glyph_and_needle(draw, now_hr, today, sunrise_hr, sunset_hr, style)

    # Info column
    _draw_column_heading(draw, weather, style)
    y = _draw_sun_section(
        draw, 60, sunrise_hr, sunset_hr, _day_length_change(today, latitude, longitude), style
    )
    if weather is not None:
        _rule(draw, y, style)
        y = _draw_weather_section(draw, y + 14, weather, style)
    _rule(draw, y, style)
    _draw_agenda(draw, y + 14, region.y + region.h - 16, todays, now, style)
