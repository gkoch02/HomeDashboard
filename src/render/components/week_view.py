from datetime import datetime, date, timedelta
from PIL import ImageDraw

from src.data.models import CalendarEvent, DayForecast
from src.render import layout as L
from src.render.fonts import (
    semibold, regular, bold, medium,
)
from src.render.primitives import (
    BLACK, WHITE, hline, vline, dashed_vline, filled_rect,
    draw_text_truncated, draw_text_wrapped, text_height, text_width,
    fmt_time as _fmt_time, events_for_day as _events_for_day, wrap_lines,
)
from src.render.theme import ComponentRegion, ThemeStyle

PAD = L.PAD_SM + 1  # 5px inner padding for columns

# Number of days in a week (not a layout detail — always 7)
_COL_COUNT = 7


def _density_tier(event_count: int, is_weekend: bool) -> str:
    """Select density tier based on event count and column type.

    Returns ``"normal"``, ``"compact"``, or ``"dense"``.
    Weekend columns have lower thresholds due to reduced height.
    """
    if is_weekend:
        if event_count >= 5:
            return "dense"
        if event_count >= 3:
            return "compact"
        return "normal"
    # Weekday
    if event_count >= 8:
        return "dense"
    if event_count >= 5:
        return "compact"
    return "normal"


def _fonts_for_tier(tier: str, style: ThemeStyle | None = None) -> tuple:
    """Return rendering parameters for the given density tier.

    Returns ``(time_font, title_font, allday_font, event_spacing,
    max_title_lines, show_location, allday_pad)``.
    """
    if style is None:
        style = ThemeStyle()

    scale = style.spacing_scale
    if tier == "dense":
        return (
            style.font_regular(9), style.font_medium(11),
            style.font_semibold(11),
            max(1, int(2 * scale)), 1, False, 4,
        )
    if tier == "compact":
        return (
            style.font_regular(10), style.font_medium(12),
            style.font_semibold(11),
            max(1, int(3 * scale)), 1, False, 4,
        )
    # normal
    return (
        style.font_regular(11), style.font_semibold(14),
        style.font_semibold(13),
        max(1, int(6 * scale)), 2, True, 6,
    )


