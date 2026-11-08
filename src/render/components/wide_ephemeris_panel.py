"""wide_ephemeris_panel.py — HomeDashboardTV's Ephemeris, set for the 1360x480 strip.

Ephemeris is the TV app's "what is ahead" plate in Seneschal's HUD dress: gold on
a dark ground, tracked caps, slab panels with one bevelled corner, and
the lit colour meaning one thing — what is under way now. This is that plate
re-cut for a strip three times as wide as it is tall, top to bottom:

  * **Header** — the EPHEMERIS wordmark over a gold rule running off the left
    edge, the check line (every source current, or which are stale) with the
    content's time, and the date.
  * **The day ahead** — the next day as a strip, an hour back and twenty-three
    ahead: the forecast temperature as a trace with its readings, the chance of
    rain as hatched bars beneath, the daylight as a lit band along the axis, the
    hours, and every timed event as a panel in one of two lanes. A gold line and
    the gold segment of the band stand at the current hour.
  * **Agenda / Conditions / Outlook** — what is on next as a column of slabs
    (birthdays in the fortnight among them), the weather now with any alert and
    four readings, and three days of outlook.

Type is sized for the panel, not the TV: the TV is read from across a room at
1080p, this plate from about a metre at 133 ppi, where the TV's 600-weight
condensed Saira sets 2-px stems and its small caps 1-px ones. So no type is
set below ``MIN_TYPE``, every face is Saira at 800 (900 on the dark plate,
whose white strokes the panel's black ink spreads into) and width 85, and the
plate shows fewer things larger: five agenda rows, four readings, three days.

Inks: on a colour panel the gold is yellow and the TV's blue becomes white; any
alert is red. On monochrome every accent is white, and the two lit states —
the event under way and an alert — become solid white slabs with black type,
so they still read as the loudest things on the plate.

Everything is a pure ink: type is set with ``fontmode = "1"`` and the only
tones are 1-px dotted rules and hatched rain, so the colour panel's ink snap
and the monochrome threshold are the identity at native size.

The strip is anchored to the clock hour holding *now*, not to *now*: the
window, the trace and the gold marker step once an hour, so an idle tick
renders byte-identically and the theme stays out of ``TIME_DRIVEN``. The
"synced" time reads ``content_time()``. Event states (under way, next) read
*now*, so they move at event boundaries, as ``wide_week``'s NOW/NEXT do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from PIL import ImageDraw, ImageFont

from src.data.models import Birthday, CalendarEvent, DashboardData, StalenessLevel, WeatherData
from src.render import fonts
from src.render.artkit import to_local_naive
from src.render.components.wide_horizon_panel import altitude_fn, sun_zone
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_illumination, moon_phase_name
from src.render.primitives import (
    content_time,
    deg_to_compass,
    fmt_time,
    next_birthday,
    round_temp,
    truncate_to_width,
    wind_unit,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_RED, INKY_YELLOW, ComponentRegion, ThemeStyle

Fill = int | tuple[int, int, int]
Poly = list[tuple[float, float]]

# Geometry, relative to the region's origin; the plate is drawn for 1360x480.

MARGIN = 24
HEADER_H = 52  # the bridge rule sits on this line
BEVEL = 6  # the cut corner on every slab

STRIP_LABEL_Y = 72  # baseline of "THE DAY AHEAD"
TRACE_TOP = 106  # the warmest reading's point; its label sits above
TRACE_BOTTOM = 146
RAIN_BOTTOM = 164  # rain bars stand on this line, under the trace
RAIN_MAX_H = 16
AXIS_Y = 168  # the daylight band is centred on this line
HOUR_LABEL_Y = 190  # baseline
LANE_TOP = 198
LANE_H = 30
LANE_GAP = 4
LANES = 2
STRIP_BOTTOM = LANE_TOP + LANES * LANE_H + (LANES - 1) * LANE_GAP

SECTION_Y = 288  # baseline of the three column labels
COLUMN_TOP = 300
COLUMN_BOTTOM = 472

AGENDA_W = 452
CONDITIONS_W = 412
COLUMN_GAP = 24
ROW_H = 30
ROW_PITCH = 35

WINDOW_LEAD_HOURS = 1  # the strip keeps this much behind the current hour
WINDOW_HOURS = 24
# A slot below this chance of rain draws no bar.
RAIN_MIN_CHANCE = 0.1
# The smallest temperature span the trace's band represents: a flat day stays flat.
MIN_TEMP_SPAN = 12.0
# The fewest pixels between hour labels.
MIN_HOUR_LABEL_SPACING = 100
# Birthdays this many days out join the agenda.
BIRTHDAY_HORIZON_DAYS = 14
# The outlook's cards: as many as fit at this width, at most this many.
MIN_CARD_W = 120
MAX_CARDS = 3
CARD_GAP = 8
TILE_GAP = 6
TILE_H = 30
# The conditions grid: two readings to a row, two rows.
MAX_READINGS = 4

# Read from about a metre on a 133-ppi panel, so no type is set below
# ``MIN_TYPE`` px (Saira caps about 2.3 mm tall, ``wide_horizon``'s floor) and
# every face is Saira at weight 800 or 900 and width 85: a 3-px stem from 18 px,
# 4 px from 22. The TV's 600-weight condensed faces set 2-px stems, and the
# small caps a 1-px stem, which do not read at that distance.
MIN_TYPE = 15
TYPE_WIDTH = 85
# The tracking of the small caps, as a fraction of their size.
TRACK = 0.08
SOLAR_HORIZON_DEG = -0.833


@dataclass(frozen=True)
class Inks:
    """The plate's inks in the canvas's mode.

    Gold plays two parts: ``gold`` fills (the lit slab, the rule, the hour's
    band) and ``gold_ink`` sets type and thin marks. They differ on the light
    plate, where yellow type on paper does not read: there the gold is only
    ever a fill, and ``now_column`` is the yellow column standing behind the
    strip at the current hour in place of the gold line.
    """

    ground: Fill
    text: Fill
    gold: Fill
    gold_ink: Fill
    on_gold: Fill  # type set on a gold fill
    red: Fill
    colour: bool
    now_column: Fill | None = None
    # Saira's weight on this ground: black ink spreads into white strokes on a
    # reflective panel, so type knocked out of the dark plate is set heavier.
    weight: int = 800


def inks_for(mode: str, light: bool = False) -> Inks:
    """The inks for *mode*: on monochrome every accent is ``text``."""
    if mode == "RGB":
        black, white = (0, 0, 0), (255, 255, 255)
        yellow = INKY_SPECTRA6_PALETTE[INKY_YELLOW]
        red = INKY_SPECTRA6_PALETTE[INKY_RED]
        if light:
            return Inks(
                white, black, yellow, black, black, red, True, now_column=yellow, weight=800
            )
        return Inks(black, white, yellow, yellow, black, red, True, weight=900)
    paper = 1 if mode == "1" else 255
    ground, text = (paper, 0) if light else (0, paper)
    return Inks(ground, text, text, text, ground, text, False, weight=800 if light else 900)


# Type


def _face(size: int, ink: Inks) -> ImageFont.FreeTypeFont:
    """Saira at *size* in the plate's weight; never below ``MIN_TYPE``."""
    return fonts.saira(max(size, MIN_TYPE), ink.weight, TYPE_WIDTH)


