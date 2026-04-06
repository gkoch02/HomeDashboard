"""scorecard_panel.py — Numeric KPI tile grid for the "scorecard" theme.

Renders a 4-column grid of metric tiles where every data source becomes a big
hero number with a label and context line.  Introduces computed metrics like
"% of day remaining" and "time until sunset".
"""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import ImageDraw

from src.data.models import DashboardData
from src.render.fonts import sg_bold, weather_icon
from src.render.moon import moon_illumination, moon_phase_glyph, moon_phase_name
from src.render.primitives import (
    draw_text_truncated,
    draw_text_wrapped,
    events_for_day,
    filled_rect,
    fmt_time,
    hline,
    text_height,
    text_width,
    vline,
)
from src.render.theme import ComponentRegion, ThemeStyle

QUOTES_FILE = Path(__file__).parent.parent.parent.parent / "config" / "quotes.json"

# Layout
_HEADER_H = 40
_COL_W = 200  # 800 / 4
_ROW1_H = 130
_ROW2_H = 130
_ROW3_H = 480 - _HEADER_H - _ROW1_H - _ROW2_H  # 180
_PAD = 10

_DEFAULT_QUOTES = [
    {"text": "Not all those who wander are lost.", "author": "J.R.R. Tolkien"},
    {"text": "Dwell on the beauty of life.", "author": "Marcus Aurelius"},
]


