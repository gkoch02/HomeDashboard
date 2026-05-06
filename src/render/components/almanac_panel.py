"""almanac_panel.py — Old-Farmer's-Almanac editorial theme.

Front-page composition that reads top to bottom like the cover of a 19th
century reference: ornamental masthead → editorial date line → four
bordered editorial sections in a 2×2 grid → triple-rule footer with the
day's aphorism.

  ┌──────────────────────────────────────────────────────────────┐
  │  ⚜            THE  DAILY  ALMANAC            ⚜              │
  │ ════════════════════════════════════════════════════════════ │
  │           VOL. CCXXVII   NO. 127   ·   WEDNESDAY             │
  │              MAY · SIX · TWO THOUSAND TWENTY-SIX             │
  │ ════════════════════════════════════════════════════════════ │
  │                                                              │
  │  ✦ THE HEAVENS ✦         │  ✦ FROM THE SKY ✦                 │
  │  Sunrise   5:48a EDT     │  Drizzle and 50° at the time      │
  │  Sunset    7:51p EDT     │  of going to press; light NW      │
  │  Day       14h 03m       │  winds. High of 72°, low 55°.     │
  │  Today    +2m 12s        │                                   │
  │  ☽ Waxing Crescent  24%  │                                   │
  │  Next Full   May 23      │                                   │
  │ ─────────────────────────┼───────────────────────────────────│
  │  ✦ THE WEEK AHEAD ✦      │  ✦ NEXT IN THE GARDEN ✦           │
  │  • Yoga at 5:30p today   │  Spring · Day 127 of 365          │
  │  • Brunch on Sunday      │  Sun lengthens by 2m daily        │
  │  • Mom's birthday May 9  │  Eta Aquariids meteor shower      │
  │                          │     in 0 days · ZHR 50            │
  │ ════════════════════════════════════════════════════════════ │
  │  "We don't see things as they are; we see them as we are."   │
  │                                            — ANAIS NIN       │
  │  ⚜      ⚜      ⚜      ⚜      ⚜      ⚜      ⚜      ⚜       │
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from PIL import ImageDraw

from src.astronomy import (
    day_length,
    day_length_delta,
    next_meteor_shower,
    sun_times,
)
from src.data.models import DashboardData
from src.render.components.info_panel import _quote_for_today
from src.render.moon import (
    moon_illumination,
    moon_phase_age,
    moon_phase_glyph,
    moon_phase_name,
)
from src.render.primitives import (
    draw_text_truncated,
    events_for_day,
    hline,
    text_height,
    text_width,
    vline,
    wrap_lines,
)
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

_PAD_X = 24

# Header band (masthead + date line)
_MASTHEAD_TOP = 14
_MASTHEAD_RULE_Y = 38
_DATELINE_KICKER_Y = 46
_DATELINE_BIG_Y = 64
_HEADER_BOTTOM_RULE_Y = 110

# Body band (four editorial sections in a 2×2 grid).  The mid-rule lands a
# little below the geometric centre so the top row (which carries the deeper
# Heavens key/value list) gets the extra breathing room it needs at the
# editorial body-text size.
_BODY_TOP = _HEADER_BOTTOM_RULE_Y + 12
_BODY_BOTTOM = 388
_BODY_MID_Y = 272
_COL_DIVIDER_X = 400  # vertical rule between left & right columns

# Footer band (triple rule + quote + author + ornament)
_FOOTER_RULE_Y = 392
_QUOTE_Y = 408
_FOOTER_ORNAMENT_Y = 466

_SYNODIC = 29.53059


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_local(dt: datetime | None, tz: tzinfo | None) -> datetime | None:
    """Convert *dt* to *tz* and strip tzinfo, or pass naive dt through."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    if tz is not None:
        dt = dt.astimezone(tz)
    else:
        dt = dt.astimezone()
    return dt.replace(tzinfo=None)


