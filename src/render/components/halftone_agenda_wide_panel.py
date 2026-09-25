"""Wide-native halftone agenda for the 1360x480 panoramic plate.

``halftone_agenda`` cuts an 800x480 plate in two: engraving and weather on the
left, today's events on the right. Stretched or fitted onto the 10.85" strip
it wastes the panel either way. This plate is the same vocabulary drawn for the
strip's own shape, in three panes divided by full-height ordered-Bayer rules:

  * **Art pane** (``ART_W``) — the procedural weather illustration from
    :func:`src.render.skyart.draw_weather_scene`, a horizontal Bayer rule, then
    the typeset weather band ``halftone_agenda`` sets: temperature numeral,
    condition, high/low, sunrise, sunset, date and feels-like. The band is
    imported from that panel rather than copied — the two plates must not
    drift apart in what they read out.
  * **Agenda pane** (``AGENDA_W``) — today's events, drawn by the same
    ``_draw_agenda_pane`` the original uses, at half again its width. Every
    state treatment comes with it: elapsed rows perforated, the event in
    progress inverted into a red bar, the next one up ticked, and the
    after-dark rollover to TOMORROW.
  * **Rail** (the rest) — what the original plate has no room for. Top to
    bottom: an inverted alert bar when the weather service has one; the
    following day's first events (``TOMORROW``, or the day after that once
    the agenda has rolled over — the theme fetches two extra days for it);
    the forecast, one row per day with glyph, high, low and chance of rain;
    the coming birthdays; and a bottom row pairing the air-quality index
    with the moon's phase.

Nothing in the rail reads the clock except through ``agenda_day``, so the
plate keeps the original's property: a tick that crosses no event boundary
renders byte-identically and costs no panel write. Every typeset region is
hardened before the backend dithers; only the illustration diffuses.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import AirQualityData, Birthday, CalendarEvent, DashboardData, WeatherData
from src.render.artkit import accent_red as _accent_red
from src.render.artkit import ink as _ink
from src.render.artkit import to_local_naive
from src.render.components.day_arc_panel import agenda_day, event_state
from src.render.components.halftone_agenda_panel import _clock as _clock_text
from src.render.components.halftone_agenda_panel import (
    _draw_weather_band,
    _location_text,
    _sun_times,
    event_times,
    inline_range,
    past_screen,
    two_line_time_fits,
)
from src.render.fonts import antonio_semibold, weather_icon
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_illumination, moon_phase_glyph, moon_phase_name
from src.render.primitives import (
    content_time,
    draw_text_truncated,
    events_for_day,
    fmt_time,
    text_height,
    text_width,
)
from src.render.skyart import draw_bayer_rule, draw_weather_scene, harden_typeset, screened_paste
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Region geometry
# ---------------------------------------------------------------------------

ART_W = 420  # illustration + weather band
DIVIDER_W = 6  # each full-height vertical Bayer rule
AGENDA_W = 560  # today's events
RAIL_X = ART_W + DIVIDER_W + AGENDA_W + DIVIDER_W  # 992
HERO_H = 292
RULE_H = 6
BAND_Y = HERO_H + RULE_H

AGENDA_PAD_X = 20
RAIL_PAD_X = 18
FOOTER_H = 22

# The pane is 52% of halftone's hero width and 99% of its height; 0.8 fills it
# the way 0.72 fills halftone_agenda's narrower pane.
SCENE_SCALE = 0.8

# Rail cells, top to bottom. Each is a labelled block; a block that does not
# fit in what is left of the rail is dropped whole rather than clipped.
TOMORROW_MAX = 3
FORECAST_MAX = 4
BIRTHDAY_MAX = 3
BIRTHDAY_LOOKAHEAD_DAYS = 14

# How many days past today the agenda and the rail can reach: the agenda rolls
# to tomorrow after dark, and the rail then shows the day after. The theme's
# event window is widened by this in ``src.app``.
EXTRA_EVENT_DAYS = 2

_LABEL_PT = 14

# --- Agenda pane geometry. The pane is 520 px of content, half again the
# original's, and the extra width is spent on data rather than on bigger
# type: a duration column against the right margin, a schedule strip under
# the header, and room for a location under every title at every tier but
# the densest.
STRIP_H = 30  # schedule strip: 16-px bar + hour labels
STRIP_MIN_HOUR = 6
STRIP_MAX_HOUR = 22
DURATION_W = 64  # right-aligned "1h 30m" column
GAP_ROW_H = 16  # "· 1h 15m free ·" marker between two events
GAP_MIN_MINUTES = 30  # shorter gaps are not worth a line

# Density tiers for the wide agenda: (max_rows, row_h, time_w, time_pt,
# title_pt, show_location, show_gaps). With 520 px the title column keeps a
# location under it at every tier but the densest, and gap markers are
# dropped before the type shrinks past 18 px, since they cost a row each.
_WIDE_TIERS: tuple[tuple[int, int, int, int, int, bool, bool], ...] = (
    (3, 76, 92, 22, 28, True, True),
    (5, 62, 84, 20, 24, True, True),
    (7, 50, 78, 18, 21, True, True),
    (9, 40, 72, 16, 18, True, False),
    (12, 32, 66, 14, 16, False, False),
)
_CELL_GAP = 8
# The air-and-moon foot, anchored to the rail bottom.
FOOT_H = 52


def art_rect(region: ComponentRegion) -> tuple[int, int, int, int]:
    """The illustration's rectangle — the part of the plate that may dither in colour."""
    art_w = min(ART_W, max(1, region.w - DIVIDER_W))
    return (region.x, region.y, region.x + art_w, region.y + min(HERO_H, region.h))


