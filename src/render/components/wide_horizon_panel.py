"""wide_horizon_panel.py — the next three days on one time axis, 1360x480.

The 10.85" strip is nearly three times as wide as it is tall, and the one
thing that shape does that an 800x480 plate cannot is carry a *long* time axis
at a readable scale. This plate lays the next 72 hours left to right and puts
everything that happens in them on that one axis, so the relationships are
read by eye rather than by comparing columns: the dinner on Thursday is after
dark, and it will be 38° and raining.

Bands, top to bottom, right of a hero block for the conditions now:

  * **Day header** — each calendar day's name set at its midnight.
  * **Sky** — a panorama whose colour at every column is the sun's real
    altitude at that moment (``astronomy.solar_altitude``): paper by day,
    yellow into red into black through each twilight, stars and the moon by
    night, the sun at each solar noon at the height it will reach. On a colour
    panel the twilights are ordered dithers between *pairs* of inks — white
    and yellow, yellow and red, red and black — so the panel shows pale
    yellow, orange and maroon it has no ink for. On a monochrome panel the
    same altitude drives a black-and-white Bayer ramp. Over the sky runs the
    temperature, drawn from the forecast's 3-hour slots
    (``WeatherData.hourly``) as a cased line, each day's high and low marked.
  * **Rain** — each slot's chance of precipitation as a bar hanging from the
    sky, its depth the chance and its density the expected amount.
  * **Hours** — a tick and label at 6a, 12p and 6p; midnight is the day rule.
  * **Events** — all-day events and birthdays as a band per day, timed events
    as bars over their real span, packed into lanes by bar-plus-label extent
    (``wide_day_panel.pack_lanes``).

The axis is not linear. Hours between ``SLEEP_HOUR`` and ``WAKE_HOUR`` take
``NIGHT_WEIGHT`` of a waking hour's width, which buys the waking hours ~19 px
each against ~16 px on a linear axis — a thirty-minute meeting is a 10-px bar
rather than an 8-px one — while the night keeps a truthful place on the axis.

Everything on the plate is a pure ink. Type is set without antialiasing
(``fontmode = "1"``) and every tone is an ordered dither computed here, so the
colour panel's nearest-ink snap and the monochrome threshold are both the
identity at native size. The sky is still declared as an art region
(``sky_rect``) so a panel that *scales* the plate re-diffuses its tones after
the resize instead of snapping a blurred dither to a flat ink.

Repaints: the window starts at the 3-hour slot holding *now*, so the plate
moves at most eight times a day on the clock — the forecast grid itself only
changes about that often. Nothing else reads the clock, and events carry no
past/current state, so an idle tick renders byte-identically.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from src.astronomy import solar_altitude, sun_times
from src.data.models import Birthday, CalendarEvent, DashboardData, HourlyForecast, WeatherData
from src.render import fonts
from src.render.artkit import to_local_naive
from src.render.components.wide_day_panel import pack_lanes
from src.render.moon import is_waxing, moon_illumination, moon_phase_age
from src.render.primitives import (
    content_time,
    deg_to_compass,
    draw_text_truncated,
    fmt_time,
    next_birthday,
    text_width,
    wind_unit,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_RED, INKY_YELLOW, ComponentRegion, ThemeStyle

Rect = tuple[int, int, int, int]
Fill = int | tuple[int, int, int]

# ---------------------------------------------------------------------------
# Geometry (relative to the region's origin; the plate is drawn for 1360x480)
# ---------------------------------------------------------------------------

HERO_W = 236  # the conditions-now block at the left end
# The hero reading's size; a reading wider than the column ("-40°", "108°"
# fit; "-108°" does not) steps down until it fits.
HERO_TEMP_PT = 128
PAD = 14

HEAD_H = 44  # day-name band
SKY_H = 206
RAIN_H = 26  # bars hang from the sky's bottom edge into this band
HOURS_H = 18
EVENTS_GAP = 6
ALLDAY_H = 22
LANE_H = 31
BAR_H = 27

# The panorama.
WINDOW_HOURS = 72
SLOT_HOURS = 3
WAKE_HOUR = 6
SLEEP_HOUR = 23
NIGHT_WEIGHT = 0.35

# How far the horizon glow lifts the sky's bottom edge, in degrees of solar
# altitude: at dusk the bottom of the band is still orange when the top has
# gone dark, which is what makes the twilight read as a sky and not a stripe.
HORIZON_GLOW_DEG = 12.0

# Temperature curve: the band of the sky it may occupy, as fractions of the
# sky's height, and the smallest temperature span the band represents — a flat
# day should look flat, not be stretched to fill the band.
CURVE_TOP = 0.40
CURVE_BOTTOM = 0.86
MIN_TEMP_SPAN = 14.0

# Beside-labels on narrow bars, as on wide_day.
LABEL_PAD = 6
MAX_BESIDE_LABEL_W = 200
MIN_BESIDE_LABEL_W = 24

STARS_PER_100PX = 16
MIN_CHIP_LABEL_W = 48  # an all-day chip narrower than this carries no label


# ---------------------------------------------------------------------------
# Inks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Inks:
    """The plate's four inks in the canvas's mode.

    On a monochrome canvas the accents fall back to ink for marks and type —
    tones never use them; the sky has its own monochrome ramp.
    """

    black: Fill
    white: Fill
    red: Fill
    yellow: Fill
    colour: bool


def inks_for(mode: str) -> Inks:
    if mode == "RGB":
        return Inks(
            black=(0, 0, 0),
            white=(255, 255, 255),
            red=INKY_SPECTRA6_PALETTE[INKY_RED],
            yellow=INKY_SPECTRA6_PALETTE[INKY_YELLOW],
            colour=True,
        )
    white = 1 if mode == "1" else 255
    return Inks(black=0, white=white, red=0, yellow=0, colour=False)


def _bayer8() -> np.ndarray:
    """The 8x8 ordered-dither matrix, normalised to thresholds in (0, 1)."""
    m = np.array([[0]])
    for _ in range(3):
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return (m + 0.5) / 64.0


_BAYER8 = _bayer8()


def bayer_field(w: int, h: int, x0: int, y0: int) -> np.ndarray:
    """An ``h x w`` array of Bayer thresholds phased to canvas coordinates.

    Phasing by the canvas position means two adjacent dithered areas line up
    as one continuous screen.
    """
    ys = (np.arange(h) + y0) % 8
    xs = (np.arange(w) + x0) % 8
    return _BAYER8[np.ix_(ys, xs)]


# ---------------------------------------------------------------------------
# The time axis
# ---------------------------------------------------------------------------


def window_start(now: datetime) -> datetime:
    """The start of the 3-hour slot holding *now* (naive local)."""
    return now.replace(
        hour=(now.hour // SLOT_HOURS) * SLOT_HOURS, minute=0, second=0, microsecond=0
    )


def hour_weight(hour: int) -> float:
    """Relative width of the clock hour starting at *hour*."""
    return 1.0 if WAKE_HOUR <= hour < SLEEP_HOUR else NIGHT_WEIGHT


class TimeAxis:
    """Piecewise-linear map between naive local time and x over the window.

    Breakpoints sit on every clock hour, each hour's width proportional to
    ``hour_weight``. ``start`` must be on an hour boundary.
    """

    def __init__(self, start: datetime, hours: int, x0: float, x1: float):
        self.start = start
        self.hours = hours
        self.end = start + timedelta(hours=hours)
        weights = [hour_weight((start + timedelta(hours=k)).hour) for k in range(hours)]
        scale = (x1 - x0) / sum(weights)
        xs = [float(x0)]
        for w in weights:
            xs.append(xs[-1] + w * scale)
        self.xs = xs
        self._scale = scale
        self.x0 = float(x0)
        self.x1 = float(x1)

    def x(self, t: datetime) -> float:
        """x for time *t*, clamped to the window."""
        h = (t - self.start).total_seconds() / 3600.0
        if h <= 0:
            return self.x0
        if h >= self.hours:
            return self.x1
        k = int(h)
        return self.xs[k] + (h - k) * (self.xs[k + 1] - self.xs[k])

    def t(self, x: float) -> datetime:
        """The time at *x* — the inverse of :meth:`x`."""
        xs = self.xs
        if x <= xs[0]:
            return self.start
        if x >= xs[-1]:
            return self.end
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= x:
                lo = mid
            else:
                hi = mid
        frac = (x - xs[lo]) / (xs[lo + 1] - xs[lo])
        return self.start + timedelta(hours=lo + frac)

    def px_per_hour(self, hour: int) -> float:
        """Width of the clock hour starting at *hour*."""
        return hour_weight(hour) * self._scale


# ---------------------------------------------------------------------------
# Sun
# ---------------------------------------------------------------------------


def has_coordinates(latitude: float | None, longitude: float | None) -> bool:
    """Coordinates are usable; exact ``(0, 0)`` means unset, as elsewhere."""
    if latitude is None or longitude is None:
        return False
    return not (latitude == 0.0 and longitude == 0.0)


def _aware(t: datetime, tz: tzinfo | None) -> datetime:
    """Naive local *t* as an aware instant; with no zone the clock is UTC."""
    return t.replace(tzinfo=tz if tz is not None else timezone.utc)


def sun_zone(tz: tzinfo | None, latitude: float | None, longitude: float | None):
    """The zone the sun is placed in: the render's own, else the one the longitude implies.

    A real run always hands the plate an aware clock. Previews and snapshot
    renders hand it a naive one, and reading that as UTC would put New York's
    night five hours late; the whole-hour zone nearest the longitude keeps the
    sun where the clock on the plate says it is.
    """
    if tz is not None or not has_coordinates(latitude, longitude):
        return tz
    return timezone(timedelta(hours=round(float(longitude) / 15.0)))  # type: ignore[arg-type]


def _clock_hours(dt: datetime | None, tz: tzinfo | None) -> float | None:
    if dt is None:
        return None
    local = to_local_naive(dt, tz)
    return local.hour + local.minute / 60.0


def altitude_fn(
    weather: WeatherData | None,
    latitude: float | None,
    longitude: float | None,
    tz: tzinfo | None,
):
    """A function ``naive local datetime -> solar altitude in degrees``.

    Computed properly from the coordinates when they are set. Without them the
    day's reported sunrise and sunset stand in for every day of the window
    (fixed 06:30 / 19:30 when weather is missing too), with a sine arc by day
    and a linear fall at night — enough to put the twilights in the right
    place, which is all the sky needs.
    """
    if has_coordinates(latitude, longitude):
        lat, lon = float(latitude), float(longitude)  # type: ignore[arg-type]
        return lambda t: solar_altitude(_aware(t, tz), lat, lon)

    rise = _clock_hours(weather.sunrise, tz) if weather else None
    down = _clock_hours(weather.sunset, tz) if weather else None
    if rise is None or down is None or down <= rise:
        rise, down = 6.5, 19.5
    span = down - rise

    def synthetic(t: datetime) -> float:
        h = t.hour + t.minute / 60.0 + t.second / 3600.0
        if rise <= h <= down:
            return 50.0 * math.sin(math.pi * (h - rise) / span)
        # Hours to the nearer of the evening's sunset and the morning's sunrise.
        if h > down:
            dist = min(h - down, rise + 24 - h)
        else:
            dist = min(rise - h, h + 24 - down)
        return max(-40.0, -12.0 * dist)

    return synthetic


def solar_noons(
    axis: TimeAxis,
    weather: WeatherData | None,
    latitude: float | None,
    longitude: float | None,
    tz: tzinfo | None,
    altitude,
) -> list[tuple[datetime, float]]:
    """``(local noon, peak altitude)`` for each solar noon inside the window."""
    out: list[tuple[datetime, float]] = []
    day = axis.start.date()
    while day <= axis.end.date():
        noon: datetime | None = None
        if has_coordinates(latitude, longitude):
            st = sun_times(day, float(latitude), float(longitude))  # type: ignore[arg-type]
            if st.solar_noon is not None:
                noon = to_local_naive(st.solar_noon, tz)
        else:
            rise = _clock_hours(weather.sunrise, tz) if weather else None
            down = _clock_hours(weather.sunset, tz) if weather else None
            if rise is None or down is None or down <= rise:
                rise, down = 6.5, 19.5
            mid = (rise + down) / 2
            noon = datetime.combine(day, datetime.min.time()) + timedelta(hours=mid)
        if noon is not None and axis.start <= noon <= axis.end:
            alt = altitude(noon)
            if alt > 0:
                out.append((noon, alt))
        day += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Sky field
# ---------------------------------------------------------------------------


def column_altitudes(axis: TimeAxis, width: int, altitude) -> np.ndarray:
    """Solar altitude at the centre of each of *width* columns from ``axis.x0``."""
    return np.array([altitude(axis.t(axis.x0 + i + 0.5)) for i in range(width)], dtype=np.float64)


def sky_field(alt: np.ndarray, height: int, x0: int, y0: int, mode: str) -> Image.Image:
    """The sky as pure inks: altitude per column, glow toward the horizon.

    Colour ramp by effective altitude ``h`` (degrees), each step a Bayer mix of
    two adjacent inks: ``h >= 12`` paper; ``12..0`` white→yellow; ``0..-6``
    yellow→red; ``-6..-14`` red→black; below that black. The ramps run wider
    than the named twilights so a dusk reads as a sky, not a stripe. Monochrome
    is one ramp, paper at 12° to solid ink at -14°.
    """
    w = alt.shape[0]
    frac = np.linspace(0.0, 1.0, height)[:, None]
    h = alt[None, :] + HORIZON_GLOW_DEG * frac
    thr = bayer_field(w, height, x0, y0)
    if mode != "RGB":
        cover = np.clip((12.0 - h) / 26.0, 0.0, 1.0)
        arr = np.where(thr < cover, 0, 255).astype(np.uint8)
        return Image.fromarray(arr, mode="L")

    k = np.array((0, 0, 0), np.uint8)
    wh = np.array((255, 255, 255), np.uint8)
    r = np.array(INKY_SPECTRA6_PALETTE[INKY_RED], np.uint8)
    y = np.array(INKY_SPECTRA6_PALETTE[INKY_YELLOW], np.uint8)
    out = np.empty((height, w, 3), np.uint8)
    out[:] = wh

    def mix(mask, a, b, cover):
        pick_b = mask & (thr < cover)
        pick_a = mask & ~(thr < cover)
        out[pick_a] = a
        out[pick_b] = b

    mix((h < 12.0) & (h >= 0.0), wh, y, np.clip((12.0 - h) / 12.0, 0.0, 1.0) ** 1.5)
    mix((h < 0.0) & (h >= -6.0), y, r, -h / 6.0)
    mix((h < -6.0) & (h >= -14.0), r, k, (-6.0 - h) / 8.0)
    out[h < -14.0] = k
    return Image.fromarray(out, mode="RGB")


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------


def window_slots(
    hourly: list[HourlyForecast], axis: TimeAxis, tz: tzinfo | None
) -> list[tuple[datetime, HourlyForecast]]:
    """Slots touching the window, one either side kept so the curve reaches the edges."""
    local = sorted(((to_local_naive(h.time, tz), h) for h in hourly), key=lambda p: p[0])
    inside = [i for i, (t, _) in enumerate(local) if axis.start <= t <= axis.end]
    if not inside:
        return []
    lo = max(0, inside[0] - 1)
    hi = min(len(local), inside[-1] + 2)
    return local[lo:hi]


def catmull_rom(points: list[tuple[float, float]], step: float = 4.0) -> list[tuple[float, float]]:
    """A smooth polyline through *points* (x strictly increasing)."""
    if len(points) < 3:
        return list(points)
    out: list[tuple[float, float]] = []
    pts = [points[0], *points, points[-1]]
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        n = max(1, int((p2[0] - p1[0]) / step))
        for j in range(n):
            t = j / n
            t2, t3 = t * t, t * t * t
            xy = tuple(
                0.5
                * (
                    2 * p1[c]
                    + (-p0[c] + p2[c]) * t
                    + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2
                    + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3
                )
                for c in (0, 1)
            )
            out.append((xy[0], xy[1]))
    out.append(points[-1])
    return out


def temp_scale(temps: list[float]) -> tuple[float, float]:
    """``(lo, hi)`` the curve band represents: the data, widened to ``MIN_TEMP_SPAN``."""
    lo, hi = min(temps), max(temps)
    if hi - lo < MIN_TEMP_SPAN:
        mid = (hi + lo) / 2
        lo, hi = mid - MIN_TEMP_SPAN / 2, mid + MIN_TEMP_SPAN / 2
    return lo, hi


def daily_extremes(
    slots: list[tuple[datetime, HourlyForecast]], axis: TimeAxis
) -> list[tuple[str, datetime, float]]:
    """Each day's high and low inside the window, as ``(kind, time, temp)``.

    A value is only labelled when it is a real turning point — no higher (for a
    high) or lower (for a low) than the slots either side of it, the slots
    just outside the window included. The window cuts days at both ends, and
    the warmest slot of a cut evening is just where the plate starts falling,
    not the day's high.
    """
    temps = [h.temp for _, h in slots]
    by_day: dict[date, list[int]] = {}
    for i, (t, _) in enumerate(slots):
        if axis.start <= t <= axis.end:
            by_day.setdefault(t.date(), []).append(i)
    out: list[tuple[str, datetime, float]] = []
    for day in sorted(by_day):
        idx = by_day[day]
        for kind, pick in (("high", max), ("low", min)):
            i = pick(idx, key=lambda j: temps[j])
            if i == 0 or i == len(slots) - 1:
                continue
            before, after = temps[i - 1], temps[i + 1]
            turning = (
                temps[i] >= before and temps[i] >= after
                if kind == "high"
                else temps[i] <= before and temps[i] <= after
            )
            if turning:
                out.append((kind, slots[i][0], temps[i]))
    return out


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def events_in_window(events: list[CalendarEvent], axis: TimeAxis) -> list[CalendarEvent]:
    """Timed events overlapping the window, by start."""
    timed = [e for e in events if not e.is_all_day and e.start < axis.end and e.end > axis.start]
    return sorted(timed, key=lambda e: (e.start, e.end))


def allday_in_window(
    events: list[CalendarEvent],
    birthdays: list[Birthday],
    axis: TimeAxis,
) -> list[tuple[datetime, datetime, str, bool]]:
    """All-day spans and birthdays in the window, as ``(start, end, label, is_birthday)``."""
    rows: list[tuple[datetime, datetime, str, bool]] = []
    for e in events:
        if not e.is_all_day:
            continue
        start = datetime.combine(_as_date(e.start), datetime.min.time())
        end = datetime.combine(_as_date(e.end), datetime.min.time())
        if end <= start:
            end = start + timedelta(days=1)
        if start < axis.end and end > axis.start:
            rows.append((start, end, e.summary, False))
    first = axis.start.date()
    for b in birthdays:
        when = next_birthday(b.date, first)
        start = datetime.combine(when, datetime.min.time())
        if start < axis.end:
            label = f"{b.name}'s birthday" if b.age is None else f"{b.name} turns {b.age}"
            rows.append((start, start + timedelta(days=1), label, True))
    rows.sort(key=lambda r: (r[0], r[3], r[2]))
    return rows


def _as_date(v) -> date:
    return v.date() if isinstance(v, datetime) else v


def event_label(evt: CalendarEvent) -> tuple[str, str]:
    """Title and time line for a bar."""
    return evt.summary, f"{fmt_time(evt.start)}–{fmt_time(evt.end)}"


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------


def _text_box(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int, int, int]:
    return draw.textbbox((0, 0), text, font=font)


def _dotted_vline(draw, x: int, y0: int, y1: int, fill, gap: int = 3) -> None:
    for y in range(y0, y1, gap):
        draw.point((x, y), fill=fill)


def _dither_rect(image: Image.Image, box: Rect, cover: float, ink: Fill) -> None:
    """Stamp *ink* through the Bayer screen at *cover* over *box* (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0 or cover <= 0:
        return
    thr = bayer_field(w, h, x0, y0)
    mask = Image.fromarray(np.where(thr < cover, 255, 0).astype(np.uint8), mode="L")
    image.paste(Image.new(image.mode, (w, h), ink), (x0, y0), mask)


def _is_dark(alt: np.ndarray, sky_x0: int, x: float) -> bool:
    i = int(min(max(x - sky_x0, 0), alt.shape[0] - 1))
    return bool(alt[i] < -9.0)


# ---------------------------------------------------------------------------
# Plate
# ---------------------------------------------------------------------------


def sky_rect(region: ComponentRegion) -> Rect:
    """The sky's rectangle in canvas coordinates — the part a scaled colour panel may dither."""
    x0 = region.x + HERO_W
    y0 = region.y + HEAD_H
    return (x0, y0, region.x + region.w, y0 + SKY_H)


def draw_wide_horizon(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """Draw the full ``wide_horizon`` plate into *region*."""
    region = region or ComponentRegion(0, 0, 1360, 480)
    style = style or ThemeStyle()
    if image is None:
        image = getattr(draw, "_image", None)
    if image is None:  # pragma: no cover - every caller passes a drawable image
        return
    ink = inks_for(image.mode)
    tz = getattr(now, "tzinfo", None)
    now_local = to_local_naive(now, tz) if isinstance(now, datetime) else now
    if not isinstance(now_local, datetime):
        now_local = datetime.combine(today, datetime.min.time())

    saved_fontmode = draw.fontmode
    draw.fontmode = "1"
    try:
        _draw_plate(draw, image, data, now_local, tz, region, ink, latitude, longitude)
    finally:
        draw.fontmode = saved_fontmode


def _draw_plate(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    data: DashboardData,
    now: datetime,
    tz: tzinfo | None,
    region: ComponentRegion,
    ink: Inks,
    latitude: float | None,
    longitude: float | None,
) -> None:
    rx, ry, rw, rh = region.x, region.y, region.w, region.h
    draw.rectangle((rx, ry, rx + rw - 1, ry + rh - 1), fill=ink.white)

    sky_x0, sky_y0, sky_x1, sky_y1 = sky_rect(region)
    axis = TimeAxis(window_start(now), WINDOW_HOURS, sky_x0, sky_x1)
    weather = data.weather
    sun_tz = sun_zone(tz, latitude, longitude)
    altitude = altitude_fn(weather, latitude, longitude, sun_tz)
    alt = column_altitudes(axis, sky_x1 - sky_x0, altitude)

    field = sky_field(alt, SKY_H, sky_x0, sky_y0, image.mode)
    image.paste(field.convert(image.mode), (sky_x0, sky_y0))

    _draw_stars(draw, axis, alt, sky_y0, ink)
    slots = window_slots(weather.hourly, axis, tz) if weather else []
    suns = _draw_suns(
        draw, axis, sky_y0, ink, weather, latitude, longitude, sun_tz, altitude, slots
    )
    suns += _draw_moons(image, draw, axis, sky_y0, ink, altitude, slots)
    _draw_midnights_in_sky(draw, axis, alt, sky_y0, sky_y1, ink)

    _draw_sky_weather(image, draw, axis, alt, slots, sky_y0, ink, suns)
    _draw_temperature(draw, axis, alt, slots, sky_x0, sky_y0, ink)

    rain_y0 = sky_y1
    _draw_rain(image, draw, axis, slots, rain_y0, ink)
    hours_y0 = rain_y0 + RAIN_H
    _draw_hours(draw, axis, hours_y0, ink)
    _draw_day_headers(draw, axis, ry, now, ink)

    ev_y0 = hours_y0 + HOURS_H + EVENTS_GAP
    _draw_events(draw, data, axis, ev_y0, ry + rh - 6, ink)

    _draw_hero(draw, data, now, tz, rx, ry, rh, ink, weather, slots, axis)


# --- sky decorations -------------------------------------------------------


def _draw_stars(draw, axis: TimeAxis, alt: np.ndarray, sky_y0: int, ink: Inks) -> None:
    """Stars in deep night, seeded per absolute clock hour so they travel with time."""
    first = _hour_index(axis.start)
    for k in range(axis.hours):
        x0, x1 = axis.xs[k], axis.xs[k + 1]
        rng = random.Random((first + k) * 7919 + 17)
        n = max(1, int(round((x1 - x0) * STARS_PER_100PX / 100)))
        for _ in range(n):
            x = rng.uniform(x0, x1)
            y = sky_y0 + rng.uniform(6, SKY_H * 0.62)
            i = int(min(max(x - axis.x0, 0), alt.shape[0] - 1))
            depth = alt[i] + HORIZON_GLOW_DEG * (y - sky_y0) / SKY_H
            if depth >= -15.0:
                continue
            if rng.random() < 0.18:
                draw.rectangle((x, y, x + 1, y + 1), fill=ink.white)
                if rng.random() < 0.4:  # a few brighter ones get a cross
                    draw.point((x - 1, y), fill=ink.white)
                    draw.point((x + 2, y + 1), fill=ink.white)
                    draw.point((x, y - 1), fill=ink.white)
                    draw.point((x + 1, y + 2), fill=ink.white)
            else:
                draw.point((x, y), fill=ink.white)


def _hour_index(t: datetime) -> int:
    return (t.toordinal() * 24) + t.hour


def moon_transit(day: date) -> datetime:
    """Local time the moon crosses the meridian on the night after *day*.

    A new moon transits at noon and a full moon at midnight, about 50 minutes
    later each day between — close enough to place the disc on the axis.
    """
    age = moon_phase_age(day)
    hours = 12.0 + 24.0 * age / 29.530588
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=hours)


def _draw_moons(image, draw, axis: TimeAxis, sky_y0: int, ink: Inks, altitude, slots=()):
    """The moon at each transit that falls in darkness; returns their x."""
    xs: list[float] = []
    day = axis.start.date() - timedelta(days=1)
    while day <= axis.end.date():
        t = moon_transit(day)
        if axis.start <= t <= axis.end and altitude(t) < -10.0 and not sun_hidden(slots, t):
            x = axis.x(t)
            _moon_disc(image, draw, int(x), sky_y0 + 42, 15, t.date(), ink)
            xs.append(x)
        day += timedelta(days=1)
    return xs


def _moon_disc(image, draw, cx: int, cy: int, r: int, day: date, ink: Inks) -> None:
    """Phase-correct moon: the lit part solid (yellow on colour), the rest outlined."""
    k = moon_illumination(day) / 100.0
    waxing = is_waxing(day)
    size = 2 * r + 1
    yy, xx = np.mgrid[-r : r + 1, -r : r + 1].astype(np.float64)
    inside = xx * xx + yy * yy <= r * r + 0.5
    edge = np.sqrt(np.clip(r * r - yy * yy, 0, None))
    term = (1 - 2 * k) * edge
    lit = inside & ((xx >= term) if waxing else (-xx >= term))
    mask = Image.fromarray((lit * 255).astype(np.uint8), mode="L")
    lit_ink = ink.yellow if ink.colour else ink.white
    image.paste(Image.new(image.mode, (size, size), lit_ink), (cx - r, cy - r), mask)
    # The dark limb as a dotted ring, so a crescent still reads as a disc.
    for a in range(0, 360, 12):
        px = cx + r * math.cos(math.radians(a))
        py = cy + r * math.sin(math.radians(a))
        dx, dy = px - cx, py - cy
        on_lit = (
            (dx >= (1 - 2 * k) * math.sqrt(max(r * r - dy * dy, 0)))
            if waxing
            else (-dx >= (1 - 2 * k) * math.sqrt(max(r * r - dy * dy, 0)))
        )
        if not on_lit:
            draw.point((round(px), round(py)), fill=ink.white)


def sun_hidden(slots, noon: datetime) -> bool:
    """True when the forecast slot holding *noon* is overcast or wet.

    Used for the moon's transit too: a body under such a slot is not drawn.
    """
    for t, h in slots:
        if t <= noon < t + timedelta(hours=SLOT_HOURS):
            level, precip = sky_kind(h.icon)
            return level >= 3 or precip in ("rain", "storm", "snow")
    return False


def _draw_suns(
    draw, axis, sky_y0, ink: Inks, weather, latitude, longitude, tz, altitude, slots=()
) -> list[float]:
    """A sun at each solar noon, as high in the band as it will climb; returns their x.

    A noon under an overcast or wet slot gets no sun — its clouds are the sky.
    """
    xs: list[float] = []
    for noon, peak in solar_noons(axis, weather, latitude, longitude, tz, altitude):
        if sun_hidden(slots, noon):
            continue
        x = axis.x(noon)
        cy = sky_y0 + 16 + 44 * (1 - min(peak, 90.0) / 90.0) + 14
        r = 13
        body = ink.yellow if ink.colour else ink.white
        for i in range(12):
            a = math.radians(i * 30 + 15)
            r0, r1 = r + 5, r + (12 if i % 2 == 0 else 8)
            draw.line(
                (
                    x + r0 * math.cos(a),
                    cy + r0 * math.sin(a),
                    x + r1 * math.cos(a),
                    cy + r1 * math.sin(a),
                ),
                fill=ink.yellow if ink.colour else ink.black,
                width=3,
            )
        draw.ellipse((x - r, cy - r, x + r, cy + r), fill=body, outline=ink.black, width=2)
        xs.append(x)
    return xs


def _draw_midnights_in_sky(draw, axis: TimeAxis, alt, sky_y0: int, sky_y1: int, ink: Inks) -> None:
    for x, _day in _midnights(axis):
        fill = ink.white if _is_dark(alt, int(axis.x0), x) else ink.black
        _dotted_vline(draw, int(round(x)), sky_y0, sky_y1, fill, gap=4)


def _midnights(axis: TimeAxis) -> list[tuple[float, date]]:
    out = []
    day = axis.start.date() + timedelta(days=1)
    while True:
        t = datetime.combine(day, datetime.min.time())
        if t >= axis.end:
            break
        out.append((axis.x(t), day))
        day += timedelta(days=1)
    return out


# --- clouds and precipitation ---------------------------------------------


def sky_kind(icon: str | None) -> tuple[int, str]:
    """``(cloud level 0-3, precipitation)`` for an OWM icon code.

    Precipitation is one of ``""``, ``"rain"``, ``"storm"``, ``"snow"``,
    ``"fog"``.
    """
    code = (icon or "")[:2]
    return {
        "01": (0, ""),
        "02": (1, ""),
        "03": (2, ""),
        "04": (3, ""),
        "09": (3, "rain"),
        "10": (2, "rain"),
        "11": (3, "storm"),
        "13": (3, "snow"),
        "50": (1, "fog"),
    }.get(code, (0, ""))


CLOUD_TOP = 10  # offset of the cloud row from the top of the sky
CLOUD_ROW_H = 58


def _cloud_mask(w: int, h: int, rng: random.Random) -> Image.Image:
    """A cumulus silhouette: a flat base under bumps that rise toward the middle."""
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    base = h - 2
    d.rounded_rectangle((1, base - h * 0.34, w - 2, base), radius=int(h * 0.17), fill=255)
    n = rng.randint(3, 5)
    for i in range(n):
        f = (i + 0.5) / n
        cx = w * f + rng.uniform(-w * 0.04, w * 0.04)
        r = h * (0.20 + 0.26 * math.sin(math.pi * f)) * rng.uniform(0.9, 1.12)
        r = min(r, (base - h * 0.2) / 1.6)
        cy = max(r + 1, base - h * 0.26 - r * 0.6)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    return mask


def _paste_cloud(image, x: float, y: float, mask: Image.Image, dark_sky: bool, ink: Inks):
    """Draw a cloud as an engraving: solid ground, ruled edge, screened shading.

    By day it is paper ruled in ink and shaded toward its base; by night it is
    ink ruled in white with a screened, moonlit top — either way it reads
    against the sky behind it.
    """
    w, h = mask.size
    x0, y0 = int(round(x)), int(round(y))
    m = np.asarray(mask)
    ground, tone = (ink.black, ink.white) if dark_sky else (ink.white, ink.black)
    image.paste(Image.new(image.mode, (w, h), ground), (x0, y0), mask)
    rows = np.linspace(0.0, 1.0, h)[:, None]
    cover = (
        np.clip((0.55 - rows) * 0.7, 0, 0.3) if dark_sky else np.clip((rows - 0.5) * 0.8, 0, 0.36)
    )
    thr = bayer_field(w, h, x0, y0)
    shade = np.where(thr < cover, 255, 0).astype(np.uint8)
    image.paste(
        Image.new(image.mode, (w, h), tone),
        (x0, y0),
        Image.fromarray(np.minimum(shade, m), mode="L"),
    )
    edge = m.astype(np.int16) - np.asarray(mask.filter(ImageFilter.MinFilter(5)))
    image.paste(
        Image.new(image.mode, (w, h), tone),
        (x0, y0),
        Image.fromarray(np.clip(edge, 0, 255).astype(np.uint8), mode="L"),
    )


# Horizontal advance between clouds, in cloud widths, by cloud level: a few
# clouds, scattered, then overlapping into overcast.
_CLOUD_ADVANCE = {1: 2.8, 2: 1.5, 3: 0.7}
SUN_CLEARANCE = 22  # a partly cloudy sky keeps its clouds this far off the sun


def _draw_sky_weather(
    image, draw, axis: TimeAxis, alt, slots, sky_y0: int, ink: Inks, bodies: list[float]
) -> None:
    """Clouds, rain, snow, lightning and fog over each forecast slot's span.

    Each slot walks its own span with a generator seeded by the slot's clock
    hour, so a cloud belongs to a moment: as the window moves on, the sky moves
    with it rather than being re-dealt.
    """
    for t, h in slots:
        end = t + timedelta(hours=SLOT_HOURS)
        if end <= axis.start or t >= axis.end:
            continue
        level, precip = sky_kind(h.icon)
        xa, xb = axis.x(max(t, axis.start)), axis.x(min(end, axis.end))
        rng = random.Random(_hour_index(t) * 104729 + 3)
        if precip == "fog":
            dark = _is_dark(alt, int(axis.x0), (xa + xb) / 2)
            mark = ink.white if dark else ink.black
            for i in range(4):
                fy = sky_y0 + SKY_H * (0.52 + 0.1 * i)
                off = (i * 5) % 10
                for fx in range(int(xa) + off, int(xb) - 6, 12):
                    draw.line((fx, fy, fx + 7, fy), fill=mark, width=2)
            continue
        if level == 0:
            continue
        x = xa + rng.uniform(0, 18)
        first_cloud = None
        while x < xb:
            w = int(rng.uniform(58, 92) * (1.2 if level == 3 else 1.0))
            ch = int(w * rng.uniform(0.40, 0.50))
            cy = sky_y0 + CLOUD_TOP + rng.uniform(0, max(1, CLOUD_ROW_H - ch))
            clear = (
                level == 3
                or bool(precip)
                or all(abs(x - sx) > SUN_CLEARANCE + w / 2 for sx in bodies)
            )
            if clear:
                dark = _is_dark(alt, int(axis.x0), x)
                _paste_cloud(image, x - w / 2, cy, _cloud_mask(w, ch, rng), dark, ink)
                mark = ink.white if dark else ink.black
                base = cy + ch
                if precip in ("rain", "storm"):
                    heavy = (h.precip_mm or 0) >= 2 or precip == "storm"
                    for sx in range(int(x - w / 2 + 8), int(x + w / 2 - 6), 5 if heavy else 8):
                        sy = base + 3 + rng.uniform(0, 8)
                        ln = rng.uniform(9, 17)
                        draw.line((sx, sy, sx - 4, sy + ln), fill=mark, width=2 if heavy else 1)
                elif precip == "snow":
                    for _ in range(int(w / 5)):
                        sx = rng.uniform(x - w / 2 + 6, x + w / 2 - 6)
                        sy = base + 4 + rng.uniform(0, 30)
                        draw.ellipse((sx - 1.5, sy - 1.5, sx + 1.5, sy + 1.5), fill=mark)
                if first_cloud is None:
                    first_cloud = (x, base)
            x += w * _CLOUD_ADVANCE[level] * rng.uniform(0.85, 1.15)
        if precip == "storm" and first_cloud is not None:
            cx, by = first_cloud
            bolt = [
                (cx + 3, by - 2),
                (cx - 7, by + 18),
                (cx + 1, by + 18),
                (cx - 9, by + 40),
                (cx + 12, by + 12),
                (cx + 4, by + 12),
                (cx + 12, by - 2),
            ]
            draw.polygon(bolt, fill=ink.yellow if ink.colour else ink.white, outline=ink.black)


# --- temperature ------------------------------------------------------------


def _draw_temperature(draw, axis: TimeAxis, alt, slots, sky_x0: int, sky_y0: int, ink: Inks):
    if len(slots) < 2:
        return
    lo, hi = temp_scale([h.temp for _, h in slots])
    top = sky_y0 + SKY_H * CURVE_TOP
    bottom = sky_y0 + SKY_H * CURVE_BOTTOM

    def y_of(temp: float) -> float:
        return bottom - (temp - lo) / (hi - lo) * (bottom - top)

    def x_of(t: datetime) -> float:
        # Unclamped, so the neighbours outside the window keep the curve's slope.
        h = (t - axis.start).total_seconds() / 3600.0
        if 0 <= h <= axis.hours:
            return axis.x(t)
        per = axis.px_per_hour(t.hour)
        return axis.x0 + h * per if h < 0 else axis.x1 + (h - axis.hours) * per

    pts = [(x_of(t), y_of(h.temp)) for t, h in slots]
    curve = [(x, y) for x, y in catmull_rom(pts) if axis.x0 - 2 <= x <= axis.x1 + 2]
    if len(curve) < 2:
        return
    core = ink.red if ink.colour else ink.black
    draw.line(curve, fill=ink.white, width=10, joint="curve")
    draw.line(curve, fill=core, width=4, joint="curve")

    font = fonts.big_shoulders_extrabold(30)
    for kind, t, temp in daily_extremes(slots, axis):
        x, y = axis.x(t), y_of(temp)
        text = f"{round(temp)}°"
        box = _text_box(draw, text, font)
        tw, th = box[2] - box[0], box[3] - box[1]
        ty = y - th - 12 if kind == "high" else y + 10
        ty = max(sky_y0 + 4, min(ty, sky_y0 + SKY_H - th - 4))
        tx = max(axis.x0 + 2, min(x - tw / 2, axis.x1 - tw - 2))
        dark = _is_dark(alt, sky_x0, x)
        fg, halo = (ink.white, ink.black) if dark else (ink.black, ink.white)
        draw.text(
            (tx - box[0], ty - box[1]),
            text,
            font=font,
            fill=fg,
            stroke_width=3,
            stroke_fill=halo,
        )
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=ink.white, outline=core, width=2)


