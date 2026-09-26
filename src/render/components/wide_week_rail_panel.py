"""wide_week_rail_panel.py — the editorial rail beside wide_week's week grid.

``wide_week`` keeps the standard week view intact and gives it the right-hand
920 px of the strip. This module draws the column to its left: a modern
broadsheet rail, set in Playfair Display with small-caps labels in the accent
and hairline rules, carrying what the week grid does not — the conditions now,
what is on or up next, a short forecast, the sky, birthdays and the day's
quote. Top to bottom:

  * **Masthead** — the weekday in display type, the ISO week and day of the
    year beneath it, and the "updated" stamp (with a stale mark when any
    source is serving cache) at the right.
  * **Weather now** — the temperature as a display numeral beside the
    condition, high and low, feels-like and wind; an inverted bar for the
    first active alert.
  * **Now / Next** — the event in progress (``NOW``, with its end), else the
    next one to start (``NEXT``, with the weekday when it is not today). This
    is the rail's only clock-driven element, and it moves only at event
    boundaries.
  * **Forecast | Sky** — three forecast days beside sunrise, sunset, the day's
    length (and its change since yesterday, with coordinates) and the moon.
  * **Birthdays** — the next two weeks' on one line.
  * **Quote** — the day's quote set large, a hanging accent quote mark, the
    author in small caps.

Colour has two jobs here, one per accent ink. **Red** (the primary accent) is
for labels and warnings: section labels, the stale mark, the alert bar.
**Yellow** (the resolved ``accent_warn``) is a highlighter and never ink —
yellow type or rules on paper are the weakest contrast the four inks give, so
it only ever sits *behind* black type: the NOW/NEXT band, the chance-of-rain
chips, a birthday falling today. On a monochrome panel ``accent_warn`` resolves
to ink, ``highlight()`` returns ``None``, and each of those falls back to plain
black type on paper.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from PIL import ImageDraw

from src.astronomy import day_length, day_length_delta, sun_times
from src.data.models import Birthday, CalendarEvent, DashboardData, WeatherData
from src.render import fonts
from src.render.artkit import to_local_naive
from src.render.components.wide_horizon_panel import sun_zone
from src.render.icons import draw_weather_icon
from src.render.moon import moon_illumination, moon_phase_glyph, moon_phase_name
from src.render.primitives import (
    content_time,
    deg_to_compass,
    draw_text_truncated,
    fmt_time,
    next_birthday,
    text_width,
    wind_unit,
    wrap_lines,
)
from src.render.quotes import quote_for
from src.render.theme import ComponentRegion, ThemeStyle

PAD = 22
BIRTHDAY_DAYS = 14
FORECAST_DAYS = 3
QUOTE_PTS = (19, 17, 16, 15)  # tried largest first until the quote fits its space
AUTHOR_H = 16
SKY_LABEL_W = 42
BAND_INSET = 10  # the NOW/NEXT type's inset inside its highlighter band

# Section tops, relative to the region. Fixed rather than flowed, so the rules
# land in the same place every day and the column reads as a page, not a list.
MAST_Y = 12
MAST_LINE_Y = 62
MAST_RULE_Y = 80
WEATHER_Y = 94
ALERT_Y = 166
NEXT_Y = 198
NEXT_RULE_Y = 256
GRID_Y = 266
ROW_H = 22
GRID_RULE_Y = 354
BIRTHDAY_Y = 363
QUOTE_Y = 394
BOTTOM_PAD = 8


# ---------------------------------------------------------------------------
# Content (pure)
# ---------------------------------------------------------------------------


def masthead_line(today: date) -> str:
    """``WEEK 15 · DAY 96`` — the ISO week and the day of the year."""
    return f"WEEK {today.isocalendar()[1]} · DAY {today.timetuple().tm_yday}"


def now_or_next(events: list[CalendarEvent], now: datetime) -> tuple[str, CalendarEvent] | None:
    """``("NOW", event)`` for a timed event in progress, else ``("NEXT", event)``.

    All-day events are skipped: the grid already shows them as bars, and one
    would sit in this slot all day. The result changes only when an event
    starts or ends — the rail's one concession to the clock.
    """
    timed = sorted((e for e in events if not e.is_all_day), key=lambda e: (e.start, e.end))
    for evt in timed:
        if evt.start <= now < evt.end:
            return "NOW", evt
    for evt in timed:
        if evt.start > now:
            return "NEXT", evt
    return None


def when_label(kind: str, evt: CalendarEvent, now: datetime) -> str:
    """The time line for a NOW/NEXT event: ``until 2:30p``, ``2p``, ``Tue 9a``."""
    if kind == "NOW":
        return f"until {fmt_time(evt.end)}"
    if evt.start.date() == now.date():
        return fmt_time(evt.start)
    if evt.start.date() == now.date() + timedelta(days=1):
        return f"Tomorrow {fmt_time(evt.start)}"
    return f"{evt.start.strftime('%a')} {fmt_time(evt.start)}"


def birthday_entries(birthdays: list[Birthday], today: date) -> list[tuple[str, bool]]:
    """Birthdays in the next two weeks, soonest first, as ``(text, is_today)``."""
    rows = []
    for b in birthdays:
        when = next_birthday(b.date, today)
        days = (when - today).days
        if days > BIRTHDAY_DAYS:
            continue
        if days == 0:
            label = "today"
        elif days == 1:
            label = "tomorrow"
        elif days < 7:
            label = when.strftime("%a")
        else:
            label = when.strftime("%b %-d")
        name = b.name if b.age is None else f"{b.name} {b.age}"
        rows.append((when, f"{name} · {label}", days == 0))
    rows.sort(key=lambda r: r[0])
    return [(text, is_today) for _, text, is_today in rows]


BIRTHDAY_GAP = 18


def birthday_line(birthdays: list[Birthday], today: date) -> str:
    """The birthday entries as one line: ``Mom · Thu     Jake 30 · Mon``."""
    return "     ".join(text for text, _ in birthday_entries(birthdays, today))


def sky_rows(
    weather: WeatherData | None,
    today: date,
    latitude: float | None,
    longitude: float | None,
    tz: tzinfo | None,
) -> list[tuple[str, str]]:
    """``(label, value)`` rows for the sun's hours and the day's length.

    Computed from the coordinates when they are set (exact ``(0, 0)`` means
    unset, as elsewhere), which also gives the change since yesterday;
    otherwise read from the weather's reported sunrise and sunset.
    """
    rise = down = None
    length: timedelta | None = None
    delta: timedelta | None = None
    if latitude is not None and longitude is not None and not (latitude == 0 and longitude == 0):
        # A naive render clock (previews, snapshots) would otherwise read the
        # UTC sun times as local; see wide_horizon_panel.sun_zone.
        tz = sun_zone(tz, latitude, longitude)
        st = sun_times(today, latitude, longitude)
        rise = to_local_naive(st.sunrise, tz) if st.sunrise else None
        down = to_local_naive(st.sunset, tz) if st.sunset else None
        length = day_length(st)
        delta = day_length_delta(today, latitude, longitude)
    elif weather is not None and weather.sunrise and weather.sunset:
        rise = to_local_naive(weather.sunrise, tz)
        down = to_local_naive(weather.sunset, tz)
        length = down - rise
    rows: list[tuple[str, str]] = []
    if rise is not None and down is not None:
        rows.append(("Sun", f"{fmt_time(rise)} – {fmt_time(down)}"))
    if length is not None and length.total_seconds() > 0:
        minutes = int(length.total_seconds() // 60)
        text = f"{minutes // 60}h {minutes % 60:02d}m"
        if delta is not None:
            secs = int(round(delta.total_seconds()))
            sign = "+" if secs >= 0 else "−"
            secs = abs(secs)
            text += f"  {sign}{secs // 60}m{secs % 60:02d}s"
        rows.append(("Day", text))
    return rows


def fit_quote(text: str, width: int, height: int) -> tuple[int, list[str]]:
    """The largest of ``QUOTE_PTS`` at which *text* and its author fit *height*.

    Set in Playfair Medium: the Regular's hairline strokes break up on a 1-bit
    plate, where type is rasterised without antialiasing.

    Line pitch is the size plus 5 px, and the author line takes ``AUTHOR_H``.
    Failing every size, the smallest, cut to the lines that fit with an ellipsis.
    """
    for pt in QUOTE_PTS:
        lines = wrap_lines(text, fonts.playfair_medium(pt), width)
        if len(lines) * (pt + 5) + AUTHOR_H <= height:
            return pt, lines
    pt = QUOTE_PTS[-1]
    room = max(1, (height - AUTHOR_H) // (pt + 5))
    lines = wrap_lines(text, fonts.playfair_medium(pt), width)
    if len(lines) > room:
        lines = lines[:room]
        lines[-1] = lines[-1].rstrip(" ,;:.") + "…"
    return pt, lines


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def highlight(style: ThemeStyle):
    """The highlighter fill (yellow), or ``None`` on a plate that has no such ink.

    ``accent_warn`` resolves to yellow on the colour panels and to ink on a
    monochrome one; a fill in ink behind ink type would black the type out.
    """
    fill = style.accent_warn
    if fill is None or fill == style.fg:
        return None
    return fill


def _label(draw, x: float, y: float, text: str, style: ThemeStyle, fill=None) -> None:
    """A section label: small caps, letter-spaced, in the accent unless *fill* says."""
    font = fonts.dm_bold(11)
    fill = style.primary_accent_fill() if fill is None else fill
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + 1.6


def _hairline(draw, x0: int, x1: int, y: int, style: ThemeStyle) -> None:
    draw.line((x0, y, x1, y), fill=style.fg, width=1)


def draw_wide_week_rail(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion,
    style: ThemeStyle,
    quote_refresh: str = "daily",
    quotes_path: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """Draw the rail into *region*."""
    tz = getattr(now, "tzinfo", None)
    local_now = to_local_naive(now, tz)
    x0 = region.x + PAD
    x1 = region.x + region.w - PAD
    width = x1 - x0
    top = region.y
    fg, accent = style.fg, style.primary_accent_fill()

    draw.rectangle(
        (region.x, region.y, region.x + region.w - 1, region.y + region.h - 1), fill=style.bg
    )
    # The rail's edge against the grid, full height.
    edge = region.x + region.w - 1
    draw.line((edge, region.y, edge, region.y + region.h), fill=fg, width=1)

    # Masthead ---------------------------------------------------------------
    weekday = today.strftime("%A")
    draw.text((x0, top + MAST_Y), weekday, font=fonts.playfair_bold(40), fill=fg)
    _label(draw, x0, top + MAST_LINE_Y, masthead_line(today), style)
    stamp = content_time(data, now)
    stamp_text = f"UPDATED {fmt_time(to_local_naive(stamp, tz)).upper()}"
    if data.is_stale:
        stamp_text = "! STALE · " + stamp_text
    small = fonts.dm_semibold(11)
    draw.text(
        (x1 - text_width(draw, stamp_text, small), top + MAST_LINE_Y),
        stamp_text,
        font=small,
        fill=accent if data.is_stale else fg,
    )
    draw.line((x0, top + MAST_RULE_Y, x1, top + MAST_RULE_Y), fill=fg, width=3)
    _hairline(draw, x0, x1, top + MAST_RULE_Y + 5, style)

    # Weather now -------------------------------------------------------------
    weather = data.weather
    wy = top + WEATHER_Y
    if weather is None:
        draw.text((x0, wy + 8), "Weather unavailable", font=fonts.playfair_medium(22), fill=fg)
    else:
        # The numeral and its degree sign are set separately: Playfair's degree
        # at display size is a ring as tall as a lowercase letter.
        temp = str(round(weather.current_temp))
        big = fonts.playfair_bold(68)
        box = draw.textbbox((0, 0), temp, font=big)
        draw.text((x0 - box[0], wy - box[1]), temp, font=big, fill=fg)
        deg_x = x0 + (box[2] - box[0]) + 4
        draw.ellipse((deg_x, wy + 2, deg_x + 14, wy + 16), outline=fg, width=3)
        cx = deg_x + 36
        cw = x1 - cx
        draw_text_truncated(
            draw,
            (cx, wy + 4),
            weather.current_description.upper(),
            fonts.dm_bold(15),
            cw,
            fill=fg,
        )
        body = fonts.dm_medium(13)
        hl = f"High {round(weather.high)}°  ·  Low {round(weather.low)}°"
        draw_text_truncated(draw, (cx, wy + 28), hl, body, cw, fill=fg)
        extras = []
        if weather.feels_like is not None:
            extras.append(f"Feels {round(weather.feels_like)}°")
        if weather.wind_speed is not None:
            wind = f"Wind {round(weather.wind_speed)} {wind_unit(weather)}"
            if weather.wind_deg is not None:
                wind += f" {deg_to_compass(weather.wind_deg)}"
            extras.append(wind)
        if extras:
            draw_text_truncated(draw, (cx, wy + 48), "  ·  ".join(extras), body, cw, fill=fg)
        if weather.alerts:
            ay = top + ALERT_Y
            draw.rectangle((x0, ay, x1, ay + 22), fill=accent)
            draw_text_truncated(
                draw,
                (x0 + 8, ay + 4),
                "!  " + weather.alerts[0].event.upper(),
                fonts.dm_bold(12),
                width - 16,
                fill=style.bg,
            )

    # Now / next ---------------------------------------------------------------
    ny = top + NEXT_Y
    hi = highlight(style)
    if hi is not None:
        # The rail's most glanceable line gets the highlighter: black type on
        # a yellow band, flush with the column like the alert bar above it.
        draw.rectangle((x0, ny - 4, x1, top + NEXT_RULE_Y - 6), fill=hi)
    found = now_or_next(data.events, local_now)
    # Red on yellow vibrates; on the band the label is set in ink, and the
    # section is inset so its type does not touch the band's edges.
    label_fill = fg if hi is not None else None
    inset = BAND_INSET if hi is not None else 0
    nx, nx1 = x0 + inset, x1 - inset
    if found is None:
        _label(draw, nx, ny, "NEXT", style, label_fill)
        draw.text((nx, ny + 18), "Nothing scheduled", font=fonts.playfair_medium(20), fill=fg)
    else:
        kind, evt = found
        _label(draw, nx, ny, kind, style, label_fill)
        when = when_label(kind, evt, local_now)
        when_font = fonts.playfair_bold(20)
        draw.text((nx, ny + 16), when, font=when_font, fill=fg)
        tx = nx + text_width(draw, when, when_font) + 12
        draw_text_truncated(
            draw, (tx, ny + 18), evt.summary, fonts.dm_semibold(17), nx1 - tx, fill=fg
        )
        if evt.location:
            draw_text_truncated(
                draw, (tx, ny + 38), evt.location, fonts.dm_medium(12), nx1 - tx, fill=fg
            )
    _hairline(draw, x0, x1, top + NEXT_RULE_Y, style)

    # Forecast | Sky ------------------------------------------------------------
    gy = top + GRID_Y
    mid = x0 + width // 2
    _label(draw, x0, gy, "FORECAST", style)
    _label(draw, mid + 12, gy, "SKY", style)
    draw.line((mid, gy, mid, top + GRID_RULE_Y - 8), fill=fg, width=1)
    row_font = fonts.dm_medium(13)
    day_font = fonts.dm_bold(13)
    if weather is not None:
        for i, day in enumerate(weather.forecast[:FORECAST_DAYS]):
            ry = gy + 20 + i * ROW_H
            draw.text((x0, ry), day.date.strftime("%a").upper(), font=day_font, fill=fg)
            draw_weather_icon(draw, (x0 + 38, ry - 3), day.icon, size=15, fill=fg)
            hl = f"{round(day.high)}° / {round(day.low)}°"
            draw.text((x0 + 64, ry), hl, font=row_font, fill=fg)
            if day.precip_chance is not None and day.precip_chance >= 0.2:
                # Rain is not an alarm, so not red: a yellow chip behind ink
                # type, or plain ink where the panel has no yellow.
                pct = f"{round(day.precip_chance * 100)}%"
                pw = text_width(draw, pct, row_font)
                px = mid - 12 - pw
                if hi is not None:
                    draw.rounded_rectangle(
                        (px - 5, ry - 2, px + pw + 5, ry + 17), radius=4, fill=hi
                    )
                draw.text((px, ry), pct, font=row_font, fill=fg)
    sx = mid + 12
    rows = sky_rows(weather, today, latitude, longitude, tz)
    for i, (label, value) in enumerate(rows):
        ry = gy + 20 + i * ROW_H
        draw.text((sx, ry), label, font=row_font, fill=fg)
        draw_text_truncated(
            draw, (sx + SKY_LABEL_W, ry), value, day_font, x1 - sx - SKY_LABEL_W, fill=fg
        )
    my = gy + 20 + len(rows) * ROW_H
    draw.text((sx, my - 3), moon_phase_glyph(today), font=fonts.weather_icon(15), fill=fg)
    moon = f"{moon_phase_name(today)} {round(moon_illumination(today))}%"
    draw_text_truncated(
        draw, (sx + SKY_LABEL_W, my), moon, row_font, x1 - sx - SKY_LABEL_W, fill=fg
    )
    _hairline(draw, x0, x1, top + GRID_RULE_Y, style)

    # Birthdays ------------------------------------------------------------------
    by = top + BIRTHDAY_Y
    entries = birthday_entries(data.birthdays, today)
    if entries:
        _label(draw, x0, by + 2, "BIRTHDAYS", style)
        bfont = fonts.dm_semibold(13)
        lx = x0 + 92
        for i, (text, is_today) in enumerate(entries):
            tw = text_width(draw, text, bfont)
            if lx + tw > x1:
                if i == 0:  # a single entry too long for the line is cut, not dropped
                    draw_text_truncated(draw, (lx, by), text, bfont, x1 - lx, fill=fg)
                break
            if is_today and hi is not None:
                draw.rounded_rectangle((lx - 5, by - 2, lx + tw + 5, by + 17), radius=4, fill=hi)
            draw.text((lx, by), text, font=bfont, fill=fg)
            lx += tw + BIRTHDAY_GAP

    # Quote ------------------------------------------------------------------------
    quote = quote_for(today, refresh=quote_refresh, now=now, path=quotes_path)
    qy = top + QUOTE_Y
    mark_font = fonts.playfair_bold(46)
    draw.text((x0 - 2, qy - 8), "“", font=mark_font, fill=accent)
    qx = x0 + 26
    pt, lines = fit_quote(quote["text"], x1 - qx, region.h - QUOTE_Y - BOTTOM_PAD)
    qfont = fonts.playfair_medium(pt)
    lh = pt + 5
    for i, ln in enumerate(lines):
        draw.text((qx, qy + i * lh), ln, font=qfont, fill=fg)
    author = "— " + quote["author"].upper()
    ay = qy + len(lines) * lh + 3
    draw_text_truncated(draw, (qx, ay), author, fonts.dm_semibold(11), x1 - qx, fill=fg)