def draw_week(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    today: date,
    forecast: list[DayForecast] | None = None,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
):
    """Draw the 7-day calendar grid starting from the Monday of the current week."""
    if region is None:
        region = ComponentRegion(L.WEEK_X, L.WEEK_Y, L.WEEK_W, L.WEEK_H)
    if style is None:
        style = ThemeStyle()

    x0 = region.x
    y0 = region.y
    total_w = region.w
    total_h = region.h

    # Compute derived layout values proportionally from the region
    header_h = max(24, total_h * 32 // 320)   # 32px at 320h → scales proportionally
    body_h = total_h - header_h
    body_top = y0 + header_h

    # Column widths: 7 equal columns; last absorbs rounding remainder
    col_w_base = total_w // _COL_COUNT
    last_col_w = total_w - col_w_base * (_COL_COUNT - 1)

    # Weekend date section: lower 50% of body (as in original)
    date_section_h = body_h // 2

    # Find Monday of this week (weekday() == 0 for Monday)
    week_start = today - timedelta(days=today.weekday())

    _col_hdr_fn = style.font_title if style.font_title is not None else style.font_bold
    day_label_font = _col_hdr_fn(14)
    day_num_font = _col_hdr_fn(16)

    _date_num_fn = style.font_date_number if style.font_date_number is not None else style.font_bold
    date_section_font = _date_num_fn(100)
    date_y = body_top + body_h - date_section_h  # top of combined date cell

    # Saturday is col 5 (Mon=0 … Sat=5, Sun=6)
    SAT_COL = 5
    sat_cx = x0 + SAT_COL * col_w_base
    combined_date_w = col_w_base + last_col_w   # last two columns merged

    week_end = week_start + timedelta(days=7)

    # --- Multi-day spanning event bars (rendered above per-day content) ---
    spanning = _collect_spanning_events(events, week_start, week_end)
    spanning_ids: set[str | None] = set()
    allday_font = style.font_semibold(13)
    span_bar_h = text_height(allday_font) + 6
    span_spacing = 2
    span_total_h = 0
    if spanning:
        for evt, first_col, last_col in spanning:
            spanning_ids.add(id(evt))

            bar_y = body_top + PAD + span_total_h
            bar_x0 = x0 + first_col * col_w_base + PAD - 1
            this_last_col_w = last_col_w if last_col == _COL_COUNT - 1 else col_w_base
            bar_x1 = x0 + last_col * col_w_base + this_last_col_w - PAD

            if style.invert_allday_bars:
                filled_rect(draw, (bar_x0, bar_y, bar_x1, bar_y + span_bar_h), fill=style.fg)
                bar_text_w = bar_x1 - bar_x0 - PAD * 2
                draw_text_truncated(
                    draw, (bar_x0 + PAD, bar_y + 3),
                    evt.summary, allday_font, bar_text_w, fill=style.bg,
                )
            else:
                draw.rectangle((bar_x0, bar_y, bar_x1, bar_y + span_bar_h), outline=style.fg)
                bar_text_w = bar_x1 - bar_x0 - PAD * 2
                draw_text_truncated(
                    draw, (bar_x0 + PAD, bar_y + 3),
                    evt.summary, allday_font, bar_text_w, fill=style.fg,
                )
            span_total_h += span_bar_h + span_spacing

    for col in range(_COL_COUNT):
        day = week_start + timedelta(days=col)
        col_w = last_col_w if col == _COL_COUNT - 1 else col_w_base
        cx = x0 + col * col_w_base
        is_today = day == today

        # Pre-compute events for this day
        day_events = _events_for_day(events, day)

        # Column header
        day_abbr = day.strftime("%a").upper()
        day_num = str(day.day)

        is_weekend = day.weekday() >= 5  # Sat=5, Sun=6

        if is_today and style.invert_today_col:
            # Inverted header for today
            filled_rect(draw, (cx, y0, cx + col_w - 1, y0 + header_h - 1), fill=style.fg)
            fnt = _col_hdr_fn(16)
            num_bb = draw.textbbox((0, 0), day_num, font=fnt)
            abbr_bb = draw.textbbox((0, 0), day_abbr, font=fnt)
            num_ink_h = num_bb[3] - num_bb[1]
            ty_num = y0 + (header_h - num_ink_h) // 2 - num_bb[1]
            ty_abbr = ty_num + num_bb[3] - abbr_bb[3]
            draw.text((cx + PAD, ty_abbr), day_abbr, font=fnt, fill=style.bg)
            abbr_w = text_width(draw, day_abbr + " ", fnt)
            draw.text((cx + PAD + abbr_w, ty_num), day_num, font=fnt, fill=style.bg)
        elif is_today and not style.invert_today_col:
            # Non-inverted today: bold text + accent
            fnt = _col_hdr_fn(16)
            num_bb = draw.textbbox((0, 0), day_num, font=fnt)
            abbr_bb = draw.textbbox((0, 0), day_abbr, font=fnt)
            num_ink_h = num_bb[3] - num_bb[1]
            ty_num = y0 + (header_h - num_ink_h) // 2 - num_bb[1]
            ty_abbr = ty_num + num_bb[3] - abbr_bb[3]
            draw.text((cx + PAD, ty_abbr), day_abbr, font=fnt, fill=style.fg)
            abbr_w = text_width(draw, day_abbr + " ", fnt)
            draw.text((cx + PAD + abbr_w, ty_num), day_num, font=fnt, fill=style.fg)
            if style.show_borders:
                # Thick 2px underline beneath the day label
                hline(draw, y0 + header_h - 3, cx + PAD, cx + col_w - PAD - 1, fill=style.fg)
                hline(draw, y0 + header_h - 2, cx + PAD, cx + col_w - PAD - 1, fill=style.fg)
            else:
                # Subtle 1px border around the column header cell
                draw.rectangle((cx, y0, cx + col_w - 1, y0 + header_h - 1), outline=style.fg)
        elif is_weekend:
            # Weekend: lighter styling — regular weight instead of semibold
            wknd_abbr_font = _col_hdr_fn(14)
            wknd_num_font = _col_hdr_fn(16)
            num_bb = draw.textbbox((0, 0), day_num, font=wknd_num_font)
            abbr_bb = draw.textbbox((0, 0), day_abbr, font=wknd_abbr_font)
            num_ink_h = num_bb[3] - num_bb[1]
            ty_num = y0 + (header_h - num_ink_h) // 2 - num_bb[1]
            ty_abbr = ty_num + num_bb[3] - abbr_bb[3]
            draw.text((cx + PAD, ty_abbr), day_abbr, font=wknd_abbr_font, fill=style.fg)
            abbr_w = text_width(draw, day_abbr + " ", wknd_abbr_font)
            draw.text((cx + PAD + abbr_w, ty_num), day_num, font=wknd_num_font, fill=style.fg)
        else:
            # Weekday (not today)
            num_bb = draw.textbbox((0, 0), day_num, font=day_num_font)
            abbr_bb = draw.textbbox((0, 0), day_abbr, font=day_label_font)
            num_ink_h = num_bb[3] - num_bb[1]
            ty_num = y0 + (header_h - num_ink_h) // 2 - num_bb[1]
            ty_abbr = ty_num + num_bb[3] - abbr_bb[3]
            draw.text((cx + PAD, ty_abbr), day_abbr, font=day_label_font, fill=style.fg)
            abbr_w = text_width(draw, day_abbr + " ", day_label_font)
            draw.text((cx + PAD + abbr_w, ty_num), day_num, font=day_num_font, fill=style.fg)

        # Header underline
        if style.show_borders:
            hline(draw, y0 + header_h - 1, cx, cx + col_w - 1, fill=style.fg)

        # Column separator (right edge)
        FRI_COL = SAT_COL - 1
        if col < _COL_COUNT - 1 and style.show_borders:
            sep_bottom = (date_y - 1) if col in (FRI_COL, SAT_COL) else (y0 + total_h - 1)
            vline(draw, cx + col_w - 1, y0, y0 + header_h - 1, fill=style.fg)
            dashed_vline(draw, cx + col_w - 1, body_top, sep_bottom, fill=style.fg)

        # Events — weekend columns give up their bottom 50% to the shared date cell
        events_body_h = (body_h - date_section_h) if is_weekend else body_h
        events_y_start = body_top + span_total_h
        adjusted_body_h = events_body_h - span_total_h

        day_events_filtered = [e for e in day_events if id(e) not in spanning_ids]

        if day_events_filtered:
            tier = _density_tier(len(day_events_filtered), is_weekend)
            (t_font, ti_font, ad_font,
             spacing, max_lines, show_loc, ad_pad) = _fonts_for_tier(tier, style)
            _draw_day_events(
                draw, day_events_filtered, cx, events_y_start,
                col_w, adjusted_body_h, t_font, ti_font,
                allday_font=ad_font, event_spacing=spacing,
                max_title_lines=max_lines, show_location=show_loc,
                allday_pad=ad_pad, style=style,
            )
        elif not day_events:  # only show dash if truly empty (no spanning events either)
            empty_font = style.font_regular(12)
            dash = "–"
            dw = text_width(draw, dash, empty_font)
            dh = text_height(empty_font)
            draw.text(
                (cx + (col_w - dw) // 2, events_y_start + adjusted_body_h // 3 - dh // 2),
                dash, font=empty_font, fill=style.fg,
            )

    # Solid left border for the combined date cell (Saturday's left edge)
    if style.show_borders:
        vline(draw, sat_cx, date_y, y0 + total_h - 1, fill=style.fg)

    # Combined "Today" cell — inverted month header, normal day number
    _month_fn = style.font_month_title if style.font_month_title is not None else style.font_bold
    month_text = today.strftime("%B").upper()
    _month_size = 33
    month_font = _month_fn(_month_size)
    mbb = draw.textbbox((0, 0), month_text, font=month_font)
    month_w = mbb[2] - mbb[0]
    # Scale down font until the text fits within the combined cell width (with padding)
    while month_w > combined_date_w - PAD * 2 and _month_size > 8:
        _month_size -= 1
        month_font = _month_fn(_month_size)
        mbb = draw.textbbox((0, 0), month_text, font=month_font)
        month_w = mbb[2] - mbb[0]
    month_h = mbb[3] - mbb[1]
    month_band_h = month_h + PAD * 2

    month_x = sat_cx + (combined_date_w - month_w) // 2 - mbb[0]
    month_y = date_y + (month_band_h - month_h) // 2 - mbb[1]
    if style.show_borders:
        # Inverted black band for month header
        filled_rect(
            draw,
            (sat_cx, date_y, sat_cx + combined_date_w - 1, date_y + month_band_h - 1),
            fill=style.fg,
        )
        draw.text((month_x, month_y), month_text, font=month_font, fill=style.bg)
    else:
        draw.text((month_x, month_y), month_text, font=month_font, fill=style.fg)

    # Day number — centred in the remaining space below the band
    day_area_y = date_y + month_band_h
    day_area_h = date_section_h - month_band_h
    dn_text = str(today.day)
    dbb = draw.textbbox((0, 0), dn_text, font=date_section_font)
    dn_w = dbb[2] - dbb[0]
    dn_h = dbb[3] - dbb[1]
    dn_x = sat_cx + (combined_date_w - dn_w) // 2 - dbb[0]
    dn_y = day_area_y + (day_area_h - dn_h) // 2 - dbb[1]
    draw.text((dn_x, dn_y), dn_text, font=date_section_font, fill=style.fg)


def _wrap_line_count(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> int:
    """Return how many lines text would wrap into at the given font/width."""
    return len(wrap_lines(text, font, max_w))


def _autofit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    style: "ThemeStyle",
    max_w: int,
    max_lines: int = 2,
    min_size: int = 9,
):
    """Return the given font, stepping down until all words fit in max_w and
    the wrapped text fits within max_lines."""
    current = font
    size = current.size
    while size > min_size:
        words = text.split()
        words_fit = all(
            draw.textbbox((0, 0), w, font=current)[2]
            - draw.textbbox((0, 0), w, font=current)[0] <= max_w
            for w in words
        )
        if words_fit and _wrap_line_count(draw, text, current, max_w) <= max_lines:
            return current
        size -= 1
        current = style.font_medium(size)
    return current


def _event_date_range(e: CalendarEvent) -> tuple[date, date]:
    """Return (start_date, end_date) for an event (end is exclusive)."""
    start_d = e.start.date() if isinstance(e.start, datetime) else e.start
    end_d = e.end.date() if isinstance(e.end, datetime) else e.end
    return start_d, end_d


def _is_multiday(e: CalendarEvent) -> bool:
    """Return True if the event is all-day and spans 2+ calendar days."""
    if not e.is_all_day:
        return False
    start_d, end_d = _event_date_range(e)
    return (end_d - start_d).days >= 2


def _collect_spanning_events(
    events: list[CalendarEvent], week_start: date, week_end: date,
) -> list[tuple[CalendarEvent, int, int]]:
    """Identify multi-day all-day events visible in the week and return their column spans.

    Returns a list of (event, first_col, last_col_inclusive) tuples, sorted by
    start date then summary.  Columns are 0-indexed (Mon=0, Sun=6).
    """
    result: list[tuple[CalendarEvent, int, int]] = []
    for e in events:
        if not _is_multiday(e):
            continue
        start_d, end_d = _event_date_range(e)
        vis_start = max(start_d, week_start)
        vis_end = min(end_d, week_end)  # end_d is exclusive
        if vis_start >= vis_end:
            continue
        first_col = (vis_start - week_start).days
        last_col = (vis_end - week_start).days - 1  # inclusive
        result.append((e, first_col, last_col))
    result.sort(key=lambda t: (t[1], t[0].summary))
    return result


def _draw_day_events(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    cx: int,
    y_start: int,
    col_w: int,
    max_h: int,
    time_font,
    title_font,
    allday_font=None,
    event_spacing: int = 6,
    max_title_lines: int = 2,
    show_location: bool = True,
    allday_pad: int = 6,
    style: ThemeStyle | None = None,
):
    if style is None:
        style = ThemeStyle()
    if allday_font is None:
        allday_font = style.font_semibold(13)

    y = y_start + PAD + 1
    max_w = col_w - PAD * 2 - 1
    time_h = text_height(time_font)
    title_h = text_height(title_font)
    loc_font = style.font_regular(10)
    loc_h = text_height(loc_font)

    for idx, event in enumerate(events):
        if y - y_start + title_h > max_h - PAD:
            remaining = len(events) - idx
            draw.text((cx + PAD, y), f"+{remaining} more", font=time_font, fill=style.fg)
            break

        if event.is_all_day:
            bar_h = text_height(allday_font) + allday_pad
            if style.invert_allday_bars:
                filled_rect(
                    draw, (cx + PAD - 1, y, cx + col_w - PAD, y + bar_h), fill=style.fg,
                )
                draw_text_truncated(
                    draw, (cx + PAD + 2, y + allday_pad // 2),
                    event.summary, allday_font, max_w - 6, fill=style.bg,
                )
            else:
                draw.rectangle(
                    (cx + PAD - 1, y, cx + col_w - PAD, y + bar_h), outline=style.fg,
                )
                draw_text_truncated(
                    draw, (cx + PAD + 2, y + allday_pad // 2),
                    event.summary, allday_font, max_w - 6, fill=style.fg,
                )
            y += bar_h + event_spacing
        else:
            start_s = _fmt_time(event.start)
            end_s = _fmt_time(event.end)
            if event.start.strftime("%p") == event.end.strftime("%p"):
                start_s = start_s.rstrip("ap")
            time_str = f"{start_s}–{end_s}"
            draw_text_truncated(
                draw, (cx + PAD, y), time_str, time_font, max_w, fill=style.fg,
            )
            y += time_h + 1
            fitted_font = _autofit_font(
                draw, event.summary, title_font, style, max_w,
                max_lines=max_title_lines,
            )
            used_h = draw_text_wrapped(
                draw, (cx + PAD, y), event.summary, fitted_font,
                max_w, max_lines=max_title_lines, line_spacing=1, fill=style.fg,
            )
            y += max(used_h, title_h)

            if show_location and event.location:
                # Normalize location to a single visual line (collapse newlines/extra spaces)
                # so y-advance stays consistent with measured single-line font height.
                loc_text = " ".join(event.location.split(",")[0].split())
                if loc_text and y - y_start + loc_h <= max_h - PAD:
                    y += 1
                    draw_text_truncated(
                        draw, (cx + PAD, y), loc_text, loc_font, max_w, fill=style.fg,
                    )
                    y += loc_h

            y += event_spacing
