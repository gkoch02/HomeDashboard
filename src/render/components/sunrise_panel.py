"""sunrise_panel.py — Sun-arc daylight dashboard panel.

Renders a semicircular sun arc showing the sun's position between sunrise and
sunset, with today's events split into daylight and evening columns.  A compact
weather/AQI/year-progress footer runs along the bottom.
"""

from __future__ import annotations

import calendar
import math
from datetime import date, datetime

from PIL import ImageDraw

from src.data.models import DashboardData
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_illumination, moon_phase_glyph, moon_phase_name
from src.render.primitives import (
    BLACK,
    dashed_hline,
    draw_text_truncated,
    events_for_day,
    filled_rect,
    fmt_time,
    hline,
    text_height,
    text_width,
    vline,
)
from src.render.theme import ComponentRegion, ThemeStyle

# Layout constants
_HEADER_H = 36
_ARC_H = 170
_FOOTER_H = 80
_SCHEDULE_H = 480 - _HEADER_H - _ARC_H - _FOOTER_H  # 194
_PAD = 12


def _sun_position_fraction(now: datetime, sunrise: datetime, sunset: datetime) -> float:
    """Return 0.0–1.0 fraction of day elapsed between sunrise and sunset.

    Returns negative values before sunrise and values >1.0 after sunset.
    """
    total = (sunset - sunrise).total_seconds()
    if total <= 0:
        return 0.5
    elapsed = (now - sunrise).total_seconds()
    return elapsed / total


def _angle_from_fraction(frac: float) -> float:
    """Convert a 0-1 fraction to an angle on the arc (pi to 0, left to right)."""
    return math.pi * (1.0 - frac)


