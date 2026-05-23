"""Full-canvas stacked sparkline dashboard for the ``trends`` theme.

Five labeled rows of time-series data, each drawn as a polyline above a
Bayer-filled area. The ordered-Bayer quantization configured by the theme
turns those area fills into clean dot patterns on Waveshare; on Inky the
RGB canvas paints the lines in blue with a yellow today-marker.

Rows:

  TEMP — 24h        : current observation + interpolated forecast across ±12 h.
  AIR               : current AQI on a 6-zone health scale.
  DAYLIGHT — 7d     : sunset − sunrise for today and the next six days.
  EVENTS — 14d      : per-day event count bars across the next two weeks.
  MOON — 30d        : illumination 0..100 across the next synodic month.

Each row degrades gracefully when the underlying data isn't available
(missing weather, no PurpleAir sensor, no coords for the daylight row).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DashboardData, WeatherData
from src.render.components.air_quality_panel import _AQI_MAX, _AQI_ZONES
from src.render.fonts import cyber_mono, weather_icon
from src.render.moon import moon_illumination, moon_phase_glyph
from src.render.primitives import events_for_day
from src.render.quantize import _BAYER_4X4
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

MASTHEAD_H = 36
ROW_COUNT = 5
LABEL_W = 130
ANNOTATION_W = 188
CHART_GAP = 14
CHART_PAD_TOP = 10
CHART_PAD_BOTTOM = 12
PAD_X = 14


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_trends(
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
) -> None:
    """Draw the full trends sparkline dashboard into *region*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        image = draw._image  # type: ignore[attr-defined]

    x0, y0, w, h = region.x, region.y, region.w, region.h
    _draw_masthead(draw, today, now, x0=x0, y0=y0, w=w, style=style)

    rows_top = y0 + MASTHEAD_H
    rows_total = h - MASTHEAD_H
    row_h = rows_total // ROW_COUNT
    spare = rows_total - row_h * ROW_COUNT

    # Distribute spare pixels to the last row so the bottom border aligns.
    row_heights = [row_h] * ROW_COUNT
    row_heights[-1] += spare

    rows = [
        ("TEMP", "24h", lambda dr, y, rh: _draw_temp_row(dr, image, data, x0, y, w, rh, style)),
        ("AIR", "now", lambda dr, y, rh: _draw_aqi_row(dr, image, data, x0, y, w, rh, style)),
        (
            "DAYLIGHT",
            "7d",
            lambda dr, y, rh: _draw_daylight_row(
                dr, image, today, latitude, longitude, x0, y, w, rh, style
            ),
        ),
        (
            "EVENTS",
            "14d",
            lambda dr, y, rh: _draw_events_row(dr, image, data, today, x0, y, w, rh, style),
        ),
        ("MOON", "30d", lambda dr, y, rh: _draw_moon_row(dr, image, today, x0, y, w, rh, style)),
    ]

    cursor_y = rows_top
    for idx, ((title, sub, drawer), rh) in enumerate(zip(rows, row_heights)):
        _draw_row_chrome(
            draw,
            x0=x0,
            y0=cursor_y,
            w=w,
            h=rh,
            title=title,
            sub=sub,
            style=style,
            draw_bottom_border=(idx < ROW_COUNT - 1),
        )
        drawer(draw, cursor_y, rh)
        cursor_y += rh


# ---------------------------------------------------------------------------
# Chrome (masthead, row label, separators)
# ---------------------------------------------------------------------------


def _draw_masthead(
    draw: ImageDraw.ImageDraw,
    today: date,
    now: datetime,
    *,
    x0: int,
    y0: int,
    w: int,
    style: ThemeStyle,
) -> None:
    title_font = style.font_bold(16)
    meta_font = style.font_medium(12)
    title = "TRENDS"
    bb = draw.textbbox((0, 0), title, font=title_font)
    draw.text((x0 + PAD_X - bb[0], y0 + 10 - bb[1]), title, font=title_font, fill=style.fg)
    meta = today.strftime("%A · %B %-d, %Y").upper() + "   ·   " + now.strftime("%-I:%M %p")
    mb = draw.textbbox((0, 0), meta, font=meta_font)
    mx = x0 + w - PAD_X - (mb[2] - mb[0]) - mb[0]
    draw.text((mx, y0 + 12 - mb[1]), meta, font=meta_font, fill=style.fg)
    # Thin bottom rule under the masthead.
    draw.line([(x0, y0 + MASTHEAD_H - 1), (x0 + w, y0 + MASTHEAD_H - 1)], fill=style.fg, width=1)