def tracked_width(draw: ImageDraw.ImageDraw, text: str, font, tracking: float = TRACK) -> float:
    """Width of *text* set with *tracking* (a fraction of the font size) between letters."""
    if not text:
        return 0.0
    gap = font.size * tracking
    return sum(draw.textlength(ch, font=font) for ch in text) + gap * (len(text) - 1)


def draw_tracked(
    draw: ImageDraw.ImageDraw,
    x: float,
    baseline: float,
    text: str,
    font,
    fill: Fill,
    *,
    tracking: float = TRACK,
    align: str = "left",
) -> float:
    """Set *text* letter-spaced on *baseline*; returns its width."""
    width = tracked_width(draw, text, font, tracking)
    if align == "right":
        x -= width
    elif align == "center":
        x -= width / 2
    gap = font.size * tracking
    for ch in text:
        draw.text((x, baseline), ch, font=font, fill=fill, anchor="ls")
        x += draw.textlength(ch, font=font) + gap
    return width


def _clock(dt: datetime) -> str:
    """'9:00 AM' — the TV's long clock form, for captions."""
    return dt.strftime("%-I:%M %p")


def _short(dt: datetime) -> str:
    """'9A', '11:30A' — the agenda's compact time."""
    return fmt_time(dt).upper()


# Lines and slabs


def dotted_hline(draw: ImageDraw.ImageDraw, y: int, x0: int, x1: int, fill: Fill) -> None:
    """A 1-px rule with every other pixel set: the TV's dim hairline in pure ink."""
    for x in range(int(x0), int(x1) + 1, 2):
        draw.point((x, y), fill=fill)


def slab_polygon(x0: float, y0: float, x1: float, y1: float, bevel: int = BEVEL) -> Poly:
    """A slab's outline with its bottom-right corner cut."""
    b = min(bevel, (x1 - x0) / 2, (y1 - y0) / 2)
    return [(x0, y0), (x1, y0), (x1, y1 - b), (x1 - b, y1), (x0, y1)]


def _dotted_poly(draw: ImageDraw.ImageDraw, poly: Poly, fill: Fill) -> None:
    """Every other pixel of the closed outline *poly*, phased to the canvas."""
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1], strict=True):
        steps = int(max(abs(bx - ax), abs(by - ay)))
        for i in range(steps + 1):
            x = round(ax + (bx - ax) * i / max(steps, 1))
            y = round(ay + (by - ay) * i / max(steps, 1))
            if (x + y) % 2 == 0:
                draw.point((x, y), fill=fill)