# --- rain -------------------------------------------------------------------


def rain_cover(mm: float | None, chance: float) -> float:
    """Screen density for a rain bar: the expected amount, or the chance without one."""
    if mm is None:
        return 0.25 + 0.35 * chance
    return float(min(1.0, 0.3 + mm / 4.0))


def _draw_rain(image, draw, axis: TimeAxis, slots, y0: int, ink: Inks) -> None:
    font = fonts.dm_semibold(11)
    stretches: list[list[tuple[float, float, float]]] = []
    current: list[tuple[float, float, float]] = []
    for t, h in slots:
        chance = h.precip_chance or 0.0
        end = t + timedelta(hours=SLOT_HOURS)
        if end <= axis.start or t >= axis.end or chance < 0.05:
            if current:
                stretches.append(current)
                current = []
            continue
        x0, x1 = axis.x(t), axis.x(end)
        depth = max(2.0, (RAIN_H - 12) * chance)
        _dither_rect(
            image, (x0 + 1, y0, x1, y0 + depth), rain_cover(h.precip_mm, chance), ink.black
        )
        draw.line((x0 + 1, y0 + depth, x1 - 1, y0 + depth), fill=ink.black, width=1)
        current.append((x0, x1, chance))
    if current:
        stretches.append(current)
    for run in stretches:
        x0, x1, peak = max(run, key=lambda r: r[2])
        if peak < 0.3:
            continue
        label = f"{round(peak * 100)}%"
        tw = text_width(draw, label, font)
        cx = max(axis.x0 + tw / 2 + 2, min((x0 + x1) / 2, axis.x1 - tw / 2 - 2))
        depth = max(2.0, (RAIN_H - 12) * peak)
        draw.text((cx - tw / 2, y0 + depth + 1), label, font=font, fill=ink.black)