def _quote_for_panel(today: date, refresh: str = "daily", now: datetime | None = None) -> dict:
    """Pick a quote deterministically."""
    if refresh == "hourly":
        dt = now if now is not None else datetime.now()
        key = f"scorecard-{today.isoformat()}T{dt.hour:02d}"
    elif refresh == "twice_daily":
        dt = now if now is not None else datetime.now()
        period = "am" if dt.hour < 12 else "pm"
        key = f"scorecard-{today.isoformat()}-{period}"
    else:
        key = f"scorecard-{today.isoformat()}"
    if QUOTES_FILE.exists():
        try:
            quotes = json.loads(QUOTES_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            quotes = _DEFAULT_QUOTES
    else:
        quotes = _DEFAULT_QUOTES
    day_hash = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return quotes[day_hash % len(quotes)]


def _draw_tile(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    hero: str,
    label: str,
    context: str,
    style: ThemeStyle,
    hero_size: int = 42,
) -> None:
    """Draw a single metric tile: big number, label, context line."""
    fg = style.fg
    hero_font = sg_bold(hero_size)
    label_font = (style.font_section_label or style.font_bold)(10)
    ctx_font = (style.font_regular)(11)

    # Hero number — vertically centred in upper 60% of tile
    hero_area_h = int(h * 0.55)
    hh = text_height(hero_font)
    hw = text_width(draw, hero, hero_font)
    hx = x + (w - hw) // 2
    hy = y + (hero_area_h - hh) // 2 + 4
    draw_text_truncated(draw, (hx, hy), hero, hero_font, w - _PAD * 2, fill=fg)

    # Label — ALL CAPS below hero
    label_y = y + hero_area_h
    lw = text_width(draw, label, label_font)
    draw.text((x + (w - lw) // 2, label_y), label, font=label_font, fill=fg)

    # Context — smaller, below label
    ctx_y = label_y + text_height(label_font) + 3
    cw = text_width(draw, context, ctx_font)
    if cw <= w - _PAD * 2:
        draw.text((x + (w - cw) // 2, ctx_y), context, font=ctx_font, fill=fg)
    else:
        draw_text_truncated(draw, (x + _PAD, ctx_y), context, ctx_font, w - _PAD * 2, fill=fg)


def draw_scorecard(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    quote_refresh: str = "daily",
) -> None:
    """Draw the scorecard KPI grid."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    x0, y0, w, _h = region.x, region.y, region.w, region.h
    fg, bg = style.fg, style.bg
    font_title = style.font_title or style.font_bold

    weather = data.weather
    # Strip tzinfo from all datetimes for safe naive comparison
    now_naive = now.replace(tzinfo=None)
    sunrise_dt = weather.sunrise.replace(tzinfo=None) if weather and weather.sunrise else None
    sunset_dt = weather.sunset.replace(tzinfo=None) if weather and weather.sunset else None

    # ── Header ──────────────────────────────────────────────────────────
    filled_rect(draw, (x0, y0, x0 + w - 1, y0 + _HEADER_H - 1), fill=fg)
    title_font = font_title(16)
    spaced_title = "S C O R E C A R D"
    draw.text((x0 + _PAD, y0 + 10), spaced_title, font=title_font, fill=bg)

    date_str = now.strftime("%a  %b %-d   %-I:%M%p").upper()
    date_font = (style.font_medium or style.font_bold)(12)
    dw = text_width(draw, date_str, date_font)
    draw.text((x0 + w - dw - _PAD, y0 + 13), date_str, font=date_font, fill=bg)

    # ── Grid lines ──────────────────────────────────────────────────────
    row1_y = y0 + _HEADER_H
    row2_y = row1_y + _ROW1_H
    row3_y = row2_y + _ROW2_H

    hline(draw, row1_y, x0, x0 + w - 1, fill=fg)
    hline(draw, row2_y, x0, x0 + w - 1, fill=fg)
    hline(draw, row3_y, x0, x0 + w - 1, fill=fg)

    # Vertical dividers for rows 1 and 2
    for col in range(1, 4):
        cx = x0 + col * _COL_W
        vline(draw, cx, row1_y, row3_y - 1, fill=fg)
    # Row 3: 2-column split
    vline(draw, x0 + _COL_W * 2, row3_y, y0 + 480 - 1, fill=fg)

    # ── Row 1 tiles ─────────────────────────────────────────────────────

    # Tile 1: Events today
    today_events = events_for_day(data.events, today)
    n_today = len(today_events)
    # Count events this week
    week_start = today - timedelta(days=today.weekday())
    week_events = [
        e
        for e in data.events
        if week_start
        <= (e.start.date() if hasattr(e.start, "date") else e.start)
        < week_start + timedelta(days=7)
    ]
    _draw_tile(
        draw,
        x0,
        row1_y,
        _COL_W,
        _ROW1_H,
        hero=str(n_today),
        label="EVENTS TODAY",
        context=f"{len(week_events)} this week",
        style=style,
    )

    # Tile 2: Temperature
    if weather:
        _draw_tile(
            draw,
            x0 + _COL_W,
            row1_y,
            _COL_W,
            _ROW1_H,
            hero=f"{weather.current_temp:.0f}°",
            label="OUTDOOR",
            context=f"H:{weather.high:.0f}° L:{weather.low:.0f}°",
            style=style,
        )
    else:
        _draw_tile(
            draw,
            x0 + _COL_W,
            row1_y,
            _COL_W,
            _ROW1_H,
            hero="—",
            label="OUTDOOR",
            context="no data",
            style=style,
        )

    # Tile 3: Air quality
    if data.air_quality:
        _draw_tile(
            draw,
            x0 + _COL_W * 2,
            row1_y,
            _COL_W,
            _ROW1_H,
            hero=str(data.air_quality.aqi),
            label="AIR QUALITY",
            context=data.air_quality.category,
            style=style,
        )
    else:
        _draw_tile(
            draw,
            x0 + _COL_W * 2,
            row1_y,
            _COL_W,
            _ROW1_H,
            hero="—",
            label="AIR QUALITY",
            context="n/a",
            style=style,
        )

    # Tile 4: Week/Year progress
    week_num = today.isocalendar()[1]
    day_of_year = today.timetuple().tm_yday
    days_in_year = 366 if calendar.isleap(today.year) else 365
    pct = int(100 * day_of_year / days_in_year)
    _draw_tile(
        draw,
        x0 + _COL_W * 3,
        row1_y,
        _COL_W,
        _ROW1_H,
        hero=f"W{week_num}",
        label=str(today.year),
        context=f"{pct}% of year",
        style=style,
    )

    # ── Row 2 tiles ─────────────────────────────────────────────────────

    # Tile 5: Day remaining %
    if sunrise_dt and sunset_dt and sunrise_dt <= now_naive <= sunset_dt:
        total_daylight = (sunset_dt - sunrise_dt).total_seconds()
        remaining = (sunset_dt - now_naive).total_seconds()
        day_pct = int(100 * remaining / total_daylight) if total_daylight > 0 else 0
        ctx = f"sunrise {fmt_time(sunrise_dt)}"
    else:
        # After sunset or before sunrise: show time until/since
        day_pct = 0
        ctx = "after sunset" if sunset_dt and now_naive > sunset_dt else "before sunrise"
    _draw_tile(
        draw,
        x0,
        row2_y,
        _COL_W,
        _ROW2_H,
        hero=f"{day_pct}%",
        label="DAYLIGHT LEFT",
        context=ctx,
        style=style,
    )

    # Tile 6: Sunset countdown
    if sunset_dt and now_naive < sunset_dt:
        delta = sunset_dt - now_naive
        hours = int(delta.total_seconds() // 3600)
        mins = int((delta.total_seconds() % 3600) // 60)
        sunset_hero = f"{hours}h{mins:02d}m" if hours > 0 else f"{mins}m"
        sunset_ctx = f"{fmt_time(sunset_dt)} sunset"
    elif sunset_dt:
        sunset_hero = "set"
        sunset_ctx = f"set at {fmt_time(sunset_dt)}"
    else:
        sunset_hero = "—"
        sunset_ctx = "no data"
    _draw_tile(
        draw,
        x0 + _COL_W,
        row2_y,
        _COL_W,
        _ROW2_H,
        hero=sunset_hero,
        label="UNTIL SUNSET",
        context=sunset_ctx,
        style=style,
    )

    # Tile 7: Next birthday
    if data.birthdays:
        bday = data.birthdays[0]
        days_until = (bday.date - today).days
        bday_ctx = bday.name
        if bday.age is not None:
            bday_ctx += f" ({bday.age})"
        _draw_tile(
            draw,
            x0 + _COL_W * 2,
            row2_y,
            _COL_W,
            _ROW2_H,
            hero=f"{days_until}d",
            label="NEXT BIRTHDAY",
            context=bday_ctx,
            style=style,
        )
    else:
        _draw_tile(
            draw,
            x0 + _COL_W * 2,
            row2_y,
            _COL_W,
            _ROW2_H,
            hero="—",
            label="NEXT BIRTHDAY",
            context="none upcoming",
            style=style,
        )

    # Tile 8: Host metric (CPU temp or load)
    if data.host_data:
        hd = data.host_data
        if hd.cpu_temp_c is not None:
            host_hero = f"{hd.cpu_temp_c:.0f}°C"
            host_label = "CPU TEMP"
            host_ctx = f"load {hd.load_1m:.2f}" if hd.load_1m is not None else ""
        elif hd.load_1m is not None:
            host_hero = f"{hd.load_1m:.2f}"
            host_label = "LOAD AVG"
            host_ctx = ""
            if hd.ram_used_mb is not None and hd.ram_total_mb is not None:
                ram_pct = int(100 * hd.ram_used_mb / hd.ram_total_mb)
                host_ctx = f"{ram_pct}% RAM"
        else:
            host_hero = "OK"
            host_label = "SYSTEM"
            host_ctx = hd.hostname or ""
        _draw_tile(
            draw,
            x0 + _COL_W * 3,
            row2_y,
            _COL_W,
            _ROW2_H,
            hero=host_hero,
            label=host_label,
            context=host_ctx,
            style=style,
        )
    else:
        _draw_tile(
            draw,
            x0 + _COL_W * 3,
            row2_y,
            _COL_W,
            _ROW2_H,
            hero="—",
            label="SYSTEM",
            context="n/a",
            style=style,
        )

    # ── Row 3: Moon (left half) + Quote (right half) ────────────────────

    moon_w = _COL_W * 2
    quote_w = w - moon_w

    # Moon tile: 4-day progression
    mx = x0 + _PAD
    my = row3_y + 16
    wi_font = weather_icon(32)
    for offset in range(-1, 3):
        d = today + timedelta(days=offset)
        glyph = moon_phase_glyph(d)
        draw.text((mx, my), glyph, font=wi_font, fill=fg)
        mx += 44

    phase_name = moon_phase_name(today)
    illum = moon_illumination(today)
    name_font = (style.font_section_label or style.font_bold)(10)
    draw.text((x0 + _PAD, my + 40), phase_name.upper(), font=name_font, fill=fg)
    illum_font = (style.font_regular)(11)
    draw.text(
        (x0 + _PAD, my + 40 + text_height(name_font) + 2),
        f"{illum:.0f}% illuminated",
        font=illum_font,
        fill=fg,
    )

    # Quote tile
    quote = _quote_for_panel(today, refresh=quote_refresh, now=now)
    qx = x0 + moon_w + _PAD
    qy = row3_y + 14
    q_font = (style.font_regular)(13)
    q_attr_font = (style.font_medium or style.font_regular)(11)
    q_text = f"\u201c{quote['text']}\u201d"
    q_max_w = quote_w - _PAD * 2

    used_h = draw_text_wrapped(draw, (qx, qy), q_text, q_font, q_max_w, max_lines=5, fill=fg)

    author = quote.get("author", "")
    if author:
        attr_str = f"\u2014 {author}"
        attr_w = text_width(draw, attr_str, q_attr_font)
        draw.text((qx + q_max_w - attr_w, qy + used_h + 4), attr_str, font=q_attr_font, fill=fg)