def draw_slab(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    ink: Inks,
    tone: str,
) -> Fill:
    """Draw a slab in *tone* and return the ink its type is set in.

    ``lit`` is a solid gold slab (under way now); ``next`` a solid outline with a
    gold edge on the left; ``alert`` a red outline, or a solid slab on
    monochrome; ``dim`` a dotted outline.
    """
    x0, y0, x1, y1 = box
    poly = slab_polygon(x0, y0, x1, y1)
    if tone == "lit":
        # Outlined where the column at now is the same yellow, or the slab merges with it.
        draw.polygon(poly, fill=ink.gold, outline=ink.text if ink.now_column else None)
        return ink.on_gold
    # Every other slab is filled with ground, so the gold line at now passes behind it.
    draw.polygon(poly, fill=ink.ground)
    if tone == "alert":
        if ink.colour:
            draw.polygon(poly, outline=ink.red)
            draw.rectangle((x0, y0, x0 + 2, y1), fill=ink.red)
            return ink.red
        draw.polygon(poly, fill=ink.text)
        return ink.ground
    if tone == "next":
        draw.polygon(poly, outline=ink.text)
        draw.rectangle((x0, y0, x0 + 3, y1), fill=ink.gold)
        return ink.text
    _dotted_poly(draw, poly, ink.text)
    return ink.text


def draw_section_label(
    draw: ImageDraw.ImageDraw, x: float, x1: float, label: str, note: str, ink: Inks
) -> None:
    """A column head: a short run, the label in tracked caps, and a note at the right."""
    font = _face(17, ink)
    draw.line((x, SECTION_Y - 6, x + 12, SECTION_Y - 6), fill=ink.text, width=3)
    draw_tracked(draw, x + 22, SECTION_Y, label, font, ink.text, tracking=0.18)
    if note:
        draw_tracked(draw, x1, SECTION_Y, note, _face(16, ink), ink.text, align="right")


# Small marks, drawn rather than set: the icon fonts have no HUD-weight versions.


def _calendar_mark(draw: ImageDraw.ImageDraw, x: float, y: float, fill: Fill) -> None:
    draw.rectangle((x, y + 1, x + 13, y + 13), outline=fill)
    draw.rectangle((x, y + 1, x + 13, y + 4), fill=fill)
    for cx in (x + 4, x + 7, x + 10):
        for cy in (y + 7, y + 10):
            draw.point((cx, cy), fill=fill)


def _gift_mark(draw: ImageDraw.ImageDraw, x: float, y: float, fill: Fill) -> None:
    draw.rectangle((x + 1, y + 6, x + 12, y + 13), outline=fill)
    draw.rectangle((x, y + 3, x + 13, y + 6), outline=fill)
    draw.line((x + 6, y + 3, x + 6, y + 13), fill=fill)
    draw.line((x + 7, y + 3, x + 7, y + 13), fill=fill)
    draw.line((x + 3, y, x + 6, y + 3), fill=fill)
    draw.line((x + 10, y, x + 7, y + 3), fill=fill)


def _check_mark(draw: ImageDraw.ImageDraw, cx: float, cy: float, fill: Fill) -> None:
    r = 8
    hexagon = [(cx - r, cy), (cx - r / 2, cy - r), (cx + r / 2, cy - r)]
    hexagon += [(cx + r, cy), (cx + r / 2, cy + r), (cx - r / 2, cy + r)]
    draw.polygon(hexagon, outline=fill)
    draw.line([(cx - 4, cy), (cx - 1, cy + 3), (cx + 4, cy - 3)], fill=fill, width=2)


def _warning_mark(draw: ImageDraw.ImageDraw, cx: float, cy: float, fill: Fill) -> None:
    draw.polygon([(cx, cy - 8), (cx + 9, cy + 7), (cx - 9, cy + 7)], outline=fill)
    draw.line((cx, cy - 3, cx, cy + 2), fill=fill, width=2)
    draw.rectangle((cx - 1, cy + 4, cx, cy + 5), fill=fill)


def _weather_glyph(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, icon: str, size: int, ink: Inks
) -> None:
    """A weather-icons glyph centred on (*cx*, *cy*); the clear-day sun is gold."""
    glyph = OWM_ICON_MAP.get(icon, FALLBACK_ICON)
    fill = ink.gold_ink if icon == "01d" else ink.text
    # The glyphs are hairline drawings; a 1-px stroke gives them the type's weight.
    draw.text(
        (cx, cy),
        glyph,
        font=fonts.weather_icon(size),
        fill=fill,
        anchor="mm",
        stroke_width=1,
        stroke_fill=fill,
    )


# The strip's model


@dataclass(frozen=True)
class Window:
    """The strip's stretch of time: from an hour before the current hour, for a day."""

    start: datetime
    hours: int
    x0: float
    x1: float

    @classmethod
    def at(cls, now: datetime, x0: float, x1: float) -> Window:
        hour = now.replace(minute=0, second=0, microsecond=0)
        return cls(hour - timedelta(hours=WINDOW_LEAD_HOURS), WINDOW_HOURS, x0, x1)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=self.hours)

    @property
    def px_per_hour(self) -> float:
        return (self.x1 - self.x0) / self.hours

    def x(self, t: datetime) -> float:
        """x for *t*, unclamped."""
        return self.x0 + (t - self.start).total_seconds() / 3600 * self.px_per_hour


@dataclass(frozen=True)
class Span:
    event: CalendarEvent
    state: str  # "active" | "next" | "later" | "past"


