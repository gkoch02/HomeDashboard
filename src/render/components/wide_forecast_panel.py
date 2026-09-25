"""wide_forecast_panel.py — a weather strip for the 1360x480 panoramic plate.

Where the ``weather`` theme stacks its forecast under the current conditions,
this plate lays the two side by side: the conditions now as a hero block at
the left end, and the coming days as a row of cards across the rest, with a
band beneath them for the things that are sometimes there — alerts, air
quality — and the moon, which always is.

Three parts:

  * **Hero** (``HERO_W``) — location, a large icon beside the temperature
    numeral, the condition, high, low and feels-like, then a two-column grid
    of humidity, wind, pressure, UV index, sunrise and sunset.
  * **Forecast row** — one card per forecast day (at most ``CARD_MAX``):
    weekday, date, icon, high over low, condition, and a filled bar for the
    chance of precipitation when the source reports one. Today's weekday is
    set in a chip in the primary accent.
  * **Lower band** — three cells: active alerts (each an inverted bar in the
    alert accent) or the note that there are none; the air-quality index and
    category when a sensor is configured; and the moon's phase, illumination
    and the countdown to the next full moon.

Nothing on the plate reads the clock: the caption uses the data timestamp,
so an idle tick renders byte-identically and costs no panel write.
"""

from __future__ import annotations

from datetime import date, datetime

from PIL import ImageDraw

from src.data.models import AirQualityData, DashboardData, WeatherData
from src.render.artkit import to_local_naive
from src.render.fonts import weather_icon as weather_icon_font
from src.render.icons import draw_weather_icon
from src.render.moon import moon_illumination, moon_phase_glyph, moon_phase_name, next_full_moon
from src.render.primitives import (
    content_time,
    deg_to_compass,
    draw_text_truncated,
    draw_text_wrapped,
    filled_rect,
    fmt_time,
    hline,
    text_height,
    text_width,
    vline,
    wind_unit,
)
from src.render.theme import ComponentRegion, ThemeStyle

HERO_W = 420
PAD = 20
CARD_MAX = 5
# The forecast row takes this much of the plate's height; the band gets the rest.
ROW_H_FRACTION = 0.62
# AQI at or above this is drawn in the alert accent (EPA "Unhealthy for
# Sensitive Groups" begins at 101).
AQI_ALERT_FROM = 101


def _alert_fill(style: ThemeStyle):
    return style.fg if style.accent_alert is None else style.accent_alert


def _tint(style: ThemeStyle):
    """The secondary accent as a fill, or ``None`` on a plate where it is ink.

    A fill behind ink text only works when the fill is not itself ink; on a
    monochrome panel the caller draws an outline instead.
    """
    fill = style.secondary_accent_fill()
    return None if fill == style.fg else fill


def _naive(dt: datetime, now: datetime) -> datetime:
    return to_local_naive(dt, getattr(now, "tzinfo", None))