def _fmt_clock(dt: datetime | None, tz: tzinfo | None, suffix: str = "") -> str:
    """Format a clock time in compact lowercase am/pm with optional tz suffix."""
    local = _to_local(dt, tz)
    if local is None:
        return "—"
    s = local.strftime("%-I:%M%p").lower()
    s = s.replace("am", "a").replace("pm", "p")
    return f"{s} {suffix}".strip()


def _fmt_duration(td: timedelta | None) -> str:
    if td is None:
        return "—"
    total = int(td.total_seconds())
    hours, rem = divmod(abs(total), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m"


def _fmt_signed_minutes(td: timedelta | None) -> str:
    """Format a signed delta as e.g. '+2m 28s' / '-1m 04s' / '0s'."""
    if td is None:
        return "—"
    total = int(td.total_seconds())
    if total == 0:
        return "0s"
    sign = "+" if total > 0 else "-"
    total = abs(total)
    minutes, seconds = divmod(total, 60)
    if minutes == 0:
        return f"{sign}{seconds}s"
    return f"{sign}{minutes}m {seconds:02d}s"


def _season(today: date) -> str:
    """Return the meteorological season name for *today* (Northern hemisphere)."""
    m = today.month
    if m in (12, 1, 2):
        return "Winter"
    if m in (3, 4, 5):
        return "Spring"
    if m in (6, 7, 8):
        return "Summer"
    return "Autumn"


def _next_phase_date(today: date, target_fraction: float) -> date:
    """Walk forward day by day until the synodic fraction crosses *target*.

    Mirrors the helper in astronomy_panel.  ``target_fraction == 0`` finds
    the next new moon; ``0.5`` finds the next full moon.
    """
    for i in range(0, 45):
        d = today + timedelta(days=i)
        prev_age = moon_phase_age(d - timedelta(days=1))
        curr_age = moon_phase_age(d)
        prev_frac = prev_age / _SYNODIC
        curr_frac = curr_age / _SYNODIC
        target = target_fraction % 1.0
        if prev_frac <= curr_frac:
            if prev_frac < target <= curr_frac:
                return d
        else:
            if target > prev_frac or target <= curr_frac:
                return d
    return today + timedelta(days=29)


def _roman(n: int) -> str:
    """Tiny Roman-numeral converter used for the volume number on the masthead."""
    table = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"),
        (1, "I"),
    ]  # fmt: skip
    if n <= 0:
        return "—"
    out: list[str] = []
    for value, sym in table:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


def _upcoming_calendar_summary(data: DashboardData, today: date, max_lines: int) -> list[str]:
    """Return a short bulleted list of the next few notable upcoming items.

    Combines today's first event, the next few timed events in the week, and
    upcoming birthdays in the next 14 days.  Capped at *max_lines*.
    """
    items: list[str] = []
    seen_summaries: set[str] = set()

    # Today's earliest timed event
    todays = [e for e in events_for_day(data.events, today) if not e.is_all_day]
    if todays:
        e = todays[0]
        local = _to_local(e.start, None)
        when = local.strftime("%-I:%M%p").lower().replace(":00", "") if local else ""
        when = when.replace("am", "a").replace("pm", "p")
        items.append(f"{e.summary} at {when} today")
        seen_summaries.add(e.summary)

    # Next few non-today timed events within the week
    for ev in sorted(
        (e for e in data.events if isinstance(e.start, datetime)),
        key=lambda e: e.start,
    ):
        if ev.is_all_day:
            continue
        if ev.summary in seen_summaries:
            continue
        ev_date = ev.start.date()
        delta = (ev_date - today).days
        if delta <= 0 or delta > 6:
            continue
        when = ev.start.strftime("%A")
        items.append(f"{ev.summary} on {when}")
        seen_summaries.add(ev.summary)
        if len(items) >= max_lines:
            return items[:max_lines]

    # Upcoming birthdays inside the next two weeks
    if data.birthdays:
        for b in data.birthdays:
            try:
                bday_this_year = b.date.replace(year=today.year)
            except ValueError:
                continue
            if bday_this_year < today:
                bday_this_year = b.date.replace(year=today.year + 1)
            delta = (bday_this_year - today).days
            if 0 <= delta <= 14:
                month_day = bday_this_year.strftime("%b %-d")
                items.append(f"{b.name}'s birthday {month_day}")
                if len(items) >= max_lines:
                    break

    if not items:
        items.append("Quiet days ahead.")
    return items[:max_lines]


