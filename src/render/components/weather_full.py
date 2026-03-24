"""Full-screen weather component for the ``weather`` theme.

Renders a large, iOS-Weather-inspired layout across the entire 800×480
canvas.  The display is divided into three visual zones:

1. **Hero** (top): large weather icon, hero temperature, condition text,
   today's hi/lo range.
2. **Metric cards + detail strip** (middle): four rounded-rectangle cards
   (feels like, wind, humidity, UV) followed by a single-line detail strip
   (sunrise/sunset, pressure, moon phase).
3. **Forecast grid** (bottom): five-day forecast columns separated by a
   thin rule, with day name, icon, hi/lo, and precipitation chance.

When weather alerts are present, an inverted banner is drawn above the
forecast grid.
"""

from datetime import date

from PIL import ImageDraw

from src.data.models import AirQualityData, WeatherData
from src.render.fonts import weather_icon as weather_icon_font
from src.render.icons import OWM_ICON_MAP, FALLBACK_ICON
from src.render.moon import moon_phase_glyph, moon_phase_name
from src.render.primitives import (
    draw_text_truncated, filled_rect, hline, text_height, text_width,
    fmt_time as _fmt_time, deg_to_compass,
)
from src.render.theme import ComponentRegion, ThemeStyle

# Weather Icons font glyph code points for metric card icons.
_GLYPH_THERMOMETER = "\uf055"
_GLYPH_WIND = "\uf050"
_GLYPH_HUMIDITY = "\uf07a"
_GLYPH_UV = "\uf06e"
_GLYPH_BAROMETER = "\uf079"
_GLYPH_SUNRISE = "\uf051"
_GLYPH_SUNSET = "\uf052"
_GLYPH_AIR_QUALITY = "\uf062"  # wi-smoke — used for the AQI metric card


