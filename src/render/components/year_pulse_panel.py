"""year_pulse_panel.py — Big-picture year view for the "year_pulse" theme.

Shows where we are in the year: year number, week number, day-of-year progress
bar, and a countdown list of upcoming events and birthdays.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from PIL import ImageDraw

from src.data.models import DashboardData
from src.render.primitives import (
    draw_text_truncated,
    filled_rect,
    hline,
    text_height,
    text_width,
)
from src.render.theme import ComponentRegion, ThemeStyle

PAD = 14
BAR_H = 16  # height of the year progress bar
BAR_RADIUS = 3  # corner rounding for the progress bar outline
MAX_COUNTDOWNS = 5  # max upcoming items to display


def draw_year_pulse(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the year-progress view inside *region*.

    Layout:
    - Top area: large year number + week number, then progress bar + day label
    - Divider rule
    - Bottom area: "COMING UP" countdown list (events + birthdays)
    """
    if region is None:
        region = ComponentRegion(0, 40, 800, 360)
    if style is None:
        style = ThemeStyle()

    x0, y0, w, h = region.x, region.y, region.w, region.h

    year = today.year
    day_of_year = today.timetuple().tm_yday
    days_in_year = 366 if calendar.isleap(year) else 365
    week_num = today.isocalendar()[1]
    pct = day_of_year / days_in_year

    # -----------------------------------------------------------------------
    # Top section — year stats
    # -----------------------------------------------------------------------
    year_font = style.font_bold(56)
    week_label_font = style.font_semibold(18)
    bar_label_font = style.font_regular(13)

    year_str = str(year)
    week_str = f"Week {week_num}"

    # Large year number (left)
    year_bb = draw.textbbox((0, 0), year_str, font=year_font)
    year_h = year_bb[3] - year_bb[1]
    draw.text(
        (x0 + PAD - year_bb[0], y0 + PAD - year_bb[1]),
        year_str,
        font=year_font,
        fill=style.fg,
    )

    # Week number (right-aligned, vertically centred with year)
    wk_bb = draw.textbbox((0, 0), week_str, font=week_label_font)
    wk_w = wk_bb[2] - wk_bb[0]
    wk_h = wk_bb[3] - wk_bb[1]
    wk_x = x0 + w - PAD - wk_w - wk_bb[0]
    wk_y = y0 + PAD + (year_h - wk_h) // 2 - wk_bb[1]
    draw.text((wk_x, wk_y), week_str, font=week_label_font, fill=style.fg)

    # Progress bar, sitting below the year number
    bar_top = y0 + PAD + year_h + 10
    bar_x0 = x0 + PAD
    bar_x1 = x0 + w - PAD
    bar_w = bar_x1 - bar_x0
    filled_w = int(bar_w * pct)

    # Outline rect
    draw.rectangle((bar_x0, bar_top, bar_x1, bar_top + BAR_H - 1), outline=style.fg)
    # Filled portion
    if filled_w > 0:
        filled_rect(
            draw, (bar_x0, bar_top, bar_x0 + filled_w - 1, bar_top + BAR_H - 1), fill=style.fg
        )

    # Bar label below: "Day X of Y · Z% complete"
    pct_int = int(pct * 100)
    bar_label = f"Day {day_of_year} of {days_in_year}  ·  {pct_int}% complete"
    bl_bb = draw.textbbox((0, 0), bar_label, font=bar_label_font)
    bl_h = bl_bb[3] - bl_bb[1]
    draw.text(
        (bar_x0 - bl_bb[0], bar_top + BAR_H + 5 - bl_bb[1]),
        bar_label,
        font=bar_label_font,
        fill=style.fg,
    )

    stats_bottom = bar_top + BAR_H + 5 + bl_h + PAD

    # -----------------------------------------------------------------------
    # Divider
    # -----------------------------------------------------------------------
    hline(draw, stats_bottom, x0 + PAD, x0 + w - PAD, fill=style.fg)

    # -----------------------------------------------------------------------
    # Bottom section — countdown list
    # -----------------------------------------------------------------------
    label_font = style.label_font()
    label_text = style.component_labels.get("year_pulse", "COMING UP")
    draw.text(
        (x0 + PAD, stats_bottom + 8),
        label_text,
        font=label_font,
        fill=style.fg,
    )
    list_top = stats_bottom + 8 + text_height(label_font) + 6

    countdowns = _build_countdowns(data, today)

    if not countdowns:
        empty_font = style.font_regular(14)
        draw.text((x0 + PAD, list_top), "Nothing coming up", font=empty_font, fill=style.fg)
        return

    arrow_font = style.font_bold(13)
    days_font = style.font_bold(13)
    name_font = style.font_regular(13)
    row_h = text_height(name_font) + 6
    bottom = y0 + h - 6

    for days_until, label in countdowns[:MAX_COUNTDOWNS]:
        if list_top + row_h > bottom:
            break

        # "→" arrow
        arrow_str = "\u2192"
        draw.text((x0 + PAD, list_top), arrow_str, font=arrow_font, fill=style.fg)
        arrow_w = text_width(draw, arrow_str, arrow_font)

        # Day count (bold)
        days_str = f"{days_until}d" if days_until > 0 else "today"
        draw.text((x0 + PAD + arrow_w + 6, list_top), days_str, font=days_font, fill=style.fg)
        days_w = text_width(draw, days_str, days_font)

        # Event / birthday name
        name_x = x0 + PAD + arrow_w + 6 + days_w + 10
        name_max_w = x0 + w - PAD - name_x
        draw_text_truncated(draw, (name_x, list_top), label, name_font, name_max_w, fill=style.fg)

        list_top += row_h


def _build_countdowns(data: DashboardData, today: date) -> list[tuple[int, str]]:
    """Merge upcoming calendar events (next 14 days) and birthdays (next 120 days).

    Returns a list of (days_until, label) sorted by days_until ascending.
    """
    items: list[tuple[int, str]] = []
    horizon_events = today + timedelta(days=14)
    horizon_bdays = today + timedelta(days=120)

    # Calendar events
    seen_event_dates: set[tuple[str, date]] = set()
    for event in data.events:
        if event.is_all_day:
            event_date = event.start.date() if isinstance(event.start, datetime) else event.start
        else:
            event_date = event.start.date()
        if today <= event_date <= horizon_events:
            key = (event.summary, event_date)
            if key not in seen_event_dates:
                seen_event_dates.add(key)
                days_until = (event_date - today).days
                items.append((days_until, event.summary))

    # Birthdays — compute next occurrence from today
    for bday in data.birthdays:
        try:
            next_occ = bday.date.replace(year=today.year)
            if next_occ < today:
                next_occ = bday.date.replace(year=today.year + 1)
        except ValueError:
            # Feb 29 edge case
            next_occ = bday.date.replace(year=today.year + 1, day=28)
        if next_occ <= horizon_bdays:
            days_until = (next_occ - today).days
            age_part = f" ({bday.age + 1})" if bday.age is not None else ""
            items.append((days_until, f"{bday.name}'s Birthday{age_part}"))

    items.sort(key=lambda t: t[0])
    return items
