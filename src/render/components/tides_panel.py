"""tides_panel.py — Alternating inverted bands for the "tides" theme.

Renders 8 full-width horizontal bands flowing top to bottom, alternating
between inverted (white-on-black) and normal (black-on-white).  Bands with
no data are skipped and the remaining bands expand to fill the canvas.

Combines fuzzy clock, events, weather, forecast, AQI+moon, birthdays,
quote, and host diagnostics in a single view.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from PIL import ImageDraw

from src.data.models import DashboardData
from src.render.components.fuzzyclock_panel import fuzzy_time
from src.render.fonts import cyber_mono, weather_icon
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_illumination, moon_phase_glyph
from src.render.primitives import (
    draw_text_truncated,
    draw_text_wrapped,
    events_for_day,
    filled_rect,
    fmt_time,
    text_height,
    text_width,
)
from src.render.theme import ComponentRegion, ThemeStyle

QUOTES_FILE = Path(__file__).parent.parent.parent.parent / "config" / "quotes.json"
_DEFAULT_QUOTES = [
    {"text": "Not all those who wander are lost.", "author": "J.R.R. Tolkien"},
    {"text": "Dwell on the beauty of life.", "author": "Marcus Aurelius"},
]

_PAD = 14  # horizontal padding inside each band


def _quote_for_panel(today: date, refresh: str = "daily", now: datetime | None = None) -> dict:
    """Pick a quote deterministically with a tides-specific key prefix."""
    if refresh == "hourly":
        dt = now if now is not None else datetime.now()
        key = f"tides-{today.isoformat()}T{dt.hour:02d}"
    elif refresh == "twice_daily":
        dt = now if now is not None else datetime.now()
        period = "am" if dt.hour < 12 else "pm"
        key = f"tides-{today.isoformat()}-{period}"
    else:
        key = f"tides-{today.isoformat()}"
    if QUOTES_FILE.exists():
        try:
            quotes = json.loads(QUOTES_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            quotes = _DEFAULT_QUOTES
    else:
        quotes = _DEFAULT_QUOTES
    day_hash = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return quotes[day_hash % len(quotes)]


# ---------------------------------------------------------------------------
# Individual band drawing functions
# ---------------------------------------------------------------------------


def _band_header(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    now: datetime,
    style: ThemeStyle,
) -> None:
    """Band 1 (inverted): Date + fuzzy clock."""
    fg, bg = style.fg, style.bg
    filled_rect(draw, (x0, y, x0 + w - 1, y + h - 1), fill=fg)

    title_font = (style.font_title or style.font_bold)(16)
    date_str = now.strftime("%A   %B %-d   %Y").upper()
    draw.text(
        (x0 + _PAD, y + (h - text_height(title_font)) // 2), date_str, font=title_font, fill=bg
    )

    fuzzy = fuzzy_time(now)
    fuzzy_font = (style.font_title or style.font_bold)(15)
    fw = text_width(draw, fuzzy, fuzzy_font)
    draw.text(
        (x0 + w - fw - _PAD, y + (h - text_height(fuzzy_font)) // 2),
        fuzzy,
        font=fuzzy_font,
        fill=bg,
    )


def _band_events(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    data: DashboardData,
    today: date,
    style: ThemeStyle,
) -> None:
    """Band 2 (normal): Today's events as flowing inline text."""
    fg = style.fg
    font = (style.font_regular)(13)

    today_events = events_for_day(data.events, today)
    if not today_events:
        draw.text(
            (x0 + _PAD, y + (h - text_height(font)) // 2), "No events today", font=font, fill=fg
        )
        return

    parts = []
    for ev in today_events:
        if ev.is_all_day:
            parts.append(f"all day {ev.summary}")
        else:
            parts.append(f"{fmt_time(ev.start)} {ev.summary}")
    text = "  \u00b7  ".join(parts)

    ty = y + 6
    line_font = font
    line_h = text_height(line_font)
    max_lines = max(1, (h - 8) // (line_h + 2))
    draw_text_wrapped(
        draw, (x0 + _PAD, ty), text, line_font, w - _PAD * 2, max_lines=max_lines, fill=fg
    )


def _band_weather(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    data: DashboardData,
    style: ThemeStyle,
) -> None:
    """Band 3 (inverted): Current weather conditions."""
    fg, bg = style.fg, style.bg
    filled_rect(draw, (x0, y, x0 + w - 1, y + h - 1), fill=fg)

    weather = data.weather
    if not weather:
        font = (style.font_regular)(13)
        draw.text(
            (x0 + _PAD, y + (h - text_height(font)) // 2),
            "Weather data unavailable",
            font=font,
            fill=bg,
        )
        return

    cy = y + (h - 20) // 2
    fx = x0 + _PAD

    # Weather icon
    glyph = OWM_ICON_MAP.get(weather.current_icon, FALLBACK_ICON)
    wi_font = weather_icon(20)
    draw.text((fx, cy - 2), glyph, font=wi_font, fill=bg)
    fx += 26

    font = (style.font_regular)(14)
    parts = [
        f"{weather.current_temp:.0f}°",
        weather.current_description.title(),
        f"H:{weather.high:.0f}° L:{weather.low:.0f}°",
    ]
    if weather.feels_like is not None:
        parts.append(f"Feels: {weather.feels_like:.0f}°")
    if weather.humidity is not None:
        parts.append(f"{weather.humidity}%")
    text = "    ".join(parts)
    draw.text((fx, cy), text, font=font, fill=bg)


def _band_forecast(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    data: DashboardData,
    style: ThemeStyle,
) -> None:
    """Band 4 (normal): 5-day forecast inline."""
    fg = style.fg
    weather = data.weather
    if not weather or not weather.forecast:
        return

    font = (style.font_regular)(13)
    cy = y + (h - text_height(font)) // 2
    fx = x0 + _PAD

    for fc in weather.forecast[:5]:
        day_name = fc.date.strftime("%a").upper()
        glyph = OWM_ICON_MAP.get(fc.icon, FALLBACK_ICON)
        wi_font = weather_icon(14)
        draw.text((fx, cy - 2), glyph, font=wi_font, fill=fg)
        fx += 18
        fc_text = f"{day_name} {fc.high:.0f}/{fc.low:.0f}"
        draw.text((fx, cy), fc_text, font=font, fill=fg)
        fx += text_width(draw, fc_text, font) + 20


def _band_environment(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    data: DashboardData,
    today: date,
    style: ThemeStyle,
) -> None:
    """Band 5 (inverted): AQI + sunrise/sunset + moon phase."""
    fg, bg = style.fg, style.bg
    filled_rect(draw, (x0, y, x0 + w - 1, y + h - 1), fill=fg)

    font = (style.font_regular)(13)
    cy = y + (h - text_height(font)) // 2
    fx = x0 + _PAD

    parts = []
    if data.air_quality:
        parts.append(f"AQI {data.air_quality.aqi}  {data.air_quality.category}")
        if data.air_quality.pm25 is not None:
            parts.append(f"PM2.5: {data.air_quality.pm25:.1f}")

    weather = data.weather
    if weather:
        if weather.sunrise:
            parts.append(f"\u2191{fmt_time(weather.sunrise)}")
        if weather.sunset:
            parts.append(f"\u2193{fmt_time(weather.sunset)}")

    # Moon phase
    moon_glyph = moon_phase_glyph(today)
    illum = moon_illumination(today)
    text = "    ".join(parts)
    draw.text((fx, cy), text, font=font, fill=bg)

    # Moon glyph at end
    tx = fx + text_width(draw, text, font) + 20
    wi_font = weather_icon(16)
    draw.text((tx, cy - 2), moon_glyph, font=wi_font, fill=bg)
    tx += 20
    draw.text((tx, cy), f"{illum:.0f}%", font=font, fill=bg)


def _band_birthdays(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    data: DashboardData,
    today: date,
    style: ThemeStyle,
) -> None:
    """Band 6 (normal): Birthday countdowns inline."""
    fg = style.fg
    font = (style.font_regular)(13)
    cy = y + (h - text_height(font)) // 2

    if not data.birthdays:
        draw.text((x0 + _PAD, cy), "No upcoming birthdays", font=font, fill=fg)
        return

    parts = []
    for bday in data.birthdays[:4]:
        days_until = (bday.date - today).days
        entry = bday.name
        if bday.age is not None:
            entry += f" ({bday.age})"
        entry += f" {days_until}d"
        parts.append(entry)
    text = "  \u00b7  ".join(parts)
    draw_text_truncated(draw, (x0 + _PAD, cy), text, font, w - _PAD * 2, fill=fg)


def _band_quote(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    today: date,
    now: datetime,
    style: ThemeStyle,
    quote_refresh: str,
) -> None:
    """Band 7 (inverted): Daily quote."""
    fg, bg = style.fg, style.bg
    filled_rect(draw, (x0, y, x0 + w - 1, y + h - 1), fill=fg)

    quote = _quote_for_panel(today, refresh=quote_refresh, now=now)
    q_text = f"\u201c{quote['text']}\u201d"
    author = quote.get("author", "")

    q_font = (style.font_regular)(15)
    a_font = (style.font_medium or style.font_regular)(12)
    max_w = w - _PAD * 2

    # Centre the quote vertically
    qy = y + 12
    used_h = draw_text_wrapped(draw, (x0 + _PAD, qy), q_text, q_font, max_w, max_lines=3, fill=bg)

    if author:
        attr = f"\u2014 {author}"
        aw = text_width(draw, attr, a_font)
        draw.text((x0 + w - aw - _PAD, qy + used_h + 4), attr, font=a_font, fill=bg)


def _band_host(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    data: DashboardData,
    style: ThemeStyle,
) -> None:
    """Band 8 (normal): Host diagnostics as inline key-value pairs."""
    fg = style.fg
    font = cyber_mono(12)
    cy = y + (h - text_height(font)) // 2

    hd = data.host_data
    if not hd:
        draw.text((x0 + _PAD, cy), "no host data", font=font, fill=fg)
        return

    parts = []
    if hd.hostname:
        parts.append(hd.hostname)
    if hd.uptime_seconds is not None:
        days = int(hd.uptime_seconds // 86400)
        hours = int((hd.uptime_seconds % 86400) // 3600)
        parts.append(f"{days}d {hours}h up")
    if hd.load_1m is not None:
        parts.append(f"load {hd.load_1m:.2f}")
    if hd.ram_used_mb is not None and hd.ram_total_mb is not None:
        ram_pct = int(100 * hd.ram_used_mb / hd.ram_total_mb)
        parts.append(f"{ram_pct}% RAM")
    if hd.cpu_temp_c is not None:
        parts.append(f"{hd.cpu_temp_c:.0f}\u00b0C")
    if hd.ip_address:
        parts.append(hd.ip_address)

    text = "  \u00b7  ".join(parts)
    draw_text_truncated(draw, (x0 + _PAD, cy), text, font, w - _PAD * 2, fill=fg)


# ---------------------------------------------------------------------------
# Main draw function
# ---------------------------------------------------------------------------

# Band definitions: (draw_fn, needs_data, default_height, inverted)
# Bands with no data are dynamically skipped.


def draw_tides(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    quote_refresh: str = "daily",
) -> None:
    """Draw alternating inverted horizontal bands showing all data sources."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    x0, y0, w, h = region.x, region.y, region.w, region.h

    # Define bands: (id, draw_callable, default_height, has_data)
    bands: list[tuple[str, int, bool]] = [
        ("header", 42, True),  # always present
        ("events", 54, True),  # always present (shows "no events" if empty)
        ("weather", 40, data.weather is not None),
        ("forecast", 50, data.weather is not None and bool(data.weather.forecast)),
        ("environment", 38, True),  # moon always available; AQI optional
        ("birthdays", 36, True),  # always present (shows "no upcoming" if empty)
        ("quote", 86, True),  # always present
        ("host", 34, data.host_data is not None),
    ]

    # Filter to bands that have data
    active_bands = [(bid, bh) for bid, bh, has_data in bands if has_data]

    # Distribute remaining vertical space proportionally
    total_default = sum(bh for _, bh in active_bands)
    remaining = h - total_default
    if remaining > 0 and active_bands:
        # Give extra space to the quote band first, then distribute evenly
        extra_per = remaining // len(active_bands)
        remainder = remaining % len(active_bands)
        adjusted = []
        for i, (bid, bh) in enumerate(active_bands):
            bonus = extra_per + (1 if i < remainder else 0)
            if bid == "quote":
                bonus += extra_per * (len(active_bands) - 1) // 2
            adjusted.append((bid, bh + bonus))
        # Re-normalise if we over-allocated
        total_adj = sum(bh for _, bh in adjusted)
        if total_adj > h:
            adjusted = active_bands  # fall back to defaults
        else:
            active_bands = adjusted

    # Draw bands sequentially
    band_drawers = {
        "header": lambda y, bh: _band_header(draw, x0, y, w, bh, now, style),
        "events": lambda y, bh: _band_events(draw, x0, y, w, bh, data, today, style),
        "weather": lambda y, bh: _band_weather(draw, x0, y, w, bh, data, style),
        "forecast": lambda y, bh: _band_forecast(draw, x0, y, w, bh, data, style),
        "environment": lambda y, bh: _band_environment(draw, x0, y, w, bh, data, today, style),
        "birthdays": lambda y, bh: _band_birthdays(draw, x0, y, w, bh, data, today, style),
        "quote": lambda y, bh: _band_quote(draw, x0, y, w, bh, today, now, style, quote_refresh),
        "host": lambda y, bh: _band_host(draw, x0, y, w, bh, data, style),
    }

    cy = y0
    for bid, bh in active_bands:
        drawer = band_drawers.get(bid)
        if drawer:
            drawer(cy, bh)
        cy += bh