# ---------------------------------------------------------------------------
# Drawing primitives specific to the almanac (rules + ornaments)
# ---------------------------------------------------------------------------


def _triple_rule(
    draw: ImageDraw.ImageDraw,
    y: int,
    x0: int,
    x1: int,
    fill,
    accent,
) -> None:
    """Draw a thick / thin / thick triple horizontal rule (newspaper style)."""
    draw.line([(x0, y), (x1, y)], fill=fill, width=2)
    draw.line([(x0, y + 5), (x1, y + 5)], fill=accent, width=1)
    draw.line([(x0, y + 9), (x1, y + 9)], fill=fill, width=2)


def _ornament(draw: ImageDraw.ImageDraw, x: int, y: int, fill, size: int = 6) -> None:
    """Draw a small four-pointed star ornament centred on (*x*, *y*)."""
    draw.polygon(
        [
            (x, y - size),
            (x + size // 2, y),
            (x, y + size),
            (x - size // 2, y),
        ],
        fill=fill,
    )
    draw.polygon(
        [
            (x - size, y),
            (x, y - size // 2),
            (x + size, y),
            (x, y + size // 2),
        ],
        fill=fill,
    )


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _draw_masthead(
    draw: ImageDraw.ImageDraw,
    region: ComponentRegion,
    today: date,
    style: ThemeStyle,
) -> None:
    """Draw the title strip and the editorial date line."""
    fg = style.fg
    accent = style.primary_accent_fill()

    title_font = (style.font_section_label or style.font_bold)(17)
    masthead = "THE  DAILY  ALMANAC"
    tw = text_width(draw, masthead, title_font)
    cx = region.x + region.w // 2
    draw.text(
        (cx - tw // 2, region.y + _MASTHEAD_TOP),
        masthead,
        font=title_font,
        fill=fg,
    )

    # Ornaments flanking the title
    ornament_y = region.y + _MASTHEAD_TOP + 8
    _ornament(draw, region.x + _PAD_X + 8, ornament_y, accent)
    _ornament(draw, region.x + region.w - _PAD_X - 8, ornament_y, accent)

    # Triple rule under the masthead
    _triple_rule(
        draw,
        region.y + _MASTHEAD_RULE_Y,
        region.x + _PAD_X,
        region.x + region.w - _PAD_X,
        fg,
        accent,
    )

    # Kicker line: VOL. <roman> · NO. <day-of-year> · WEEKDAY
    kicker_font = (style.font_section_label or style.font_bold)(13)
    vol = _roman(today.year - 1799)  # arbitrary but stable
    day_of_year = today.timetuple().tm_yday
    kicker = f"VOL. {vol}   NO. {day_of_year}   ·   {today.strftime('%A').upper()}"
    kw = text_width(draw, kicker, kicker_font)
    draw.text(
        (cx - kw // 2, region.y + _DATELINE_KICKER_Y),
        kicker,
        font=kicker_font,
        fill=fg,
    )

    # Big editorial dateline
    big_font = (style.font_title or style.font_bold)(32)
    dateline = today.strftime("%B %-d, %Y").upper()
    bw = text_width(draw, dateline, big_font)
    draw.text(
        (cx - bw // 2, region.y + _DATELINE_BIG_Y),
        dateline,
        font=big_font,
        fill=fg,
    )

    # Closing triple rule below the dateline
    _triple_rule(
        draw,
        region.y + _HEADER_BOTTOM_RULE_Y - 4,
        region.x + _PAD_X,
        region.x + region.w - _PAD_X,
        fg,
        accent,
    )


def _draw_section_header(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    style: ThemeStyle,
) -> int:
    """Render a section label with a flanking ornament + underline.

    Cinzel is a classical Roman caps font and lacks decorative-glyph code
    points (❖, ✨, …), so the ornament here is hand-drawn next to the label
    rather than baked into the string.  Returns the next y to draw at.
    """
    label_font = (style.font_section_label or style.font_bold)(13)
    accent = style.primary_accent_fill()
    fg = style.fg

    lh = text_height(label_font)
    # Hand-drawn diamond ornament left of the label
    ox = x + 4
    oy = y + lh // 2 + 1
    _ornament(draw, ox, oy, accent, size=4)

    text_x = x + 16
    lw = text_width(draw, label, label_font)
    draw.text((text_x, y), label, font=label_font, fill=fg)

    # Mirror ornament after the label
    _ornament(draw, text_x + lw + 12, oy, accent, size=4)

    # Accent-coloured underline below the whole label cluster
    underline_y = y + lh + 2
    draw.line([(x, underline_y), (text_x + lw + 20, underline_y)], fill=accent, width=1)
    return underline_y + 8


def _draw_kv_row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    key: str,
    value: str,
    key_w: int,
    style: ThemeStyle,
    *,
    body_size: int = 15,
) -> int:
    """Draw a Playfair key/value row in the editorial body."""
    key_font = style.font_regular(body_size)
    val_font = style.font_semibold(body_size)
    draw.text((x, y), key, font=key_font, fill=style.fg)
    draw.text((x + key_w, y), value, font=val_font, fill=style.fg)
    return y + max(text_height(key_font), text_height(val_font)) + 4


def _draw_heavens(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    today: date,
    weather,
    latitude: float | None,
    longitude: float | None,
    tz: tzinfo | None,
    style: ThemeStyle,
) -> None:
    """Sun + moon column (top-left)."""
    y = _draw_section_header(draw, x, y, "THE HEAVENS", style)

    # Resolve sun times: lat/lon → astronomy module; else weather fallback.
    sunrise = sunset = None
    day_len: timedelta | None = None
    delta: timedelta | None = None
    if latitude is not None and longitude is not None and (latitude, longitude) != (0.0, 0.0):
        st = sun_times(today, latitude, longitude)
        sunrise = st.sunrise
        sunset = st.sunset
        day_len = day_length(st)
        delta = day_length_delta(today, latitude, longitude)
    elif weather is not None:
        sunrise = weather.sunrise
        sunset = weather.sunset
        if sunrise and sunset:
            day_len = sunset - sunrise

    key_w = 130
    y = _draw_kv_row(draw, x, y, "Sunrise", _fmt_clock(sunrise, tz), key_w, style)
    y = _draw_kv_row(draw, x, y, "Sunset", _fmt_clock(sunset, tz), key_w, style)
    # Day length + today's lengthening combined into one editorial line so
    # the Heavens column fits comfortably in the top body row.
    if delta is None:
        day_value = _fmt_duration(day_len)
    else:
        day_value = f"{_fmt_duration(day_len)}   ({_fmt_signed_minutes(delta)})"
    y = _draw_kv_row(draw, x, y, "Day length", day_value, key_w, style)

    # Moon row: glyph + name + illumination — kept as one editorial line.
    from src.render.fonts import weather_icon as _wi

    moon_glyph = moon_phase_glyph(today)
    moon_name = moon_phase_name(today)
    illum = moon_illumination(today)
    glyph_font = _wi(28)
    moon_font = style.font_semibold(15)
    glyph_h = text_height(glyph_font)
    moon_h = text_height(moon_font)
    line_h = max(glyph_h, moon_h)
    moon_y = y + 2
    draw.text((x, moon_y - 4), moon_glyph, font=glyph_font, fill=style.fg)
    moon_text = f"{moon_name} · {illum:.0f}%"
    draw.text(
        (x + 36, moon_y + (line_h - moon_h) // 2),
        moon_text,
        font=moon_font,
        fill=style.fg,
    )
    y = moon_y + line_h + 4

    full = _next_phase_date(today + timedelta(days=1), 0.5)
    y = _draw_kv_row(draw, x, y, "Next Full", full.strftime("%b %-d"), key_w, style)


def _draw_sky(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    weather,
    style: ThemeStyle,
) -> None:
    """Editorial weather prose (top-right)."""
    y = _draw_section_header(draw, x, y, "FROM THE SKY", style)

    body_font = style.font_regular(15)
    if weather is None:
        draw.text(
            (x, y),
            "No bulletin from the weather service today.",
            font=body_font,
            fill=style.fg,
        )
        return

    parts: list[str] = []
    desc = (weather.current_description or "").strip()
    if desc:
        parts.append(desc.capitalize())
    if weather.current_temp is not None:
        parts.append(f"and {weather.current_temp:.0f}°")
    sentence = " ".join(parts).strip()
    if sentence:
        sentence += " at the time of going to press."
    else:
        sentence = "Conditions unsettled at the time of going to press."

    if weather.wind_speed:
        from src.render.primitives import deg_to_compass

        compass = deg_to_compass(weather.wind_deg) if weather.wind_deg is not None else ""
        wind_phrase = (
            f"{compass} winds at {weather.wind_speed:.0f} mph"
            if compass
            else (f"Winds {weather.wind_speed:.0f} mph")
        )
        sentence += f" {wind_phrase}."

    if weather.high is not None and weather.low is not None:
        sentence += f" High near {weather.high:.0f}°, low near {weather.low:.0f}°."

    if weather.alerts:
        first = weather.alerts[0].event
        sentence += f"  Note: {first}."

    lines = wrap_lines(sentence, body_font, width)[:5]
    for line in lines:
        draw.text((x, y), line, font=body_font, fill=style.fg)
        y += text_height(body_font) + 3


def _draw_week_ahead(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    data: DashboardData,
    today: date,
    style: ThemeStyle,
) -> None:
    """Bulleted upcoming-events list (bottom-left)."""
    y = _draw_section_header(draw, x, y, "THE WEEK AHEAD", style)

    items = _upcoming_calendar_summary(data, today, max_lines=4)
    body_font = style.font_regular(15)
    accent = style.primary_accent_fill()
    bullet = "•"
    for item in items:
        draw.text((x, y), bullet, font=body_font, fill=accent)
        draw_text_truncated(draw, (x + 14, y), item, body_font, width - 14, fill=style.fg)
        y += text_height(body_font) + 4


def _draw_garden(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    today: date,
    latitude: float | None,
    longitude: float | None,
    style: ThemeStyle,
) -> None:
    """Season + day-of-year + meteor shower (bottom-right)."""
    y = _draw_section_header(draw, x, y, "NEXT IN THE GARDEN", style)

    body_font = style.font_regular(15)
    bold_font = style.font_semibold(15)
    accent = style.primary_accent_fill()

    season = _season(today)
    day_of_year = today.timetuple().tm_yday
    days_in_year = (
        366 if (today.year % 400 == 0 or (today.year % 4 == 0 and today.year % 100 != 0)) else 365
    )  # noqa: E501
    season_line = f"{season}  ·  Day {day_of_year} of {days_in_year}"
    draw.text((x, y), season_line, font=bold_font, fill=style.fg)
    y += text_height(bold_font) + 4

    if latitude is not None and longitude is not None and (latitude, longitude) != (0.0, 0.0):
        delta = day_length_delta(today, latitude, longitude)
        if delta is not None:
            seconds = int(delta.total_seconds())
            sign = "lengthens" if seconds > 0 else "shortens"
            mag = abs(seconds)
            mins, secs = divmod(mag, 60)
            duration = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            draw.text(
                (x, y),
                f"Sun {sign} by {duration} daily",
                font=body_font,
                fill=style.fg,
            )
            y += text_height(body_font) + 4

    shower, days = next_meteor_shower(today)
    if days == 0:
        when = "tonight"
    elif days == 1:
        when = "tomorrow"
    else:
        when = f"in {days} days"
    # Hand-drawn star ornament beside the shower name (Playfair has no ✨ glyph).
    star_y = y + text_height(bold_font) // 2 + 1
    _ornament(draw, x + 5, star_y, accent, size=4)
    draw.text((x + 16, y), shower.name, font=bold_font, fill=accent)
    y += text_height(bold_font) + 2
    draw.text(
        (x + 16, y),
        f"meteor shower {when}  ·  ZHR {shower.zhr}",
        font=body_font,
        fill=style.fg,
    )


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    region: ComponentRegion,
    today: date,
    now: datetime,
    style: ThemeStyle,
    quote_refresh: str,
) -> None:
    """Triple rule + quote + author + ornament line."""
    fg = style.fg
    accent = style.primary_accent_fill()
    cx = region.x + region.w // 2

    _triple_rule(
        draw,
        region.y + _FOOTER_RULE_Y,
        region.x + _PAD_X,
        region.x + region.w - _PAD_X,
        fg,
        accent,
    )

    quote = _quote_for_today(today, refresh=quote_refresh, now=now)
    quote_font = (style.font_quote or style.font_regular)(17)
    author_font = (style.font_quote_author or style.font_semibold)(13)

    text = f"“{quote['text']}”"
    avail = region.w - 2 * _PAD_X
    lines = wrap_lines(text, quote_font, avail)
    if len(lines) > 2:
        quote_font = (style.font_quote or style.font_regular)(14)
        lines = wrap_lines(text, quote_font, avail)[:3]
    else:
        lines = lines[:2]
    y = region.y + _QUOTE_Y
    for line in lines:
        lw = text_width(draw, line, quote_font)
        draw.text((cx - lw // 2, y), line, font=quote_font, fill=fg)
        y += text_height(quote_font) + 2

    author = f"— {quote['author'].upper()}"
    aw = text_width(draw, author, author_font)
    draw.text((cx - aw // 2, y + 2), author, font=author_font, fill=accent)

    # Closing ornament strip — five evenly spaced little stars
    yy = region.y + _FOOTER_ORNAMENT_Y
    span = region.w - 2 * _PAD_X
    for i in range(5):
        ox = region.x + _PAD_X + int(span * (i + 0.5) / 5)
        _ornament(draw, ox, yy, fg, size=4)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_almanac(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    quote_refresh: str = "daily",
) -> None:
    """Render the full-canvas almanac page inside *region*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    tz = now.tzinfo
    weather = data.weather

    _draw_masthead(draw, region, today, style)

    # Vertical rule between the two columns inside the body band.
    vline(
        draw,
        region.x + _COL_DIVIDER_X,
        region.y + _BODY_TOP - 4,
        region.y + _BODY_BOTTOM,
        fill=style.fg,
    )
    # Horizontal rule between the top and bottom rows of the 2×2 body grid.
    hline(
        draw,
        region.y + _BODY_MID_Y,
        region.x + _PAD_X,
        region.x + region.w - _PAD_X,
        fill=style.fg,
    )

    # Top-left: HEAVENS
    _draw_heavens(
        draw,
        region.x + _PAD_X,
        region.y + _BODY_TOP,
        _COL_DIVIDER_X - _PAD_X * 2,
        today,
        weather,
        latitude,
        longitude,
        tz,
        style,
    )
    # Top-right: SKY
    _draw_sky(
        draw,
        region.x + _COL_DIVIDER_X + _PAD_X,
        region.y + _BODY_TOP,
        region.w - _COL_DIVIDER_X - 2 * _PAD_X,
        weather,
        style,
    )
    # Bottom-left: WEEK AHEAD
    _draw_week_ahead(
        draw,
        region.x + _PAD_X,
        region.y + _BODY_MID_Y + 12,
        _COL_DIVIDER_X - _PAD_X * 2,
        data,
        today,
        style,
    )
    # Bottom-right: GARDEN
    _draw_garden(
        draw,
        region.x + _COL_DIVIDER_X + _PAD_X,
        region.y + _BODY_MID_Y + 12,
        region.w - _COL_DIVIDER_X - 2 * _PAD_X,
        today,
        latitude,
        longitude,
        style,
    )

    _draw_footer(draw, region, today, now, style, quote_refresh)
