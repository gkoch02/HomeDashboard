"""Split-plate weather engraving + agenda for the ``halftone_agenda`` theme.

``halftone`` gives its whole width to the engraving and squeezes the calendar
down to a single NEXT line; ``day_arc`` promotes the calendar by turning the
artwork into a time axis. This variant takes the third option: it cuts the
plate down the middle. The left pane keeps halftone's hero illustration with
the weather read-out beneath it, and the right pane is given entirely to
today's events.

Three parts:

  * **Left pane** (372 px) — the procedural weather scene from
    :func:`src.render.skyart.draw_weather_scene`, a 6-px ordered-Bayer rule,
    then a typeset band: temperature numeral, condition, high/low, sunrise and
    sunset, the date and the feels-like reading.
  * **Divider** (6 px) — a full-height vertical Bayer rule.
  * **Right pane** (422 px) — a TODAY header over as many event rows as the
    pane can set at a legible size, with an "updated" caption in the bottom
    corner.

The scene is drawn at ``SCENE_SCALE`` into a rect roughly half of halftone's
width. ``draw_weather_scene`` maps its placements onto whatever rect it is
handed and takes element sizes from that scale separately, so the composition
survives the narrower, nearly-square pane instead of simply shrinking.

The agenda is a plain list: every row is set the same way and carries its
event's start and end time. It began with ``day_arc``'s state encoding —
elapsed rows Bayer-perforated, the event in progress inverted into a solid
bar, the next one up accented — and all three were removed, because each
depends on a large or dithered area of ink surviving the panel and none of
them does under partial refresh. Waveshare's fast waveform leaves a filled bar
reading as charcoal and a screened row as mud, and partial refresh is worth
keeping for its speed. After dark, once every timed event has ended, the pane
still rolls over to tomorrow, now behind a plain TOMORROW dateline.

No external assets — every illustration is generated from PIL primitives.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo

from PIL import Image, ImageDraw, ImageFont

from src.data.models import CalendarEvent, DashboardData, WeatherData
from src.render.artkit import ink as _ink
from src.render.artkit import to_local_naive

# The after-dark rollover is shared with ``day_arc`` rather than re-derived:
# both themes decide "is today spent?" against the same clock, and a second
# copy of the rule would be free to drift out of agreement with the first.
from src.render.components.day_arc_panel import agenda_day
from src.render.fonts import weather_icon
from src.render.primitives import (
    content_time,
    draw_text_truncated,
    events_for_day,
    fmt_time,
    text_height,
    text_width,
    wrap_lines,
)
from src.render.quantize import _BAYER_4X4
from src.render.skyart import draw_bayer_rule, draw_weather_scene, harden_typeset
from src.render.theme import ComponentRegion, ThemeStyle

# Weather Icons glyphs — Righteous has no sunrise/sunset marks of its own.
_SUNRISE_GLYPH = ""  # wi-sunrise
_SUNSET_GLYPH = ""  # wi-sunset

# ---------------------------------------------------------------------------
# Region geometry
# ---------------------------------------------------------------------------

ART_W = 372  # left pane: illustration + weather band
DIVIDER_W = 6  # full-height vertical Bayer rule
AGENDA_X = ART_W + DIVIDER_W  # 378 — right pane starts here

HERO_H = 292  # illustration height inside the left pane
RULE_H = 6  # horizontal Bayer rule under the illustration
BAND_Y = HERO_H + RULE_H  # 298 — weather band top

ART_PAD_X = 18
AGENDA_PAD_X = 20
FOOTER_H = 22  # bottom strip of the agenda pane, for the "updated" caption

# Element sizes for the weather scene, as a fraction of halftone's hero. The
# pane is 47% as wide but 99% as tall, so scaling by width alone would leave a
# stranded little sun in a large square; 0.72 fills the pane while keeping the
# widest assemblies (three-cloud overcast, the partly-cloudy sun-plus-cloud
# pair) inside its edges.
SCENE_SCALE = 0.72

# Weather band rows, as offsets from the band top. The band is 182 px tall;
# each row owns its slice outright so a three-digit temperature or a wrapped
# two-line condition can't push into the row beneath it.
_TEMP_ZONE_Y = 6
_TEMP_ZONE_H = 92
_BAND_RULE_Y = 100
_SUN_ROW_Y = 106
_SUN_ROW_H = 36
_DATE_ROW_Y = 144
_DATE_ROW_H = 32

# Fixed reservation for the temperature numeral, so the condition column keeps
# its width whether the reading is "8°" or "108°". Same trick as halftone's
# TEMP_COL_W, at this pane's smaller display size.
#
# The sizes below are the largest the band will take. 78 pt sets "108°" at
# 153 px, which leaves the condition column 165 px — just enough for the widest
# OWM phrase ("heavy intensity rain") to wrap the way it does now, as
# "HEAVY INTENSITY / RAIN". At 82 pt it breaks as "HEAVY / INTENSITY RAIN" and
# at 86 pt it needs three lines, which overruns the zone. The column reserves
# 8 px past the numeral so a 3-digit reading never crowds the stack.
TEMP_PT = 78
TEMP_COL_W = 161
TEMP_COL_GAP = 10
# Condition and high/low, sized to match the numeral they sit beside.
COND_PT = 19
HIGH_LOW_PT = 21

# Density tiers for the agenda column: (max_rows, row_h, time_w, time_pt,
# title_pt, show_location). Tuned for this pane — 382 px of content width and
# ~400 px of height, which is half as wide and half again as tall as day_arc's
# agenda, so the tiers run to more rows before the type has to shrink.
_DENSITY_TIERS: tuple[tuple[int, int, int, int, int, bool], ...] = (
    (2, 76, 100, 22, 30, True),
    (4, 64, 92, 20, 26, True),
    (6, 52, 84, 18, 22, True),
    (8, 42, 76, 16, 19, False),
    (11, 33, 68, 14, 17, False),
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_halftone_agenda(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full ``halftone_agenda`` plate into *region* of *image*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        # The production caller (``canvas.render_dashboard``) always passes the
        # backing image via ``RenderContext.image``. This branch only fires for
        # tests that build an ``ImageDraw.Draw`` directly without forwarding
        # the image — fall back to the private attribute rather than crashing.
        image = draw._image  # type: ignore[attr-defined]

    mode = image.mode
    x0, y0, w, h = region.x, region.y, region.w, region.h
    tz = now.tzinfo
    now_naive = to_local_naive(now, tz)
    # OWM hands back aware sun times while events are already naive local;
    # normalise once here so nothing downstream compares the two kinds.
    sunrise, sunset = _sun_times(data.weather, tz)

    art_w = min(ART_W, max(1, w - DIVIDER_W))
    hero_h = min(HERO_H, h)
    band_y = y0 + BAND_Y
    band_h = max(0, h - BAND_Y)

    # --- Left pane: illustration, rule, weather band.
    icon = data.weather.current_icon if data.weather is not None else None
    draw_weather_scene(
        image,
        (x0, y0, x0 + art_w, y0 + hero_h),
        icon,
        today,
        scale=SCENE_SCALE,
    )
    draw_bayer_rule(image, x0, y0 + HERO_H, art_w, RULE_H, mode)
    if band_h > 0:
        _draw_weather_band(
            draw,
            image,
            data.weather,
            today,
            style,
            x0=x0,
            y0=band_y,
            w=art_w,
            h=band_h,
            sunrise=sunrise,
            sunset=sunset,
        )

    # --- Divider: one vertical rule down the whole plate.
    draw_bayer_rule(image, x0 + art_w, y0, DIVIDER_W, h, mode, orientation="vertical")

    # --- Right pane: paper field, then the agenda over it. The underlay is
    # solid so Floyd-Steinberg has nothing to diffuse into the small type.
    pane_x = x0 + art_w + DIVIDER_W
    pane_w = max(0, w - art_w - DIVIDER_W)
    if pane_w <= 0:
        return
    paper = Image.new("L", (pane_w, h), 255)
    if mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (pane_x, y0))

    day, is_tomorrow = agenda_day(data.events, today, now_naive, sunset)
    _draw_agenda_pane(
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

    # --- "updated HH:MM am" caption in the bottom corner of the agenda pane.
    ink = _ink(mode)
    footer_font = style.font_medium(16)
    stamp = f"updated {_clock(to_local_naive(content_time(data, now), tz)).lower()}"
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

    # Both typeset regions are solid ink on solid paper, so snap them to pure
    # black and white before the backend's Floyd-Steinberg pass gets to them.
    # Left to dither, the antialiased glyph edges come off the panel ragged and
    # the white type in the in-progress bar erodes the bar around it. The
    # illustration above is untouched and still dithers — that is the point of
    # the theme.
    if band_h > 0:
        harden_typeset(image, (x0, band_y, art_w, band_h))
    harden_typeset(image, (pane_x, y0, pane_w, h))


# ---------------------------------------------------------------------------
# Left pane — typeset weather band
# ---------------------------------------------------------------------------


def _fmt_temp(value: float | None) -> str:
    return "—" if value is None else f"{int(round(value))}°"


def _clock(dt: datetime) -> str:
    """Full am/pm clock string, e.g. ``6:24 AM``.

    The band uses this rather than :func:`src.render.primitives.fmt_time` (the
    compact ``6:24a`` the agenda rows use) because it has the room, and because
    the sun times read as an almanac line here — the same call halftone makes
    for the row this band descends from.
    """
    return dt.strftime("%-I:%M %p").lstrip("0")


def _sun_times(
    weather: WeatherData | None,
    tz: tzinfo | None,
) -> tuple[datetime | None, datetime | None]:
    """Today's sunrise/sunset as naive local datetimes, or ``None`` when absent."""
    if weather is None:
        return (None, None)
    rise = to_local_naive(weather.sunrise, tz) if weather.sunrise is not None else None
    down = to_local_naive(weather.sunset, tz) if weather.sunset is not None else None
    return (rise, down)