def spans(events: list[CalendarEvent], now: datetime, window: Window) -> list[Span]:
    """The timed events overlapping *window*, soonest first, each with its state."""
    seen_next = False
    out: list[Span] = []
    timed = [
        e for e in events if not e.is_all_day and e.end > window.start and e.start < window.end
    ]
    for event in sorted(timed, key=lambda e: (e.start, e.summary)):
        if event.end <= now:
            state = "past"
        elif event.start <= now:
            state = "active"
        elif not seen_next:
            seen_next = True
            state = "next"
        else:
            state = "later"
        out.append(Span(event, state))
    return out


# The order spans claim lanes in: what is under way and next before what is
# over, so a past event's label never pushes the next one off the strip.
LANE_PRIORITY = {"active": 0, "next": 1, "later": 2, "past": 3}


def lanes(
    extents: list[tuple[float, float]], count: int, priority: list[int] | None = None
) -> list[int | None]:
    """The lane each (x0, x1) extent takes: the first lane it overlaps nothing in.

    Extents claim lanes in *priority* order (lowest first, then their own order).
    ``None`` for an extent with no lane free among *count*; the strip leaves it off.
    """
    order = sorted(range(len(extents)), key=lambda i: (priority[i] if priority else 0, i))
    taken: list[list[tuple[float, float]]] = [[] for _ in range(max(count, 0))]
    out: list[int | None] = [None] * len(extents)
    for i in order:
        x0, x1 = extents[i]
        for lane, held in enumerate(taken):
            if all(x1 <= a + 1e-6 or x0 >= b - 1e-6 for a, b in held):
                held.append((x0, x1))
                out[i] = lane
                break
    return out


def label_step(px_per_hour: float, min_spacing: float = MIN_HOUR_LABEL_SPACING) -> int:
    """The hours between the strip's labels: the fewest that leave *min_spacing* px."""
    return next((s for s in (1, 2, 3, 4, 6) if s * px_per_hour >= min_spacing), 6)


def daylight(window: Window, altitude, step_px: int = 2) -> list[tuple[float, float]]:
    """The x-extents of *window* in which the sun is up, sampled every *step_px*."""
    stretches: list[tuple[float, float]] = []
    start: float | None = None
    x = window.x0
    while x <= window.x1:
        t = window.start + timedelta(hours=(x - window.x0) / window.px_per_hour)
        up = altitude(t) > SOLAR_HORIZON_DEG
        if up and start is None:
            start = x
        elif not up and start is not None:
            stretches.append((start, x))
            start = None
        x += step_px
    if start is not None:
        stretches.append((start, window.x1))
    return stretches


def trace_points(
    weather: WeatherData, hour: datetime, window: Window, tz: tzinfo | None
) -> list[tuple[datetime, float, float | None]]:
    """(time, temperature, chance of rain) along the strip: now's reading at the
    current hour, then each forecast slot after it inside the window."""
    points: list[tuple[datetime, float, float | None]] = [(hour, weather.current_temp, None)]
    for slot in weather.hourly:
        t = to_local_naive(slot.time, tz)
        if hour < t <= window.end:
            points.append((t, slot.temp, slot.precip_chance))
    return points


# The plate


def draw_wide_ephemeris(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    light: bool = False,
) -> None:
    """Draw the full ``wide_ephemeris`` plate into *region*; *light* on a paper ground."""
    region = region or ComponentRegion(0, 0, 1360, 480)
    image = getattr(draw, "_image", None)
    ink = inks_for(image.mode if image is not None else "L", light)
    tz = getattr(now, "tzinfo", None)
    now_local = to_local_naive(now, tz) if isinstance(now, datetime) else None
    if now_local is None:
        now_local = datetime.combine(today, datetime.min.time())

    saved = draw.fontmode
    draw.fontmode = "1"
    try:
        rx, ry, rw, rh = region.x, region.y, region.w, region.h
        draw.rectangle((rx, ry, rx + rw - 1, ry + rh - 1), fill=ink.ground)
        _draw_header(draw, data, now_local.date(), content_time(data, now), tz, region, ink)
        _draw_strip(draw, data, now_local, tz, region, ink, latitude, longitude)
        x = rx + MARGIN
        _draw_agenda(draw, data, now_local, x, x + AGENDA_W, ry, ink)
        x += AGENDA_W + COLUMN_GAP
        _draw_conditions(draw, data, now_local.date(), x, x + CONDITIONS_W, ry, ink)
        x += CONDITIONS_W + COLUMN_GAP
        _draw_outlook(draw, data, now_local.date(), x, rx + rw - MARGIN, ry, ink)
    finally:
        draw.fontmode = saved


def stale_sources(data: DashboardData) -> list[str]:
    """The sources gone stale, by the name the check line gives them, in a fixed order."""
    names = [("events", "CALENDAR"), ("weather", "WEATHER")]
    names += [("birthdays", "BIRTHDAYS"), ("air_quality", "AIR")]
    flagged = (StalenessLevel.STALE, StalenessLevel.EXPIRED)
    return [label for key, label in names if data.source_staleness.get(key) in flagged]