def _draw_row_chrome(
    draw: ImageDraw.ImageDraw,
    *,
    x0: int,
    y0: int,
    w: int,
    h: int,
    title: str,
    sub: str,
    style: ThemeStyle,
    draw_bottom_border: bool,
) -> None:
    """Render row label column and the bottom separator (skipped for last row)."""
    title_font = style.font_section_label(12) if style.font_section_label else style.font_bold(12)
    sub_font = style.font_medium(10)
    # Title line (e.g. "TEMP").
    tb = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        (x0 + PAD_X - tb[0], y0 + 14 - tb[1]),
        title,
        font=title_font,
        fill=style.fg,
    )
    # Subtitle (e.g. "24h") in muted weight on the next line.
    sb = draw.textbbox((0, 0), sub, font=sub_font)
    draw.text(
        (x0 + PAD_X - sb[0], y0 + 30 - sb[1]),
        sub,
        font=sub_font,
        fill=style.fg,
    )
    if draw_bottom_border:
        draw.line([(x0, y0 + h - 1), (x0 + w, y0 + h - 1)], fill=style.fg, width=1)


def _annotation_x_range(x0: int, w: int) -> tuple[int, int]:
    """(left, right) inclusive bounds of the right-hand annotation column."""
    return (x0 + w - ANNOTATION_W, x0 + w - PAD_X)


def _chart_x_range(x0: int, w: int) -> tuple[int, int]:
    return (x0 + LABEL_W, x0 + w - ANNOTATION_W - CHART_GAP)


def _draw_text_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    right: int,
    top: int,
    font,
    fill,
) -> tuple[int, int]:
    """Right-anchor *text* at *(right, top)*. Returns (width, height) drawn."""
    bb = draw.textbbox((0, 0), text, font=font)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    x = right - tw - bb[0]
    y = top - bb[1]
    draw.text((x, y), text, font=font, fill=fill)
    return tw, th


def _chart_y_range(y0: int, h: int) -> tuple[int, int]:
    return (y0 + CHART_PAD_TOP, y0 + h - CHART_PAD_BOTTOM)


# ---------------------------------------------------------------------------
# Sparkline + Bayer-fill helpers
# ---------------------------------------------------------------------------


