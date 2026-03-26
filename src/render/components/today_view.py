"""today_view.py — Single-day focused view for the "today" theme.

Renders a large date panel on the left and a spacious event list on the right,
showcasing today's schedule in a comfortable, large-format layout.
"""

from datetime import date

from PIL import ImageDraw

from src.data.models import CalendarEvent, DayForecast
from src.render.primitives import (
    filled_rect, vline,
    draw_text_truncated, draw_text_wrapped, text_height, text_width,
    fmt_time as _fmt_time, events_for_day as _events_for_today,
)
from src.render.theme import ComponentRegion, ThemeStyle

PAD = 10


def draw_today(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    today: date,
    forecast: list[DayForecast] | None = None,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw a single-day focused view with a large date panel and event list.

    The left ~30% shows the day name, date number, and month in large inverted text.
    The right ~70% lists today's events with generous fonts and spacing.
    """
    if region is None:
        region = ComponentRegion(0, 60, 800, 280)
    if style is None:
        style = ThemeStyle()

    x0, y0, total_w, total_h = region.x, region.y, region.w, region.h

    # Split into left date panel (~30%) and right events panel (~70%)
    date_panel_w = total_w * 3 // 10  # ~240px at default 800w
    events_x = x0 + date_panel_w
    events_w = total_w - date_panel_w

    # --- Left date panel (inverted) ---
    filled_rect(draw, (x0, y0, x0 + date_panel_w - 1, y0 + total_h - 1), fill=style.fg)

    day_name = today.strftime("%A").upper()
    month_text = today.strftime("%B").upper()
    date_num = str(today.day)

    day_font = style.font_semibold(22)
    month_font = style.font_semibold(18)
    num_font = style.font_bold(90)

    # Day name pinned to top
    day_bb = draw.textbbox((0, 0), day_name, font=day_font)
    day_w = day_bb[2] - day_bb[0]
    day_h = day_bb[3] - day_bb[1]
    day_x = x0 + (date_panel_w - day_w) // 2 - day_bb[0]
    day_y = y0 + PAD - day_bb[1]
    draw.text((day_x, day_y), day_name, font=day_font, fill=style.bg)

    # Month name pinned to bottom
    month_bb = draw.textbbox((0, 0), month_text, font=month_font)
    month_w = month_bb[2] - month_bb[0]
    month_h = month_bb[3] - month_bb[1]
    month_x = x0 + (date_panel_w - month_w) // 2 - month_bb[0]
    month_y = y0 + total_h - PAD - month_h - month_bb[1]
    draw.text((month_x, month_y), month_text, font=month_font, fill=style.bg)

    # Date number centred in the remaining space between day name and month
    num_bb = draw.textbbox((0, 0), date_num, font=num_font)
    num_w = num_bb[2] - num_bb[0]
    num_h = num_bb[3] - num_bb[1]
    top_reserved = y0 + PAD + day_h + PAD
    bottom_reserved = y0 + total_h - PAD - month_h - PAD
    mid_zone_h = bottom_reserved - top_reserved
    num_x = x0 + (date_panel_w - num_w) // 2 - num_bb[0]
    num_y = top_reserved + (mid_zone_h - num_h) // 2 - num_bb[1]
    draw.text((num_x, num_y), date_num, font=num_font, fill=style.bg)

    # Separator between date panel and events
    vline(draw, events_x, y0, y0 + total_h - 1, fill=style.fg)

    # --- Right events panel ---
    today_events = _events_for_today(events, today)
    _draw_event_list(
        draw, today_events,
        events_x + PAD, y0, events_w - PAD * 2, total_h,
        style,
    )


def _draw_event_list(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    x: int,
    y0: int,
    max_w: int,
    total_h: int,
    style: ThemeStyle,
) -> None:
    """Draw today's events in a large, spacious list."""
    time_font = style.font_regular(13)
    title_font = style.font_semibold(16)
    allday_font = style.font_semibold(15)
    loc_font = style.font_regular(12)

    allday_bar_h = text_height(allday_font) + 8
    event_spacing = 10

    if not events:
        empty_font = style.font_regular(16)
        msg = "No events today"
        msg_bb = draw.textbbox((0, 0), msg, font=empty_font)
        msg_w = msg_bb[2] - msg_bb[0]
        msg_h = msg_bb[3] - msg_bb[1]
        draw.text(
            (x + (max_w - msg_w) // 2 - msg_bb[0], y0 + (total_h - msg_h) // 2 - msg_bb[1]),
            msg, font=empty_font, fill=style.fg,
        )
        return

    time_h = text_height(time_font)
    title_h = text_height(title_font)
    # Minimum height needed to render each event type (used for overflow guard).
    # Timed: time line + gap + one title line + spacing.
    # All-day: bar + spacing.
    min_timed_h = time_h + 2 + title_h + event_spacing
    min_allday_h = allday_bar_h + event_spacing
    # Height reserved for the "+N more" overflow indicator.
    more_h = time_h
    bottom = y0 + total_h - PAD  # absolute y limit for content

    y = y0 + PAD
    for idx, event in enumerate(events):
        min_h = min_allday_h if event.is_all_day else min_timed_h
        if y + min_h > bottom:
            remaining = len(events) - idx
            more_y = min(y, bottom - more_h)
            draw.text((x, more_y), f"+{remaining} more", font=time_font, fill=style.fg)
            break

        if event.is_all_day:
            bar_x1 = x + max_w
            if style.invert_allday_bars:
                filled_rect(draw, (x, y, bar_x1, y + allday_bar_h - 1), fill=style.fg)
                draw_text_truncated(
                    draw, (x + 6, y + 4),
                    event.summary, allday_font, max_w - 12, fill=style.bg,
                )
            else:
                draw.rectangle((x, y, bar_x1, y + allday_bar_h - 1), outline=style.fg)
                draw_text_truncated(
                    draw, (x + 6, y + 4),
                    event.summary, allday_font, max_w - 12, fill=style.fg,
                )
            y += allday_bar_h + event_spacing
        else:
            # Time range
            start_s = _fmt_time(event.start)
            end_s = _fmt_time(event.end)
            if event.start.strftime("%p") == event.end.strftime("%p"):
                start_s = start_s.rstrip("ap")
            time_str = f"{start_s}–{end_s}"
            draw_text_truncated(draw, (x, y), time_str, time_font, max_w, fill=style.fg)
            y += time_h + 2

            # Title — limit to however many lines fit in the remaining space.
            remaining_for_title = bottom - event_spacing - y
            max_lines = max(1, remaining_for_title // (title_h + 2))
            used_h = draw_text_wrapped(
                draw, (x, y), event.summary, title_font,
                max_w, max_lines=min(2, max_lines), line_spacing=2, fill=style.fg,
            )
            y += max(used_h, title_h)

            # Location (first segment only)
            if event.location:
                # Normalize location to a single visual line (collapse newlines/extra spaces)
                # so y-advance stays consistent with measured single-line font height.
                loc_text = " ".join(event.location.split(",")[0].split())
                if loc_text and y + text_height(loc_font) <= bottom:
                    y += 2
                    draw_text_truncated(draw, (x, y), loc_text, loc_font, max_w, fill=style.fg)
                    y += text_height(loc_font)

            y += event_spacing