def _draw_header(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    synced: datetime,
    tz: tzinfo | None,
    region: ComponentRegion,
    ink: Inks,
) -> None:
    rx, ry, rw = region.x, region.y, region.w
    wordmark = fonts.michroma(26)
    x = rx + MARGIN
    draw.text((x, ry + 37), "EPHEMERIS", font=wordmark, fill=ink.gold_ink, anchor="ls")
    mark_end = x + draw.textlength("EPHEMERIS", font=wordmark)

    # The bridge rule: dim across the plate, gold off the left edge under the wordmark.
    dotted_hline(draw, ry + HEADER_H, rx, rx + rw - 1, ink.text)
    draw.rectangle((rx, ry + HEADER_H - 1, mark_end + 18, ry + HEADER_H + 1), fill=ink.gold)

    stale = stale_sources(data)
    cx = mark_end + 46
    caps = _face(16, ink)
    synced_text = "SYNCED " + _clock(to_local_naive(synced, tz))
    if stale:
        alert = ink.red if ink.colour else ink.text
        _warning_mark(draw, cx, ry + 31, alert)
        line = "STALE · " + ", ".join(stale) + " · " + synced_text
        draw_tracked(draw, cx + 18, ry + 36, line, caps, alert)
    else:
        _check_mark(draw, cx, ry + 31, ink.text)
        draw_tracked(draw, cx + 18, ry + 36, "ALL AS EXPECTED · " + synced_text, caps, ink.text)

    dateline = today.strftime("%a, %b %-d").upper()
    draw_tracked(
        draw,
        rx + rw - MARGIN,
        ry + 37,
        dateline,
        _face(22, ink),
        ink.text,
        tracking=0.14,
        align="right",
    )


def _draw_strip(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    now: datetime,
    tz: tzinfo | None,
    region: ComponentRegion,
    ink: Inks,
    latitude: float | None,
    longitude: float | None,
) -> None:
    rx, ry, rw = region.x, region.y, region.w
    x0, x1 = rx + MARGIN, rx + rw - MARGIN
    window = Window.at(now, x0, x1)
    hour = window.start + timedelta(hours=WINDOW_LEAD_HOURS)
    weather = data.weather

    # The head.
    draw.line((x0, ry + STRIP_LABEL_Y - 5, x0 + 12, ry + STRIP_LABEL_Y - 5), fill=ink.text, width=2)
    draw_tracked(
        draw, x0 + 22, ry + STRIP_LABEL_Y, "THE DAY AHEAD", _face(17, ink), ink.text, tracking=0.18
    )
    note = "NEXT 24 H"
    if weather and weather.sunrise and weather.sunset:
        rise = to_local_naive(weather.sunrise, tz)
        down = to_local_naive(weather.sunset, tz)
        note += f" · RISE {_clock(rise)} · SET {_clock(down)}"
    draw_tracked(draw, x1, ry + STRIP_LABEL_Y, note, _face(16, ink), ink.text, align="right")

    # The axis: a dim hairline, the daylight lit along it, a tick each hour.
    axis_y = ry + AXIS_Y
    now_x = window.x(hour)
    if ink.now_column is not None:
        draw.rectangle(
            (now_x, ry + TRACE_TOP - 22, now_x + window.px_per_hour, ry + STRIP_BOTTOM),
            fill=ink.now_column,
        )
    dotted_hline(draw, axis_y, x0, x1, ink.text)
    altitude = altitude_fn(weather, latitude, longitude, sun_zone(tz, latitude, longitude))
    for a, b in daylight(window, altitude):
        draw.rectangle((a, axis_y - 1, b, axis_y + 1), fill=ink.text)
    draw.rectangle((now_x, axis_y - 2, now_x + window.px_per_hour, axis_y + 2), fill=ink.gold)
    for k in range(window.hours + 1):
        hx = round(x0 + k * window.px_per_hour)
        draw.line((hx, axis_y + 3, hx, axis_y + 5), fill=ink.text)

    # The gold line at the current hour, from the trace to the last lane; the
    # readings and labels it crosses are knocked out of it. Where the hour is a
    # column instead, NOW is set inside it.
    now_font = _face(16, ink)
    if ink.now_column is None:
        draw.rectangle((now_x - 1, ry + TRACE_TOP - 22, now_x, ry + STRIP_BOTTOM), fill=ink.gold)
        half = tracked_width(draw, "NOW", now_font) / 2
        draw.rectangle(
            (now_x - half - 3, ry + HOUR_LABEL_Y - 12, now_x + half + 3, ry + HOUR_LABEL_Y + 3),
            fill=ink.ground,
        )
        label_x = now_x
    else:
        label_x = now_x + window.px_per_hour / 2
    draw_tracked(draw, label_x, ry + HOUR_LABEL_Y, "NOW", now_font, ink.gold_ink, align="center")

    _draw_hour_labels(draw, window, label_x, ry, ink)

    if weather is not None:
        _draw_trace(draw, weather, hour, window, tz, ry, ink)

    _draw_lanes(draw, data, now, window, ry, ink)