def _draw_sparkline(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    values: list[float | None],
    *,
    line_fill,
    fill_color,
    now_index: int | None = None,
    accent_now,
    bayer_threshold: int = 96,
) -> None:
    """Render a sparkline polyline + Bayer-filled area.

    *values* may contain ``None`` entries (treated as gaps).
    *rect* = (x0, y0, x1, y1) inclusive chart bounds.
    *bayer_threshold*: lower → fewer dots (sparser fill).
    """
    x0, y0, x1, y1 = rect
    if x1 <= x0 + 4 or y1 <= y0 + 4:
        return
    real = [v for v in values if v is not None]
    if len(real) < 2:
        # Not enough data — draw a midline so the row chrome isn't empty.
        midy = (y0 + y1) // 2
        draw.line([(x0, midy), (x1, midy)], fill=line_fill, width=1)
        return

    vmin = min(real)
    vmax = max(real)
    if vmax - vmin < 1e-9:
        vmin -= 0.5
        vmax += 0.5
    # 8% headroom top + bottom so the line never sits on the chart edge.
    span = vmax - vmin
    vmin -= span * 0.08
    vmax += span * 0.08

    n = len(values)
    chart_w = x1 - x0
    chart_h = y1 - y0

    def _x_for(i: int) -> float:
        if n == 1:
            return x0 + chart_w / 2
        return x0 + chart_w * i / (n - 1)

    def _y_for(v: float) -> float:
        t = (v - vmin) / (vmax - vmin)
        return y1 - t * chart_h

    # Build the line + the fill polygon, handling None-as-gap.
    line_points: list[tuple[float, float]] = []
    fill_segments: list[list[tuple[int, int]]] = []
    current: list[tuple[float, float]] = []
    for i, v in enumerate(values):
        if v is None:
            if len(current) >= 2:
                fill_segments.append(_fill_polygon_from_curve(current, y1))
                line_points.extend(current)
                line_points.append((None, None))  # type: ignore[arg-type]
            current = []
            continue
        current.append((_x_for(i), _y_for(v)))
    if len(current) >= 2:
        fill_segments.append(_fill_polygon_from_curve(current, y1))
        line_points.extend(current)

    # Render Bayer fills first, then the line on top.
    for poly in fill_segments:
        _bayer_fill_polygon(image, poly, on_color=fill_color, threshold=bayer_threshold)

    # Draw the polyline. ``line_points`` may contain ``(None, None)`` markers
    # to split segments; PIL doesn't accept those so split into chunks.
    chunk: list[tuple[float, float]] = []
    for p in line_points:
        if p == (None, None):  # type: ignore[comparison-overlap]
            if len(chunk) >= 2:
                draw.line(chunk, fill=line_fill, width=2)
            chunk = []
        else:
            chunk.append(p)
    if len(chunk) >= 2:
        draw.line(chunk, fill=line_fill, width=2)

    # Now marker.
    if now_index is not None and 0 <= now_index < n and values[now_index] is not None:
        mx = _x_for(now_index)
        my = _y_for(values[now_index])
        r = 4
        draw.ellipse((mx - r, my - r, mx + r, my + r), fill=accent_now, outline=line_fill)
        # Vertical tick from the marker down to the baseline.
        draw.line([(mx, my + r + 1), (mx, y1)], fill=accent_now, width=1)


def _fill_polygon_from_curve(
    curve: list[tuple[float, float]], baseline_y: float
) -> list[tuple[int, int]]:
    """Close *curve* down to *baseline_y* and integerise for polygon rasterisation."""
    poly: list[tuple[int, int]] = [(int(round(x)), int(round(y))) for x, y in curve]
    poly.append((int(round(curve[-1][0])), int(round(baseline_y))))
    poly.append((int(round(curve[0][0])), int(round(baseline_y))))
    return poly


def _bayer_fill_polygon(
    image: Image.Image,
    polygon_xy: list[tuple[int, int]],
    *,
    on_color,
    threshold: int = 96,
) -> None:
    """Rasterise *polygon_xy* as a Bayer-thresholded fill into *image*.

    Builds an L mask sized to the polygon bounding box, then for every
    set mask pixel writes *on_color* into the canvas wherever the local
    Bayer threshold is met. Below *threshold* turns the pixel on.
    """
    if len(polygon_xy) < 3:
        return
    xs = [p[0] for p in polygon_xy]
    ys = [p[1] for p in polygon_xy]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    iw = max(1, x_max - x_min + 1)
    ih = max(1, y_max - y_min + 1)
    mask = Image.new("L", (iw, ih), 0)
    mdraw = ImageDraw.Draw(mask)
    shifted = [(p[0] - x_min, p[1] - y_min) for p in polygon_xy]
    mdraw.polygon(shifted, fill=255)
    mpx = mask.load()
    cpx = image.load()
    img_w, img_h = image.size
    for yy in range(ih):
        cy = y_min + yy
        if cy < 0 or cy >= img_h:
            continue
        for xx in range(iw):
            if not mpx[xx, yy]:
                continue
            cx = x_min + xx
            if cx < 0 or cx >= img_w:
                continue
            if _BAYER_4X4[cy & 3][cx & 3] < threshold:
                cpx[cx, cy] = on_color


# ---------------------------------------------------------------------------
# Row 1: TEMP — 24h
# ---------------------------------------------------------------------------


