"""wide_day_panel.py — today's timeline laid across a 1360x480 panoramic plate.

The 10.85" Waveshare panel is a strip nearly three times as wide as it is
tall, and a strip is the natural shape for a time axis. This plate gives the
whole middle of the panel to today, hours running left to right, with each
event drawn as a bar spanning its real start and end. A date-and-weather block
sits at the left end and an "up next" rail at the right.

Three parts:

  * **Left block** (``LEFT_W``) — weekday, a hero day-of-month numeral, the
    month, then the weather now: icon, temperature, condition, high and low,
    feels-like, sunrise and sunset, and an inverted alert bar when one is
    active.
  * **Timeline** — an hour axis from ``AXIS_MIN_HOUR`` to ``AXIS_MAX_HOUR``,
    widened when an event falls outside it, with a label at every hour the
    width allows. Timed events are packed into lanes (an event takes the
    first lane whose previous occupant has ended) and drawn as bars. All-day
    events sit as chips on the title row. A marker in the alert accent shows
    the current time.
  * **Right rail** (``RIGHT_W``) — the next few timed events still to come,
    today or tomorrow, then birthdays in the coming week.

Each bar encodes its event's state: one already over is outlined with a
dashed rule and set in the regular weight, the one in progress is a solid bar
in the alert accent (red on a colour panel, ink on a monochrome one) with the
text knocked out, and one still to come carries a solid two-pixel outline. The
marker and the states read the clock, so this is a time-driven plate: it
changes every tick. On a colour panel, whose full refresh flashes for twenty
seconds, pair it with ``display.min_refresh_interval_seconds`` — the throttle
defers the change rather than dropping it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TypeVar

from PIL import ImageDraw

from src.data.models import Birthday, CalendarEvent, DashboardData, WeatherData
from src.render.artkit import to_local_naive
from src.render.icons import draw_weather_icon
from src.render.primitives import (
    content_time,
    dashed_hline,
    dashed_vline,
    deg_to_compass,
    draw_text_truncated,
    events_for_day,
    filled_rect,
    fmt_time,
    hline,
    text_height,
    text_width,
    vline,
)
from src.render.theme import ComponentRegion, ThemeStyle

T = TypeVar("T")

# Plate geometry. The blocks are fixed widths rather than fractions: the rail
# holds a list at one type size and the left block a numeral at another, and
# neither wants to grow with the panel.
LEFT_W = 300
RIGHT_W = 270
PAD = 18

# The axis always spans at least these hours; an event outside them widens it.
AXIS_MIN_HOUR = 6
AXIS_MAX_HOUR = 22

# Hour labels are set every hour when a column is at least this wide, else
# every other hour — "10a" in the label face is ~22 px.
LABEL_EVERY_HOUR_MIN_PX = 34

LANE_H = 40
LANE_GAP = 6
# A bar wide enough for its title sets it inside; a narrower one — a
# thirty-minute meeting is 24 px on a sixteen-hour axis — sets it alongside,
# and the label's width then counts toward the lane packing, so a run of short
# meetings cascades down the lanes with every name attached rather than
# sitting in one lane as a row of anonymous boxes. A label beside a bar is
# capped at this width.
LABEL_PAD = 8
MAX_BESIDE_LABEL_W = 220

UP_NEXT_MAX = 4
BIRTHDAY_MAX = 3
BIRTHDAY_LOOKAHEAD_DAYS = 7

# Filled chips on the title row for all-day events.
ALLDAY_CHIP_MAX = 3


def _alert_fill(style: ThemeStyle):
    return style.fg if style.accent_alert is None else style.accent_alert


def _naive(dt: datetime, now: datetime) -> datetime:
    """Bring an aware timestamp onto the naive local clock the events use."""
    return to_local_naive(dt, getattr(now, "tzinfo", None))


def pack_lanes(items: list[tuple[float, float, T]]) -> list[list[T]]:
    """Pack ``(x0, x1, item)`` intervals into lanes so that no two in a lane overlap.

    Intervals are taken in order of their left edge and each goes to the first
    lane whose last occupant ends by its start — the classic interval-
    partitioning greedy, which uses the minimum number of lanes. Callers
    decide what an interval is: the panel packs each bar *with its label*, so
    a label never runs under the next bar.
    """
    lanes: list[list[T]] = []
    ends: list[float] = []
    for x0, x1, item in sorted(items, key=lambda t: (t[0], t[1])):
        for i, end in enumerate(ends):
            if end <= x0:
                lanes[i].append(item)
                ends[i] = x1
                break
        else:
            lanes.append([item])
            ends.append(x1)
    return lanes


def event_lanes(events: list[CalendarEvent]) -> list[list[CalendarEvent]]:
    """Pack timed *events* into lanes by their time span alone."""
    return pack_lanes([(e.start.timestamp(), e.end.timestamp(), e) for e in events])


def axis_hours(events: list[CalendarEvent], today: date) -> tuple[int, int]:
    """The ``(start, end)`` hours the axis spans for today's timed *events*.

    Never narrower than ``AXIS_MIN_HOUR``–``AXIS_MAX_HOUR``; an event outside
    that window pushes the nearer end out to the hour boundary that contains
    it, clamped to the calendar day.
    """
    start, end = AXIS_MIN_HOUR, AXIS_MAX_HOUR
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    for evt in events:
        first = max(evt.start, day_start)
        last = min(evt.end, day_end)
        start = min(start, first.hour)
        if last >= day_end:
            end_h = 24
        else:
            end_h = last.hour + (1 if (last.minute or last.second) else 0)
        end = max(end, end_h)
    return max(0, start), min(24, end)


def event_state(evt: CalendarEvent, now: datetime) -> str:
    """``"past"``, ``"active"`` or ``"upcoming"`` relative to *now* (naive local)."""
    if evt.end <= now:
        return "past"
    if evt.start <= now:
        return "active"
    return "upcoming"


def upcoming_events(events: list[CalendarEvent], now: datetime, limit: int) -> list[CalendarEvent]:
    """The next *limit* timed events starting after *now*, soonest first."""
    later = [e for e in events if not e.is_all_day and e.start > now]
    return sorted(later, key=lambda e: e.start)[:limit]


def next_occurrence(bday: Birthday, today: date) -> date:
    """*bday*'s next anniversary on or after *today* (Feb 29 → Feb 28 off leap years)."""
    for year in (today.year, today.year + 1):
        try:
            candidate = bday.date.replace(year=year)
        except ValueError:
            candidate = date(year, 2, 28)
        if candidate >= today:
            return candidate
    return today  # unreachable: next year always qualifies


