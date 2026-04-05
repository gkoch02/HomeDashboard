"""newspaper_panel.py — Left-column event list for the "newspaper" theme.

Renders today's calendar events as newspaper "articles": time as a dateline,
title as a headline, and optional location as a subhead.  All-day events appear
as a compact strip at the bottom of the column above a thin rule.
"""

from __future__ import annotations

from datetime import date

from PIL import ImageDraw

from src.data.models import CalendarEvent
from src.render.primitives import (
    draw_text_truncated,
    draw_text_wrapped,
    events_for_day,
    filled_rect,
    fmt_time,
    hline,
    text_height,
)
from src.render.theme import ComponentRegion, ThemeStyle

PAD = 10
ALLDAY_STRIP_H = 60  # pixels reserved at the bottom for all-day events


def draw_newspaper_events(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    today: date,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw today's events as newspaper articles inside *region*.

    Layout:
    - Section label at top ("TODAY'S AGENDA" or custom label)
    - Timed events listed from top, each with dateline + headline + subhead
    - All-day events as a compact bar strip at the bottom
    - "No events today" placeholder when the schedule is empty
    """
    if region is None:
        region = ComponentRegion(0, 60, 530, 420)
    if style is None:
        style = ThemeStyle()

    x0, y0, w, h = region.x, region.y, region.w, region.h

    today_events = events_for_day(events, today)
    timed = [e for e in today_events if not e.is_all_day]
    allday = [e for e in today_events if e.is_all_day]

    label_font = style.label_font()
    label_h = text_height(label_font)

    # --- Section label ---
    label_text = style.component_labels.get("newspaper_events", "TODAY'S AGENDA")
    draw.text((x0 + PAD, y0 + PAD), label_text, font=label_font, fill=style.fg)
    label_bottom = y0 + PAD + label_h + 4
    hline(draw, label_bottom, x0 + PAD, x0 + w - PAD, fill=style.fg)

    content_top = label_bottom + 6

    # Reserve the bottom strip for all-day events (only when they exist)
    allday_zone_top = y0 + h - ALLDAY_STRIP_H if allday else y0 + h
    timed_bottom = allday_zone_top - PAD

    # --- Timed events (articles) ---
    dateline_font = style.font_regular(11)
    headline_font = style.font_semibold(15)
    subhead_font = style.font_regular(11)
    more_font = style.font_regular(11)

    dateline_h = text_height(dateline_font)
    headline_h = text_height(headline_font)
    subhead_h = text_height(subhead_font)
    more_h = text_height(more_font)

    event_gap = 8  # space between events
    content_w = w - PAD * 2

    if not timed and not allday:
        empty_font = style.font_regular(15)
        msg = "No events today"
        bb = draw.textbbox((0, 0), msg, font=empty_font)
        mw = bb[2] - bb[0]
        mh = bb[3] - bb[1]
        draw.text(
            (x0 + (w - mw) // 2 - bb[0], y0 + h // 2 - mh // 2 - bb[1]),
            msg,
            font=empty_font,
            fill=style.fg,
        )
        return

    y = content_top
    for idx, event in enumerate(timed):
        # Minimum height to render this event (dateline + headline + gap)
        min_h = dateline_h + 2 + headline_h + event_gap
        if y + min_h > timed_bottom:
            remaining = len(timed) - idx
            draw.text((x0 + PAD, min(y, timed_bottom - more_h)), f"+{remaining} more",
                      font=more_font, fill=style.fg)
            break

        # Dateline (time range)
        start_s = fmt_time(event.start)
        end_s = fmt_time(event.end)
        if event.start.strftime("%p") == event.end.strftime("%p"):
            start_s = start_s.rstrip("ap")
        dateline = f"{start_s}–{end_s}"
        draw.text((x0 + PAD, y), dateline, font=dateline_font, fill=style.fg)
        y += dateline_h + 2

        # Headline (title) — up to 2 wrapped lines
        remaining_h = timed_bottom - event_gap - y
        max_lines = max(1, min(2, remaining_h // (headline_h + 2)))
        used = draw_text_wrapped(
            draw, (x0 + PAD, y), event.summary, headline_font,
            content_w, max_lines=max_lines, line_spacing=2, fill=style.fg,
        )
        y += max(used, headline_h)

        # Subhead (location first segment)
        if event.location and y + subhead_h <= timed_bottom:
            loc = " ".join(event.location.split(",")[0].split())
            if loc:
                y += 2
                draw_text_truncated(draw, (x0 + PAD, y), loc, subhead_font, content_w,
                                    fill=style.fg)
                y += subhead_h

        y += event_gap

    # --- All-day strip at bottom ---
    if allday:
        strip_top = allday_zone_top
        hline(draw, strip_top, x0 + PAD, x0 + w - PAD, fill=style.fg)

        allday_font = style.font_semibold(12)
        allday_h = text_height(allday_font)
        bar_h = allday_h + 6
        ay = strip_top + 6

        for event in allday:
            if ay + bar_h > y0 + h - 4:
                break
            bx0, bx1 = x0 + PAD, x0 + w - PAD
            if style.invert_allday_bars:
                filled_rect(draw, (bx0, ay, bx1, ay + bar_h - 1), fill=style.fg)
                draw_text_truncated(draw, (bx0 + 6, ay + 3), event.summary, allday_font,
                                    bx1 - bx0 - 12, fill=style.bg)
            else:
                draw.rectangle((bx0, ay, bx1, ay + bar_h - 1), outline=style.fg)
                draw_text_truncated(draw, (bx0 + 6, ay + 3), event.summary, allday_font,
                                    bx1 - bx0 - 12, fill=style.fg)
            ay += bar_h + 4