def _draw_temp_row(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    data: DashboardData,
    x0: int,
    y0: int,
    w: int,
    h: int,
    style: ThemeStyle,
) -> None:
    weather = data.weather
    if weather is None:
        _row_fallback(draw, x0, y0, w, h, "no weather data", style)
        return
    series, now_index = _build_temp_series(weather)
    cx0, cx1 = _chart_x_range(x0, w)
    cy0, cy1 = _chart_y_range(y0, h)
    fill_color = style.primary_accent_fill()
    accent_now = style.secondary_accent_fill()
    _draw_sparkline(
        image,
        draw,
        (cx0, cy0, cx1, cy1),
        series,
        line_fill=fill_color,
        fill_color=fill_color,
        now_index=now_index,
        accent_now=accent_now,
        bayer_threshold=96,
    )
    # Annotation: large temp, NOW / HIGH / LOW stacked beneath.
    _, annot_right = _annotation_x_range(x0, w)
    big_font = cyber_mono(20)
    label_font = style.font_medium(10)
    value = weather.current_temp
    txt = "—" if value is None else f"{int(round(value))}°"
    tw, th = _draw_text_right(
        draw, txt, right=annot_right, top=y0 + 8, font=big_font, fill=style.fg
    )
    sub_lines = [
        f"NOW  ·  H {_round_temp(weather.high)}°",
        f"L {_round_temp(weather.low)}°",
    ]
    sy = y0 + 8 + th + 2
    for line in sub_lines:
        _, lh = _draw_text_right(
            draw, line, right=annot_right, top=sy, font=label_font, fill=style.fg
        )
        sy += lh + 3


def _round_temp(v: float | None) -> str:
    return "—" if v is None else str(int(round(v)))


def _build_temp_series(weather: WeatherData) -> tuple[list[float | None], int]:
    """Build a 13-point series spanning now-12h .. now+12h.

    Anchors: current_temp at index 6 (now), and forecast highs/lows at
    nominal noon / midnight slots interpolated linearly.
    """
    n = 13
    half = n // 2
    series: list[float | None] = [None] * n
    series[half] = float(weather.current_temp)
    fc = weather.forecast or []
    if fc:
        # Anchor the next forecast high a few hours ahead, low overnight.
        next_high = fc[0].high
        next_low = fc[0].low
        if len(fc) > 1:
            next_high_2 = fc[1].high
        else:
            next_high_2 = fc[0].high
        # +4h (mid-afternoon-ish) → high, +9h → low, +14h → next high
        if half + 2 < n:
            series[half + 2] = float(next_high)
        if half + 5 < n:
            series[half + 5] = float(next_low)
        if half + 7 < n:
            series[half + 7] = float(next_high_2)
        # -3h → slightly lower than current (descending toward overnight low)
        if half - 3 >= 0:
            series[half - 3] = float((weather.current_temp + weather.low) / 2)
        # -6h → low
        if half - 6 >= 0:
            series[half - 6] = float(weather.low)
    # Linear interpolation across gaps.
    _interpolate(series)
    return series, half


def _interpolate(series: list[float | None]) -> None:
    """In-place linear interpolation across ``None`` values between anchors."""
    n = len(series)
    # Forward fill leading Nones from the first real value.
    first_real = next((i for i, v in enumerate(series) if v is not None), None)
    if first_real is None:
        return
    for i in range(first_real):
        series[i] = series[first_real]
    last_real = max(i for i, v in enumerate(series) if v is not None)
    for i in range(last_real + 1, n):
        series[i] = series[last_real]
    # Interpolate between real anchors.
    i = 0
    while i < n:
        if series[i] is None:
            j = i
            while j < n and series[j] is None:
                j += 1
            if j >= n:
                break
            v_left = series[i - 1]
            v_right = series[j]
            assert v_left is not None and v_right is not None
            span = j - i + 1
            for k in range(i, j):
                t = (k - i + 1) / span
                series[k] = v_left + (v_right - v_left) * t
            i = j
        else:
            i += 1


# ---------------------------------------------------------------------------
# Row 2: AIR — current AQI
# ---------------------------------------------------------------------------