def _stipple_fill(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    fill: int = BLACK,
) -> None:
    """Fill a region with a stippled dot pattern (checkerboard every 3px)."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if (x + y) % 3 == 0:
                draw.point((x, y), fill=fill)


def draw_sunrise(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the sunrise sun-arc dashboard."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    x0, y0, w, _h = region.x, region.y, region.w, region.h
    fg, bg = style.fg, style.bg
    font_title = style.font_title or style.font_bold
    font_label = style.font_section_label or style.font_bold
    font_body = style.font_regular

    weather = data.weather
    # Strip tzinfo from all datetimes for safe naive comparison
    now_naive = now.replace(tzinfo=None)
    sunrise_dt = weather.sunrise.replace(tzinfo=None) if weather and weather.sunrise else None
    sunset_dt = weather.sunset.replace(tzinfo=None) if weather and weather.sunset else None

    # ── Header ──────────────────────────────────────────────────────────
    header_y = y0
    filled_rect(draw, (x0, header_y, x0 + w - 1, header_y + _HEADER_H - 1), fill=fg)

    title_font = font_title(14)
    date_str = now.strftime("%A, %b %-d")
    time_str = now.strftime("%-I:%M%p").lower().replace("am", "a").replace("pm", "p")
    draw.text((x0 + _PAD, header_y + 8), "Home Dashboard", font=title_font, fill=bg)

    right_text = f"{date_str}  {time_str}"
    if weather:
        right_text += f"   {weather.current_temp:.0f}°"
    rt_w = text_width(draw, right_text, font_title(13))
    draw.text((x0 + w - rt_w - _PAD, header_y + 9), right_text, font=font_title(13), fill=bg)

    # ── Sun Arc Area ────────────────────────────────────────────────────
    arc_y = header_y + _HEADER_H
    arc_cx = x0 + w // 2
    arc_radius = 120
    horizon_y = arc_y + _ARC_H - 40  # horizon line position
    arc_cy = horizon_y  # arc centre on the horizon

    # Draw the arc (semicircle above horizon)
    arc_bbox = (
        arc_cx - arc_radius,
        arc_cy - arc_radius,
        arc_cx + arc_radius,
        arc_cy + arc_radius,
    )
    draw.arc(arc_bbox, 180, 360, fill=fg, width=2)

    # Tick marks along the arc at 3-hour intervals
    if sunrise_dt and sunset_dt:
        total_hours = (sunset_dt - sunrise_dt).total_seconds() / 3600
        for tick_h in range(0, int(total_hours) + 1, 3):
            frac = tick_h / total_hours if total_hours > 0 else 0.5
            frac = max(0.0, min(1.0, frac))
            angle = _angle_from_fraction(frac)
            tx = arc_cx + int(arc_radius * math.cos(angle))
            ty = arc_cy - int(arc_radius * math.sin(angle))
            # Small tick
            draw.line(
                [
                    (tx, ty),
                    (
                        tx + int(6 * math.cos(angle)),
                        ty - int(6 * math.sin(angle)),
                    ),
                ],
                fill=fg,
                width=1,
            )

    # Position the sun or moon glyph on the arc
    from src.render.fonts import weather_icon

    is_daytime = sunrise_dt and sunset_dt and sunrise_dt <= now_naive <= sunset_dt
    if sunrise_dt and sunset_dt:
        frac = _sun_position_fraction(now_naive, sunrise_dt, sunset_dt)
        frac_clamped = max(0.0, min(1.0, frac))
        angle = _angle_from_fraction(frac_clamped)
        glyph_x = arc_cx + int(arc_radius * math.cos(angle))
        glyph_y = arc_cy - int(arc_radius * math.sin(angle))

        if is_daytime:
            # Sun glyph
            glyph = OWM_ICON_MAP.get("01d", FALLBACK_ICON)
            glyph_font = weather_icon(28)
        else:
            # Moon glyph
            glyph = moon_phase_glyph(today)
            glyph_font = weather_icon(28)

        gb = draw.textbbox((0, 0), glyph, font=glyph_font)
        gw, gh = gb[2] - gb[0], gb[3] - gb[1]
        draw.text((glyph_x - gw // 2, glyph_y - gh // 2), glyph, font=glyph_font, fill=fg)

    # Horizon line (dashed)
    dashed_hline(draw, horizon_y, x0 + _PAD, x0 + w - _PAD, on=4, off=4, fill=fg)

    # Sunrise/sunset labels on horizon
    if sunrise_dt:
        sr_str = fmt_time(sunrise_dt)
        draw.text((x0 + _PAD, horizon_y + 3), sr_str, font=font_body(11), fill=fg)
    if sunset_dt:
        ss_str = fmt_time(sunset_dt)
        ss_w = text_width(draw, ss_str, font_body(11))
        draw.text((x0 + w - ss_w - _PAD, horizon_y + 3), ss_str, font=font_body(11), fill=fg)

    # Stippled ground below horizon
    ground_top = horizon_y + 18
    ground_bottom = arc_y + _ARC_H - 1
    if ground_bottom > ground_top:
        _stipple_fill(draw, x0, ground_top, x0 + w - 1, ground_bottom, fill=fg)

    # ── Schedule (Daylight / Tonight) ───────────────────────────────────
    sched_y = arc_y + _ARC_H
    hline(draw, sched_y, x0, x0 + w - 1, fill=fg)

    half_w = w // 2
    vline(draw, x0 + half_w, sched_y, sched_y + _SCHEDULE_H - 1, fill=fg)

    today_events = events_for_day(data.events, today)
    timed_events = [e for e in today_events if not e.is_all_day]
    allday_events = [e for e in today_events if e.is_all_day]

    # Split timed events by sunset
    if sunset_dt:
        day_events = [e for e in timed_events if e.start < sunset_dt]
        night_events = [e for e in timed_events if e.start >= sunset_dt]
    else:
        day_events = timed_events
        night_events = []

    # Column labels
    label_font = font_label(11)
    draw.text((x0 + _PAD, sched_y + 4), "DAYLIGHT", font=label_font, fill=fg)
    draw.text((x0 + half_w + _PAD, sched_y + 4), "TONIGHT", font=label_font, fill=fg)

    label_h = text_height(label_font) + 8
    row_font = font_body(12)
    row_h = text_height(row_font) + 4
    max_rows = (_SCHEDULE_H - label_h - 4) // row_h

    # Draw daylight events
    ey = sched_y + label_h
    for i, ev in enumerate(allday_events[:1] + day_events[: max_rows - 1]):
        if ev.is_all_day:
            line = f"all day  {ev.summary}"
        else:
            line = f"{fmt_time(ev.start)}  {ev.summary}"
        draw_text_truncated(draw, (x0 + _PAD, ey), line, row_font, half_w - _PAD * 2, fill=fg)
        ey += row_h

    # Draw evening events
    ey = sched_y + label_h
    for i, ev in enumerate(night_events[:max_rows]):
        line = f"{fmt_time(ev.start)}  {ev.summary}"
        draw_text_truncated(
            draw, (x0 + half_w + _PAD, ey), line, row_font, half_w - _PAD * 2, fill=fg
        )
        ey += row_h

    # Moon phase in evening column (if space and no events fill it)
    if len(night_events) < max_rows - 2:
        moon_y = sched_y + _SCHEDULE_H - 36
        moon_glyph = moon_phase_glyph(today)
        moon_name = moon_phase_name(today)
        illum = moon_illumination(today)
        moon_font = weather_icon(22)
        info_font = font_body(11)
        draw.text((x0 + half_w + _PAD, moon_y), moon_glyph, font=moon_font, fill=fg)
        moon_text = f"{moon_name}  {illum:.0f}%"
        draw.text((x0 + half_w + _PAD + 28, moon_y + 3), moon_text, font=info_font, fill=fg)

    # ── Footer ──────────────────────────────────────────────────────────
    footer_y = sched_y + _SCHEDULE_H
    hline(draw, footer_y, x0, x0 + w - 1, fill=fg)

    footer_font = font_body(13)
    fy = footer_y + 8
    fx = x0 + _PAD

    # Weather icon + temp
    if weather:
        wi_glyph = OWM_ICON_MAP.get(weather.current_icon, FALLBACK_ICON)
        wi_font = weather_icon(20)
        draw.text((fx, fy - 2), wi_glyph, font=wi_font, fill=fg)
        fx += 24
        temp_str = f"{weather.current_temp:.0f}°  {weather.current_description.title()}"
        draw.text((fx, fy), temp_str, font=footer_font, fill=fg)
        fx += text_width(draw, temp_str, footer_font) + 16
        hilo = f"H:{weather.high:.0f}° L:{weather.low:.0f}°"
        draw.text((fx, fy), hilo, font=footer_font, fill=fg)
        fx += text_width(draw, hilo, footer_font) + 16

    # AQI
    if data.air_quality:
        aqi_str = f"AQI {data.air_quality.aqi} {data.air_quality.category}"
        draw.text((fx, fy), aqi_str, font=footer_font, fill=fg)
        fx += text_width(draw, aqi_str, footer_font) + 16

    # Year progress
    day_of_year = today.timetuple().tm_yday
    days_in_year = 366 if calendar.isleap(today.year) else 365
    yr_str = f"Day {day_of_year}/{days_in_year}"
    draw.text((fx, fy), yr_str, font=footer_font, fill=fg)

    # Second footer row: forecast
    if weather and weather.forecast:
        fy2 = fy + text_height(footer_font) + 4
        fx2 = x0 + _PAD
        fc_font = font_body(11)
        for fc in weather.forecast[:4]:
            day_name = fc.date.strftime("%a").upper()
            fc_text = f"{day_name} {fc.high:.0f}/{fc.low:.0f}"
            wi = OWM_ICON_MAP.get(fc.icon, FALLBACK_ICON)
            draw.text((fx2, fy2 - 2), wi, font=weather_icon(14), fill=fg)
            fx2 += 18
            draw.text((fx2, fy2), fc_text, font=fc_font, fill=fg)
            fx2 += text_width(draw, fc_text, fc_font) + 14