def draw_halftone_agenda_wide(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full ``halftone_agenda_wide`` plate into *region* of *image*."""
    if region is None:
        region = ComponentRegion(0, 0, 1360, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        image = draw._image  # type: ignore[attr-defined]

    mode = image.mode
    x0, y0, w, h = region.x, region.y, region.w, region.h
    tz = now.tzinfo
    now_naive = to_local_naive(now, tz)
    sunrise, sunset = _sun_times(data.weather, tz)

    art_w = min(ART_W, max(1, w - DIVIDER_W))
    hero_h = min(HERO_H, h)
    band_h = max(0, h - BAND_Y)

    # --- Art pane.
    icon = data.weather.current_icon if data.weather is not None else None
    draw_weather_scene(image, (x0, y0, x0 + art_w, y0 + hero_h), icon, today, scale=SCENE_SCALE)
    draw_bayer_rule(image, x0, y0 + HERO_H, art_w, RULE_H, mode)
    if band_h > 0:
        _draw_weather_band(
            draw,
            image,
            data.weather,
            today,
            style,
            x0=x0,
            y0=y0 + BAND_Y,
            w=art_w,
            h=band_h,
            sunrise=sunrise,
            sunset=sunset,
        )
    draw_bayer_rule(image, x0 + art_w, y0, DIVIDER_W, h, mode, orientation="vertical")

    # --- Agenda pane on clean paper.
    pane_x = x0 + art_w + DIVIDER_W
    pane_w = min(AGENDA_W, max(0, w - art_w - DIVIDER_W))
    if pane_w <= 0:
        return
    _paper(image, pane_x, y0, pane_w, h)
    day, is_tomorrow = agenda_day(data.events, today, now_naive, sunset)
    _draw_wide_agenda(
        image,
        draw,
        data.events,
        day,
        is_tomorrow,
        now_naive,
        style,
        x0=pane_x + AGENDA_PAD_X,
        y0=y0 + 14,
        w=pane_w - AGENDA_PAD_X * 2,
        h=h - 14 - FOOTER_H,
    )
    ink = _ink(mode)
    footer_font = style.font_medium(16)
    stamp = f"updated {_clock_text(to_local_naive(content_time(data, now), tz)).lower()}"
    sw = text_width(draw, stamp, footer_font)
    draw.text(
        (
            pane_x + pane_w - AGENDA_PAD_X - sw,
            y0 + h - FOOTER_H + (FOOTER_H - text_height(footer_font)) // 2,
        ),
        stamp,
        font=footer_font,
        fill=ink,
    )

    # --- Rail.
    rail_x = pane_x + pane_w
    rail_w = max(0, x0 + w - rail_x)
    if rail_w > DIVIDER_W:
        draw_bayer_rule(image, rail_x, y0, DIVIDER_W, h, mode, orientation="vertical")
        rail_x += DIVIDER_W
        rail_w -= DIVIDER_W
        _paper(image, rail_x, y0, rail_w, h)
        _draw_rail(
            image,
            draw,
            data,
            today,
            day + timedelta(days=1),
            is_tomorrow,
            style,
            x0=rail_x + RAIL_PAD_X,
            y0=y0 + 14,
            w=rail_w - 2 * RAIL_PAD_X,
            h=h - 14 - 10,
        )

    if band_h > 0:
        harden_typeset(image, (x0, y0 + BAND_Y, art_w, band_h))
    harden_typeset(image, (pane_x, y0, pane_w, h))
    if rail_w > 0:
        harden_typeset(image, (rail_x, y0, rail_w, h))


def _paper(image: Image.Image, x: int, y: int, w: int, h: int) -> None:
    paper = Image.new("L", (w, h), 255)
    if image.mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x, y))


# ---------------------------------------------------------------------------
# Agenda pane
# ---------------------------------------------------------------------------


def _minutes(evt: CalendarEvent) -> int:
    return max(0, int((evt.end - evt.start).total_seconds() // 60))


def fmt_duration(minutes: int) -> str:
    """``45m``, ``1h``, ``1h 30m`` — the compact form the duration column sets."""
    h, m = divmod(max(0, minutes), 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def booked_minutes(events: list[CalendarEvent]) -> int:
    """Minutes covered by timed *events*, overlaps counted once."""
    spans = sorted((e.start, e.end) for e in events if not e.is_all_day and e.end > e.start)
    total = 0
    cursor = None
    for start, end in spans:
        if cursor is None or start >= cursor:
            total += int((end - start).total_seconds() // 60)
            cursor = end
        elif end > cursor:
            total += int((end - cursor).total_seconds() // 60)
            cursor = end
    return total


def gap_after(events: list[CalendarEvent], index: int) -> int | None:
    """Free minutes between timed event *index* and the next timed event, if any.

    The gap is measured from the latest end so far, so a long event that
    swallows the next short one does not report a phantom gap.
    """
    this = events[index]
    if this.is_all_day:
        return None
    latest_end = max(e.end for e in events[: index + 1] if not e.is_all_day)
    for nxt in events[index + 1 :]:
        if nxt.is_all_day:
            continue
        gap = int((nxt.start - latest_end).total_seconds() // 60)
        return max(0, gap)
    return None


def wide_metrics(
    n_events: int, n_gaps: int, avail_h: int
) -> tuple[int, int, int, int, int, bool, bool]:
    """Pick the roomiest tier whose rows (and gap markers, where it shows them) fit."""
    for tier in _WIDE_TIERS:
        max_rows, row_h, *_rest, show_gaps = tier
        needed = n_events * row_h + (n_gaps * GAP_ROW_H if show_gaps else 0)
        if n_events <= max_rows and needed <= avail_h:
            return tier
    return _WIDE_TIERS[-1]


def strip_hours(events: list[CalendarEvent], day: date) -> tuple[int, int]:
    """The schedule strip's hour span: at least 6a–10p, widened by an event outside it."""
    start, end = STRIP_MIN_HOUR, STRIP_MAX_HOUR
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    for evt in events:
        if evt.is_all_day:
            continue
        first = max(evt.start, day_start)
        last = min(evt.end, day_end)
        start = min(start, first.hour)
        end = max(end, 24 if last >= day_end else last.hour + (1 if last.minute else 0))
    return max(0, start), min(24, end)


def _draw_schedule_strip(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    day: date,
    now: datetime,
    style: ThemeStyle,
    *,
    x0: int,
    y0: int,
    w: int,
) -> None:
    """A day-long bar with a block per timed event, in the row treatments.

    The same reading as the rows below, compressed to a glance: where the day
    is dense, where it is free, and how much of it is spent. Blocks take the
    row's own encoding — an elapsed block perforated, the one in progress in
    the accent, the rest solid — so the strip changes only at event
    boundaries, like everything else on the pane.
    """
    mode = image.mode
    ink = _ink(mode)
    bar_h = 14
    start_h, end_h = strip_hours(events, day)
    span = max(1, end_h - start_h) * 60
    day_start = datetime.combine(day, datetime.min.time())

    def x_for(dt: datetime) -> int:
        minutes = (dt - day_start).total_seconds() / 60 - start_h * 60
        return x0 + round(max(0.0, min(1.0, minutes / span)) * w)

    # Baseline and hour ticks, labelled every three hours.
    draw.line([(x0, y0 + bar_h), (x0 + w, y0 + bar_h)], fill=ink, width=1)
    tick_font = style.font_medium(10)
    for hour in range(start_h, end_h + 1):
        x = x_for(day_start + timedelta(hours=hour))
        draw.line([(x, y0 + bar_h), (x, y0 + bar_h + 3)], fill=ink, width=1)
        if (hour - start_h) % 3 == 0 and hour < end_h:
            label = fmt_time(day_start + timedelta(hours=hour))
            draw.text((x + 2, y0 + bar_h + 3), label, font=tick_font, fill=ink)

    for evt in events:
        if evt.is_all_day:
            continue
        bx0 = x_for(max(evt.start, day_start))
        bx1 = max(bx0 + 3, x_for(min(evt.end, day_start + timedelta(days=1))))
        state = event_state(evt, now)
        box = (bx0, y0, bx1, y0 + bar_h - 1)
        if state == "now":
            draw.rectangle(box, fill=_accent_red(mode))
        elif state == "past":

            def _fill(d: ImageDraw.ImageDraw, _w=bx1 - bx0, _h=bar_h - 1) -> None:
                d.rectangle((0, 0, _w, _h), fill=0)

            screened_paste(image, (bx0, y0, bx1 - bx0 + 1, bar_h), _fill, threshold=128)
        else:
            draw.rectangle(box, fill=ink)


def _draw_time_cell(
    draw: ImageDraw.ImageDraw,
    start: str,
    end: str | None,
    *,
    x0: int,
    y: int,
    time_pt: int,
    row_h: int,
    fill,
) -> None:
    """Start and end labels in the condensed face; inline for whole hours, else stacked."""
    font = antonio_semibold(time_pt + 2)
    inline = inline_range(start, end)
    if inline is not None:
        draw.text((x0, y + 4), inline, font=font, fill=fill)
        return
    if end is None or not two_line_time_fits(time_pt, row_h):
        draw.text((x0, y + 4), start, font=font, fill=fill)
        return
    draw.text((x0, y + 4), f"{start} –", font=font, fill=fill)
    draw.text((x0, y + 5 + time_pt), end, font=font, fill=fill)


def _draw_wide_row(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    event: CalendarEvent,
    state: str,
    style: ThemeStyle,
    *,
    x0: int,
    y: int,
    w: int,
    row_h: int,
    time_w: int,
    time_pt: int,
    title_pt: int,
    show_location: bool,
    is_next: bool,
) -> None:
    """One agenda row: time cell, tick, title (+ location), duration.

    The treatments are the original pane's — elapsed rows perforated, the
    running one inverted, the rest crisp — with two additions the width
    pays for: a duration set against the right margin, and the next event's
    title in the accent, the way a literary clock sets the phrase that
    names the hour. On a monochrome panel the accent is ink and the tick
    still marks it.
    """
    mode = image.mode
    ink = _ink(mode)
    title_font = style.font_bold(title_pt)
    loc_font = style.font_medium(max(12, time_pt - 2))
    dur_font = antonio_semibold(time_pt + 2)
    start_str, end_str = event_times(event)
    two_line = end_str is not None and inline_range(start_str, end_str) is None
    two_line = two_line and two_line_time_fits(time_pt, row_h)
    title_x = x0 + time_w + 12
    title_w = max(20, w - (time_w + 12) - DURATION_W - 8)
    loc_y = 4 + text_height(title_font)
    content_h = max(
        text_height(title_font) + (text_height(loc_font) + 2 if show_location else 0) + 4,
        (5 + 2 * time_pt) if two_line else (4 + time_pt),
    )
    bar_top = y + 2
    bar_bot = min(y + row_h - 3, bar_top + content_h)
    duration = "" if event.is_all_day else fmt_duration(_minutes(event))
    dur_x = x0 + w - text_width(draw, duration, dur_font)

    def _body(d: ImageDraw.ImageDraw, ox: int, oy: int, fill) -> None:
        _draw_time_cell(d, start_str, end_str, x0=ox, y=oy, time_pt=time_pt, row_h=row_h, fill=fill)
        used = draw_text_truncated(
            d, (ox + time_w + 12, oy + 2), event.summary, title_font, title_w, fill=fill
        )
        if show_location and used:
            location = _location_text(event)
            if location:
                draw_text_truncated(
                    d, (ox + time_w + 12, oy + loc_y), location, loc_font, title_w, fill=fill
                )
        if duration:
            d.text((dur_x - x0 + ox, oy + 4), duration, font=dur_font, fill=fill)

    if state == "now":
        draw.rectangle((x0 - 6, bar_top - 2, x0 + w, bar_bot + 2), fill=_accent_red(mode))
        _body(draw, x0, y, style.bg)
        return
    if state == "past":
        screened_paste(
            image,
            (x0, y, w, max(1, row_h - 2)),
            lambda d: _body(d, 0, 0, 0),
            threshold=past_screen(title_pt),
        )
        return

    mark = _accent_red(mode) if is_next else ink
    _draw_time_cell(draw, start_str, end_str, x0=x0, y=y, time_pt=time_pt, row_h=row_h, fill=ink)
    tick = (x0 + time_w, bar_top, x0 + time_w + 3, bar_bot)
    if event.is_all_day:
        draw.rectangle(tick, outline=mark)
    else:
        draw.rectangle(tick, fill=mark)
    used = draw_text_truncated(
        draw, (title_x, y + 2), event.summary, title_font, title_w, fill=mark
    )
    if show_location and used:
        location = _location_text(event)
        if location:
            draw_text_truncated(draw, (title_x, y + loc_y), location, loc_font, title_w, fill=ink)
    if duration:
        draw.text((dur_x, y + 4), duration, font=dur_font, fill=ink)


def _draw_wide_agenda(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    day: date,
    is_tomorrow: bool,
    now: datetime,
    style: ThemeStyle,
    *,
    x0: int,
    y0: int,
    w: int,
    h: int,
) -> None:
    """Header with the day's totals, the schedule strip, a rule, then the rows."""
    mode = image.mode
    ink = _ink(mode)
    title_font = (style.font_title or style.font_bold)(26)
    meta_font = style.font_semibold(14)
    day_events = events_for_day(events, day)
    timed = [e for e in day_events if not e.is_all_day]

    # Header: TODAY / TOMORROW chip on the left; the day's totals on the right,
    # in the small-caps metadata voice a literary clock uses for its dateline.
    if is_tomorrow:
        chip = "TOMORROW"
        cw = text_width(draw, chip, title_font)
        ch = text_height(title_font)
        draw.rectangle((x0 - 4, y0 - 2, x0 + cw + 12, y0 + ch + 10), fill=ink)
        draw.text((x0 + 4, y0 + 3), chip, font=title_font, fill=style.bg)
    else:
        draw.text((x0, y0 + 3), "TODAY", font=title_font, fill=ink)
    parts = [f"{len(day_events)} EVENT" + ("S" if len(day_events) != 1 else "")]
    booked = booked_minutes(timed)
    if booked:
        parts.append(f"{fmt_duration(booked).upper()} BOOKED")
    nxt = next((e for e in timed if event_state(e, now) == "next"), None)
    if nxt is not None:
        parts.append(f"NEXT {fmt_time(nxt.start).upper()}")
    meta = " · ".join(parts)
    draw.text((x0 + w - text_width(draw, meta, meta_font), y0 + 14), meta, font=meta_font, fill=ink)

    strip_y = y0 + text_height(title_font) + 16
    _draw_schedule_strip(image, draw, day_events, day, now, style, x0=x0, y0=strip_y, w=w)

    rule_y = strip_y + STRIP_H + 6
    draw_bayer_rule(image, x0, rule_y, w, 3, mode)
    rows_y = rule_y + 12
    rows_h = h - (rows_y - y0)
    if rows_h <= 0:
        return

    if not day_events:
        empty_font = (style.font_title or style.font_bold)(22)
        msg = "Nothing scheduled"
        draw.text(
            (
                x0 + (w - text_width(draw, msg, empty_font)) // 2,
                rows_y + (rows_h - text_height(empty_font)) // 2,
            ),
            msg,
            font=empty_font,
            fill=ink,
        )
        return

    gaps = [gap_after(day_events, i) for i in range(len(day_events))]
    n_gaps = sum(1 for g in gaps if g is not None and g >= GAP_MIN_MINUTES)
    max_rows, row_h, time_w, time_pt, title_pt, show_loc, show_gaps = wide_metrics(
        len(day_events), n_gaps, rows_h
    )
    gap_h = GAP_ROW_H if show_gaps else 0
    # Fit rows plus the gap markers among them into the height on hand; the
    # last slot goes to "+N more" when the day runs past it.
    visible: list[CalendarEvent] = []
    used_h = 0
    for i, evt in enumerate(day_events):
        need = row_h + (gap_h if gaps[i] is not None and gaps[i] >= GAP_MIN_MINUTES else 0)
        if used_h + need > rows_h or len(visible) >= max_rows:
            break
        visible.append(evt)
        used_h += need
    overflow = len(day_events) - len(visible)
    if overflow and len(visible) > 1:
        visible = visible[:-1]
        overflow += 1

    next_up = next((e for e in visible if not e.is_all_day and event_state(e, now) == "next"), None)
    gap_font = style.font_medium(12)
    y = rows_y
    for i, event in enumerate(visible):
        _draw_wide_row(
            image,
            draw,
            event,
            event_state(event, now),
            style,
            x0=x0,
            y=y,
            w=w,
            row_h=row_h,
            time_w=time_w,
            time_pt=time_pt,
            title_pt=title_pt,
            show_location=show_loc,
            is_next=event is next_up,
        )
        y += row_h
        gap = gaps[i]
        last_visible = i == len(visible) - 1
        if (
            show_gaps
            and gap is not None
            and gap >= GAP_MIN_MINUTES
            and not (last_visible and overflow)
        ):
            label = f"{fmt_duration(gap)} free"
            lw = text_width(draw, label, gap_font)
            mid = y + gap_h // 2
            lx = x0 + time_w + 12
            draw.line([(lx, mid), (lx + 18, mid)], fill=ink, width=1)
            draw.text(
                (lx + 24, mid - text_height(gap_font) // 2 - 1), label, font=gap_font, fill=ink
            )
            draw.line([(lx + 30 + lw, mid), (x0 + w, mid)], fill=ink, width=1)
            y += gap_h

    if overflow:
        more_font = style.font_bold(title_pt)
        draw.text((x0 + time_w + 12, y + 2), f"+{overflow} more", font=more_font, fill=ink)


# ---------------------------------------------------------------------------
# Rail
# ---------------------------------------------------------------------------


class _Cursor:
    """A top-down flow down the rail; each cell asks for room before drawing."""

    def __init__(self, y: int, bottom: int):
        self.y = y
        self.bottom = bottom

    def take(self, needed: int) -> bool:
        return self.y + needed <= self.bottom

    def advance(self, used: int) -> None:
        self.y += used + _CELL_GAP


def _label(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    style: ThemeStyle,
    x: int,
    y: int,
    w: int,
) -> int:
    """Section label in the display face over a 3-px Bayer rule; returns height used."""
    font = (style.font_section_label or style.font_bold)(_LABEL_PT)
    draw.text((x, y), text, font=font, fill=_ink(image.mode))
    rule_y = y + text_height(font) + 6
    draw_bayer_rule(image, x, rule_y, w, 3, image.mode)
    return rule_y + 3 - y + 8


def forecast_rows(weather: WeatherData | None, today: date, limit: int) -> list:
    """The forecast days after *today*, soonest first, at most *limit*."""
    if weather is None:
        return []
    days = [fc for fc in weather.forecast if fc.date > today]
    return sorted(days, key=lambda fc: fc.date)[:limit]


def birthday_countdown(bday: Birthday, today: date) -> tuple[int, str]:
    """``(days_until, label)`` using the birthday bar's convention (Feb 29 → Feb 28)."""
    for year in (today.year, today.year + 1):
        try:
            when = bday.date.replace(year=year)
        except ValueError:
            when = date(year, 2, 28)
        if when >= today:
            break
    days_until = (when - today).days
    if days_until == 0:
        label = "Today!"
    elif days_until == 1:
        label = "Tomorrow"
    else:
        label = f"in {days_until}d"
    return days_until, label


def upcoming_birthdays(birthdays: list[Birthday], today: date, *, days: int, limit: int) -> list:
    """``(days_until, label, birthday)`` rows within *days*, soonest first."""
    rows = [(*birthday_countdown(b, today), b) for b in birthdays]
    rows = [r for r in rows if r[0] <= days]
    rows.sort(key=lambda r: (r[0], r[2].name))
    return rows[:limit]


def _draw_rail(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    next_day: date,
    rolled_over: bool,
    style: ThemeStyle,
    *,
    x0: int,
    y0: int,
    w: int,
    h: int,
) -> None:
    mode = image.mode
    ink = _ink(mode)
    cur = _Cursor(y0, y0 + h)
    weather = data.weather

    # --- Alerts: an inverted bar per alert, in the accent.
    alerts = weather.alerts if weather is not None else []
    if alerts:
        bar_font = style.font_bold(15)
        bar_h = text_height(bar_font) + 10
        for alert in alerts[:2]:
            if not cur.take(bar_h):
                break
            draw.rectangle((x0 - 6, cur.y, x0 + w, cur.y + bar_h), fill=_accent_red(mode))
            draw_text_truncated(
                draw,
                (x0 + 4, cur.y + 5),
                f"! {alert.event.upper()}",
                bar_font,
                w - 10,
                fill=style.bg,
            )
            cur.y += bar_h + 4
        cur.y += _CELL_GAP - 4

    # --- The next day's events.
    time_font = style.font_semibold(14)
    title_font = style.font_bold(16)
    row_h = 24
    label = "TOMORROW" if not rolled_over else next_day.strftime("%A").upper()
    if cur.take(24 + row_h):
        used = _label(image, draw, label, style, x0, cur.y, w)
        y = cur.y + used
        events = events_for_day(data.events, next_day)
        shown = events[:TOMORROW_MAX]
        if not shown:
            draw.text((x0, y), "Nothing scheduled", font=style.font_medium(15), fill=ink)
            y += row_h
        for evt in shown:
            start, _ = event_times(evt)
            draw.text((x0, y + 2), start, font=time_font, fill=ink)
            draw_text_truncated(draw, (x0 + 66, y), evt.summary, title_font, w - 66, fill=ink)
            y += row_h
        if len(events) > len(shown):
            draw.text((x0 + 66, y), f"+{len(events) - len(shown)} more", font=title_font, fill=ink)
            y += row_h
        cur.advance(y - cur.y)

    # --- Forecast.
    days = forecast_rows(weather, today, FORECAST_MAX)
    frow_h = 24
    if days and cur.take(24 + frow_h):
        used = _label(image, draw, "FORECAST", style, x0, cur.y, w)
        y = cur.y + used
        day_font = style.font_bold(15)
        temp_font = style.font_semibold(15)
        pct_font = style.font_medium(13)
        glyph_font = weather_icon(20)
        for fc in days:
            if not cur.take((y - cur.y) + frow_h):
                break
            draw.text((x0, y + 3), fc.date.strftime("%a").upper(), font=day_font, fill=ink)
            glyph = OWM_ICON_MAP.get(fc.icon, FALLBACK_ICON)
            gb = draw.textbbox((0, 0), glyph, font=glyph_font)
            draw.text(
                (x0 + 48 - gb[0], y + 13 - (gb[1] + gb[3]) // 2), glyph, font=glyph_font, fill=ink
            )
            temps = f"{fc.high:.0f}° / {fc.low:.0f}°"
            draw.text((x0 + 84, y + 3), temps, font=temp_font, fill=ink)
            if fc.precip_chance is not None:
                pct = f"{max(0.0, min(1.0, fc.precip_chance)) * 100:.0f}%"
                draw.text(
                    (x0 + w - text_width(draw, pct, pct_font), y + 5), pct, font=pct_font, fill=ink
                )
            y += frow_h
        cur.advance(y - cur.y)

    # --- Birthdays take what is left above the foot.
    rows = upcoming_birthdays(
        data.birthdays, today, days=BIRTHDAY_LOOKAHEAD_DAYS, limit=BIRTHDAY_MAX
    )
    brow_h = 22
    foot_top = y0 + h - FOOT_H
    room = foot_top - _CELL_GAP - cur.y
    if rows and room >= 34 + brow_h:
        used = _label(image, draw, "BIRTHDAYS", style, x0, cur.y, w)
        y = cur.y + used
        fits = max(1, (foot_top - _CELL_GAP - y) // brow_h)
        name_font = style.font_medium(15)
        soon_font = style.font_bold(15)
        for days_until, when, bday in rows[:fits]:
            text = f"{when} — {bday.name}"
            if bday.age is not None:
                text += f" ({bday.age})"
            font = soon_font if days_until <= 1 else name_font
            if days_until == 0:
                draw.rectangle((x0 - 6, y, x0 + w, y + brow_h - 2), fill=_accent_red(mode))
                draw_text_truncated(draw, (x0, y + 2), text, font, w, fill=style.bg)
            else:
                draw_text_truncated(draw, (x0, y + 2), text, font, w, fill=ink)
            y += brow_h

    # --- Foot: air quality beside the moon, anchored to the rail bottom.
    draw_bayer_rule(image, x0, foot_top, w, 3, mode)
    half = w // 2
    _draw_air_cell(image, draw, data.air_quality, style, x0, foot_top + 9, half - 8)
    _draw_moon_cell(image, draw, today, style, x0 + half + 8, foot_top + 9, w - half - 8)


def _draw_air_cell(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    air: AirQualityData | None,
    style: ThemeStyle,
    x: int,
    y: int,
    w: int,
) -> None:
    """``AIR`` caption, then the index numeral with its category beside it."""
    ink = _ink(image.mode)
    cap_font = (style.font_section_label or style.font_bold)(11)
    draw.text((x, y), "AIR", font=cap_font, fill=ink)
    y += text_height(cap_font) + 2
    if air is None:
        draw.text((x, y + 4), "No sensor", font=style.font_medium(13), fill=ink)
        return
    aqi_font = (style.font_title or style.font_bold)(26)
    aqi = str(air.aqi)
    ab = draw.textbbox((0, 0), aqi, font=aqi_font)
    fill = _accent_red(image.mode) if air.aqi >= 101 else ink
    draw.text((x - ab[0], y - ab[1]), aqi, font=aqi_font, fill=fill)
    tx = x + (ab[2] - ab[0]) + 8
    cat_font = style.font_semibold(12)
    draw_text_truncated(draw, (tx, y), air.category.upper(), cat_font, w - (tx - x), fill=ink)
    draw.text(
        (tx, y + text_height(cat_font) + 1),
        f"PM2.5 {air.pm25:.1f}",
        font=style.font_regular(11),
        fill=ink,
    )


def _draw_moon_cell(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    today: date,
    style: ThemeStyle,
    x: int,
    y: int,
    w: int,
) -> None:
    """``MOON`` caption, then the phase glyph with its name and illumination."""
    ink = _ink(image.mode)
    cap_font = (style.font_section_label or style.font_bold)(11)
    draw.text((x, y), "MOON", font=cap_font, fill=ink)
    y += text_height(cap_font) + 2
    glyph_font = weather_icon(26)
    glyph = moon_phase_glyph(today)
    gb = draw.textbbox((0, 0), glyph, font=glyph_font)
    draw.text((x - gb[0], y - gb[1]), glyph, font=glyph_font, fill=ink)
    tx = x + (gb[2] - gb[0]) + 8
    name_font = style.font_semibold(12)
    draw_text_truncated(
        draw, (tx, y), moon_phase_name(today).upper(), name_font, w - (tx - x), fill=ink
    )
    draw.text(
        (tx, y + text_height(name_font) + 1),
        f"{moon_illumination(today):.0f}% lit",
        font=style.font_regular(11),
        fill=ink,
    )