def _draw_aqi_row(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    data: DashboardData,
    x0: int,
    y0: int,
    w: int,
    h: int,
    style: ThemeStyle,
) -> None:
    aq = data.air_quality
    if aq is None:
        _row_fallback(draw, x0, y0, w, h, "no PurpleAir sensor configured", style)
        return
    cx0, cx1 = _chart_x_range(x0, w)
    cy0, cy1 = _chart_y_range(y0, h)
    bar_y0 = cy0 + 8
    bar_y1 = cy1 - 6

    fill_color = style.primary_accent_fill()
    accent_now = style.secondary_accent_fill()

    # Six zones progressively darker; we Bayer-fill each with increasing density.
    zone_bounds_low = 0
    for zone_idx, (upper, label) in enumerate(_AQI_ZONES):
        x_start = cx0 + int((cx1 - cx0) * (zone_bounds_low / _AQI_MAX))
        x_end = cx0 + int((cx1 - cx0) * (upper / _AQI_MAX))
        if x_end <= x_start:
            zone_bounds_low = upper
            continue
        # Density ramps from very sparse (Good) to very dense (Hazardous).
        threshold = int(20 + zone_idx * 40)
        poly = [
            (x_start, bar_y0),
            (x_end, bar_y0),
            (x_end, bar_y1),
            (x_start, bar_y1),
        ]
        _bayer_fill_polygon(image, poly, on_color=fill_color, threshold=threshold)
        # Zone label below the bar.
        label_font = style.font_medium(9)
        lb = draw.textbbox((0, 0), label, font=label_font)
        mid_x = (x_start + x_end) // 2 - (lb[2] - lb[0]) // 2 - lb[0]
        draw.text((mid_x, bar_y1 + 4 - lb[1]), label, font=label_font, fill=style.fg)
        zone_bounds_low = upper

    # Frame around the whole scale bar.
    draw.rectangle((cx0, bar_y0, cx1, bar_y1), outline=style.fg, width=1)

    # Marker for current AQI.
    aqi_clamped = max(0, min(_AQI_MAX, int(aq.aqi)))
    mx = cx0 + int((cx1 - cx0) * (aqi_clamped / _AQI_MAX))
    draw.line([(mx, bar_y0 - 4), (mx, bar_y1 + 2)], fill=accent_now, width=2)
    # Small triangle pointer.
    tri = [
        (mx, bar_y0 - 4),
        (mx - 4, bar_y0 - 11),
        (mx + 4, bar_y0 - 11),
    ]
    draw.polygon(tri, fill=accent_now, outline=style.fg)

    # Annotation: big AQI number, category, PM2.5 detail — right-aligned stack.
    _, annot_right = _annotation_x_range(x0, w)
    big_font = cyber_mono(22)
    cat_font = style.font_medium(11)
    pm_font = style.font_medium(9)
    aqi_text = str(aq.aqi)
    _, big_h = _draw_text_right(
        draw, aqi_text, right=annot_right, top=y0 + 6, font=big_font, fill=style.fg
    )
    _, cat_h = _draw_text_right(
        draw,
        aq.category.upper(),
        right=annot_right,
        top=y0 + 6 + big_h + 2,
        font=cat_font,
        fill=style.fg,
    )
    pm_text = f"PM2.5  {aq.pm25:.1f} µg/m³"
    _draw_text_right(
        draw,
        pm_text,
        right=annot_right,
        top=y0 + 6 + big_h + 2 + cat_h + 4,
        font=pm_font,
        fill=style.fg,
    )


# ---------------------------------------------------------------------------
# Row 3: DAYLIGHT — next 7 days
# ---------------------------------------------------------------------------