def _draw_hour_labels(
    draw: ImageDraw.ImageDraw, window: Window, now_x: float, ry: int, ink: Inks
) -> None:
    step = label_step(window.px_per_hour)
    font = _face(15, ink)
    for k in range(window.hours + 1):
        t = window.start + timedelta(hours=k)
        if t.hour % step:
            continue
        x = window.x(t)
        text = t.strftime("%-I %p")
        half = tracked_width(draw, text, font) / 2
        if abs(x - now_x) < half + 26 or x - half < window.x0 or x + half > window.x1:
            continue
        draw_tracked(draw, x, ry + HOUR_LABEL_Y, text, font, ink.text, align="center")


def _draw_trace(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData,
    hour: datetime,
    window: Window,
    tz: tzinfo | None,
    ry: int,
    ink: Inks,
) -> None:
    points = trace_points(weather, hour, window, tz)
    temps = [p[1] for p in points]
    lo, hi = min(temps), max(temps)
    if hi - lo < MIN_TEMP_SPAN:
        mid = (hi + lo) / 2
        lo, hi = mid - MIN_TEMP_SPAN / 2, mid + MIN_TEMP_SPAN / 2
    top, bottom = ry + TRACE_TOP, ry + TRACE_BOTTOM

    def y_of(temp: float) -> float:
        return bottom - (temp - lo) / (hi - lo) * (bottom - top)

    # Rain under the trace: each slot's chance as a hatched bar over the slot.
    for i, (t, _temp, chance) in enumerate(points):
        if chance is None or chance < RAIN_MIN_CHANCE:
            continue
        end = points[i + 1][0] if i + 1 < len(points) else t + timedelta(hours=3)
        a = max(window.x(t) + 3, window.x0)
        b = min(window.x(end) - 3, window.x1)
        if b - a < 2:
            continue
        h = max(2, round(RAIN_MAX_H * min(chance, 1.0)))
        yb = ry + RAIN_BOTTOM
        draw.line((a, yb - h, b, yb - h), fill=ink.text)
        for hx in range(round(a), round(b) + 1, 3):
            draw.line((hx, yb - h, hx, yb), fill=ink.text)

    xy = [(window.x(t), y_of(temp)) for t, temp, _ in points]
    if len(xy) > 1:
        draw.line(xy, fill=ink.text, width=2)
    font = _face(16, ink)
    for i, ((px, py), (_, temp, _c)) in enumerate(zip(xy, points, strict=True)):
        is_now = i == 0
        fill = ink.gold_ink if is_now else ink.text
        draw.rectangle((px - 2, py - 2, px + 2, py + 2), fill=fill)
        label = f"{round_temp(temp)}°"
        half = tracked_width(draw, label, font, 0.05) / 2
        lx = min(px, window.x1 - half)
        if ink.now_column is None:
            draw.rectangle((lx - half - 2, py - 20, lx + half + 2, py - 6), fill=ink.ground)
        draw_tracked(draw, lx, py - 8, label, font, fill, tracking=0.05, align="center")


def _draw_lanes(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    now: datetime,
    window: Window,
    ry: int,
    ink: Inks,
) -> None:
    items = spans(data.events, now, window)
    title_font, time_font = _face(20, ink), _face(15, ink)
    extents: list[tuple[float, float]] = []
    labels: list[tuple[str, str]] = []
    for span in items:
        e = span.event
        a = max(window.x(e.start), window.x0)
        b = min(window.x(e.end), window.x1)
        when = _short(e.start)
        label_w = draw.textlength(e.summary, font=title_font) + 10
        label_w += tracked_width(draw, when, time_font) + 22
        b = min(max(b, a + min(label_w, 260)), window.x1)
        extents.append((a, b))
        labels.append((e.summary, when))
    for span, lane, (a, b), (title, when) in zip(
        items,
        lanes(
            [(a, b + 6) for a, b in extents],
            LANES,
            [LANE_PRIORITY[span.state] for span in items],
        ),
        extents,
        labels,
        strict=True,
    ):
        if lane is None:
            continue
        y0 = ry + LANE_TOP + lane * (LANE_H + LANE_GAP)
        tone = {"active": "lit", "next": "next"}.get(span.state, "dim")
        type_ink = draw_slab(draw, (a, y0, b, y0 + LANE_H), ink, tone)
        tx = a + (10 if tone == "next" else 8)
        room = b - tx - 8
        when_w = tracked_width(draw, when, time_font)
        show_when = draw.textlength(title, font=title_font) + 10 + when_w <= room
        title_room = room - (when_w + 10 if show_when else 0)
        if title_room < 24:
            continue
        shown = truncate_to_width(draw, title, title_font, int(title_room))
        draw.text((tx, y0 + 20), shown, font=title_font, fill=type_ink, anchor="ls")
        if show_when:
            wx = tx + draw.textlength(shown, font=title_font) + 10
            draw_tracked(draw, wx, y0 + 19, when, time_font, type_ink)


# Agenda


@dataclass(frozen=True)
class Row:
    title: str
    detail: str
    kind: str  # "event" | "birthday"
    tone: str  # "lit" | "next" | "dim"
    key: tuple


