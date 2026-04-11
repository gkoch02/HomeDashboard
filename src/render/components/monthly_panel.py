"""Monthly calendar heatmap panel for the ``monthly`` theme."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from PIL import ImageDraw

from src.data.models import CalendarEvent, DashboardData
from src.render.primitives import draw_text_truncated, text_height
from src.render.theme import ComponentRegion, ThemeStyle

PAD = 12
HEADER_H = 52
WEEKDAY_H = 24
GRID_TOP = HEADER_H + WEEKDAY_H + 6
GRID_BOTTOM_PAD = 10
CELL_GAP = 4
LEGEND_STEPS = 4
FIRST_WEEKDAY = 6  # Sunday
WEEKDAY_NAMES = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]

def draw_monthly(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw a month-view calendar with heatmap-shaded event density."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=1)

    x0, y0, w, h = region.x, region.y, region.w, region.h
    grid_dates = _month_grid_dates(today)
    density = _density_by_day(data.events, [d for d in grid_dates if d is not None])
    max_density = max((density[d] for d in grid_dates if d is not None), default=0)

    title_font = style.font_bold(28)
    meta_font = style.font_regular(12)
    weekday_font = style.font_semibold(12)
    day_font = style.font_bold(18)
    count_font = style.font_semibold(12)

    title_text = today.strftime("%B %Y").upper()
    title_bb = draw.textbbox((0, 0), title_text, font=title_font)
    draw.text((x0 + PAD - title_bb[0], y0 + PAD - title_bb[1]), title_text, font=title_font, fill=style.fg)

    meta_text = _month_meta_text(today, max_density)
    meta_bb = draw.textbbox((0, 0), meta_text, font=meta_font)
    meta_y = y0 + PAD + (title_bb[3] - title_bb[1]) + 2
    draw.text((x0 + PAD - meta_bb[0], meta_y - meta_bb[1]), meta_text, font=meta_font, fill=style.fg)

    _draw_legend(draw, x0 + w - PAD - 180, y0 + PAD + 8, style, max_density)

    grid_y = y0 + GRID_TOP
    cell_w = (w - PAD * 2 - CELL_GAP * 6) // 7
    cell_h = (h - GRID_TOP - GRID_BOTTOM_PAD - CELL_GAP * 5) // 6

    for col, label in enumerate(WEEKDAY_NAMES):
        wx = x0 + PAD + col * (cell_w + CELL_GAP)
        wb = draw.textbbox((0, 0), label, font=weekday_font)
        draw.text((wx + 4 - wb[0], y0 + HEADER_H - wb[1]), label, font=weekday_font, fill=style.fg)

    for idx, day in enumerate(grid_dates):
        row, col = divmod(idx, 7)
        cx = x0 + PAD + col * (cell_w + CELL_GAP)
        cy = grid_y + row * (cell_h + CELL_GAP)
        if day is None:
            continue

        rect = (cx, cy, cx + cell_w - 1, cy + cell_h - 1)
        count = density.get(day, 0)
        level = _density_level(count, max_density)
        fill = _heat_fill(level, style)
        outline = _outline_fill(day, today, style)

        draw.rounded_rectangle(rect, radius=6, fill=style.bg, outline=outline, width=2 if day == today else 1)
        if isinstance(style.fg, tuple):
            draw.rounded_rectangle(rect, radius=6, fill=fill, outline=None)
            draw.rounded_rectangle(rect, radius=6, fill=None, outline=outline, width=2 if day == today else 1)

        day_fill = _text_fill_for_cell(fill, style)
        if day == today:
            chip = _today_chip_rect(rect)
            draw.rounded_rectangle(chip, radius=5, fill=style.fg)
            day_fill = style.bg
        else:
            chip = None

        day_str = str(day.day)
        day_bb = draw.textbbox((0, 0), day_str, font=day_font)
        day_x = cx + 8 - day_bb[0]
        day_y = cy + 6 - day_bb[1]
        if chip is not None:
            day_x = chip[0] + (chip[2] - chip[0] - (day_bb[2] - day_bb[0])) // 2 - day_bb[0]
            day_y = chip[1] + (chip[3] - chip[1] - (day_bb[3] - day_bb[1])) // 2 - day_bb[1]
        draw.text((day_x, day_y), day_str, font=day_font, fill=day_fill)

        count_y = cy + cell_h - text_height(count_font) - 8
        if count > 0:
            count_text = "1 event" if count == 1 else f"{count} events"
            count_x = cx + 8
            if not isinstance(style.fg, tuple):
                indicator_w = _draw_monochrome_density_indicator(draw, rect, level, style)
                count_x += indicator_w + 6
            draw_text_truncated(
                draw,
                (count_x, count_y),
                count_text,
                count_font,
                cell_w - 16 - (count_x - (cx + 8)),
                fill=_text_fill_for_cell(fill, style),
            )
        elif day == today:
            draw.text((cx + 8, count_y), "today", font=count_font, fill=style.fg)

def _month_grid_dates(today: date) -> list[date | None]:
    """Return a six-row Sunday-first grid, blanking cells outside the month."""
    cal = calendar.Calendar(firstweekday=FIRST_WEEKDAY)
    weeks = cal.monthdatescalendar(today.year, today.month)
    while len(weeks) < 6:
        last_week = weeks[-1]
        weeks.append([d + timedelta(days=7) for d in last_week])
    result: list[date | None] = []
    for week in weeks[:6]:
        for d in week:
            result.append(d if d.month == today.month else None)
    return result


def _density_by_day(events: list[CalendarEvent], days: list[date]) -> dict[date, int]:
    """Count how many events fall on each visible day."""
    visible = set(days)
    counts = {day: 0 for day in days}
    for event in events:
        for day in _event_days(event):
            if day in visible:
                counts[day] += 1
    return counts


def _event_days(event: CalendarEvent) -> list[date]:
    """Return the calendar day(s) an event should contribute to."""
    if event.is_all_day:
        start = event.start.date() if isinstance(event.start, datetime) else event.start
        end = event.end.date() if isinstance(event.end, datetime) else event.end
        if end <= start:
            return [start]
        return [start + timedelta(days=offset) for offset in range((end - start).days)]
    return [event.start.date()]


def _density_level(count: int, max_density: int) -> int:
    if count <= 0:
        return 0
    if max_density <= 1:
        return LEGEND_STEPS
    return max(1, min(LEGEND_STEPS, round((count / max_density) * LEGEND_STEPS)))


def _heat_fill(level: int, style: ThemeStyle) -> int | tuple[int, int, int]:
    if isinstance(style.fg, tuple):
        return [
            (255, 249, 235),
            (255, 236, 162),
            (247, 179, 84),
            (224, 92, 54),
            (175, 28, 28),
        ][level]
    return style.bg


def _text_fill_for_cell(fill: int | tuple[int, int, int], style: ThemeStyle) -> int | tuple[int, int, int]:
    if isinstance(fill, tuple):
        luminance = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
        return style.bg if luminance < 150 and isinstance(style.bg, tuple) else style.fg
    return style.fg


def _outline_fill(day: date, today: date, style: ThemeStyle) -> int | tuple[int, int, int]:
    if day == today:
        return style.fg
    if isinstance(style.fg, tuple):
        return (145, 86, 34) if day.month == today.month else (200, 190, 170)
    return style.fg


def _quiet_fill(style: ThemeStyle) -> int | tuple[int, int, int]:
    return (122, 103, 80) if isinstance(style.fg, tuple) else style.fg


def _month_meta_text(today: date, max_density: int) -> str:
    month_name = today.strftime("%B")
    if max_density <= 0:
        return f"{month_name} looks open."
    suffix = "event" if max_density == 1 else "events"
    return f"Busiest day this month: {max_density} {suffix}."


def _draw_legend(draw: ImageDraw.ImageDraw, x: int, y: int, style: ThemeStyle, max_density: int) -> None:
    label_font = style.font_regular(11)
    swatch = 14
    gap = 4
    draw.text((x, y), "LESS", font=label_font, fill=_quiet_fill(style))
    sx = x + 34
    for level in range(1, LEGEND_STEPS + 1):
        if isinstance(style.fg, tuple):
            draw.rounded_rectangle(
                (sx, y - 1, sx + swatch, y + swatch - 1),
                radius=3,
                fill=_heat_fill(level, style),
                outline=_outline_fill(date(2000, 1, 1), date(2000, 1, 1), style),
            )
        else:
            draw.rounded_rectangle((sx, y - 1, sx + swatch, y + swatch - 1), radius=3, outline=style.fg)
            for n in range(level):
                bx = sx + 2 + n * 3
                draw.rectangle((bx, y + 2, bx + 1, y + swatch - 4), fill=style.fg)
        sx += swatch + gap
    draw.text((sx + 6, y), "MORE", font=label_font, fill=_quiet_fill(style))
    if max_density > 0:
        draw.text((x, y + 16), f"scale to {max_density}+", font=label_font, fill=_quiet_fill(style))

def _draw_monochrome_density_indicator(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    level: int,
    style: ThemeStyle,
) -> int:
    """Draw a compact 1-bit density meter and return its width."""
    x0, _, _, y1 = rect
    block_w = 5
    block_h = 8
    gap = 2
    base_y = y1 - block_h - 9
    total_w = LEGEND_STEPS * block_w + (LEGEND_STEPS - 1) * gap
    for idx in range(LEGEND_STEPS):
        bx = x0 + 8 + idx * (block_w + gap)
        by = base_y
        if idx < level:
            draw.rectangle((bx, by, bx + block_w - 1, by + block_h - 1), fill=style.fg)
        else:
            draw.rectangle((bx, by, bx + block_w - 1, by + block_h - 1), outline=style.fg)
    return total_w


def _today_chip_rect(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Return the top-right highlight chip bounds for today's date."""
    _, y0, x1, _ = rect
    chip_w = 28
    chip_h = 22
    return (x1 - chip_w - 6, y0 + 5, x1 - 6, y0 + 5 + chip_h)