def _draw_daylight_row(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    today: date,
    latitude: float | None,
    longitude: float | None,
    x0: int,
    y0: int,
    w: int,
    h: int,
    style: ThemeStyle,
) -> None:
    if latitude is None or longitude is None or (abs(latitude) < 1e-6 and abs(longitude) < 1e-6):
        _row_fallback(draw, x0, y0, w, h, "set weather.latitude / longitude", style)
        return
    from src.astronomy import day_length, day_length_delta, sun_times

    series: list[float | None] = []
    for i in range(7):
        d = today + timedelta(days=i)
        st = sun_times(d, latitude, longitude)
        dl = day_length(st)
        series.append(dl.total_seconds() / 3600.0 if dl else None)

    cx0, cx1 = _chart_x_range(x0, w)
    cy0, cy1 = _chart_y_range(y0, h)
    fill_color = style.primary_accent_fill()
    accent_now = style.secondary_accent_fill()
    _draw_sparkline(
        image,
        draw,
        (cx0, cy0, cx1, cy1),
        series,
        line_fill=fill_color,
        fill_color=fill_color,
        now_index=0,
        accent_now=accent_now,
        bayer_threshold=84,
    )

    # Annotation: today's day length + signed delta vs yesterday.
    _, annot_right = _annotation_x_range(x0, w)
    today_hours = series[0]
    if today_hours is None:
        big_text = "—"
    else:
        hh = int(today_hours)
        mm = int(round((today_hours - hh) * 60))
        big_text = f"{hh}h {mm:02d}m"
    big_font = cyber_mono(18)
    _, big_h = _draw_text_right(
        draw, big_text, right=annot_right, top=y0 + 8, font=big_font, fill=style.fg
    )

    label_font = style.font_medium(10)
    delta = day_length_delta(today, latitude, longitude)
    if delta is None:
        delta_text = "delta —"
    else:
        secs = int(delta.total_seconds())
        sign = "+" if secs >= 0 else "−"
        absm = abs(secs) // 60
        delta_text = f"{sign}{absm} min vs yesterday"
    _draw_text_right(
        draw,
        delta_text,
        right=annot_right,
        top=y0 + 8 + big_h + 4,
        font=label_font,
        fill=style.fg,
    )


# ---------------------------------------------------------------------------
# Row 4: EVENTS — bars across next 14 days
# ---------------------------------------------------------------------------