# --- axis -------------------------------------------------------------------


def _draw_hours(draw, axis: TimeAxis, y0: int, ink: Inks) -> None:
    font = fonts.dm_semibold(12)
    draw.line((axis.x0, y0, axis.x1, y0), fill=ink.black, width=1)
    t = axis.start.replace(minute=0)
    while t <= axis.end:
        if t.hour in (6, 12, 18):
            x = axis.x(t)
            draw.line((x, y0, x, y0 + 4), fill=ink.black, width=1)
            label = fmt_time(t)
            tw = text_width(draw, label, font)
            if axis.x0 + 2 <= x - tw / 2 and x + tw / 2 <= axis.x1 - 2:
                draw.text((x - tw / 2, y0 + 4), label, font=font, fill=ink.black)
        t += timedelta(hours=1)


def _draw_day_headers(draw, axis: TimeAxis, y0: int, now: datetime, ink: Inks) -> None:
    font = fonts.big_shoulders_black(34)
    small = fonts.dm_bold(13)
    starts = [(axis.x0, axis.start.date())] + _midnights(axis)
    for i, (x, day) in enumerate(starts):
        x_end = starts[i + 1][0] if i + 1 < len(starts) else axis.x1
        if i > 0:
            draw.line((x, y0, x, y0 + HEAD_H), fill=ink.black, width=2)
        if day == now.date():
            # Keyed to the window's slot, not the clock, so the switch lands on
            # a repaint the plate makes anyway.
            name = "TONIGHT" if axis.start.hour >= 18 else "TODAY"
        elif day == now.date() + timedelta(days=1):
            name = "TOMORROW"
        else:
            name = day.strftime("%A").upper()
        room = x_end - x - 16
        tw = text_width(draw, name, font)
        date_label = day.strftime("%b %-d").upper()
        dw = text_width(draw, date_label, small)
        if tw > room:
            name = day.strftime("%a").upper()
            tw = text_width(draw, name, font)
        if tw > room:
            continue
        fill = ink.red if (day == now.date() and ink.colour) else ink.black
        box = _text_box(draw, name, font)
        draw.text((x + 8 - box[0], y0 + 6 - box[1]), name, font=font, fill=fill)
        if tw + dw + 10 <= room:
            draw.text((x + 8 + tw + 8, y0 + 20), date_label, font=small, fill=ink.black)


