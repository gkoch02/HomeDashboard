"""Full-screen air quality component for the ``air_quality`` theme.

Renders a rich environmental health dashboard across the entire 800×480 canvas,
organised into four visual zones:

1. **AQI Hero + Scale** (top, 180px): large AQI number and category on the left;
   a 6-zone health-scale bar with a position indicator on the right.
2. **Particulate Matter row** (140px): PM1.0 / PM2.5 / PM10 readings with
   µg/m³ units, centred in three equal columns.
3. **Ambient sensor cards** (100px): up to three rounded-rect cards for
   temperature, humidity, and pressure from the PurpleAir sensor.
4. **Weather + forecast strip** (bottom, 140px): current conditions on the left,
   a 4-day forecast grid on the right.

All zones degrade gracefully: missing optional fields (PM1, temp, humidity …)
are silently omitted, and the entire display falls back to a centred "No air
quality data" message when ``data.air_quality`` is ``None``.

Layout (800 × 480):
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  47                      │ ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   │
  │  GOOD                    │ Good  Mod  USG  Unhlthy  V.Unhlthy  Hazard  │
  │  AIR QUALITY             │                                              │
  ├──────────────────────────────────────────────────────────────────────────┤
  │    PM1.0  ·  3.2         PM2.5  ·  12.4         PM10  ·  28.1  µg/m³  │
  ├──────────────────────────────────────────────────────────────────────────┤
  │  ┌────────────┐  ┌────────────┐  ┌────────────┐                        │
  │  │  72°F      │  │  65%       │  │  1013 hPa  │                        │
  │  │ Sensor Temp│  │ Humidity   │  │ Pressure   │                        │
  │  └────────────┘  └────────────┘  └────────────┘                        │
  ├──────────────────────────────────────────────────────────────────────────┤
  │  ⛅ 72°F  Partly Cloudy  H:78 L:60  │  Mon  Tue  Wed  Thu              │
  └──────────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from datetime import date

from PIL import ImageDraw

from src.data.models import AirQualityData, DashboardData, WeatherData
from src.render.fonts import weather_icon as weather_icon_font
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.primitives import (
    draw_text_truncated,
    filled_rect,
    hline,
    text_height,
    text_width,
    vline,
)
from src.render.theme import ComponentRegion, ThemeStyle

# Weather Icons glyphs reused from weather_full
_GLYPH_THERMOMETER = "\uf055"
_GLYPH_HUMIDITY = "\uf07a"
_GLYPH_BAROMETER = "\uf079"
_GLYPH_WIND = "\uf050"

# AQI health-scale zones: (upper_bound_inclusive, short_label)
_AQI_ZONES: list[tuple[int, str]] = [
    (50,  "Good"),
    (100, "Moderate"),
    (150, "USG"),
    (200, "Unhealthy"),
    (300, "V.Unhealthy"),
    (500, "Hazardous"),
]
_AQI_MAX = 500


def draw_air_quality_full(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date | None = None,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full-screen air quality dashboard."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    if data.air_quality is None:
        _draw_unavailable(draw, region, style)
        return

    x0, y0 = region.x, region.y
    W, H = region.w, region.h

    # Zone heights — tuned for 480px canvas
    hero_h = int(H * 0.375)      # ~180px
    pm_h = int(H * 0.146)        # ~70px
    cards_h = int(H * 0.208)     # ~100px
    # Weather strip gets the remainder
    weather_h = H - hero_h - pm_h - cards_h   # ~130px

    hero_top = y0
    pm_top = hero_top + hero_h
    cards_top = pm_top + pm_h
    weather_top = cards_top + cards_h

    # Thin separator rules between zones
    hline(draw, pm_top, x0 + 20, x0 + W - 20, fill=style.fg)
    hline(draw, cards_top, x0 + 20, x0 + W - 20, fill=style.fg)
    hline(draw, weather_top, x0, x0 + W, fill=style.fg)

    _draw_aqi_hero(draw, data.air_quality, x0, hero_top, W, hero_h, style)
    _draw_pm_row(draw, data.air_quality, x0, pm_top, W, pm_h, style)
    _draw_ambient_cards(draw, data.air_quality, x0, cards_top, W, cards_h, style)
    _draw_weather_strip(draw, data.weather, today, x0, weather_top, W, weather_h, style)


# ---------------------------------------------------------------------------
# Zone 1: AQI hero + scale bar
# ---------------------------------------------------------------------------

def _draw_aqi_hero(
    draw: ImageDraw.ImageDraw,
    aq: AirQualityData,
    x0: int, y0: int, W: int, H: int,
    style: ThemeStyle,
) -> None:
    """Left: large AQI number + category label.  Right: 6-zone scale bar."""
    fg = style.fg

    split = int(W * 0.28)   # left column width
    pad = 20

    # ── Left: AQI number, category, section label ────────────────────────
    lx = x0 + pad
    ly = y0 + pad

    # "AIR QUALITY" section label — plain bold text
    label_text = "AIR QUALITY"
    label_font = style.font_bold(22)
    draw.text((lx, ly), label_text, font=label_font, fill=fg)
    label_bottom = ly + text_height(label_font) + 8

    # Large AQI number
    aqi_str = str(aq.aqi)
    aqi_size = 96
    aqi_font = style.font_bold(aqi_size)
    # Scale down if very wide (rare but safe)
    while aqi_size > 52:
        aqi_font = style.font_bold(aqi_size)
        if text_width(draw, aqi_str, aqi_font) <= split - 2 * pad:
            break
        aqi_size -= 4

    draw.text((lx, label_bottom), aqi_str, font=aqi_font, fill=fg)
    aqi_bottom = label_bottom + text_height(aqi_font)

    # Category text
    cat_font = style.font_medium(24)
    draw.text((lx, aqi_bottom + 4), aq.category, font=cat_font, fill=fg)

    # ── Right: 6-zone scale bar ──────────────────────────────────────────
    rx0 = x0 + split
    rx_pad = 8
    bar_x = rx0 + rx_pad
    bar_w = W - split - rx_pad * 2
    bar_h = 40
    # Centre bar vertically in top ~60% of zone
    bar_y = y0 + int(H * 0.28)

    _draw_scale_bar(draw, aq.aqi, bar_x, bar_y, bar_w, bar_h, style)


def _draw_scale_bar(
    draw: ImageDraw.ImageDraw,
    aqi: int,
    bar_x: int, bar_y: int, bar_w: int, bar_h: int,
    style: ThemeStyle,
) -> None:
    """Horizontal 6-zone AQI health scale with filled progress and tick."""
    fg = style.fg
    bg = style.bg

    # Clamp to valid range
    aqi_clamped = max(0, min(aqi, _AQI_MAX))

    # Pixel x-position of the current AQI within the bar
    fill_x = bar_x + int(aqi_clamped / _AQI_MAX * bar_w)

    # Draw the outline of the full bar
    draw.rectangle(
        [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
        outline=fg, width=1,
    )

    # Fill from left to fill_x (solid black = "used up" portion)
    if fill_x > bar_x + 1:
        filled_rect(draw, (bar_x + 1, bar_y + 1, fill_x, bar_y + bar_h - 1), fill=fg)

    # Zone dividers and labels
    label_font = style.font_regular(12)
    prev_bound = 0
    for upper, zone_label in _AQI_ZONES:
        div_x = bar_x + int(upper / _AQI_MAX * bar_w)

        # Vertical divider — white if inside filled area, black if in empty area
        if div_x < fill_x:
            vline(draw, div_x, bar_y, bar_y + bar_h, fill=bg)
        elif div_x > bar_x:
            vline(draw, div_x, bar_y, bar_y + bar_h, fill=fg)

        # Zone label centred below its zone
        zone_mid_x = bar_x + int((prev_bound + upper) / 2 / _AQI_MAX * bar_w)
        lw = text_width(draw, zone_label, label_font)
        draw.text(
            (zone_mid_x - lw // 2, bar_y + bar_h + 4),
            zone_label, font=label_font, fill=fg,
        )
        prev_bound = upper

    # Downward triangle pointer below the bar at exact AQI position
    tri_cx = fill_x
    tri_top = bar_y + bar_h + 2
    tri_h = 6
    draw.polygon(
        [(tri_cx, tri_top + tri_h), (tri_cx - 4, tri_top), (tri_cx + 4, tri_top)],
        fill=fg,
    )


# ---------------------------------------------------------------------------
# Zone 2: Particulate matter row
# ---------------------------------------------------------------------------

def _draw_pm_row(
    draw: ImageDraw.ImageDraw,
    aq: AirQualityData,
    x0: int, y0: int, W: int, H: int,
    style: ThemeStyle,
) -> None:
    """Three-column PM1.0 / PM2.5 / PM10 readings."""
    fg = style.fg

    # Build the list of readings to display (always PM2.5; PM1 and PM10 optional)
    readings: list[tuple[str, str]] = []
    if aq.pm1 is not None:
        readings.append(("PM1.0", f"{aq.pm1:.1f}"))
    readings.append(("PM2.5", f"{aq.pm25:.1f}"))
    if aq.pm10 is not None:
        readings.append(("PM10", f"{aq.pm10:.1f}"))

    n = len(readings)
    col_w = W // n
    cy = y0 + H // 2

    val_font = style.font_bold(32)
    label_font = style.font_regular(18)
    unit_font = style.font_regular(15)

    val_h = text_height(val_font)
    label_h = text_height(label_font)
    block_h = label_h + 4 + val_h
    block_top = cy - block_h // 2

    for i, (pm_label, pm_val) in enumerate(readings):
        col_cx = x0 + i * col_w + col_w // 2

        # Label (e.g. "PM2.5")
        lw = text_width(draw, pm_label, label_font)
        draw.text((col_cx - lw // 2, block_top), pm_label, font=label_font, fill=fg)

        # Value
        vw = text_width(draw, pm_val, val_font)
        draw.text((col_cx - vw // 2, block_top + label_h + 4), pm_val, font=val_font, fill=fg)

        # Thin vertical separator between columns (not after last)
        if i < n - 1:
            sep_x = x0 + (i + 1) * col_w
            vline(draw, sep_x, y0 + 10, y0 + H - 10, fill=fg)

    # µg/m³ unit — bottom-right corner of the zone, small
    unit_str = "µg/m³"
    uw = text_width(draw, unit_str, unit_font)
    draw.text(
        (x0 + W - uw - 14, y0 + H - text_height(unit_font) - 6),
        unit_str, font=unit_font, fill=fg,
    )


# ---------------------------------------------------------------------------
# Zone 3: Ambient sensor cards (temp / humidity / pressure)
# ---------------------------------------------------------------------------

def _draw_ambient_cards(
    draw: ImageDraw.ImageDraw,
    aq: AirQualityData,
    x0: int, y0: int, W: int, H: int,
    style: ThemeStyle,
) -> None:
    """Up to three rounded-rect metric cards for sensor ambient readings."""
    fg = style.fg

    cards: list[tuple[str, str, str]] = []  # (glyph, value, label)
    if aq.temperature is not None:
        cards.append((_GLYPH_THERMOMETER, f"{aq.temperature:.0f}°F", "Sensor Temp"))
    if aq.humidity is not None:
        cards.append((_GLYPH_HUMIDITY, f"{aq.humidity:.0f}%", "Humidity"))
    if aq.pressure is not None:
        cards.append((_GLYPH_BAROMETER, f"{aq.pressure:.0f} hPa", "Pressure"))

    if not cards:
        return

    n = len(cards)
    margin = 30
    gap = 20
    card_w = (W - 2 * margin - gap * (n - 1)) // n
    card_h = H - 16
    card_y = y0 + 8

    icon_font = weather_icon_font(24)
    val_font = style.font_bold(22)
    label_font = style.font_regular(17)

    label_h = text_height(label_font)

    for i, (glyph, value, label) in enumerate(cards):
        card_x = x0 + margin + i * (card_w + gap)

        draw.rounded_rectangle(
            [card_x, card_y, card_x + card_w, card_y + card_h],
            radius=6, outline=fg, width=1,
        )

        inner_cx = card_x + card_w // 2

        # Measure icon and value bboxes for layout
        gbbox = draw.textbbox((0, 0), glyph, font=icon_font)
        gw = gbbox[2] - gbbox[0]
        gh = gbbox[3] - gbbox[1]
        vbbox = draw.textbbox((0, 0), value, val_font)
        vw = vbbox[2] - vbbox[0]
        vh = vbbox[3] - vbbox[1]
        row_h = max(gh, vh)

        # Label sits at the bottom; vertically centre the icon+value in the space above it
        label_top = card_y + card_h - label_h - 7
        content_top = card_y + 6
        content_h = label_top - 4 - content_top
        row_y = content_top + (content_h - row_h) // 2

        # Horizontally centre icon + value row
        total_w = gw + 6 + vw
        row_x = inner_cx - total_w // 2

        # Draw icon and value vertically centred on the same baseline
        icon_y = row_y + (row_h - gh) // 2
        val_y = row_y + (row_h - vh) // 2
        draw.text(
            (row_x - gbbox[0], icon_y - gbbox[1]),
            glyph, font=icon_font, fill=fg,
        )
        draw.text(
            (row_x + gw + 6 - vbbox[0], val_y - vbbox[1]),
            value, font=val_font, fill=fg,
        )

        # Label centred at bottom of card
        lw = text_width(draw, label, label_font)
        draw.text(
            (inner_cx - lw // 2, label_top),
            label, font=label_font, fill=fg,
        )


# ---------------------------------------------------------------------------
# Zone 4: Weather + forecast strip
# ---------------------------------------------------------------------------

def _draw_weather_strip(
    draw: ImageDraw.ImageDraw,
    wx: WeatherData | None,
    today: date | None,
    x0: int, y0: int, W: int, H: int,
    style: ThemeStyle,
) -> None:
    """Left: current conditions.  Right: 4-day forecast columns."""
    fg = style.fg

    if wx is None:
        font = style.font_regular(12)
        msg = "Weather unavailable"
        mw = text_width(draw, msg, font)
        draw.text(
            (x0 + (W - mw) // 2, y0 + (H - text_height(font)) // 2),
            msg, font=font, fill=fg,
        )
        return

    # Split: current on left 260px, forecast on right
    current_w = 260
    forecast_x = x0 + current_w
    forecast_w = W - current_w

    # Thin vertical rule between current and forecast
    vline(draw, forecast_x, y0 + 8, y0 + H - 8, fill=fg)

    _draw_current_conditions(draw, wx, x0, y0, current_w, H, style)
    _draw_forecast_columns(draw, wx, today, forecast_x, y0, forecast_w, H, style)


def _draw_current_conditions(
    draw: ImageDraw.ImageDraw,
    wx: WeatherData,
    x0: int, y0: int, W: int, H: int,
    style: ThemeStyle,
) -> None:
    """Current weather icon, temperature, description, and hi/lo."""
    fg = style.fg
    pad = 14
    cy = y0 + H // 2

    # Weather icon
    icon_size = 44
    icon_font = weather_icon_font(icon_size)
    glyph = OWM_ICON_MAP.get(wx.current_icon, FALLBACK_ICON)
    gbbox = draw.textbbox((0, 0), glyph, font=icon_font)
    gh = gbbox[3] - gbbox[1]
    # Vertically centre icon in top half of strip
    icon_y = cy - gh - 2
    draw.text(
        (x0 + pad - gbbox[0], icon_y - gbbox[1]),
        glyph, font=icon_font, fill=fg,
    )
    icon_right = x0 + pad + (gbbox[2] - gbbox[0]) + 8

    # Temperature to the right of icon
    temp_str = f"{wx.current_temp:.0f}°"
    temp_font = style.font_bold(38)
    tbbox = draw.textbbox((0, 0), temp_str, font=temp_font)
    draw.text(
        (icon_right - tbbox[0], icon_y - tbbox[1]),
        temp_str, font=temp_font, fill=fg,
    )

    # Description below icon row
    desc_font = style.font_regular(19)
    desc = wx.current_description.title()
    desc_y = cy + 4
    draw_text_truncated(draw, (x0 + pad, desc_y), desc, desc_font, W - pad - 10, fill=fg)

    # Hi / Lo
    hilo_font = style.font_regular(17)
    hilo_str = f"H:{wx.high:.0f}°  L:{wx.low:.0f}°"
    hilo_y = desc_y + text_height(desc_font) + 2
    if hilo_y + text_height(hilo_font) <= y0 + H - 2:
        draw.text((x0 + pad, hilo_y), hilo_str, font=hilo_font, fill=fg)


def _draw_forecast_columns(
    draw: ImageDraw.ImageDraw,
    wx: WeatherData,
    today: date | None,
    x0: int, y0: int, W: int, H: int,
    style: ThemeStyle,
) -> None:
    """Up to 4 forecast day columns."""
    fg = style.fg
    forecast = (wx.forecast or [])[:4]
    if not forecast:
        return

    n = len(forecast)
    col_w = W // n
    day_font = style.font_medium(19)
    hilo_font = style.font_regular(17)
    precip_font = style.font_regular(15)
    icon_size = 28

    for i, fc in enumerate(forecast):
        col_cx = x0 + i * col_w + col_w // 2
        row_y = y0 + 10

        # Day name
        day_str = fc.date.strftime("%a")
        dw = text_width(draw, day_str, day_font)
        draw.text((col_cx - dw // 2, row_y), day_str, font=day_font, fill=fg)
        row_y += text_height(day_font) + 7

        # Icon
        icon_font = weather_icon_font(icon_size)
        glyph = OWM_ICON_MAP.get(fc.icon, FALLBACK_ICON)
        gbbox = draw.textbbox((0, 0), glyph, font=icon_font)
        gw = gbbox[2] - gbbox[0]
        draw.text(
            (col_cx - gw // 2 - gbbox[0], row_y - gbbox[1]),
            glyph, font=icon_font, fill=fg,
        )
        row_y += icon_size + 7

        # Hi / Lo
        hilo_str = f"{fc.high:.0f}°/{fc.low:.0f}°"
        hw = text_width(draw, hilo_str, hilo_font)
        draw.text((col_cx - hw // 2, row_y), hilo_str, font=hilo_font, fill=fg)
        row_y += text_height(hilo_font) + 5

        # Precip chance
        if fc.precip_chance is not None and fc.precip_chance >= 0.05:
            precip_str = f"{fc.precip_chance:.0%}"
            pw = text_width(draw, precip_str, precip_font)
            if row_y + text_height(precip_font) <= y0 + H - 2:
                draw.text((col_cx - pw // 2, row_y), precip_str, font=precip_font, fill=fg)


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _draw_unavailable(
    draw: ImageDraw.ImageDraw,
    region: ComponentRegion,
    style: ThemeStyle,
) -> None:
    """Centred message when air quality data is not configured."""
    font = style.font_medium(16)
    msg = "Air Quality Unavailable"
    mw = text_width(draw, msg, font)
    mh = text_height(font)
    draw.text(
        (region.x + (region.w - mw) // 2, region.y + (region.h - mh) // 2),
        msg, font=font, fill=style.fg,
    )