def upcoming_birthdays(
    birthdays: list[Birthday], today: date, *, days: int, limit: int
) -> list[tuple[date, Birthday]]:
    """Birthdays falling within the next *days* days, soonest first."""
    horizon = today + timedelta(days=days)
    rows = [(next_occurrence(b, today), b) for b in birthdays]
    rows = [(d, b) for d, b in rows if d <= horizon]
    rows.sort(key=lambda r: (r[0], r[1].name))
    return rows[:limit]


def draw_wide_day(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full ``wide_day`` plate into *region*."""
    if region is None:
        region = ComponentRegion(0, 0, 1360, 480)
    if style is None:
        style = ThemeStyle()

    now_local = _naive(now, now)
    x0, y0, w, h = region.x, region.y, region.w, region.h

    left = (x0, y0, LEFT_W, h)
    centre = (x0 + LEFT_W, y0, w - LEFT_W - RIGHT_W, h)
    right = (x0 + w - RIGHT_W, y0, RIGHT_W, h)

    _draw_left_block(draw, data.weather, today, now_local, left, style)
    vline(draw, x0 + LEFT_W, y0, y0 + h, fill=style.fg)
    vline(draw, x0 + LEFT_W + 1, y0, y0 + h, fill=style.fg)
    _draw_timeline(draw, data.events, today, now_local, centre, style)
    vline(draw, x0 + w - RIGHT_W - 1, y0, y0 + h, fill=style.fg)
    vline(draw, x0 + w - RIGHT_W, y0, y0 + h, fill=style.fg)
    _draw_right_rail(draw, data, today, now_local, right, style)

    # Bottom-right caption — data time, never the render clock.
    stamp = content_time(data, now)
    caption = f"Updated {stamp.strftime('%b %-d')} · {fmt_time(stamp)}"
    cap_font = style.font_regular(11)
    draw.text(
        (x0 + w - PAD - text_width(draw, caption, cap_font), y0 + h - 8 - text_height(cap_font)),
        caption,
        font=cap_font,
        fill=style.fg,
    )


# ---------------------------------------------------------------------------
# Left block
# ---------------------------------------------------------------------------


def _draw_left_block(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    today: date,
    now: datetime,
    rect: tuple[int, int, int, int],
    style: ThemeStyle,
) -> None:
    x0, y0, w, h = rect
    lx = x0 + PAD

    weekday_font = style.font_bold(24)
    draw.text((lx, y0 + 16), today.strftime("%A").upper(), font=weekday_font, fill=style.fg)

    numeral_fn = style.font_date_number or style.font_bold
    numeral_font = numeral_fn(150)
    numeral = str(today.day)
    nb = draw.textbbox((0, 0), numeral, font=numeral_font)
    numeral_top = y0 + 48
    draw.text((lx - nb[0] - 4, numeral_top - nb[1]), numeral, font=numeral_font, fill=style.fg)
    numeral_bottom = numeral_top + (nb[3] - nb[1])

    month_font = style.font_semibold(22)
    draw.text(
        (lx, numeral_bottom + 10),
        today.strftime("%B %Y").upper(),
        font=month_font,
        fill=style.primary_accent_fill(),
    )

    rule_y = numeral_bottom + 10 + text_height(month_font) + 14
    hline(draw, rule_y, lx, x0 + w - PAD, fill=style.fg)

    wy = rule_y + 12
    if weather is None:
        draw.text((lx, wy + 8), "Weather unavailable", font=style.font_medium(16), fill=style.fg)
        return

    draw_weather_icon(draw, (lx, wy + 2), weather.current_icon, size=56, fill=style.fg)
    temp_font = style.font_bold(52)
    draw.text((lx + 76, wy - 6), f"{weather.current_temp:.0f}°", font=temp_font, fill=style.fg)

    desc_font = style.font_medium(16)
    desc_y = wy + 66
    draw_text_truncated(
        draw,
        (lx, desc_y),
        weather.current_description.capitalize(),
        desc_font,
        w - 2 * PAD,
        fill=style.fg,
    )

    row_font = style.font_regular(15)
    row_y = desc_y + text_height(desc_font) + 8
    parts = [f"H {weather.high:.0f}°", f"L {weather.low:.0f}°"]
    if weather.feels_like is not None:
        parts.append(f"Feels {weather.feels_like:.0f}°")
    draw_text_truncated(draw, (lx, row_y), "   ".join(parts), row_font, w - 2 * PAD, fill=style.fg)

    row2_y = row_y + text_height(row_font) + 6
    parts = []
    if weather.sunrise is not None and weather.sunset is not None:
        parts.append(
            f"↑ {fmt_time(_naive(weather.sunrise, now))}  ↓ {fmt_time(_naive(weather.sunset, now))}"
        )
    if weather.wind_speed is not None:
        unit = "m/s" if weather.units == "metric" else "mph"
        wind = f"Wind {weather.wind_speed:.0f} {unit}"
        if weather.wind_deg is not None:
            wind += f" {deg_to_compass(weather.wind_deg)}"
        parts.append(wind)
    if parts:
        draw_text_truncated(
            draw, (lx, row2_y), "   ".join(parts), row_font, w - 2 * PAD, fill=style.fg
        )

    if weather.alerts:
        bar_font = style.font_semibold(14)
        bar_h = text_height(bar_font) + 10
        bar_y = row2_y + text_height(row_font) + 12
        fill = _alert_fill(style)
        filled_rect(draw, (lx, bar_y, x0 + w - PAD, bar_y + bar_h), fill=fill)
        names = " · ".join(a.event for a in weather.alerts[:2])
        draw_text_truncated(
            draw, (lx + 8, bar_y + 5), f"! {names}", bar_font, w - 2 * PAD - 16, fill=style.bg
        )


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def _draw_timeline(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    today: date,
    now: datetime,
    rect: tuple[int, int, int, int],
    style: ThemeStyle,
) -> None:
    x0, y0, w, h = rect
    todays = events_for_day(events, today)
    timed = [e for e in todays if not e.is_all_day]
    allday = [e for e in todays if e.is_all_day]

    # Title row: TODAY · N events, all-day chips against the right edge.
    label_font = style.label_font()
    title_y = y0 + 16
    title = style.component_labels.get("wide_day", "TODAY")
    draw.text((x0 + PAD, title_y), title, font=label_font, fill=style.primary_accent_fill())
    count_font = style.font_regular(14)
    n = len(todays)
    count = "no events" if n == 0 else ("1 event" if n == 1 else f"{n} events")
    draw.text(
        (x0 + PAD + text_width(draw, title, label_font) + 10, title_y),
        f"· {count}",
        font=count_font,
        fill=style.fg,
    )
    _draw_allday_chips(draw, allday, (x0 + w - PAD, title_y), style)

    # Axis.
    axis_y = y0 + 68
    ax0 = x0 + PAD
    ax1 = x0 + w - PAD
    aw = ax1 - ax0
    start_h, end_h = axis_hours(timed, today)
    span_min = max(60, (end_h - start_h) * 60)
    day_start = datetime.combine(today, datetime.min.time())

    def x_for(dt: datetime) -> float:
        minutes = (dt - day_start).total_seconds() / 60 - start_h * 60
        return ax0 + max(0.0, min(1.0, minutes / span_min)) * aw

    hline(draw, axis_y, ax0, ax1, fill=style.fg)
    hline(draw, axis_y + 1, ax0, ax1, fill=style.fg)
    hour_px = aw / max(1, end_h - start_h)
    label_step = 1 if hour_px >= LABEL_EVERY_HOUR_MIN_PX else 2
    tick_font = style.font_regular(12)
    lanes_top = axis_y + 26
    lanes_bottom = y0 + h - 30
    for hour in range(start_h, end_h + 1):
        x = round(ax0 + (hour - start_h) * hour_px)
        vline(draw, x, axis_y - 5, axis_y + 5, fill=style.fg)
        if (hour - start_h) % label_step:
            continue
        label = fmt_time(day_start + timedelta(hours=hour % 24)) if hour < 24 else "12a"
        lw = text_width(draw, label, tick_font)
        draw.text(
            (x - lw // 2, axis_y - 8 - text_height(tick_font)), label, font=tick_font, fill=style.fg
        )
        if start_h < hour < end_h:
            dashed_vline(draw, x, lanes_top, lanes_bottom, on=1, off=5, fill=style.fg)

    # Lanes. Each item is the bar plus the label it will carry, so packing by
    # the item keeps labels clear of neighbouring bars.
    title_font = style.font_bold(15)
    time_font = style.font_regular(11)
    items: list[tuple[float, float, _Bar]] = []
    for evt in timed:
        bx0 = round(x_for(max(evt.start, day_start)))
        bx1 = max(round(x_for(min(evt.end, day_start + timedelta(days=1)))), bx0 + 6)
        title, detail = _bar_text(evt)
        label_w = max(text_width(draw, title, title_font), text_width(draw, detail, time_font))
        inside = bx1 - bx0 >= label_w + 2 * LABEL_PAD
        beside_w = 0 if inside else min(label_w, MAX_BESIDE_LABEL_W) + LABEL_PAD
        bar = _Bar(evt, bx0, bx1, inside, min(ax1, bx1 + beside_w))
        items.append((bx0, bar.extent_x1 + LABEL_PAD, bar))
    lanes = pack_lanes(items)
    max_lanes = max(1, (lanes_bottom - lanes_top) // (LANE_H + LANE_GAP))
    shown, hidden = lanes[:max_lanes], lanes[max_lanes:]
    for i, lane in enumerate(shown):
        ly = lanes_top + i * (LANE_H + LANE_GAP)
        for bar in lane:
            _draw_bar(draw, bar, event_state(bar.evt, now), ly, style, title_font, time_font)

    overflow = sum(len(lane) for lane in hidden)
    if overflow:
        more_font = style.font_semibold(13)
        draw.text((ax0, lanes_bottom + 6), f"+{overflow} more", font=more_font, fill=style.fg)

    if not timed:
        empty_font = style.font_medium(20)
        msg = "Nothing scheduled today" if not allday else "No timed events today"
        mw = text_width(draw, msg, empty_font)
        mid_y = (lanes_top + lanes_bottom) // 2
        draw.text(
            (x0 + (w - mw) // 2, mid_y - text_height(empty_font) // 2),
            msg,
            font=empty_font,
            fill=style.fg,
        )

    # NOW marker — only when the moment is on the axis.
    if day_start + timedelta(hours=start_h) <= now < day_start + timedelta(hours=end_h):
        nx = round(x_for(now))
        fill = _alert_fill(style)
        vline(draw, nx, axis_y - 6, lanes_bottom, fill=fill)
        vline(draw, nx + 1, axis_y - 6, lanes_bottom, fill=fill)
        chip_font = style.font_bold(11)
        chip_w = text_width(draw, "NOW", chip_font) + 10
        chip_h = text_height(chip_font) + 6
        cx0 = min(max(ax0, nx - chip_w // 2), ax1 - chip_w)
        filled_rect(draw, (cx0, axis_y + 3, cx0 + chip_w, axis_y + 3 + chip_h), fill=fill)
        draw.text((cx0 + 5, axis_y + 6), "NOW", font=chip_font, fill=style.bg)


def _draw_allday_chips(
    draw: ImageDraw.ImageDraw,
    allday: list[CalendarEvent],
    right_top: tuple[int, int],
    style: ThemeStyle,
) -> None:
    """Filled chips for all-day events, laid right-to-left from *right_top*."""
    if not allday:
        return
    chip_font = style.font_semibold(13)
    chip_h = text_height(chip_font) + 8
    right, top = right_top
    shown = allday[:ALLDAY_CHIP_MAX]
    labels = [e.summary for e in shown]
    if len(allday) > ALLDAY_CHIP_MAX:
        labels.append(f"+{len(allday) - ALLDAY_CHIP_MAX}")
    x = right
    for label in reversed(labels):
        tw = min(text_width(draw, label, chip_font), 180)
        cw = tw + 16
        x -= cw
        filled_rect(draw, (x, top - 4, x + cw, top - 4 + chip_h), fill=style.fg)
        draw_text_truncated(draw, (x + 8, top), label, chip_font, tw, fill=style.bg)
        x -= 8


class _Bar:
    """One event's bar on the axis and where its label goes."""

    __slots__ = ("evt", "x0", "x1", "inside", "extent_x1")

    def __init__(self, evt: CalendarEvent, x0: int, x1: int, inside: bool, extent_x1: int):
        self.evt = evt
        self.x0 = x0
        self.x1 = x1
        self.inside = inside  # label inside the bar, else beside it
        self.extent_x1 = extent_x1  # right edge of bar + beside-label


def _bar_text(evt: CalendarEvent) -> tuple[str, str]:
    detail = f"{fmt_time(evt.start)}–{fmt_time(evt.end)}"
    if evt.location:
        detail += f" · {evt.location}"
    return evt.summary, detail


def _draw_bar(
    draw: ImageDraw.ImageDraw,
    bar: _Bar,
    state: str,
    top: int,
    style: ThemeStyle,
    title_font,
    time_font,
) -> None:
    """Draw one event bar and its label; the treatment encodes *state*."""
    bx0, bx1 = bar.x0, bar.x1
    by0, by1 = top, top + LANE_H
    if state == "active":
        filled_rect(draw, (bx0, by0, bx1, by1), fill=_alert_fill(style))
        inside_fill = style.bg
    elif state == "upcoming":
        draw.rectangle((bx0, by0, bx1, by1), outline=style.fg, width=2)
        inside_fill = style.fg
    else:
        dashed_hline(draw, by0, bx0, bx1, on=3, off=3, fill=style.fg)
        dashed_hline(draw, by1, bx0, bx1, on=3, off=3, fill=style.fg)
        dashed_vline(draw, bx0, by0, by1, on=3, off=3, fill=style.fg)
        dashed_vline(draw, bx1, by0, by1, on=3, off=3, fill=style.fg)
        inside_fill = style.fg
        title_font = style.font_regular(15)

    title, detail = _bar_text(bar.evt)
    if bar.inside:
        tx, max_w, fill = bx0 + LABEL_PAD, bx1 - bx0 - 2 * LABEL_PAD, inside_fill
    else:
        tx, max_w, fill = bx1 + LABEL_PAD, bar.extent_x1 - (bx1 + LABEL_PAD), style.fg
    if max_w < 12:
        return
    draw_text_truncated(draw, (tx, by0 + 4), title, title_font, max_w, fill=fill)
    draw_text_truncated(draw, (tx, by0 + 23), detail, time_font, max_w, fill=fill)


# ---------------------------------------------------------------------------
# Right rail
# ---------------------------------------------------------------------------


def _draw_right_rail(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    rect: tuple[int, int, int, int],
    style: ThemeStyle,
) -> None:
    x0, y0, w, h = rect
    rx = x0 + PAD
    inner_w = w - 2 * PAD
    label_font = style.label_font()
    accent = style.primary_accent_fill()

    draw.text((rx, y0 + 16), "UP NEXT", font=label_font, fill=accent)
    hline(draw, y0 + 16 + text_height(label_font) + 8, rx, x0 + w - PAD, fill=style.fg)

    y = y0 + 16 + text_height(label_font) + 18
    time_font = style.font_bold(15)
    day_font = style.font_regular(12)
    title_font = style.font_medium(15)
    tomorrow = today + timedelta(days=1)
    nexts = upcoming_events(data.events, now, UP_NEXT_MAX)
    if not nexts:
        draw.text((rx, y), "Nothing more scheduled", font=style.font_regular(14), fill=style.fg)
        y += 30
    for evt in nexts:
        when = fmt_time(evt.start)
        draw.text((rx, y), when, font=time_font, fill=style.fg)
        if evt.start.date() == tomorrow:
            draw.text(
                (rx + text_width(draw, when, time_font) + 8, y + 2),
                "tomorrow",
                font=day_font,
                fill=accent,
            )
        elif evt.start.date() != today:
            draw.text(
                (rx + text_width(draw, when, time_font) + 8, y + 2),
                evt.start.strftime("%a"),
                font=day_font,
                fill=accent,
            )
        draw_text_truncated(
            draw,
            (rx, y + text_height(time_font) + 2),
            evt.summary,
            title_font,
            inner_w,
            fill=style.fg,
        )
        y += text_height(time_font) + text_height(title_font) + 12

    # Birthdays in the coming week.
    by = max(y + 12, y0 + 272)
    draw.text((rx, by), "BIRTHDAYS", font=label_font, fill=accent)
    hline(draw, by + text_height(label_font) + 8, rx, x0 + w - PAD, fill=style.fg)
    by += text_height(label_font) + 18
    rows = upcoming_birthdays(
        data.birthdays, today, days=BIRTHDAY_LOOKAHEAD_DAYS, limit=BIRTHDAY_MAX
    )
    row_font = style.font_medium(14)
    if not rows:
        draw.text((rx, by), "None this week", font=style.font_regular(14), fill=style.fg)
        return
    for when, bday in rows:
        day_label = "Today" if when == today else when.strftime("%a %-d")
        text = f"{day_label} · {bday.name}"
        if bday.age is not None:
            text += f" ({bday.age})"
        draw_text_truncated(draw, (rx, by), text, row_font, inner_w, fill=style.fg)
        by += text_height(row_font) + 8