# --- events -----------------------------------------------------------------


def _draw_events(draw, data: DashboardData, axis: TimeAxis, y0: int, y1: int, ink: Inks):
    # Midnight rules and hour hairlines through the events band.
    for x, _day in _midnights(axis):
        draw.line((x, y0 - EVENTS_GAP - HOURS_H - RAIN_H, x, y1), fill=ink.black, width=2)
    t = axis.start
    while t <= axis.end:
        if t.hour in (6, 12, 18):
            _dotted_vline(draw, int(round(axis.x(t))), y0, y1, ink.black, gap=4)
        t += timedelta(hours=1)

    y = y0
    allday = allday_in_window(data.events, data.birthdays, axis)
    font_ad = fonts.dm_bold(13)
    if allday:
        items = []
        for start, end, label, bday in allday:
            x0, x1 = axis.x(start), axis.x(end)
            lw = text_width(draw, label, font_ad) + 16
            items.append((x0, max(x1, x0 + lw), (x0, x1, label, bday)))
        rows = pack_lanes(items)[:2]
        for row in rows:
            for x0, x1, label, bday in row:
                bx0, bx1 = x0 + 2, x1 - 3
                if bday:
                    draw.rectangle(
                        (bx0, y, bx1, y + ALLDAY_H - 4), fill=ink.white, outline=ink.red, width=2
                    )
                    fill_t = ink.red
                else:
                    draw.rectangle((bx0, y, bx1, y + ALLDAY_H - 4), fill=ink.red)
                    fill_t = ink.white
                if bx1 - bx0 >= MIN_CHIP_LABEL_W:
                    draw_text_truncated(
                        draw, (bx0 + 7, y + 2), label, font_ad, bx1 - bx0 - 12, fill=fill_t
                    )
            y += ALLDAY_H

    lanes_avail = max(0, (y1 - y) // LANE_H)
    events = events_in_window(data.events, axis)
    if not events or lanes_avail == 0:
        return

    title_font = fonts.dm_bold(15)
    time_font = fonts.dm_medium(12)
    items = []
    for evt in events:
        x0, x1 = axis.x(evt.start), axis.x(evt.end)
        x1 = max(x1, x0 + 6)
        title, when = event_label(evt)
        need = max(text_width(draw, title, title_font), text_width(draw, when, time_font)) + 14
        inside = (x1 - x0) >= need
        extent = x1 if inside else x1 + LABEL_PAD + min(need, MAX_BESIDE_LABEL_W)
        items.append((x0, min(extent, axis.x1) + 4, (evt, x0, x1, inside)))
    lanes = pack_lanes(items)
    shown = lanes[:lanes_avail]
    hidden = [it for lane in lanes[lanes_avail:] for it in lane]

    for li, lane in enumerate(shown):
        ly = y + li * LANE_H
        for evt, x0, x1, inside in lane:
            title, when = event_label(evt)
            clipped_left = evt.start < axis.start
            draw.rectangle((x0 + 1, ly, x1 - 1, ly + BAR_H - 1), fill=ink.black)
            if clipped_left:
                draw.polygon(
                    [(x0 + 1, ly), (x0 + 7, ly + BAR_H / 2), (x0 + 1, ly + BAR_H - 1)],
                    fill=ink.white,
                )
            if inside:
                tx, room, fill = x0 + 7, x1 - x0 - 12, ink.white
            else:
                tx, fill = x1 + LABEL_PAD, ink.black
                room = min(MAX_BESIDE_LABEL_W, axis.x1 - tx - 4)
                if room < MIN_BESIDE_LABEL_W:
                    continue
            draw_text_truncated(draw, (tx, ly - 2), title, title_font, room, fill=fill)
            draw_text_truncated(draw, (tx, ly + 14), when, time_font, room, fill=fill)

    if hidden:
        by_day: dict[date, int] = {}
        for evt, *_ in hidden:
            by_day[evt.start.date()] = by_day.get(evt.start.date(), 0) + 1
        font = fonts.dm_bold(12)
        for day, n in by_day.items():
            end = datetime.combine(day + timedelta(days=1), datetime.min.time())
            label = f"+{n} more"
            tw = text_width(draw, label, font)
            x = min(axis.x(end), axis.x1) - tw - 6
            draw.text((x, y1 - 14), label, font=font, fill=ink.red if ink.colour else ink.black)


# --- hero -------------------------------------------------------------------


def outlook(slots, axis: TimeAxis) -> list[tuple[str, str]]:
    """Three facts about the window worth reading without the chart."""
    inside = [(t, h) for t, h in slots if axis.start <= t < axis.end]
    if not inside:
        return []
    rows: list[tuple[str, str]] = []
    t_hi, h_hi = max(inside, key=lambda p: p[1].temp)
    t_lo, h_lo = min(inside, key=lambda p: p[1].temp)
    rows.append(("WARMEST", f"{_when(t_hi)} · {round(h_hi.temp)}°"))
    rows.append(("COLDEST", f"{_when(t_lo)} · {round(h_lo.temp)}°"))
    wet = [(t, h) for t, h in inside if (h.precip_chance or 0) >= 0.3]
    if wet:
        first_t = wet[0][0]
        run = [wet[0]]
        for t, h in wet[1:]:
            if t - run[-1][0] <= timedelta(hours=SLOT_HOURS):
                run.append((t, h))
            else:
                break
        last_end = run[-1][0] + timedelta(hours=SLOT_HOURS)
        peak = max((h.precip_chance or 0) for _, h in run)
        until = "midnight" if last_end.hour == 0 else fmt_time(last_end)
        span = f"{_when(first_t)}–{until}"
        rows.append(("RAIN", f"{span} · {round(peak * 100)}%"))
    else:
        rows.append(("RAIN", "none in sight"))
    return rows


def _when(t: datetime) -> str:
    return f"{t.strftime('%a')} {fmt_time(t)}"


def _draw_hero(
    draw,
    data: DashboardData,
    now: datetime,
    tz,
    rx: int,
    ry: int,
    rh: int,
    ink: Inks,
    weather,
    slots=(),
    axis: TimeAxis | None = None,
):
    x0, x1 = rx, rx + HERO_W
    draw.rectangle((x0, ry, x1 - 1, ry + rh - 1), fill=ink.black)
    left = x0 + PAD + 2
    width = HERO_W - 2 * PAD - 4
    white = ink.white
    accent = ink.yellow if ink.colour else white

    label_font = fonts.dm_bold(13)
    draw.text((left, ry + 14), "NOW", font=label_font, fill=accent)
    if weather is None:
        big = fonts.big_shoulders_black(44)
        draw.text((left, ry + 40), "NO DATA", font=big, fill=white)
        _draw_hero_foot(draw, data, now, tz, left, width, ry + rh, white)
        return

    temp = f"{round(weather.current_temp)}°"
    pt = HERO_TEMP_PT
    big = fonts.big_shoulders_black(pt)
    box = _text_box(draw, temp, big)
    while box[2] - box[0] > width and pt > 48:
        pt -= 8
        big = fonts.big_shoulders_black(pt)
        box = _text_box(draw, temp, big)
    draw.text((left - box[0], ry + 34 - box[1]), temp, font=big, fill=white)

    y = ry + 34 + (box[3] - box[1]) + 14
    cond = fonts.big_shoulders_extrabold(30)
    draw_text_truncated(
        draw, (left, y), weather.current_description.upper(), cond, width, fill=white
    )
    y += 36
    body = fonts.dm_semibold(15)
    draw.text(
        (left, y), f"H {round(weather.high)}°   L {round(weather.low)}°", font=body, fill=white
    )
    y += 22
    extras = []
    if weather.feels_like is not None:
        extras.append(f"Feels {round(weather.feels_like)}°")
    if weather.wind_speed is not None:
        wind = f"{round(weather.wind_speed)} {wind_unit(weather)}"
        if weather.wind_deg is not None:
            wind += f" {deg_to_compass(weather.wind_deg)}"
        extras.append(wind)
    if extras:
        draw_text_truncated(
            draw, (left, y), "  ·  ".join(extras), fonts.dm_medium(14), width, fill=white
        )
        y += 22
    if weather.sunrise is not None and weather.sunset is not None:
        rise = fmt_time(to_local_naive(weather.sunrise, tz))
        down = fmt_time(to_local_naive(weather.sunset, tz))
        draw.text((left, y), f"↑ {rise}    ↓ {down}", font=fonts.dm_medium(14), fill=white)
        y += 26

    if weather.alerts:
        alert = weather.alerts[0].event.upper()
        bar_fill = ink.red if ink.colour else white
        text_fill = white if ink.colour else ink.black
        draw.rectangle((left - 4, y, x1 - PAD, y + 24), fill=bar_fill)
        draw_text_truncated(
            draw, (left + 2, y + 4), f"! {alert}", fonts.dm_bold(13), width - 4, fill=text_fill
        )
        y += 30

    rows = outlook(list(slots), axis) if axis is not None else []
    if rows:
        label_font = fonts.dm_bold(11)
        value_font = fonts.big_shoulders_extrabold(23)
        oy = max(y + 8, ry + rh - 36 - 44 * len(rows))
        draw.line((left, oy - 8, x1 - PAD, oy - 8), fill=white, width=1)
        for label, value in rows:
            draw.text((left, oy), label, font=label_font, fill=accent)
            draw_text_truncated(draw, (left, oy + 13), value, value_font, width, fill=white)
            oy += 44

    _draw_hero_foot(draw, data, now, tz, left, width, ry + rh, white)


def _draw_hero_foot(draw, data: DashboardData, now: datetime, tz, left, width, bottom, fill):
    font = fonts.dm_medium(12)
    stamp = content_time(data, now)
    if stamp.tzinfo is not None:
        stamp = to_local_naive(stamp, tz)
    parts = []
    if data.weather and data.weather.location_name:
        parts.append(data.weather.location_name)
    parts.append(f"updated {fmt_time(stamp)}")
    draw_text_truncated(draw, (left, bottom - 24), "  ·  ".join(parts), font, width, fill=fill)