def _day_word(day: date, today: date) -> str:
    if day == today:
        return "TODAY"
    if day == today + timedelta(days=1):
        return "TOMORROW"
    if day < today + timedelta(days=7):
        return day.strftime("%A").upper()
    return day.strftime("%b %-d").upper()


def agenda_rows(events: list[CalendarEvent], birthdays: list[Birthday], now: datetime) -> list[Row]:
    """What is on now and next, then the rest, birthdays in the fortnight among them."""
    today = now.date()
    rows: list[Row] = []
    seen_next = False
    for e in sorted(events, key=lambda e: (e.start, e.summary)):
        if e.is_all_day:
            if e.end.date() <= today:
                continue
            day = max(e.start.date(), today)
            detail = "ALL DAY" if day == today else _day_word(day, today)
            rows.append(Row(e.summary, detail, "event", "dim", (day, 0, e.start, e.summary)))
            continue
        if e.end <= now:
            continue
        if e.start <= now:
            detail, tone = "UNTIL " + _short(e.end), "lit"
        else:
            day = e.start.date()
            when = _short(e.start)
            detail = when if day == today else f"{_day_word(day, today)} {when}"
            tone = "next" if not seen_next else "dim"
            seen_next = True
        rows.append(Row(e.summary, detail, "event", tone, (e.start.date(), 1, e.start, e.summary)))
    for b in birthdays:
        day = next_birthday(b.date, today)
        if (day - today).days > BIRTHDAY_HORIZON_DAYS:
            continue
        rows.append(Row(b.name, _day_word(day, today), "birthday", "dim", (day, 0, None, b.name)))
    rows.sort(key=lambda r: (r.tone != "lit", r.key[0], r.key[1], r.key[2] or now, r.key[3]))
    return rows


def _draw_agenda(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    now: datetime,
    x0: float,
    x1: float,
    ry: int,
    ink: Inks,
) -> None:
    limit = (COLUMN_BOTTOM - COLUMN_TOP + (ROW_PITCH - ROW_H)) // ROW_PITCH
    rows = agenda_rows(data.events, data.birthdays, now)
    # The note counts today and tomorrow, as the TV's does; the rows run on past them.
    tomorrow = now.date() + timedelta(days=1)
    ahead = sum(1 for r in rows if r.key[0] <= tomorrow)
    rows = rows[:limit]
    draw_section_label(draw, x0, x1, "AGENDA", f"{ahead} AHEAD", ink)
    title_font, detail_font = _face(22, ink), _face(16, ink)
    if not rows:
        draw_tracked(draw, x0, ry + COLUMN_TOP + 22, "NOTHING AHEAD", _face(16, ink), ink.text)
        return
    for i, row in enumerate(rows):
        y0 = ry + COLUMN_TOP + i * ROW_PITCH
        type_ink = draw_slab(draw, (x0, y0, x1, y0 + ROW_H), ink, row.tone)
        mark = _gift_mark if row.kind == "birthday" else _calendar_mark
        mark(draw, x0 + 12, y0 + 8, type_ink)
        detail_w = draw_tracked(
            draw, x1 - 14, y0 + 21, row.detail, detail_font, type_ink, align="right"
        )
        room = int(x1 - 14 - detail_w - 14 - (x0 + 36))
        title = truncate_to_width(draw, row.title, title_font, room)
        draw.text((x0 + 36, y0 + 23), title, font=title_font, fill=type_ink, anchor="ls")


# Conditions


def readings(data: DashboardData, today: date) -> list[tuple[str, str]]:
    """The conditions grid as (label, value), in order, skipping what is missing."""
    w = data.weather
    out: list[tuple[str, str]] = []
    if w is not None:
        out.append(("HUMIDITY", f"{w.humidity}%"))
        if w.wind_speed is not None:
            compass = f" {deg_to_compass(w.wind_deg)}" if w.wind_deg is not None else ""
            out.append(("WIND", f"{round(w.wind_speed)}{compass} {wind_unit(w)}"))
    aq = data.air_quality
    if aq is not None:
        out.append((f"AIR · {aq.category.upper()}", f"{aq.aqi} AQI"))
    if w is not None and w.uv_index is not None:
        out.append((f"UV · {_uv_word(w.uv_index)}", f"{round(w.uv_index)}"))
    if w is not None and w.pressure is not None:
        out.append(("PRESSURE", f"{round(w.pressure)} hPa"))
    out.append((moon_phase_name(today).upper(), f"{round(moon_illumination(today))}% lit"))
    return out[:MAX_READINGS]


def _uv_word(uv: float) -> str:
    for ceiling, word in ((3, "LOW"), (6, "MODERATE"), (8, "HIGH"), (11, "VERY HIGH")):
        if uv < ceiling:
            return word
    return "EXTREME"


