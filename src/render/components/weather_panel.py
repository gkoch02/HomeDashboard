from __future__ import annotations

from datetime import date

from PIL import ImageDraw

from src.data.models import AirQualityData, StalenessLevel, WeatherData
from src.render import layout as L
from src.render.fonts import weather_icon as weather_icon_font
from src.render.icons import draw_weather_icon
from src.render.moon import moon_phase_glyph
from src.render.primitives import (
    deg_to_compass,
    draw_staleness_glyph,
    draw_text_truncated,
    filled_rect,
    hline,
    text_width,
    vline,
)
from src.render.primitives import (
    fmt_time as _fmt_time,
)
from src.render.theme import ComponentRegion, ThemeStyle


def _aqi_accent(style: ThemeStyle, aqi: int) -> int:
    if aqi <= 50:
        return style.accent_good if style.accent_good is not None else style.fg
    if aqi <= 150:
        return style.accent_warn if style.accent_warn is not None else style.fg
    return style.accent_alert if style.accent_alert is not None else style.fg


def draw_weather(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    today: date | None = None,
    *,
    air_quality: AirQualityData | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    staleness: StalenessLevel | None = None,
):
    if region is None:
        region = ComponentRegion(L.WEATHER_X, L.WEATHER_Y, L.WEATHER_W, L.WEATHER_H)
    if style is None:
        style = ThemeStyle()

    x0 = region.x
    y0 = region.y
    w = region.w
    h = region.h
    pad = L.PAD

    # Top border (2px for stronger section separation)
    if style.show_borders:
        hline(draw, y0, x0, x0 + w, fill=style.fg)
        hline(draw, y0 + 1, x0, x0 + w, fill=style.fg)

        # Right separator
        vline(draw, x0 + w - 1, y0, y0 + h, fill=style.fg)

    # Section label + moon phase icon
    label_font = style.label_font()
    weather_label = style.component_labels.get("weather", "WEATHER")

    # Append city name when it fits between the label and the moon glyph.
    # Reserve ~26px on the right for the moon glyph + padding.
    if weather is not None and weather.location_name:
        max_label_w = w - pad * 2 - 26
        candidate = f"{weather_label} · {weather.location_name}"
        if text_width(draw, candidate, label_font) <= max_label_w:
            weather_label = candidate

    draw.text((x0 + pad, y0 + pad), weather_label, font=label_font, fill=style.fg)

    if today is not None:
        moon_glyph = moon_phase_glyph(today)
        moon_size = 20
        moon_font = weather_icon_font(moon_size)
        label_bbox = draw.textbbox((0, 0), weather_label, font=label_font)
        label_mid_y = y0 + pad + label_bbox[1] + (label_bbox[3] - label_bbox[1]) // 2
        moon_bbox = draw.textbbox((0, 0), moon_glyph, font=moon_font)
        moon_glyph_w = moon_bbox[2] - moon_bbox[0]
        moon_y = label_mid_y - (moon_bbox[3] - moon_bbox[1]) // 2 - moon_bbox[1]
        moon_x = x0 + w - pad - moon_glyph_w - moon_bbox[0] - 2  # 2px inside right separator
        draw.text((moon_x, moon_y), moon_glyph, font=moon_font, fill=style.fg)

    if weather is None:
        msg_font = style.font_regular(13)
        msg = "Unavailable"
        bbox = draw.textbbox((0, 0), msg, font=msg_font)
        mw = bbox[2] - bbox[0]
        mh = bbox[3] - bbox[1]
        draw.text((x0 + (w - mw) // 2, y0 + (h - mh) // 2), msg, font=msg_font, fill=style.fg)
        return

    # Internal layout computed proportionally from the region dimensions.
    # Reference proportions are based on the original 300×120 weather panel.
    icon_x_offset = int(w * 0.04)  # ~12px at 300w
    temp_x_offset = int(w * 0.26)  # ~78px at 300w
    detail_x_offset = int(w * 0.513)  # ~154px at 300w

    show_forecast = style.show_forecast_strip
    if show_forecast:
        # Standard proportional layout — leaves room for the forecast strip.
        forecast_h = int(h * 0.317)  # ~38px at 120h
        content_y_offset = int(h * 0.233)  # ~28px at 120h
        hilo_y_offset = content_y_offset + int(h * 0.117)  # ~14px step = row 2
        detail3_y_offset = content_y_offset + int(h * 0.217)  # ~26px step = row 3
        detail4_y_offset = content_y_offset + int(h * 0.317)  # ~38px step = row 4
    else:
        # No-forecast layout — spread the four detail rows evenly across the
        # full panel height so the content is not crowded.
        forecast_h = 0
        _label_reserved = pad + 14 + 4  # approx label height + gap
        _row_step = max(12, (h - _label_reserved - pad) // 4)
        content_y_offset = _label_reserved
        hilo_y_offset = content_y_offset + _row_step
        detail3_y_offset = hilo_y_offset + _row_step
        detail4_y_offset = detail3_y_offset + _row_step

    # Weather icon (left side)
    icon_x = x0 + icon_x_offset
    icon_y = y0 + content_y_offset
    draw_weather_icon(draw, (icon_x, icon_y), weather.current_icon, size=40, fill=style.fg)

    # Temperature (big) — right of icon
    temp_font = style.font_bold(36)
    temp_str = f"{weather.current_temp:.0f}°"
    draw.text((x0 + temp_x_offset, icon_y - 2), temp_str, font=temp_font, fill=style.fg)

    # Right-column detail rows
    right_x = x0 + detail_x_offset
    max_detail_w = w - detail_x_offset - pad

    # Row 1: description
    desc_font = style.font_medium(13)
    draw_text_truncated(
        draw,
        (right_x, y0 + content_y_offset),
        weather.current_description.title(),
        desc_font,
        max_detail_w,
        fill=style.fg,
    )

    # Row 2: hi/lo + UV index when available
    hilo_font = style.font_medium(12)
    hilo_str = f"H:{weather.high:.0f}°  L:{weather.low:.0f}°"
    if weather.uv_index is not None:
        uv_suffix = f"  UV:{weather.uv_index:.0f}"
        if text_width(draw, hilo_str + uv_suffix, hilo_font) <= max_detail_w:
            hilo_str += uv_suffix
    draw_text_truncated(
        draw,
        (right_x, y0 + hilo_y_offset),
        hilo_str,
        hilo_font,
        max_detail_w,
        fill=style.fg,
    )

    # Row 3: feels-like + wind speed
    detail3_font = style.font_regular(11)
    detail3_parts: list[str] = []
    if weather.feels_like is not None:
        detail3_parts.append(f"Feels {weather.feels_like:.0f}°")
    if weather.wind_speed is not None:
        wind_str = f"Wind {weather.wind_speed:.0f}mph"
        if weather.wind_deg is not None:
            wind_str += f" {deg_to_compass(weather.wind_deg)}"
        detail3_parts.append(wind_str)
    detail3_text = "  ·  ".join(detail3_parts) if detail3_parts else f"{weather.humidity}% humidity"
    draw_text_truncated(
        draw,
        (right_x, y0 + detail3_y_offset),
        detail3_text,
        detail3_font,
        max_detail_w,
        fill=style.fg,
    )

    # Row 4: sunrise / sunset
    if weather.sunrise is not None or weather.sunset is not None:
        sun_parts: list[str] = []
        if weather.sunrise is not None:
            sun_parts.append(f"↑{_fmt_time(weather.sunrise)}")
        if weather.sunset is not None:
            sun_parts.append(f"↓{_fmt_time(weather.sunset)}")
        draw_text_truncated(
            draw,
            (right_x, y0 + detail4_y_offset),
            "  ".join(sun_parts),
            detail3_font,
            max_detail_w,
            fill=style.fg,
        )

    if not show_forecast:
        if staleness in (StalenessLevel.STALE, StalenessLevel.EXPIRED):
            draw_staleness_glyph(draw, region, style)
        return

    # Forecast strip along the bottom.
    forecast_top = y0 + h - forecast_h
    if style.show_borders:
        hline(draw, forecast_top, x0, x0 + w, fill=style.fg)

    forecast_items = weather.forecast or []
    n_alerts = len(weather.alerts)

    if n_alerts >= 2:
        n_forecast_cols = min(len(forecast_items), 1)
        n_cols = 2 + n_forecast_cols
        show_aqi_col = False
    elif n_alerts == 1:
        n_forecast_cols = min(len(forecast_items), 2)
        n_cols = 1 + n_forecast_cols
        show_aqi_col = False
    elif air_quality is not None:
        n_forecast_cols = min(len(forecast_items), 2)
        n_cols = n_forecast_cols + 1  # last col is AQI
        show_aqi_col = True
    else:
        n_cols = min(len(forecast_items), 3)
        show_aqi_col = False

    if n_cols == 0:
        return

    col_w = w // n_cols
    day_font = style.font_semibold(11)
    hilo_sm_font = style.font_regular(11)
    icon_size = 18
    forecast_idx = 0

    for i in range(n_cols):
        cx = x0 + i * col_w

        if n_alerts >= 2 and i < 2:
            _draw_alert_column(
                draw,
                weather.alerts[i].event,
                cx,
                forecast_top,
                col_w,
                forecast_h,
                style,
            )
        elif n_alerts == 1 and i == 0:
            _draw_alert_column(
                draw,
                weather.alerts[0].event,
                cx,
                forecast_top,
                col_w,
                forecast_h,
                style,
            )
        elif show_aqi_col and air_quality is not None and i == n_cols - 1:
            _draw_aqi_column(draw, air_quality, cx, forecast_top, col_w, forecast_h, style)
        else:
            if forecast_idx < len(forecast_items):
                fc = forecast_items[forecast_idx]
                forecast_idx += 1
                fx = cx + pad
                draw_weather_icon(
                    draw,
                    (fx, forecast_top + 2),
                    fc.icon,
                    size=icon_size,
                    fill=style.fg,
                )
                text_x = fx + icon_size + 8
                draw.text(
                    (text_x, forecast_top + 2),
                    fc.date.strftime("%a"),
                    font=day_font,
                    fill=style.fg,
                )
                draw.text(
                    (text_x, forecast_top + 14),
                    f"{fc.high:.0f}°/{fc.low:.0f}°",
                    font=hilo_sm_font,
                    fill=style.fg,
                )
                if fc.precip_chance is not None and fc.precip_chance >= 0.05:
                    precip_font = style.font_regular(10)
                    draw.text(
                        (text_x, forecast_top + 25),
                        f"{fc.precip_chance:.0%}",
                        font=precip_font,
                        fill=style.fg,
                    )

        # Column separators
        if i < n_cols - 1 and style.show_borders:
            vline(draw, cx + col_w, forecast_top, y0 + h, fill=style.fg)

    if staleness in (StalenessLevel.STALE, StalenessLevel.EXPIRED):
        draw_staleness_glyph(draw, region, style)


_GLYPH_AQI = "\uf062"  # wi-smoke (same glyph used by weather_full AQI card)


def _draw_aqi_column(
    draw: ImageDraw.ImageDraw,
    air_quality: AirQualityData,
    cx: int,
    top: int,
    col_w: int,
    col_h: int,
    style: ThemeStyle,
) -> None:
    """Draw a compact AQI summary filling one forecast column."""
    accent = _aqi_accent(style, air_quality.aqi)
    icon_font = weather_icon_font(14)
    val_font = style.font_semibold(11)
    lbl_font = style.font_regular(10)

    icon_bbox = draw.textbbox((0, 0), _GLYPH_AQI, font=icon_font)
    icon_h = icon_bbox[3] - icon_bbox[1]

    val_str = f"AQI {air_quality.aqi}"
    val_bbox = draw.textbbox((0, 0), val_str, font=val_font)
    val_h = val_bbox[3] - val_bbox[1]

    # Truncate category to fit the column width minus padding
    max_w = col_w - L.PAD * 2
    category = air_quality.category
    lbl_bbox = draw.textbbox((0, 0), category, font=lbl_font)
    while len(category) > 1 and lbl_bbox[2] - lbl_bbox[0] > max_w:
        category = category[:-1]
        lbl_bbox = draw.textbbox((0, 0), category + "…", font=lbl_font)
    if category != air_quality.category:
        category = category + "…"
    lbl_bbox = draw.textbbox((0, 0), category, font=lbl_font)
    lbl_h = lbl_bbox[3] - lbl_bbox[1]

    gap = 2
    total_h = icon_h + gap + val_h + gap + lbl_h
    ty = top + (col_h - total_h) // 2

    # Icon centered in column
    icon_w = icon_bbox[2] - icon_bbox[0]
    draw.text(
        (cx + (col_w - icon_w) // 2 - icon_bbox[0], ty - icon_bbox[1]),
        _GLYPH_AQI,
        font=icon_font,
        fill=accent,
    )
    ty += icon_h + gap

    # AQI value
    val_w = val_bbox[2] - val_bbox[0]
    draw.text(
        (cx + (col_w - val_w) // 2 - val_bbox[0], ty - val_bbox[1]),
        val_str,
        font=val_font,
        fill=accent,
    )
    ty += val_h + gap

    # Category label
    lbl_w = lbl_bbox[2] - lbl_bbox[0]
    draw.text(
        (cx + (col_w - lbl_w) // 2 - lbl_bbox[0], ty - lbl_bbox[1]),
        category,
        font=lbl_font,
        fill=accent,
    )


def _draw_alert_column(
    draw: ImageDraw.ImageDraw,
    alert_event: str,
    cx: int,
    top: int,
    col_w: int,
    col_h: int,
    style: ThemeStyle,
) -> None:
    """Draw an inverted alert bar filling one forecast column."""
    fill = style.accent_alert if style.accent_alert is not None else style.fg
    filled_rect(draw, (cx, top, cx + col_w - 1, top + col_h - 1), fill=fill)

    alert_font = style.font_semibold(10)
    label = f"! {alert_event}"
    max_w = col_w - L.PAD * 2

    # Word-wrap into up to 2 lines
    words = label.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if text_width(draw, test, alert_font) <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    lines = lines[:2]

    # Truncate last line if needed
    for i, line in enumerate(lines):
        if text_width(draw, line, alert_font) > max_w:
            while line and text_width(draw, line + "...", alert_font) > max_w:
                line = line[:-1]
            lines[i] = line + "..."

    line_h = draw.textbbox((0, 0), "Ag", font=alert_font)
    lh = line_h[3] - line_h[1]
    total_h = lh * len(lines) + (len(lines) - 1) * 2
    ty = top + (col_h - total_h) // 2

    for line in lines:
        lw = text_width(draw, line, alert_font)
        tx = cx + (col_w - lw) // 2
        draw.text((tx, ty), line, font=alert_font, fill=style.bg)
        ty += lh + 2
