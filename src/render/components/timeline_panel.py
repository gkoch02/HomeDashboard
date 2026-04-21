"""timeline_panel.py — Hourly day-view timeline for the "timeline" theme.

Renders today's schedule as event blocks on a vertical hourly grid, making free
time visually obvious at a glance.  A dashed "now" line marks the current time.
"""

from __future__ import annotations

from datetime import date, datetime

from PIL import ImageDraw

from src.data.models import CalendarEvent
from src.render.primitives import (
    draw_text_truncated,
    events_for_day,
    filled_rect,
    hline,
    text_height,
    vline,
)
from src.render.theme import ComponentRegion, ThemeStyle

# Visible hour range on the timeline
_START_HOUR = 7  # 7 AM
_END_HOUR = 21  # 9 PM (exclusive top boundary)
_VISIBLE_HOURS = _END_HOUR - _START_HOUR  # 14 hours

# Layout constants
_AXIS_W = 52  # width of the left hour-label axis
_ALLDAY_H = 14  # height of the all-day bar strip at the very top
_PAD_RIGHT = 6


def draw_timeline(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw an hourly timeline of today's events inside *region*.

    The left axis shows hour labels (_START_HOUR – _END_HOUR).
    Event blocks span the timeline area proportionally to their time range.
    A dashed horizontal line marks the current time when it falls in range.
    All-day events occupy a narrow strip across the top.
    """
    if region is None:
        region = ComponentRegion(0, 40, 800, 360)
    if style is None:
        style = ThemeStyle()

    x0, y0, w, h = region.x, region.y, region.w, region.h

    today_events = events_for_day(events, today)
    timed = [e for e in today_events if not e.is_all_day]
    allday = [e for e in today_events if e.is_all_day]

    # Reserve top strip for all-day events
    allday_top = y0
    timeline_top = y0 + (_ALLDAY_H + 2 if allday else 0)
    timeline_h = h - (timeline_top - y0)
    timeline_x = x0 + _AXIS_W
    timeline_w = w - _AXIS_W - _PAD_RIGHT

    # Pixels per minute within the visible range
    total_minutes = _VISIBLE_HOURS * 60
    px_per_min = timeline_h / total_minutes

    label_font = style.font_regular(11)
    label_h = text_height(label_font)

    # --- Hour grid lines and labels ---
    for hour in range(_START_HOUR, _END_HOUR + 1):
        offset_min = (hour - _START_HOUR) * 60
        y = timeline_top + int(offset_min * px_per_min)
        if y > y0 + h:
            break

        # Hour label (right-aligned in axis)
        if hour < 12:
            label = f"{hour}a"
        elif hour == 12:
            label = "12p"
        else:
            label = f"{hour - 12}p"

        lb = draw.textbbox((0, 0), label, font=label_font)
        lw = lb[2] - lb[0]
        lx = x0 + _AXIS_W - lw - 6 - lb[0]
        ly = y - label_h // 2 - lb[1]
        draw.text((lx, ly), label, font=label_font, fill=style.fg)

        # Subtle grid line across timeline area
        if hour < _END_HOUR:
            hline(draw, y, timeline_x, timeline_x + timeline_w, fill=style.fg)

    # Vertical axis separator
    vline(draw, timeline_x - 1, timeline_top, y0 + h, fill=style.fg)

    # --- All-day bar strip ---
    if allday:
        allday_font = style.font_regular(10)
        segment_w = timeline_w // max(len(allday), 1)
        for i, event in enumerate(allday):
            bx0 = timeline_x + i * segment_w
            bx1 = bx0 + segment_w - 2
            if style.invert_allday_bars:
                filled_rect(draw, (bx0, allday_top, bx1, allday_top + _ALLDAY_H - 1), fill=style.fg)
                draw_text_truncated(
                    draw,
                    (bx0 + 3, allday_top + 2),
                    event.summary,
                    allday_font,
                    bx1 - bx0 - 6,
                    fill=style.bg,
                )
            else:
                draw.rectangle((bx0, allday_top, bx1, allday_top + _ALLDAY_H - 1), outline=style.fg)
                draw_text_truncated(
                    draw,
                    (bx0 + 3, allday_top + 2),
                    event.summary,
                    allday_font,
                    bx1 - bx0 - 6,
                    fill=style.fg,
                )

    # --- Timed event blocks ---
    # Group overlapping events into columns to avoid visual collisions
    columns = _assign_columns(timed)
    num_cols = max(columns.values(), default=0) + 1 if columns else 1

    event_font = style.font_regular(11)
    event_h_min = text_height(event_font) + 4

    for orig_idx, event in enumerate(timed):
        col_idx = columns.get(orig_idx, 0)
        col_w = timeline_w // num_cols
        ex0 = timeline_x + col_idx * col_w + 1
        ex1 = ex0 + col_w - 2

        start_min = _minutes_from_start(event.start, today)
        end_min = _minutes_from_start(event.end, today)

        # Clamp to visible range
        start_min = max(start_min, 0)
        end_min = min(end_min, total_minutes)
        if start_min >= end_min:
            continue

        ey0 = timeline_top + int(start_min * px_per_min)
        ey1 = timeline_top + int(end_min * px_per_min)
        block_h = max(ey1 - ey0, event_h_min)

        # Inverted filled block
        filled_rect(draw, (ex0, ey0, ex1, ey0 + block_h - 1), fill=style.fg)
        if block_h >= text_height(event_font) + 4:
            draw_text_truncated(
                draw,
                (ex0 + 3, ey0 + 2),
                event.summary,
                event_font,
                ex1 - ex0 - 6,
                fill=style.bg,
            )

    # --- Current-time indicator ---
    if today == now.date():
        now_min = (now.hour - _START_HOUR) * 60 + now.minute
        if 0 <= now_min <= total_minutes:
            ny = timeline_top + int(now_min * px_per_min)
            # Dashed line: 4px on, 3px off
            x = timeline_x
            while x <= timeline_x + timeline_w:
                draw.line(
                    [(x, ny), (min(x + 3, timeline_x + timeline_w), ny)],
                    fill=style.primary_accent_fill(),
                    width=2,
                )
                x += 7


def _minutes_from_start(dt: datetime, today: date) -> int:
    """Return minutes offset from _START_HOUR on *today*.

    Off-day events clamp to the start (previous day) or end (next day) of the
    visible window so they don't render outside it.
    """
    dt_date = dt.date()
    if dt_date != today:
        return 0 if dt_date < today else _VISIBLE_HOURS * 60
    return (dt.hour - _START_HOUR) * 60 + dt.minute


def _assign_columns(events: list[CalendarEvent]) -> dict[int, int]:
    """Greedily assign column indices so overlapping events don't share a column.

    Returns a mapping of original list index → column index.
    """
    # Work with (original_index, event) pairs sorted by start time
    indexed = sorted(enumerate(events), key=lambda t: t[1].start)
    assignments: dict[int, int] = {}  # original index → column index
    col_ends: list[datetime] = []  # end time of last event assigned to each column

    for orig_idx, event in indexed:
        placed = False
        for col_idx, col_end in enumerate(col_ends):
            if event.start >= col_end:
                assignments[orig_idx] = col_idx
                col_ends[col_idx] = event.end
                placed = True
                break
        if not placed:
            new_col = len(col_ends)
            assignments[orig_idx] = new_col
            col_ends.append(event.end)

    return assignments