def _draw_weather_band(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    weather: WeatherData | None,
    today: date,
    style: ThemeStyle,
    *,
    x0: int,
    y0: int,
    w: int,
    h: int,
    sunrise: datetime | None,
    sunset: datetime | None,
) -> None:
    """Paint the typeset weather read-out under the illustration.

    ┌────────────────────────────────┐
    │        PARTLY CLOUDY           │
    │  74°   H 76°  ·  L 63°         │
    │ ·············(hairline)······· │
    │  ☀ 6:24 AM        ☼ 7:51 PM    │
    │  MON · APR 6 · 2026   FEELS 71°│
    └────────────────────────────────┘
    """
    mode = image.mode

    # Clean paper under the whole band so the dithered scene above never bleeds
    # into the type. Every glyph below is drawn in solid ink: mid-grey text is
    # destroyed by Floyd-Steinberg, so hierarchy comes from size, not tone.
    paper = Image.new("L", (w, h), 255)
    if mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x0, y0))
    ink = _ink(mode)

    left = x0 + ART_PAD_X
    right = x0 + w - ART_PAD_X

    # --- Temperature numeral, centred in its fixed-width column.
    temp_font = (style.font_title or style.font_bold)(TEMP_PT)
    temp_text = _fmt_temp(weather.current_temp if weather else None)
    tb = draw.textbbox((0, 0), temp_text, font=temp_font)
    temp_w = tb[2] - tb[0]
    zone_top = y0 + _TEMP_ZONE_Y
    zone_mid = zone_top + _TEMP_ZONE_H // 2
    draw.text(
        (
            left + (TEMP_COL_W - temp_w) // 2 - tb[0],
            zone_mid - (tb[3] - tb[1]) // 2 - tb[1],
        ),
        temp_text,
        font=temp_font,
        fill=ink,
    )

    # --- Condition + high/low, stacked beside the numeral and centred on the
    # same midline. The condition wraps to a second line rather than being
    # truncated: the OWM phrases that overrun this column ("heavy intensity
    # rain") are exactly the ones worth reading in full.
    stack_x = left + TEMP_COL_W + TEMP_COL_GAP
    stack_w = max(20, right - stack_x)
    cond_font = (style.font_section_label or style.font_bold)(COND_PT)
    hl_font = style.font_semibold(HIGH_LOW_PT)

    lines: list[tuple[str, ImageFont.FreeTypeFont]] = []
    if weather is not None:
        if weather.current_description:
            wrapped = wrap_lines(weather.current_description.upper(), cond_font, stack_w)
            if len(wrapped) > 2:
                # Fold the overflow into the second line rather than dropping
                # it: draw_text_truncated then ellipsizes, so a phrase like
                # "thunderstorm with light drizzle" reads as cut off instead of
                # as a complete but wrong "THUNDERSTORM WITH LIGHT".
                wrapped = [wrapped[0], " ".join(wrapped[1:])]
            for line in wrapped:
                lines.append((line, cond_font))
        lines.append((f"H {_fmt_temp(weather.high)}  ·  L {_fmt_temp(weather.low)}", hl_font))
    else:
        lines.append(("AWAITING", cond_font))
        lines.append(("WEATHER DATA", cond_font))

    measured = [(text, font, draw.textbbox((0, 0), text, font=font)) for text, font in lines]
    line_gap = 6
    stack_h = sum(bb[3] - bb[1] for _, _, bb in measured) + line_gap * (len(measured) - 1)
    cursor_y = zone_mid - stack_h // 2
    for text, font, bb in measured:
        draw_text_truncated(draw, (stack_x, cursor_y - bb[1]), text, font, stack_w, fill=ink)
        cursor_y += (bb[3] - bb[1]) + line_gap

    # --- Hairline between the headline block and the almanac rows.
    _draw_hairline(image, left, y0 + _BAND_RULE_Y, right - left, mode)

    # --- Sunrise on the left, sunset against the right margin.
    sun_mid = y0 + _SUN_ROW_Y + _SUN_ROW_H // 2
    time_font = style.font_semibold(18)
    glyph_font = weather_icon(24)
    if sunrise is not None:
        _draw_glyph_time(
            draw, _SUNRISE_GLYPH, glyph_font, _clock(sunrise), time_font, left, sun_mid, ink
        )
    if sunset is not None:
        pair_w = (
            text_width(draw, _SUNSET_GLYPH, glyph_font)
            + 6
            + text_width(draw, _clock(sunset), time_font)
        )
        _draw_glyph_time(
            draw, _SUNSET_GLYPH, glyph_font, _clock(sunset), time_font, right - pair_w, sun_mid, ink
        )

    # --- Date on the left, feels-like against the right margin.
    date_mid = y0 + _DATE_ROW_Y + _DATE_ROW_H // 2
    date_font = (style.font_section_label or style.font_bold)(18)
    date_text = today.strftime("%a · %b %-d · %Y").upper()
    db = draw.textbbox((0, 0), date_text, font=date_font)
    draw.text(
        (left - db[0], date_mid - (db[3] - db[1]) // 2 - db[1]), date_text, font=date_font, fill=ink
    )

    if weather is not None and weather.feels_like is not None:
        feels_font = style.font_regular(15)
        feels_text = f"FEELS {_fmt_temp(weather.feels_like)}"
        fb = draw.textbbox((0, 0), feels_text, font=feels_font)
        draw.text(
            (right - (fb[2] - fb[0]) - fb[0], date_mid - (fb[3] - fb[1]) // 2 - fb[1]),
            feels_text,
            font=feels_font,
            fill=ink,
        )


def _draw_glyph_time(
    draw: ImageDraw.ImageDraw,
    glyph: str,
    glyph_font: ImageFont.FreeTypeFont,
    label: str,
    label_font: ImageFont.FreeTypeFont,
    x: float,
    mid_y: int,
    ink: int | tuple[int, int, int],
) -> None:
    """Draw *glyph* then *label*, both centred on the *mid_y* midline.

    The two faces have unrelated metrics, so each is placed off its own visible
    bounding box instead of a shared baseline — otherwise the Weather Icons
    glyph sits visibly low against Righteous digits.
    """
    for text, font in ((glyph, glyph_font), (label, label_font)):
        bb = draw.textbbox((0, 0), text, font=font)
        draw.text((x - bb[0], mid_y - (bb[1] + bb[3]) // 2), text, font=font, fill=ink)
        x += (bb[2] - bb[0]) + 6


def _draw_hairline(image: Image.Image, x0: int, y: int, w: int, mode: str) -> None:
    """Single-row dotted rule, matching the plate's Bayer motif at hairline weight."""
    on = _ink(mode)
    px = image.load()
    assert px is not None
    for xx in range(w):
        if _BAYER_4X4[0][xx & 3] < 128:
            px[x0 + xx, y] = on


# ---------------------------------------------------------------------------
# Right pane — agenda
# ---------------------------------------------------------------------------


def agenda_metrics(n_events: int, avail_h: int) -> tuple[int, int, int, int, int, bool]:
    """Pick the roomiest density tier that shows *n_events* within *avail_h*.

    Capacity is tested against the height actually on hand rather than the
    tier's nominal ``max_rows``, so a tier whose rows overrun the pane can't
    collapse a four-event day into two rows plus "+2 more".
    """
    for tier in _DENSITY_TIERS:
        if min(tier[0], avail_h // max(1, tier[1])) >= n_events:
            return tier
    return _DENSITY_TIERS[-1]


def event_times(event: CalendarEvent) -> tuple[str, str | None]:
    """Return ``(start, end)`` labels for *event*; *end* is None when unusable.

    An all-day event has no clock times to show, and a timed event running past
    midnight would read as ending before it starts, so both fall back to a
    single label.
    """
    if event.is_all_day:
        return ("ALL DAY", None)
    start = _strip_tz(event.start)
    end = _strip_tz(event.end)
    if end <= start or end.date() != start.date():
        return (fmt_time(start), None)
    return (fmt_time(start), fmt_time(end))


def _strip_tz(dt: datetime) -> datetime:
    """Drop tzinfo without converting — event times are already naive local."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _location_text(event: CalendarEvent) -> str:
    """First comma-segment of the location, whitespace-collapsed."""
    if not event.location:
        return ""
    return " ".join(event.location.split(",")[0].split())


def two_line_time_fits(time_pt: int, row_h: int) -> bool:
    """Can a row set the start and end times on two lines?

    Line two sits one pixel under line one, and the pair has to clear the row.
    True for every tier but the densest, whose 33-px rows are 4 px short.
    """
    return 2 * time_pt + 7 <= row_h - 2


def _draw_time_cell(
    draw: ImageDraw.ImageDraw,
    start: str,
    end: str | None,
    style: ThemeStyle,
    *,
    x0: int,
    y: int,
    time_pt: int,
    row_h: int,
    fill: int | tuple[int, int, int],
) -> None:
    """Draw the start time, with the end time stacked underneath it.

    Stacking rather than setting a range inline is what keeps the treatment
    uniform: an inline range's width depends on the times themselves — a
    meridiem-crossing pair like "11:30a-1:15p" is half again as wide as
    "12:30-2p" — so some rows would show an end time and their neighbours
    wouldn't, at the same density. Stacked, the cell is never wider than one
    label, which every tier's column already fits, and the only question left
    is vertical room. The densest tier has none and drops the end time; see
    :func:`two_line_time_fits`.
    """
    time_font = style.font_semibold(time_pt)
    if end is None or not two_line_time_fits(time_pt, row_h):
        draw.text((x0, y + 4), start, font=time_font, fill=fill)
        return
    # The trailing dash carries the eye down to the second line.
    draw.text((x0, y + 4), f"{start} –", font=time_font, fill=fill)
    draw.text((x0, y + 5 + time_pt), end, font=time_font, fill=fill)


def _draw_event_row(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    event: CalendarEvent,
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
) -> None:
    """Draw one agenda row. Every row is set identically.

    The pane used to encode event state in the rendering — the event in
    progress inverted into a solid bar, elapsed rows perforated on a Bayer
    lattice, the next one up accented. All three depended on large or dithered
    areas of ink surviving the panel, and under partial refresh they don't:
    Waveshare's fast waveform leaves a filled bar reading as charcoal and a
    screened row as mud. The pane is now just the day's list, which costs
    nothing on a fast refresh.
    """
    mode = image.mode
    ink = _ink(mode)
    # One weight heavier than the role each of these fills. See the theme
    # module: at these sizes DM Sans at its nominal weight lays down noticeably
    # less ink than the Righteous in the weather pane, and on a panel that
    # reads as grey text rather than as lighter text.
    title_font = style.font_bold(title_pt)
    loc_font = style.font_medium(max(12, time_pt - 2))

    start_str, end_str = event_times(event)
    title_x = x0 + time_w + 12
    title_w = max(20, w - (time_w + 12))
    # The tick brackets the row's *type*, not its pitch: the roomiest tier sets
    # 76-px rows so a two-event day breathes, and a rule drawn to the full row
    # height there would read as a column divider rather than an event mark.
    content_h = text_height(title_font) + (text_height(loc_font) + 2 if show_location else 0)
    tick = (x0 + time_w, y + 2, x0 + time_w + 3, y + 2 + content_h + 4)

    _draw_time_cell(
        draw,
        start_str,
        end_str,
        style,
        x0=x0,
        y=y,
        time_pt=time_pt,
        row_h=row_h,
        fill=ink,
    )
    # Filled for a timed event, outlined for an all-day one — a property of the
    # event, not of where the clock happens to be.
    if event.is_all_day:
        draw.rectangle(tick, outline=ink)
    else:
        draw.rectangle(tick, fill=ink)
    used = draw_text_truncated(draw, (title_x, y + 2), event.summary, title_font, title_w, fill=ink)
    if show_location and used:
        location = _location_text(event)
        if location:
            draw_text_truncated(
                draw,
                (title_x, y + 4 + text_height(title_font)),
                location,
                loc_font,
                title_w,
                fill=ink,
            )


def _draw_agenda_pane(
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
    """Header, rule and event rows for the right pane."""
    mode = image.mode
    ink = _ink(mode)
    title_font = (style.font_title or style.font_bold)(26)
    count_font = style.font_semibold(14)

    day_events = events_for_day(events, day)

    # Header. A rolled-over agenda gets an inverted TOMORROW chip so it can
    # never be misread as today's.
    # Plain type, not an inverted chip: a filled block is the first thing a
    # fast-waveform refresh washes out, and the pane no longer uses fills.
    draw.text(
        (x0, y0 + 3),
        "TOMORROW" if is_tomorrow else "TODAY",
        font=title_font,
        fill=ink,
    )

    count = f"{len(day_events)} EVENT" + ("S" if len(day_events) != 1 else "")
    draw.text(
        (x0 + w - text_width(draw, count, count_font), y0 + 14),
        count,
        font=count_font,
        fill=ink,
    )

    rule_y = y0 + text_height(title_font) + 16
    draw_bayer_rule(image, x0, rule_y, w, 3, mode)

    rows_y = rule_y + 14
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

    max_rows, row_h, time_w, time_pt, title_pt, show_loc = agenda_metrics(len(day_events), rows_h)
    # The tier sets the type size; the row count comes from the space actually
    # on hand, so an overrunning tier can't push "+N more" into the footer.
    fits = max(1, min(max_rows, rows_h // row_h))
    if len(day_events) > fits:
        # Give the last slot to the "+N more" line rather than a truncated row.
        visible = day_events[: max(1, fits - 1)]
    else:
        visible = day_events
    overflow = len(day_events) - len(visible)

    # Rows start under the rule and run down, at the tier's own pitch. Row
    # heights are sized to their type rather than stretched to fill the pane,
    # so a light day reads as a short list with the day's remaining space below
    # it — centring it instead left two events floating in the middle of the
    # pane with gaps above and below that looked like a layout fault.
    y = rows_y
    for event in visible:
        _draw_event_row(
            image,
            draw,
            event,
            style,
            x0=x0,
            y=y,
            w=w,
            row_h=row_h,
            time_w=time_w,
            time_pt=time_pt,
            title_pt=title_pt,
            show_location=show_loc,
        )
        y += row_h

    if overflow:
        # Plain ink at row weight. Screening it the way an elapsed row is
        # screened made it the faintest thing on the plate: a past row at least
        # has its neighbours to read against, while this line sits alone under
        # the last row with nothing around it. It is the one line that says the
        # day continues past what is shown, so it has to survive the panel.
        more_font = style.font_bold(title_pt)
        draw.text(
            (x0 + time_w + 12, y + 2),
            f"+{overflow} more",
            font=more_font,
            fill=_ink(image.mode),
        )