def _draw_conditions(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    x0: float,
    x1: float,
    ry: int,
    ink: Inks,
) -> None:
    w = data.weather
    place = (w.location_name or "").upper() if w else ""
    draw_section_label(draw, x0, x1, "CONDITIONS", place, ink)
    top = ry + COLUMN_TOP
    if w is None:
        draw_tracked(draw, x0, top + 22, "NO WEATHER", _face(16, ink), ink.text)
        y = top
    else:
        _weather_glyph(draw, x0 + 34, top + 32, w.current_icon, 48, ink)
        numeral = fonts.michroma(52)
        tx = x0 + 80
        reading = round_temp(w.current_temp)
        # Michroma has one weight, thin for its size at a metre; a 1-px stroke thickens it.
        draw.text(
            (tx, top + 60),
            reading,
            font=numeral,
            fill=ink.text,
            anchor="ls",
            stroke_width=1,
            stroke_fill=ink.text,
        )
        tx += draw.textlength(reading, font=numeral) + 4
        draw.text(
            (tx, top + 60), "°", font=fonts.saira(52, ink.weight - 100), fill=ink.text, anchor="ls"
        )
        dx = tx + 30
        room = int(x1 - dx)
        sky_font = _face(20, ink)
        sky = truncate_to_width(draw, w.current_description.upper(), sky_font, room)
        draw_tracked(draw, dx, top + 28, sky, sky_font, ink.text)
        parts = [f"H {round_temp(w.high)}°", f"L {round_temp(w.low)}°"]
        if w.feels_like is not None:
            parts.append(f"FEELS {round_temp(w.feels_like)}°")
        draw_tracked(draw, dx, top + 56, "  ".join(parts), _face(17, ink), ink.text)
        y = top + 70
        if w.alerts:
            box = (x0, y, x1, y + 26)
            type_ink = draw_slab(draw, box, ink, "alert")
            _warning_mark(draw, x0 + 18, y + 13, type_ink)
            alert_font = _face(17, ink)
            text = truncate_to_width(draw, w.alerts[0].event.upper(), alert_font, int(x1 - x0 - 60))
            draw_tracked(draw, x0 + 36, y + 20, text, alert_font, type_ink)
            y += 26 + TILE_GAP
        else:
            y += 10

    # The readings, two to a row: the label at the left, the value at the right.
    cells = readings(data, today)
    tile_w = (x1 - x0 - TILE_GAP) / 2
    label_font, value_font = _face(15, ink), _face(22, ink)
    for i, (label, value) in enumerate(cells):
        tx0 = x0 + (i % 2) * (tile_w + TILE_GAP)
        ty0 = y + (i // 2) * (TILE_H + TILE_GAP)
        if ty0 + TILE_H > ry + COLUMN_BOTTOM:
            break
        draw_slab(draw, (tx0, ty0, tx0 + tile_w, ty0 + TILE_H), ink, "dim")
        value = truncate_to_width(draw, value, value_font, int(tile_w / 2))
        value_w = draw.textlength(value, font=value_font)
        draw.text((tx0 + tile_w - 12, ty0 + 23), value, font=value_font, fill=ink.text, anchor="rs")
        label = truncate_to_width(draw, label, label_font, int(tile_w - value_w - 30))
        draw_tracked(draw, tx0 + 10, ty0 + 21, label, label_font, ink.text)


# Outlook


def _draw_outlook(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    x0: float,
    x1: float,
    ry: int,
    ink: Inks,
) -> None:
    days = [d for d in (data.weather.forecast if data.weather else []) if d.date > today]
    fit = int((x1 - x0 + CARD_GAP) // (MIN_CARD_W + CARD_GAP))
    days = days[: min(fit, MAX_CARDS)]
    draw_section_label(draw, x0, x1, "OUTLOOK", f"{len(days)} DAYS" if days else "", ink)
    if not days:
        draw_tracked(draw, x0, ry + COLUMN_TOP + 22, "NO FORECAST", _face(16, ink), ink.text)
        return
    n = len(days)
    card_w = (x1 - x0 - (n - 1) * CARD_GAP) / n
    top, bottom = ry + COLUMN_TOP, ry + COLUMN_BOTTOM
    for i, day in enumerate(days):
        cx0 = x0 + i * (card_w + CARD_GAP)
        mid = cx0 + card_w / 2
        draw_slab(draw, (cx0, top, cx0 + card_w, bottom), ink, "dim")
        day_name = day.date.strftime("%a").upper()
        day_font = _face(19, ink)
        draw_tracked(
            draw, mid, top + 30, day_name, day_font, ink.text, tracking=0.2, align="center"
        )
        _weather_glyph(draw, mid, top + 72, day.icon, 46, ink)
        high, low = f"{round_temp(day.high)}°", f"{round_temp(day.low)}°"
        hf, lf = _face(36, ink), _face(26, ink)
        hw, lw = draw.textlength(high, font=hf), draw.textlength(low, font=lf)
        hx = mid - (hw + 8 + lw) / 2
        draw.text((hx, top + 134), high, font=hf, fill=ink.text, anchor="ls")
        draw.text((hx + hw + 8, top + 134), low, font=lf, fill=ink.text, anchor="ls")
        chance = day.precip_chance
        rain = f"{round(chance * 100)}% RAIN" if chance and chance >= RAIN_MIN_CHANCE else "DRY"
        fill = ink.gold_ink if rain != "DRY" else ink.text
        draw_tracked(draw, mid, top + 162, rain, _face(17, ink), fill, align="center")