def draw_weather_full(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    today: date | None = None,
    *,
    air_quality: AirQualityData | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full-screen weather display."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    if weather is None:
        _draw_unavailable(draw, region, style)
        return

    x0, y0 = region.x, region.y
    W, H = region.w, region.h

    # ── Zone heights (proportional to 480px canvas) ──────────────────
    hero_h = int(H * 0.44)        # ~211px: icon + temp + desc + hi/lo
    cards_h = int(H * 0.115)      # ~55px: metric cards row
    detail_h = int(H * 0.06)      # ~29px: sunrise/sunset/pressure/moon
    alert_h = int(H * 0.055)      # ~26px: alert banner (if needed)
    # Remaining space goes to forecast grid

    hero_top = y0
    cards_top = hero_top + hero_h
    detail_top = cards_top + cards_h

    has_alerts = bool(weather.alerts)
    if has_alerts:
        alert_top = detail_top + detail_h
        forecast_top = alert_top + alert_h
    else:
        alert_top = None
        forecast_top = detail_top + detail_h

    forecast_h = y0 + H - forecast_top

    # ── Draw each zone ───────────────────────────────────────────────
    _draw_hero(draw, weather, x0, hero_top, W, hero_h, style)
    _draw_metric_cards(draw, weather, x0, cards_top, W, cards_h, style, air_quality=air_quality)
    _draw_detail_strip(draw, weather, today, x0, detail_top, W, detail_h, style,
                       air_quality=air_quality)

    if has_alerts and alert_top is not None:
        _draw_alert_banner(draw, weather, x0, alert_top, W, alert_h, style)

    # Thin rule above forecast
    rule_y = forecast_top - 1
    hline(draw, rule_y, x0 + 30, x0 + W - 30, fill=style.fg)

    _draw_forecast_grid(draw, weather, x0, forecast_top, W, forecast_h, style)


def _draw_hero(draw, weather, x0, y0, W, H, style):
    """Large weather icon, hero temperature, description, and hi/lo."""
    fg = style.fg
    cx = x0 + W // 2  # horizontal centre

    # Weather icon — large centred glyph
    icon_size = 70
    icon_font = weather_icon_font(icon_size)
    glyph = OWM_ICON_MAP.get(weather.current_icon, FALLBACK_ICON)
    glyph_bbox = draw.textbbox((0, 0), glyph, font=icon_font)
    glyph_w = glyph_bbox[2] - glyph_bbox[0]
    glyph_h = glyph_bbox[3] - glyph_bbox[1]
    icon_x = cx - glyph_w // 2 - glyph_bbox[0]
    icon_y = y0 + 8 - glyph_bbox[1]
    draw.text((icon_x, icon_y), glyph, font=icon_font, fill=fg)

    # Hero temperature
    temp_str = f"{weather.current_temp:.0f}°"
    temp_size = 64
    temp_font = style.font_bold(temp_size)
    # Auto-scale down if temp string is too wide (e.g. "-100°")
    max_temp_w = int(W * 0.5)
    while temp_size > 40:
        temp_font = style.font_bold(temp_size)
        tw = text_width(draw, temp_str, temp_font)
        if tw <= max_temp_w:
            break
        temp_size -= 4

    temp_bbox = draw.textbbox((0, 0), temp_str, font=temp_font)
    temp_w = temp_bbox[2] - temp_bbox[0]
    temp_x = cx - temp_w // 2 - temp_bbox[0]
    temp_y = y0 + 8 + glyph_h + 2
    draw.text((temp_x, temp_y), temp_str, font=temp_font, fill=fg)
    temp_bottom = temp_y + text_height(temp_font)

    # Description
    desc_font = style.font_medium(16)
    desc = weather.current_description.title()
    desc_w = text_width(draw, desc, desc_font)
    desc_x = cx - desc_w // 2
    desc_y = temp_bottom + 4
    draw_text_truncated(draw, (desc_x, desc_y), desc, desc_font, W - 60, fill=fg)

    # Hi / Lo
    hilo_font = style.font_regular(13)
    hilo_str = f"H: {weather.high:.0f}°  ·  L: {weather.low:.0f}°"
    hilo_w = text_width(draw, hilo_str, hilo_font)
    hilo_x = cx - hilo_w // 2
    hilo_y = desc_y + text_height(desc_font) + 2
    # Clamp to stay within hero zone
    max_hilo_y = y0 + H - text_height(hilo_font) - 2
    hilo_y = min(hilo_y, max_hilo_y)
    draw.text((hilo_x, hilo_y), hilo_str, font=hilo_font, fill=fg)


def _draw_metric_cards(draw, weather, x0, y0, W, H, style, *, air_quality=None):
    """Four evenly-spaced rounded-rect metric cards."""
    fg = style.fg

    # Build card data: list of (icon_glyph, value, label)
    cards = []

    # Feels like
    if weather.feels_like is not None:
        cards.append((_GLYPH_THERMOMETER, f"{weather.feels_like:.0f}°", "Feels like"))
    else:
        cards.append((_GLYPH_THERMOMETER, f"{weather.current_temp:.0f}°", "Temp"))

    # Wind
    if weather.wind_speed is not None:
        wind_val = f"{weather.wind_speed:.0f}"
        if weather.wind_deg is not None:
            wind_val += f" {deg_to_compass(weather.wind_deg)}"
        cards.append((_GLYPH_WIND, wind_val, "Wind mph"))
    else:
        cards.append((_GLYPH_WIND, "—", "Wind"))

    # Humidity
    cards.append((_GLYPH_HUMIDITY, f"{weather.humidity}%", "Humidity"))

    # UV index or Pressure (prefer UV when available)
    if weather.uv_index is not None:
        cards.append((_GLYPH_UV, f"{weather.uv_index:.0f}", "UV index"))
    elif weather.pressure is not None:
        cards.append((_GLYPH_BAROMETER, f"{weather.pressure:.0f}", "hPa"))
    else:
        cards.append((_GLYPH_UV, "—", "UV index"))

    # Air quality (optional 5th card from PurpleAir)
    if air_quality is not None:
        cards.append((
            _GLYPH_AIR_QUALITY,
            f"AQI {air_quality.aqi}",
            air_quality.category[:11],  # truncate "Unhealthy for Sensitive Groups" → "Unhealthy f"
        ))

    # Layout: variable card count with equal widths
    n = len(cards)
    margin = 30
    gap = 16
    total_gap = gap * (n - 1)
    card_w = (W - 2 * margin - total_gap) // n
    card_h = H - 8  # 4px top/bottom padding
    card_y = y0 + 4

    icon_font = weather_icon_font(18)
    value_font = style.font_semibold(14)
    label_font = style.font_regular(10)

    for i, (glyph, value, label) in enumerate(cards):
        card_x = x0 + margin + i * (card_w + gap)

        # Rounded rectangle outline
        draw.rounded_rectangle(
            [card_x, card_y, card_x + card_w, card_y + card_h],
            radius=6, outline=fg, width=1,
        )

        # Centre content vertically within card
        inner_cx = card_x + card_w // 2

        # Icon glyph + value on one line
        glyph_bbox = draw.textbbox((0, 0), glyph, font=icon_font)
        glyph_w = glyph_bbox[2] - glyph_bbox[0]
        val_w = text_width(draw, value, value_font)
        spacing = 5
        total_w = glyph_w + spacing + val_w
        line_x = inner_cx - total_w // 2

        line_y = card_y + 6
        draw.text(
            (line_x - glyph_bbox[0], line_y - glyph_bbox[1]),
            glyph, font=icon_font, fill=fg,
        )
        val_bbox = draw.textbbox((0, 0), value, font=value_font)
        draw.text(
            (line_x + glyph_w + spacing - val_bbox[0],
             line_y - val_bbox[1]),
            value, font=value_font, fill=fg,
        )

        # Label below
        label_w = text_width(draw, label, label_font)
        label_x = inner_cx - label_w // 2
        label_y = card_y + card_h - text_height(label_font) - 5
        draw.text((label_x, label_y), label, font=label_font, fill=fg)


def _draw_detail_strip(draw, weather, today, x0, y0, W, H, style, *, air_quality=None):
    """Single centred line: sunrise/sunset · pressure · moon phase."""
    fg = style.fg
    cx = x0 + W // 2
    font = style.font_regular(12)
    mid_y = y0 + (H - text_height(font)) // 2

    parts = []

    # Sunrise / sunset
    if weather.sunrise is not None or weather.sunset is not None:
        sun_parts = []
        if weather.sunrise is not None:
            sun_parts.append(f"\u2191{_fmt_time(weather.sunrise)}")
        if weather.sunset is not None:
            sun_parts.append(f"\u2193{_fmt_time(weather.sunset)}")
        parts.append("  ".join(sun_parts))

    # Pressure (if not already shown in cards — i.e. when UV is available)
    if weather.pressure is not None and weather.uv_index is not None:
        parts.append(f"{weather.pressure:.0f} hPa")

    # Particulate matter breakdown (PM1 / PM2.5 / PM10) when AQI data is present
    if air_quality is not None:
        pm_segs = []
        if air_quality.pm1 is not None:
            pm_segs.append(f"PM1 {air_quality.pm1:.1f}")
        pm_segs.append(f"PM2.5 {air_quality.pm25:.1f}")
        if air_quality.pm10 is not None:
            pm_segs.append(f"PM10 {air_quality.pm10:.1f}")
        parts.append("  ·  ".join(pm_segs) + " µg/m³")

    # Moon phase
    if today is not None:
        # Placeholder entry — the moon glyph is rendered with its own font below
        parts.append("__moon__")

    if not parts:
        return

    # Join all parts with a dot separator, but render moon glyph with its own font
    # For simplicity: if moon is the last part, render it specially
    if today is not None and len(parts) >= 1:
        # Render text parts (everything except moon) then moon separately
        text_parts = parts[:-1]

        text_str = "   ·   ".join(text_parts)
        if text_str:
            text_str += "   ·   "

        # Calculate total width for centering
        text_w = text_width(draw, text_str, font) if text_str else 0
        moon_icon_font = weather_icon_font(16)

        # Moon glyph and name
        moon_glyph_char = moon_phase_glyph(today)
        moon_name_str = moon_phase_name(today)

        glyph_bbox = draw.textbbox((0, 0), moon_glyph_char, font=moon_icon_font)
        glyph_w = glyph_bbox[2] - glyph_bbox[0]
        moon_label_w = text_width(draw, f"  {moon_name_str}", font)
        moon_total_w = glyph_w + moon_label_w

        total_w = text_w + moon_total_w
        start_x = cx - total_w // 2

        if text_str:
            draw.text((start_x, mid_y), text_str, font=font, fill=fg)

        # Moon glyph (weather icon font)
        moon_x = start_x + text_w
        glyph_mid_y = mid_y + text_height(font) // 2
        draw.text(
            (moon_x - glyph_bbox[0],
             glyph_mid_y - (glyph_bbox[3] - glyph_bbox[1]) // 2 - glyph_bbox[1]),
            moon_glyph_char, font=moon_icon_font, fill=fg,
        )

        # Moon name (regular font)
        name_x = moon_x + glyph_w
        draw.text((name_x, mid_y), f"  {moon_name_str}", font=font, fill=fg)
    else:
        full_str = "   ·   ".join(parts)
        full_w = text_width(draw, full_str, font)
        draw.text((cx - full_w // 2, mid_y), full_str, font=font, fill=fg)


def _draw_alert_banner(draw, weather, x0, y0, W, H, style):
    """Inverted banner showing weather alerts."""
    fg = style.fg
    bg = style.bg

    filled_rect(draw, (x0, y0, x0 + W - 1, y0 + H - 1), fill=fg)

    alert_texts = [f"⚠ {a.event}" for a in weather.alerts[:3]]
    alert_str = "   ·   ".join(alert_texts)

    alert_font = style.font_semibold(12)
    max_w = W - 60

    aw = text_width(draw, alert_str, alert_font)
    if aw > max_w:
        # Truncate
        draw_text_truncated(
            draw,
            (x0 + 30, y0 + (H - text_height(alert_font)) // 2),
            alert_str, alert_font, max_w, fill=bg,
        )
    else:
        draw.text(
            (x0 + (W - aw) // 2, y0 + (H - text_height(alert_font)) // 2),
            alert_str, font=alert_font, fill=bg,
        )


def _draw_forecast_grid(draw, weather, x0, y0, W, H, style):
    """Five-day forecast columns: day name, icon, hi/lo, precip chance."""
    fg = style.fg
    forecast = (weather.forecast or [])[:5]

    if not forecast:
        font = style.font_regular(13)
        msg = "No forecast data"
        mw = text_width(draw, msg, font)
        draw.text(
            (x0 + (W - mw) // 2, y0 + (H - text_height(font)) // 2),
            msg, font=font, fill=fg,
        )
        return

    n = len(forecast)
    margin = 30
    usable_w = W - 2 * margin
    col_w = usable_w // n

    day_font = style.font_semibold(13)
    hilo_font = style.font_regular(13)
    precip_font = style.font_regular(11)
    icon_size = 28

    for i, fc in enumerate(forecast):
        col_cx = x0 + margin + i * col_w + col_w // 2

        # Day name
        day_str = fc.date.strftime("%a")
        dw = text_width(draw, day_str, day_font)
        day_y = y0 + 8
        draw.text((col_cx - dw // 2, day_y), day_str, font=day_font, fill=fg)

        # Weather icon
        icon_y = day_y + text_height(day_font) + 6
        # Centre the icon glyph
        icon_font = weather_icon_font(icon_size)
        glyph = OWM_ICON_MAP.get(fc.icon, FALLBACK_ICON)
        gbbox = draw.textbbox((0, 0), glyph, font=icon_font)
        gw = gbbox[2] - gbbox[0]
        draw.text(
            (col_cx - gw // 2 - gbbox[0], icon_y - gbbox[1]),
            glyph, font=icon_font, fill=fg,
        )

        # Hi / Lo
        hilo_str = f"{fc.high:.0f}°/{fc.low:.0f}°"
        hw = text_width(draw, hilo_str, hilo_font)
        hilo_y = icon_y + icon_size + 6
        draw.text((col_cx - hw // 2, hilo_y), hilo_str, font=hilo_font, fill=fg)

        # Precipitation chance (only if >= 5%)
        if fc.precip_chance is not None and fc.precip_chance >= 0.05:
            precip_str = f"{fc.precip_chance:.0%}"
            pw = text_width(draw, precip_str, precip_font)
            precip_y = hilo_y + text_height(hilo_font) + 3
            draw.text(
                (col_cx - pw // 2, precip_y), precip_str,
                font=precip_font, fill=fg,
            )


def _draw_unavailable(draw, region, style):
    """Centred fallback when weather data is None."""
    font = style.font_medium(18)
    msg = "Weather Unavailable"
    mw = text_width(draw, msg, font)
    mh = text_height(font)
    draw.text(
        (region.x + (region.w - mw) // 2, region.y + (region.h - mh) // 2),
        msg, font=font, fill=style.fg,
    )
