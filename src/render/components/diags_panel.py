"""Diagnostics (diags) component — full-canvas text readout of all data sources.

Two-column layout:
  Left:  WEATHER (all fields) + FORECAST strip + HOST SYSTEM
  Right: CALENDAR (per-day event counts, Mon–Sun) + AIR QUALITY + BIRTHDAYS + STATUS
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import ImageDraw

from src._version import __version__
from src.data.models import AirQualityData, DashboardData, HostData, StalenessLevel
from src.render.primitives import (
    deg_to_compass, draw_text_truncated, fmt_time,
    hline, text_height, text_width, vline,
)
from src.render.theme import ComponentRegion, ThemeStyle

# ── Layout constants ───────────────────────────────────────────────────────────
_HEADER_H = 28          # header bar height
_CONTENT_TOP = 4        # extra gap below header rule before content starts
_L_X_PAD = 10           # left column left-margin inside region
_L_W = 378              # left column usable width (10 → 388)
_DIVIDER_X = 400        # vertical divider x offset from region.x
_R_X = 412              # right column start x offset from region.x
_R_W = 376              # right column usable width (412 → 788)

_LINE_H = 14            # height of each data row
_LABEL_SIZE = 11        # section label font size (dm_bold)
_LABEL_PAD = 4          # gap below label before first data row
_DATA_SIZE = 12         # data row font size (cyber_mono via font_regular)
_SRC_SIZE = 10          # source attribution font size (right of label)
_KEY_W = 100            # key-column width in key-value rows
_SECTION_GAP = 8        # gap added before and after section-separator hlines
_MAX_FORECAST = 6
_MAX_BIRTHDAYS = 5
_MAX_ALERTS = 2


# ── Public entry point ────────────────────────────────────────────────────────

def draw_diags(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date | None = None,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full-canvas diagnostics readout."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()
    if today is None:
        now = data.fetched_at
        today = now.date() if isinstance(now, datetime) else date.today()

    fg = style.fg
    rx, ry = region.x, region.y

    # Header
    _draw_header(draw, rx, ry, region.w, data, style)

    # Rule below header
    rule_y = ry + _HEADER_H
    hline(draw, rule_y, rx, rx + region.w, fill=fg)

    # Vertical column divider
    div_x = rx + _DIVIDER_X
    vline(draw, div_x, rule_y, ry + region.h - 1, fill=fg)

    content_y = rule_y + _CONTENT_TOP + 2  # ≈ ry + 34

    # ── Left column ──
    lx = rx + _L_X_PAD
    ly = content_y
    ly = _weather_section(draw, lx, ly, _L_W, data.weather, style)
    ly = _sep(draw, lx, ly, _L_W, fg)
    ly = _forecast_section(draw, lx, ly, _L_W, data.weather, style)
    ly = _sep(draw, lx, ly, _L_W, fg)
    _host_section(draw, lx, ly, _L_W, data.host_data, style)

    # Version number pinned to bottom of left column
    ver_font = style.font_regular(_DATA_SIZE - 1)
    ver_str = f"v{__version__}"
    ver_y = ry + region.h - text_height(ver_font) - 4
    draw.text((lx, ver_y), ver_str, font=ver_font, fill=fg)

    # ── Right column ──
    rcx = rx + _R_X
    ry_c = content_y
    ry_c = _calendar_section(draw, rcx, ry_c, _R_W, data.events, today, style)
    ry_c = _sep(draw, rcx, ry_c, _R_W, fg)
    ry_c = _aq_section(draw, rcx, ry_c, _R_W, data.air_quality, style)
    ry_c = _sep(draw, rcx, ry_c, _R_W, fg)
    ry_c = _birthday_section(draw, rcx, ry_c, _R_W, data.birthdays, today, style)
    ry_c = _sep(draw, rcx, ry_c, _R_W, fg)
    _status_section(draw, rcx, ry_c, _R_W, data, style)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sep(draw, x, y, w, fg):
    """Draw a horizontal section separator. Returns y after the post-gap."""
    y += _SECTION_GAP
    hline(draw, y, x, x + w, fill=fg)
    y += _SECTION_GAP
    return y


def _draw_header(draw, rx, ry, w, data: DashboardData, style: ThemeStyle) -> None:
    fg = style.fg
    title_font = style.font_bold(_LABEL_SIZE + 3)
    title_y = ry + (_HEADER_H - text_height(title_font)) // 2
    draw.text((rx + 10, title_y), "DIAGNOSTICS", font=title_font, fill=fg)

    now = data.fetched_at
    ts_font = style.font_regular(_DATA_SIZE - 1)
    if isinstance(now, datetime):
        ts_str = now.strftime("%-d %b  ") + fmt_time(now)
    else:
        ts_str = str(now)
    if data.is_stale:
        ts_str = "! " + ts_str
    ts_w = text_width(draw, ts_str, ts_font)
    ts_y = ry + (_HEADER_H - text_height(ts_font)) // 2
    draw.text((rx + w - ts_w - 10, ts_y), ts_str, font=ts_font, fill=fg)


def _label(
    draw: ImageDraw.ImageDraw,
    x: int, y: int, w: int,
    text: str,
    style: ThemeStyle,
    source: str = "",
) -> int:
    """Draw section label with optional right-aligned source attribution.
    Returns y advanced past the label row."""
    fg = style.fg
    lf = style.font_bold(_LABEL_SIZE)
    draw.text((x, y), text, font=lf, fill=fg)
    if source:
        sf = style.font_regular(_SRC_SIZE)
        sw = text_width(draw, source, sf)
        sy = y + (text_height(lf) - text_height(sf)) // 2
        draw.text((x + w - sw, sy), source, font=sf, fill=fg)
    return y + text_height(lf) + _LABEL_PAD


def _kv(
    draw: ImageDraw.ImageDraw,
    x: int, y: int,
    key: str, value: str,
    style: ThemeStyle,
    col_w: int,
) -> int:
    """Draw a key-value row. Returns y advanced by _LINE_H."""
    fg = style.fg
    f = style.font_regular(_DATA_SIZE)
    draw_text_truncated(draw, (x, y), key, f, _KEY_W - 4, fill=fg)
    draw_text_truncated(draw, (x + _KEY_W, y), value, f, col_w - _KEY_W, fill=fg)
    return y + _LINE_H


# ── Section renderers ─────────────────────────────────────────────────────────

def _weather_section(draw, x, y, w, weather, style) -> int:
    y = _label(draw, x, y, w, "WEATHER", style, source="OpenWeatherMap")
    if weather is None:
        return _kv(draw, x, y, "", "unavailable", style, w)

    y = _kv(draw, x, y, "Condition", weather.current_description.title(), style, w)
    hi_lo = f"(Hi {weather.high:.0f} / Lo {weather.low:.0f})"
    y = _kv(draw, x, y, "Temp", f"{weather.current_temp:.0f}°  {hi_lo}", style, w)
    if weather.feels_like is not None:
        y = _kv(draw, x, y, "Feels like", f"{weather.feels_like:.0f}°", style, w)
    y = _kv(draw, x, y, "Humidity", f"{weather.humidity}%", style, w)
    if weather.wind_speed is not None:
        wind = f"{weather.wind_speed:.0f} mph"
        if weather.wind_deg is not None:
            wind += f"  {deg_to_compass(weather.wind_deg)}"
        y = _kv(draw, x, y, "Wind", wind, style, w)
    if weather.pressure is not None:
        y = _kv(draw, x, y, "Pressure", f"{weather.pressure:.0f} hPa", style, w)
    if weather.uv_index is not None:
        y = _kv(draw, x, y, "UV Index", f"{weather.uv_index:.0f}", style, w)
    if weather.sunrise is not None:
        y = _kv(draw, x, y, "Sunrise", fmt_time(weather.sunrise), style, w)
    if weather.sunset is not None:
        y = _kv(draw, x, y, "Sunset", fmt_time(weather.sunset), style, w)
    if weather.alerts:
        names = ", ".join(a.event for a in weather.alerts[:_MAX_ALERTS])
        y = _kv(draw, x, y, "Alerts", names, style, w)
    return y


def _fmt_uptime(seconds: float) -> str:
    """Format uptime seconds as 'Xd Yh Zm'."""
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _host_section(draw, x, y, w, host: HostData | None, style) -> int:
    y = _label(draw, x, y, w, "HOST SYSTEM", style)
    if host is None:
        return _kv(draw, x, y, "", "unavailable", style, w)

    if host.hostname is not None:
        y = _kv(draw, x, y, "Hostname", host.hostname, style, w)
    if host.uptime_seconds is not None:
        y = _kv(draw, x, y, "Uptime", _fmt_uptime(host.uptime_seconds), style, w)
    if host.load_1m is not None and host.load_5m is not None and host.load_15m is not None:
        load_str = f"{host.load_1m:.2f} / {host.load_5m:.2f} / {host.load_15m:.2f}"
        y = _kv(draw, x, y, "Load", load_str, style, w)
    if host.ram_used_mb is not None and host.ram_total_mb is not None:
        pct = int(host.ram_used_mb / host.ram_total_mb * 100)
        ram_str = f"{host.ram_used_mb:.0f} / {host.ram_total_mb:.0f} MB  ({pct}%)"
        y = _kv(draw, x, y, "RAM", ram_str, style, w)
    if host.disk_used_gb is not None and host.disk_total_gb is not None:
        pct = int(host.disk_used_gb / host.disk_total_gb * 100)
        disk_str = f"{host.disk_used_gb:.1f} / {host.disk_total_gb:.1f} GB  ({pct}%)"
        y = _kv(draw, x, y, "Disk", disk_str, style, w)
    if host.cpu_temp_c is not None:
        y = _kv(draw, x, y, "CPU Temp", f"{host.cpu_temp_c:.1f}\u00b0C", style, w)
    if host.ip_address is not None:
        y = _kv(draw, x, y, "IP", host.ip_address, style, w)
    return y


def _forecast_section(draw, x, y, w, weather, style) -> int:
    y = _label(draw, x, y, w, "FORECAST", style, source="OpenWeatherMap")
    if weather is None or not weather.forecast:
        return _kv(draw, x, y, "", "unavailable", style, w)

    f = style.font_regular(_DATA_SIZE)
    fg = style.fg
    DAY_W, HILO_W, PRECIP_W = 34, 54, 32
    desc_w = w - DAY_W - HILO_W - PRECIP_W - 6

    for fc in weather.forecast[:_MAX_FORECAST]:
        draw.text((x, y), fc.date.strftime("%a"), font=f, fill=fg)
        draw.text((x + DAY_W, y), f"{fc.high:.0f}/{fc.low:.0f}", font=f, fill=fg)
        draw_text_truncated(
            draw, (x + DAY_W + HILO_W, y),
            fc.description.title(), f, desc_w, fill=fg,
        )
        if fc.precip_chance is not None:
            draw.text(
                (x + w - PRECIP_W, y), f"{fc.precip_chance:.0%}", font=f, fill=fg,
            )
        y += _LINE_H
    return y


def _calendar_section(draw, x, y, w, events, today, style) -> int:
    y = _label(draw, x, y, w, "CALENDAR", style, source="Google Calendar")
    week_start = today - timedelta(days=today.weekday())
    for i in range(7):
        day = week_start + timedelta(days=i)
        count = sum(
            1 for e in events
            if (e.start.date() if isinstance(e.start, datetime) else e.start) == day
        )
        value = f"{count} event{'s' if count != 1 else ''}"
        y = _kv(draw, x, y, day.strftime("%a %b %-d"), value, style, w)
    return y


def _aq_section(draw, x, y, w, aq: AirQualityData | None, style) -> int:
    y = _label(draw, x, y, w, "AIR QUALITY", style, source="PurpleAir")
    if aq is None:
        return _kv(draw, x, y, "", "not configured", style, w)

    y = _kv(draw, x, y, "AQI", f"{aq.aqi}  {aq.category}", style, w)
    y = _kv(draw, x, y, "PM2.5", f"{aq.pm25:.1f} \u00b5g/m\u00b3", style, w)
    if aq.pm1 is not None:
        y = _kv(draw, x, y, "PM1.0", f"{aq.pm1:.1f} \u00b5g/m\u00b3", style, w)
    if aq.pm10 is not None:
        y = _kv(draw, x, y, "PM10", f"{aq.pm10:.1f} \u00b5g/m\u00b3", style, w)
    if aq.temperature is not None:
        y = _kv(draw, x, y, "Temp", f"{aq.temperature:.1f}\u00b0F", style, w)
    if aq.humidity is not None:
        y = _kv(draw, x, y, "Humidity", f"{aq.humidity:.0f}%", style, w)
    if aq.pressure is not None:
        y = _kv(draw, x, y, "Pressure", f"{aq.pressure:.1f} hPa", style, w)
    return y


def _birthday_section(draw, x, y, w, birthdays, today, style) -> int:
    y = _label(draw, x, y, w, "BIRTHDAYS", style)
    if not birthdays:
        return _kv(draw, x, y, "", "none upcoming", style, w)
    for bday in birthdays[:_MAX_BIRTHDAYS]:
        date_str = bday.date.strftime("%b %-d")
        value = f"{date_str}  ({bday.age})" if bday.age is not None else date_str
        y = _kv(draw, x, y, bday.name, value, style, w)
    return y


def _staleness_str(level: StalenessLevel | None) -> str:
    if level is None:
        return "n/a"
    return {
        StalenessLevel.FRESH: "Fresh",
        StalenessLevel.AGING: "Aging",
        StalenessLevel.STALE: "Stale !",
        StalenessLevel.EXPIRED: "Expired !",
    }.get(level, "Unknown")


def _status_section(draw, x, y, w, data: DashboardData, style) -> int:
    y = _label(draw, x, y, w, "STATUS", style)
    pairs = [("weather", "Weather"), ("events", "Calendar"), ("air_quality", "Air quality")]
    for src_key, label in pairs:
        level = data.source_staleness.get(src_key)
        y = _kv(draw, x, y, label, _staleness_str(level), style, w)
    return y