def draw_wide_forecast(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full ``wide_forecast`` plate into *region*."""
    if region is None:
        region = ComponentRegion(0, 0, 1360, 480)
    if style is None:
        style = ThemeStyle()

    x0, y0, w, h = region.x, region.y, region.w, region.h
    weather = data.weather

    _draw_hero(draw, weather, now, (x0, y0, HERO_W, h), style)
    vline(draw, x0 + HERO_W, y0, y0 + h, fill=style.fg)
    vline(draw, x0 + HERO_W + 1, y0, y0 + h, fill=style.fg)

    rx0 = x0 + HERO_W + 2
    rw = w - HERO_W - 2
    row_h = int(h * ROW_H_FRACTION)
    _draw_forecast_row(draw, weather, today, (rx0, y0, rw, row_h), style)
    hline(draw, y0 + row_h, rx0, x0 + w, fill=style.fg)
    hline(draw, y0 + row_h + 1, rx0, x0 + w, fill=style.fg)
    _draw_band(
        draw, weather, data.air_quality, today, (rx0, y0 + row_h + 2, rw, h - row_h - 2), style
    )

    stamp = content_time(data, now)
    caption = f"Updated {stamp.strftime('%b %-d')} · {fmt_time(stamp)}"
    cap_font = style.font_regular(11)
    draw.text(
        (x0 + w - PAD - text_width(draw, caption, cap_font), y0 + h - 8 - text_height(cap_font)),
        caption,
        font=cap_font,
        fill=style.fg,
    )


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------


def _draw_hero(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    now: datetime,
    rect: tuple[int, int, int, int],
    style: ThemeStyle,
) -> None:
    x0, y0, w, h = rect
    hx = x0 + PAD
    inner_w = w - 2 * PAD
    label_font = style.label_font()
    label = style.component_labels.get("weather", "WEATHER")
    if weather is not None and weather.location_name:
        label = f"{label} · {weather.location_name.upper()}"
    draw_text_truncated(
        draw, (hx, y0 + 16), label, label_font, inner_w, fill=style.primary_accent_fill()
    )

    if weather is None:
        msg_font = style.font_medium(20)
        draw.text((hx, y0 + h // 2 - 10), "Weather unavailable", font=msg_font, fill=style.fg)
        return

    icon_top = y0 + 52
    draw_weather_icon(draw, (hx, icon_top), weather.current_icon, size=112, fill=style.fg)
    temp_font = style.font_bold(104)
    temp = f"{weather.current_temp:.0f}°"
    tb = draw.textbbox((0, 0), temp, font=temp_font)
    draw.text((hx + 150 - tb[0], icon_top + 4 - tb[1]), temp, font=temp_font, fill=style.fg)

    desc_font = style.font_medium(22)
    desc_y = icon_top + 132
    used = draw_text_wrapped(
        draw,
        (hx, desc_y),
        weather.current_description.capitalize(),
        desc_font,
        inner_w,
        max_lines=2,
        fill=style.fg,
    )

    hilo_font = style.font_semibold(20)
    hilo_y = desc_y + used + 8
    hilo = f"H {weather.high:.0f}°   L {weather.low:.0f}°"
    if weather.feels_like is not None:
        hilo += f"   Feels {weather.feels_like:.0f}°"
    draw_text_truncated(draw, (hx, hilo_y), hilo, hilo_font, inner_w, fill=style.fg)

    # Detail grid: two columns, three rows.
    grid_y = hilo_y + text_height(hilo_font) + 18
    hline(draw, grid_y - 8, hx, x0 + w - PAD, fill=style.fg)
    key_font = style.font_regular(13)
    val_font = style.font_semibold(17)
    col_w = inner_w // 2
    row_h = 34
    wind = "—"
    if weather.wind_speed is not None:
        wind = f"{weather.wind_speed:.0f} {wind_unit(weather)}"
        if weather.wind_deg is not None:
            wind += f" {deg_to_compass(weather.wind_deg)}"
    cells = [
        ("HUMIDITY", f"{weather.humidity}%"),
        ("WIND", wind),
        ("PRESSURE", f"{weather.pressure:.0f} hPa" if weather.pressure is not None else "—"),
        ("UV INDEX", f"{weather.uv_index:.0f}" if weather.uv_index is not None else "—"),
        ("SUNRISE", fmt_time(_naive(weather.sunrise, now)) if weather.sunrise else "—"),
        ("SUNSET", fmt_time(_naive(weather.sunset, now)) if weather.sunset else "—"),
    ]
    for i, (key, value) in enumerate(cells):
        cx = hx + (i % 2) * col_w
        cy = grid_y + (i // 2) * row_h
        if cy + row_h > y0 + h - 24:
            break
        draw.text((cx, cy), key, font=key_font, fill=style.primary_accent_fill())
        draw_text_truncated(
            draw, (cx, cy + text_height(key_font) + 1), value, val_font, col_w - 8, fill=style.fg
        )


# ---------------------------------------------------------------------------
# Forecast row
# ---------------------------------------------------------------------------


def _draw_forecast_row(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    today: date,
    rect: tuple[int, int, int, int],
    style: ThemeStyle,
) -> None:
    x0, y0, w, h = rect
    days = list(weather.forecast[:CARD_MAX]) if weather is not None else []
    if not days:
        msg_font = style.font_medium(20)
        msg = "No forecast available"
        draw.text(
            (x0 + (w - text_width(draw, msg, msg_font)) // 2, y0 + h // 2 - 10),
            msg,
            font=msg_font,
            fill=style.fg,
        )
        return

    card_w = w // len(days)
    day_font = style.font_bold(22)
    date_font = style.font_regular(13)
    hi_font = style.font_bold(34)
    lo_font = style.font_regular(24)
    desc_font = style.font_regular(14)
    pct_font = style.font_regular(12)
    accent = style.primary_accent_fill()
    tint = _tint(style)

    for i, fc in enumerate(days):
        cx0 = x0 + i * card_w
        cx1 = cx0 + card_w if i < len(days) - 1 else x0 + w
        mid = (cx0 + cx1) // 2
        inner_w = cx1 - cx0 - 2 * 14
        if i:
            vline(draw, cx0, y0 + 14, y0 + h - 14, fill=style.fg)

        is_today = fc.date == today
        name = "TODAY" if is_today else fc.date.strftime("%a").upper()
        nw = text_width(draw, name, day_font)
        ny = y0 + 18
        if is_today:
            chip = (mid - nw // 2 - 10, ny - 4, mid + nw // 2 + 10, ny + text_height(day_font) + 4)
            filled_rect(draw, chip, fill=accent)
            draw.text((mid - nw // 2, ny), name, font=day_font, fill=style.bg)
        else:
            draw.text((mid - nw // 2, ny), name, font=day_font, fill=style.fg)

        date_str = fc.date.strftime("%b %-d")
        draw.text(
            (mid - text_width(draw, date_str, date_font) // 2, ny + text_height(day_font) + 8),
            date_str,
            font=date_font,
            fill=style.fg,
        )

        icon_size = 64
        icon_y = ny + text_height(day_font) + 8 + text_height(date_font) + 12
        draw_weather_icon(
            draw, (mid - icon_size // 2, icon_y), fc.icon, size=icon_size, fill=style.fg
        )

        hi = f"{fc.high:.0f}°"
        lo = f"{fc.low:.0f}°"
        hi_w = text_width(draw, hi, hi_font)
        lo_w = text_width(draw, lo, lo_font)
        gap = 10
        tx = mid - (hi_w + gap + lo_w) // 2
        temps_y = icon_y + icon_size + 14
        draw.text((tx, temps_y), hi, font=hi_font, fill=style.fg)
        draw.text(
            (tx + hi_w + gap, temps_y + text_height(hi_font) - text_height(lo_font)),
            lo,
            font=lo_font,
            fill=style.fg,
        )

        desc_y = temps_y + text_height(hi_font) + 10
        desc = fc.description.capitalize()
        dw = min(text_width(draw, desc, desc_font), inner_w)
        draw_text_truncated(draw, (mid - dw // 2, desc_y), desc, desc_font, inner_w, fill=style.fg)

        if fc.precip_chance is not None:
            bar_y = desc_y + text_height(desc_font) + 12
            if bar_y + 12 <= y0 + h - 12:
                pct = max(0.0, min(1.0, fc.precip_chance))
                label = f"{pct * 100:.0f}%"
                lw = text_width(draw, label, pct_font)
                bar_w = inner_w - lw - 8
                bx0 = cx0 + 14
                draw.rectangle((bx0, bar_y, bx0 + bar_w, bar_y + 10), outline=style.fg, width=1)
                fill_w = round(bar_w * pct)
                if fill_w > 0:
                    filled_rect(
                        draw,
                        (bx0, bar_y, bx0 + fill_w, bar_y + 10),
                        fill=tint if tint is not None else style.fg,
                    )
                draw.text((bx0 + bar_w + 8, bar_y - 3), label, font=pct_font, fill=style.fg)


# ---------------------------------------------------------------------------
# Lower band
# ---------------------------------------------------------------------------


def _draw_band(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    air: AirQualityData | None,
    today: date,
    rect: tuple[int, int, int, int],
    style: ThemeStyle,
) -> None:
    x0, y0, w, h = rect
    cell_w = w // 3
    label_font = style.label_font()
    accent = style.primary_accent_fill()
    body_font = style.font_regular(15)

    # Alerts.
    ax = x0 + PAD
    draw.text((ax, y0 + 14), "ALERTS", font=label_font, fill=accent)
    ay = y0 + 14 + text_height(label_font) + 10
    alerts = weather.alerts if weather is not None else []
    if alerts:
        bar_font = style.font_semibold(15)
        bar_h = text_height(bar_font) + 10
        for alert in alerts[:3]:
            if ay + bar_h > y0 + h - 8:
                break
            filled_rect(draw, (ax, ay, x0 + cell_w - PAD, ay + bar_h), fill=_alert_fill(style))
            draw_text_truncated(
                draw,
                (ax + 8, ay + 5),
                f"! {alert.event}",
                bar_font,
                cell_w - 2 * PAD - 16,
                fill=style.bg,
            )
            ay += bar_h + 6
    else:
        draw.text((ax, ay), "No active alerts", font=body_font, fill=style.fg)
    vline(draw, x0 + cell_w, y0 + 12, y0 + h - 12, fill=style.fg)

    # Air quality.
    qx = x0 + cell_w + PAD
    draw.text((qx, y0 + 14), "AIR QUALITY", font=label_font, fill=accent)
    qy = y0 + 14 + text_height(label_font) + 6
    if air is None:
        draw.text((qx, qy + 4), "No sensor configured", font=body_font, fill=style.fg)
    else:
        aqi_font = style.font_bold(54)
        aqi = str(air.aqi)
        aqi_fill = _alert_fill(style) if air.aqi >= AQI_ALERT_FROM else style.fg
        ab = draw.textbbox((0, 0), aqi, font=aqi_font)
        draw.text((qx - ab[0], qy - ab[1]), aqi, font=aqi_font, fill=aqi_fill)
        aqi_w = ab[2] - ab[0]
        cat_font = style.font_semibold(16)
        draw_text_truncated(
            draw,
            (qx + aqi_w + 12, qy + 6),
            air.category,
            cat_font,
            cell_w - 2 * PAD - aqi_w - 12,
            fill=style.fg,
        )
        draw.text(
            (qx + aqi_w + 12, qy + 6 + text_height(cat_font) + 4),
            f"PM2.5  {air.pm25:.1f} µg/m³",
            font=style.font_regular(13),
            fill=style.fg,
        )
    vline(draw, x0 + 2 * cell_w, y0 + 12, y0 + h - 12, fill=style.fg)

    # Moon.
    mx = x0 + 2 * cell_w + PAD
    draw.text((mx, y0 + 14), "MOON", font=label_font, fill=accent)
    my = y0 + 14 + text_height(label_font) + 6
    glyph_font = weather_icon_font(56)
    glyph = moon_phase_glyph(today)
    gb = draw.textbbox((0, 0), glyph, font=glyph_font)
    draw.text((mx - gb[0], my - gb[1]), glyph, font=glyph_font, fill=style.fg)
    tx = mx + (gb[2] - gb[0]) + 14
    name_font = style.font_semibold(16)
    draw_text_truncated(
        draw,
        (tx, my + 2),
        moon_phase_name(today),
        name_font,
        cell_w - 2 * PAD - (tx - mx),
        fill=style.fg,
    )
    detail_font = style.font_regular(13)
    draw.text(
        (tx, my + 2 + text_height(name_font) + 4),
        f"{moon_illumination(today):.0f}% illuminated",
        font=detail_font,
        fill=style.fg,
    )
    _, days_to_full = next_full_moon(today)
    when = (
        "tonight"
        if days_to_full == 0
        else (f"in {days_to_full} days" if days_to_full != 1 else "tomorrow")
    )
    draw.text(
        (tx, my + 2 + text_height(name_font) + 4 + text_height(detail_font) + 3),
        f"Full moon {when}",
        font=detail_font,
        fill=style.fg,
    )
