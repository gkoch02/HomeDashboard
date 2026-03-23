from datetime import date

from PIL import ImageDraw

from src.data.models import WeatherData
from src.render import layout as L
from src.render.fonts import bold, regular, medium, semibold, weather_icon as weather_icon_font
from src.render.primitives import (
    BLACK, WHITE, draw_text_truncated, filled_rect, hline, text_width, vline,
    fmt_time as _fmt_time, deg_to_compass,
)
from src.render.icons import draw_weather_icon
from src.render.moon import moon_phase_glyph
from src.render.theme import ComponentRegion, ThemeStyle


def draw_weather(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    today: date | None = None,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
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
    icon_x_offset = int(w * 0.04)    # ~12px at 300w
    temp_x_offset = int(w * 0.26)    # ~78px at 300w
    detail_x_offset = int(w * 0.513) # ~154px at 300w
    forecast_h = int(h * 0.317)      # ~38px at 120h
    content_y_offset = int(h * 0.233)  # ~28px at 120h
    hilo_y_offset = content_y_offset + int(h * 0.117)   # ~14px step = row 2
    detail3_y_offset = content_y_offset + int(h * 0.217)  # ~26px step = row 3
    detail4_y_offset = content_y_offset + int(h * 0.317)  # ~38px step = row 4

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
        draw, (right_x, y0 + content_y_offset),
        weather.current_description.title(), desc_font, max_detail_w, fill=style.fg,
    )

    # Row 2: hi/lo + UV index when available
    hilo_font = style.font_medium(12)
    hilo_str = f"H:{weather.high:.0f}°  L:{weather.low:.0f}°"
    if weather.uv_index is not None:
        uv_suffix = f"  UV:{weather.uv_index:.0f}"
        if text_width(draw, hilo_str + uv_suffix, hilo_font) <= max_detail_w:
            hilo_str += uv_suffix
    draw_text_truncated(
        draw, (right_x, y0 + hilo_y_offset), hilo_str, hilo_font, max_detail_w,
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
        draw, (right_x, y0 + detail3_y_offset),
        detail3_text, detail3_font, max_detail_w, fill=style.fg,
    )

    # Row 4: sunrise / sunset
    if weather.sunrise is not None or weather.sunset is not None:
        sun_parts: list[str] = []
        if weather.sunrise is not None:
            sun_parts.append(f"↑{_fmt_time(weather.sunrise)}")
        if weather.sunset is not None:
            sun_parts.append(f"↓{_fmt_time(weather.sunset)}")
        draw_text_truncated(
            draw, (right_x, y0 + detail4_y_offset),
            "  ".join(sun_parts), detail3_font, max_detail_w, fill=style.fg,
        )

    # Forecast strip along the bottom.
    forecast_top = y0 + h - forecast_h
    if style.show_borders:
        hline(draw, forecast_top, x0, x0 + w, fill=style.fg)

    forecast_items = weather.forecast or []
    n_alerts = len(weather.alerts)

    if n_alerts >= 2:
        n_forecast_cols = min(len(forecast_items), 1)
        n_cols = 2 + n_forecast_cols
    elif n_alerts == 1:
        n_forecast_cols = min(len(forecast_items), 2)
        n_cols = 1 + n_forecast_cols
    else:
        n_cols = min(len(forecast_items), 3)

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
                draw, weather.alerts[i].event, cx, forecast_top, col_w, forecast_h, style,
            )
        elif n_alerts == 1 and i == 0:
            _draw_alert_column(
                draw, weather.alerts[0].event, cx, forecast_top, col_w, forecast_h, style,
            )
        else:
            if forecast_idx < len(forecast_items):
                fc = forecast_items[forecast_idx]
                forecast_idx += 1
                fx = cx + pad
                draw_weather_icon(
                    draw, (fx, forecast_top + 2), fc.icon, size=icon_size, fill=style.fg,
                )
                text_x = fx + icon_size + 8
                draw.text(
                    (text_x, forecast_top + 2),
                    fc.date.strftime("%a"), font=day_font, fill=style.fg,
                )
                draw.text(
                    (text_x, forecast_top + 14),
                    f"{fc.high:.0f}°/{fc.low:.0f}°", font=hilo_sm_font, fill=style.fg,
                )
                if fc.precip_chance is not None and fc.precip_chance >= 0.05:
                    precip_font = style.font_regular(10)
                    draw.text(
                        (text_x, forecast_top + 25),
                        f"{fc.precip_chance:.0%}", font=precip_font, fill=style.fg,
                    )

        # Column separators
        if i < n_cols - 1 and style.show_borders:
            vline(draw, cx + col_w, forecast_top, y0 + h, fill=style.fg)


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
    filled_rect(draw, (cx, top, cx + col_w - 1, top + col_h - 1), fill=style.fg)

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