def _draw_events_row(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    data: DashboardData,
    today: date,
    x0: int,
    y0: int,
    w: int,
    h: int,
    style: ThemeStyle,
) -> None:
    counts: list[int] = []
    for i in range(14):
        d = today + timedelta(days=i)
        counts.append(_event_count_for_day(data.events, d))
    cx0, cx1 = _chart_x_range(x0, w)
    cy0, cy1 = _chart_y_range(y0, h)
    chart_w = cx1 - cx0
    chart_h = cy1 - cy0
    max_count = max(counts) if counts and max(counts) > 0 else 1
    fill_color = style.primary_accent_fill()
    accent_now = style.secondary_accent_fill()

    n = len(counts)
    bar_w = max(6, chart_w // n - 3)
    gap = max(2, (chart_w - bar_w * n) // max(1, n - 1)) if n > 1 else 0
    total_w = bar_w * n + gap * (n - 1)
    start_x = cx0 + (chart_w - total_w) // 2
    baseline_y = cy1 - 2

    for i, count in enumerate(counts):
        bx0 = start_x + i * (bar_w + gap)
        bx1 = bx0 + bar_w - 1
        height_frac = count / max_count if max_count > 0 else 0
        bh = int(chart_h * height_frac)
        by1 = baseline_y
        by0 = baseline_y - bh
        if bh > 0:
            poly = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
            _bayer_fill_polygon(image, poly, on_color=fill_color, threshold=128)
            draw.rectangle((bx0, by0, bx1, by1), outline=style.fg, width=1)
        else:
            # Empty-day tick at the baseline.
            draw.line([(bx0, baseline_y), (bx1, baseline_y)], fill=style.fg, width=1)
        if i == 0:
            # Today gets an accent outline above the bar regardless of height.
            top_y = by0 - 2 if bh > 0 else baseline_y - 4
            draw.line([(bx0, top_y), (bx1, top_y)], fill=accent_now, width=2)

    # Day-of-week strip beneath the bars (Sun..Sat).
    dow_font = style.font_medium(9)
    for i in range(n):
        bx0 = start_x + i * (bar_w + gap)
        d = today + timedelta(days=i)
        if i == 0:
            label = "TODAY"
        else:
            label = d.strftime("%a")[:1]
        lb = draw.textbbox((0, 0), label, font=dow_font)
        lx = bx0 + bar_w // 2 - (lb[2] - lb[0]) // 2 - lb[0]
        draw.text((lx, baseline_y + 3 - lb[1]), label, font=dow_font, fill=style.fg)

    # Annotation: today's count + week total.
    _, annot_right = _annotation_x_range(x0, w)
    big_font = cyber_mono(20)
    label_font = style.font_medium(10)
    today_count = counts[0]
    week_total = sum(counts[:7])
    big_text = f"{today_count} today"
    _, big_h = _draw_text_right(
        draw, big_text, right=annot_right, top=y0 + 8, font=big_font, fill=style.fg
    )
    sub_text = f"{week_total} this week"
    _draw_text_right(
        draw,
        sub_text,
        right=annot_right,
        top=y0 + 8 + big_h + 4,
        font=label_font,
        fill=style.fg,
    )


def _event_count_for_day(events: list[CalendarEvent], day: date) -> int:
    return len(events_for_day(events, day))


# ---------------------------------------------------------------------------
# Row 5: MOON — illumination 30 days
# ---------------------------------------------------------------------------


def _draw_moon_row(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    today: date,
    x0: int,
    y0: int,
    w: int,
    h: int,
    style: ThemeStyle,
) -> None:
    series = [moon_illumination(today + timedelta(days=i)) for i in range(30)]
    cx0, cx1 = _chart_x_range(x0, w)
    cy0, cy1 = _chart_y_range(y0, h)
    fill_color = style.primary_accent_fill()
    accent_now = style.secondary_accent_fill()
    _draw_sparkline(
        image,
        draw,
        (cx0, cy0, cx1, cy1),
        series,  # type: ignore[arg-type]
        line_fill=fill_color,
        fill_color=fill_color,
        now_index=0,
        accent_now=accent_now,
        bayer_threshold=72,
    )

    # Find next full moon (illumination crosses ~99%).
    next_full = None
    for i, illum in enumerate(series):
        if illum >= 99.0:
            next_full = i
            break

    # Annotation: percentage + days-to-next-full + phase glyph stamped at far right.
    annot_left, annot_right = _annotation_x_range(x0, w)
    glyph_font = weather_icon(32)
    glyph = moon_phase_glyph(today)
    label_font = style.font_medium(10)
    pct_font = cyber_mono(16)

    # Glyph at the far-right of the annotation column.
    gb = draw.textbbox((0, 0), glyph, font=glyph_font)
    gw = gb[2] - gb[0]
    glyph_x = annot_right - gw - gb[0]
    draw.text((glyph_x, y0 + 6 - gb[1]), glyph, font=glyph_font, fill=style.fg)

    # Numeric data right-aligned against the glyph's left edge (with padding).
    text_right = annot_right - gw - 10
    illum_today = series[0]
    pct_text = f"{int(round(illum_today))}%"
    _, pct_h = _draw_text_right(
        draw, pct_text, right=text_right, top=y0 + 6, font=pct_font, fill=style.fg
    )
    if next_full is None:
        full_text = "no full in 30d"
    elif next_full == 0:
        full_text = "FULL TODAY"
    else:
        full_text = f"FULL in {next_full}d"
    _draw_text_right(
        draw,
        full_text,
        right=text_right,
        top=y0 + 6 + pct_h + 4,
        font=label_font,
        fill=style.fg,
    )


# ---------------------------------------------------------------------------
# Shared fallback
# ---------------------------------------------------------------------------


def _row_fallback(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    w: int,
    h: int,
    message: str,
    style: ThemeStyle,
) -> None:
    cx0, cx1 = _chart_x_range(x0, w)
    cy0, cy1 = _chart_y_range(y0, h)
    midy = (cy0 + cy1) // 2
    draw.line([(cx0, midy), (cx1, midy)], fill=style.fg, width=1)
    font = style.font_medium(11)
    bb = draw.textbbox((0, 0), message, font=font)
    mx = cx0 + (cx1 - cx0) // 2 - (bb[2] - bb[0]) // 2 - bb[0]
    my = midy - (bb[3] - bb[1]) // 2 - bb[1] - 14
    # Draw a small paper rectangle behind the text so the midline doesn't cut through it.
    pad = 6
    rect = (mx - pad, my - 2, mx + (bb[2] - bb[0]) + pad, my + (bb[3] - bb[1]) + 2)
    draw.rectangle(rect, fill=style.bg)
    draw.text((mx, my), message, font=font, fill=style.fg)
