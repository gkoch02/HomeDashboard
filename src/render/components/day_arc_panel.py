"""Full-canvas day-ribbon + agenda plate for the ``day_arc`` theme.

``day_arc`` is the calendar-forward sibling of ``halftone``. It keeps that
theme's engraving language — procedural greyscale gradients quantized to a
Floyd-Steinberg halftone, solid-ink typography, ordered-Bayer rules — but
re-tasks the artwork so it *is* the calendar rather than competing with it.

Three bands, top to bottom:

  * **Ribbon** (160 px) — a horizontal sky gradient tracking the sun's height
    across today, with the sun (or moon, after dark) riding an arc at the
    current time's real horizontal position and weather art drawn around it.
  * **Axis strip** (40 px) — the ribbon's baseline doubles as a time axis:
    a daylight bar, hour ticks, a NOW caret, one pip per timed event and the
    hour labels, so the shape of the day is readable at a glance. Each of
    those gets its own exclusive row band; see the ``_AXIS_*`` constants.
  * **Body** (274 px) — a full-height agenda on the left and a supporting rail
    (temperature, conditions, birthdays) on the right.

Dithering carries meaning in the agenda rather than being decoration: elapsed
events are perforated on a Bayer lattice so they read as spent, the event
happening right now is inverted into a solid bar, and everything still to come
is crisp. See :func:`src.render.skyart.screened_paste` for why the screening is
applied after typesetting rather than by drawing in mid-grey.

After sunset the ribbon goes dark and, once every one of today's timed events
has ended, the agenda rolls over to tomorrow behind an inverted ``TOMORROW``
chip. The ribbon always depicts *now*; the agenda depicts what is next.

No external assets — every illustration is generated from PIL primitives.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from PIL import Image, ImageDraw

from src.astronomy import sun_times
from src.data.models import Birthday, CalendarEvent, DashboardData, WeatherData
from src.render.artkit import accent_red as _accent_red
from src.render.artkit import grey as _grey
from src.render.artkit import ink as _ink
from src.render.artkit import to_local_naive
from src.render.fonts import weather_icon
from src.render.moon import moon_phase_age
from src.render.moon_render import MoonTones, render_moon_disc
from src.render.primitives import (
    draw_text_truncated,
    events_for_day,
    fmt_time,
    text_height,
    text_width,
)
from src.render.skyart import (
    accent_yellow as _accent_yellow,
)
from src.render.skyart import (
    draw_bayer_rule,
    draw_cloud,
    draw_lightning,
    draw_precip,
    illustration_kind,
    radial_gradient_disc,
    screened_paste,
)
from src.render.theme import ComponentRegion, ThemeStyle

# Weather Icons glyphs — the text faces used here have no ↑/↓ arrows, so the
# footer borrows these two from the bundled Weather Icons font.
_SUNRISE_GLYPH = ""  # wi-sunrise
_SUNSET_GLYPH = ""  # wi-sunset

# ---------------------------------------------------------------------------
# Region geometry
# ---------------------------------------------------------------------------

SKY_H = 160  # dithered sky + disc + weather art
AXIS_Y = SKY_H  # solid horizon hairline sits on this row
AXIS_H = 40  # paper-white strip carrying ticks, pips, the caret and labels
RIBBON_H = SKY_H + AXIS_H  # 200
RULE_H = 6  # ordered-Bayer separator
BODY_Y = RIBBON_H + RULE_H  # 206
FOOTER_H = 22  # bottom caption strip ("↑ sunrise ↓ sunset … updated")

PAD_X = 20
AGENDA_W = 548  # left column: the promoted content
DIVIDER_X = 550
RAIL_X = 568  # right rail content starts here
RAIL_W = 212

# The axis strip is white so every tick, pip and label can be drawn in solid
# ink. Marks drawn onto the sky itself would vanish into the night gradient at
# one end of the day and wash out against the midday band at the other.
#
# Every element gets an *exclusive* row band, all offsets relative to AXIS_Y.
# They used to share rows, which made collisions a matter of luck: an event
# starting on the hour puts its pip at exactly the x its hour label is centred
# on, so the two could only ever land on top of each other. Keep these bands
# disjoint — ``TestAxisStripBands`` fails the build if they stop being so.
#
#   y+0            baseline hairline
#   y+2  … y+4     daylight bar
#   y+6  … y+14    hour ticks + NOW caret
#   y+16 … y+24    event pips
#   y+26 … y+27    in-progress duration bar
#   y+28 … y+38    hour labels (glyph ink lands ~3 px below the draw origin)
_AXIS_BAR_Y = 2
_AXIS_BAR_H = 3
_AXIS_TICK_Y = 6
_AXIS_TICK_MAJOR_H = 8
_AXIS_TICK_MINOR_H = 4
# The caret shares the tick row on purpose: it marks the current moment *on the
# timeline*, so it belongs with the ticks, and the 1 px of tick it covers where
# they coincide is a non-loss.
_AXIS_CARET_H = 9
_AXIS_CARET_HALF_W = 8
_AXIS_PIP_Y = 16
_AXIS_PIP_H = 9
_AXIS_DUR_Y = 26
_AXIS_DUR_H = 2
_AXIS_LABEL_Y = 28
_AXIS_LABEL_PT = 11

# Sky tones. Chosen inside halftone's proven range: Floyd-Steinberg only reads
# as a visible halftone well below mid-grey, so the midday peak stays dark
# enough to dither while the sun disc (255→210) still punches through it.
_SKY_NIGHT = 40
_SKY_HORIZON = 96
_SKY_NOON = 150
_SKY_STORM_DROP = 30
# After sunset the whole ramp is scaled by this so the ribbon reads as dark at
# a glance without flattening the day's shape out of it.
_NIGHT_DIM = 0.45

# Disc placement. The disc rides a sine arc between sunrise and sunset so its
# height encodes solar altitude — a second reading for free.
DISC_R = 34
DISC_BASE_Y = 120  # centre y at sunrise / sunset — 6 px clear of the baseline
DISC_ARC_RISE = 66  # additional rise at solar midpoint (peak centre y = 54)

# Axis window shaping.
DAY_FRACTION = 0.78  # share of the axis width given to the daylight core
MIN_MARGIN_FR = 0.06  # floor for each non-empty night margin
AXIS_MIN_HOUR = 4  # never start the axis before 04:00 local
AXIS_MAX_HOUR = 24  # never run past midnight

# Bayer cut for elapsed content: retains roughly 60% of the ink.
_PAST_SCREEN = 96
_MORE_SCREEN = 96

# Rollover falls back to this hour when no sunset is available.
_FALLBACK_DUSK_HOUR = 18

# RNG salts. Distinct from halftone's so the two themes don't share a star
# field. Seeds are derived from ``today.toordinal()`` rather than ``hash()``
# because ``str.__hash__`` is randomised per process and pixel snapshots
# depend on these fields being reproducible.
_STAR_SALT = 0xDA7
_FOG_SALT = 0xF0A


# ---------------------------------------------------------------------------
# Time axis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeAxis:
    """Piecewise-linear time → x map for the ribbon.

    The axis is split into three linear segments — pre-dawn margin, daylight
    core, post-dusk margin — with the daylight core given ``DAY_FRACTION`` of
    the width regardless of season. A purely linear axis would shrink the
    midwinter arc to a third of the ribbon; compressing the night margins
    instead keeps the day's shape legible year-round while still placing a
    20:00 dinner at a truthful position.

    All datetimes are naive local. ``sunrise``/``sunset`` are ``None`` when the
    day has no usable sun data (polar latitudes, or no location and no weather),
    in which case the map degrades to a single linear segment.
    """

    start: datetime
    end: datetime
    sunrise: datetime | None
    sunset: datetime | None
    civil_dawn: datetime | None
    civil_dusk: datetime | None
    x0: int
    x1: int
    dawn_w: int
    day_w: int
    dusk_w: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    def x_for(self, dt: datetime) -> int:
        """Pixel x for *dt*, clamped to ``[x0, x1]``. Never raises."""
        if dt <= self.start:
            return self.x0
        if dt >= self.end:
            return self.x1
        if self.sunrise is None or self.sunset is None:
            span = (self.end - self.start).total_seconds()
            frac = (dt - self.start).total_seconds() / max(1.0, span)
            return self.x0 + int(round(self.width * frac))

        if dt < self.sunrise:
            span = (self.sunrise - self.start).total_seconds()
            frac = (dt - self.start).total_seconds() / max(1.0, span)
            return self.x0 + int(round(self.dawn_w * frac))
        if dt <= self.sunset:
            span = (self.sunset - self.sunrise).total_seconds()
            frac = (dt - self.sunrise).total_seconds() / max(1.0, span)
            return self.x0 + self.dawn_w + int(round(self.day_w * frac))
        span = (self.end - self.sunset).total_seconds()
        frac = (dt - self.sunset).total_seconds() / max(1.0, span)
        return self.x0 + self.dawn_w + self.day_w + int(round(self.dusk_w * frac))


def _floor_hour(dt: datetime) -> datetime:
    """Round *dt* down to the hour."""
    return dt.replace(minute=0, second=0, microsecond=0)


def _ceil_hour(dt: datetime) -> datetime:
    """Round *dt* up to the hour."""
    floored = dt.replace(minute=0, second=0, microsecond=0)
    return floored if floored == dt else floored + timedelta(hours=1)


def build_time_axis(
    today: date,
    now: datetime,
    events: list[CalendarEvent],
    sunrise: datetime | None,
    sunset: datetime | None,
    civil_dawn: datetime | None,
    civil_dusk: datetime | None,
    x0: int,
    x1: int,
) -> TimeAxis:
    """Build the ribbon's time axis. Pure — every input is already naive local.

    *events* must already be filtered to *today*: the bounds expand to cover
    them, so passing a whole week would stretch the axis across several days.

    Bounds expand to cover the day's events (within ``AXIS_MIN_HOUR`` and
    ``AXIS_MAX_HOUR``) so no pip is ever clamped off the end of a real day.
    """
    midnight = datetime.combine(today, time())
    floor_limit = midnight + timedelta(hours=AXIS_MIN_HOUR)
    ceil_limit = midnight + timedelta(hours=AXIS_MAX_HOUR)
    usable = sunrise is not None and sunset is not None and sunset > sunrise

    lo = midnight + timedelta(hours=5)
    hi = midnight + timedelta(hours=23)
    if usable:
        assert sunrise is not None and sunset is not None
        lo = sunrise - timedelta(hours=1)
        hi = sunset + timedelta(hours=1)

    for ev in events:
        if ev.is_all_day:
            continue
        lo = min(lo, _strip_tz(ev.start))
        hi = max(hi, _strip_tz(ev.end))
    lo = min(lo, now)
    hi = max(hi, now)

    # Hard-clamp to today. Sun times, an overrunning event or a stale ``now``
    # can all sit outside the day; the ribbon only ever depicts one day.
    start = max(_floor_hour(lo), floor_limit)
    end = min(_ceil_hour(hi), ceil_limit)
    if end <= start:
        end = min(start + timedelta(hours=1), ceil_limit)
    if end <= start:
        start = floor_limit
        end = ceil_limit

    total = max(1, x1 - x0)
    if not usable or not (start < sunrise < sunset < end):  # type: ignore[operator]
        # Single linear segment. Also covers a sunrise/sunset pair that the
        # expanded bounds swallowed (an all-night event, say).
        if usable:
            assert sunrise is not None and sunset is not None
            sr = min(max(sunrise, start), end)
            ss = min(max(sunset, start), end)
        else:
            sr = ss = None  # type: ignore[assignment]
        return TimeAxis(
            start=start,
            end=end,
            sunrise=sr,
            sunset=ss,
            civil_dawn=civil_dawn,
            civil_dusk=civil_dusk,
            x0=x0,
            x1=x1,
            dawn_w=0,
            day_w=total,
            dusk_w=0,
        )

    assert sunrise is not None and sunset is not None
    dawn_dur = (sunrise - start).total_seconds()
    dusk_dur = (end - sunset).total_seconds()
    day_w = int(total * DAY_FRACTION)
    rem = total - day_w
    if dawn_dur <= 0 and dusk_dur <= 0:
        dawn_w = dusk_w = 0
    elif dawn_dur <= 0:
        dawn_w, dusk_w = 0, rem
    elif dusk_dur <= 0:
        dawn_w, dusk_w = rem, 0
    else:
        floor = int(total * MIN_MARGIN_FR)
        dawn_w = int(rem * dawn_dur / (dawn_dur + dusk_dur))
        dawn_w = max(floor, min(rem - floor, dawn_w))
        dusk_w = rem - dawn_w
    day_w = total - dawn_w - dusk_w

    return TimeAxis(
        start=start,
        end=end,
        sunrise=sunrise,
        sunset=sunset,
        civil_dawn=civil_dawn,
        civil_dusk=civil_dusk,
        x0=x0,
        x1=x1,
        dawn_w=dawn_w,
        day_w=day_w,
        dusk_w=dusk_w,
    )


def _resolve_day_bounds(
    today: date,
    weather: WeatherData | None,
    latitude: float | None,
    longitude: float | None,
    tz: tzinfo | None,
) -> tuple[datetime | None, datetime | None, datetime | None, datetime | None]:
    """Return ``(civil_dawn, sunrise, sunset, civil_dusk)`` as naive local times.

    Prefers computed values from :mod:`src.astronomy` when a location is set,
    and falls back to the OWM-reported sunrise/sunset otherwise. Exact
    ``(0.0, 0.0)`` counts as unset — the same convention the ``astronomy`` and
    ``light_cycle`` panels use.
    """
    if latitude is not None and longitude is not None and (latitude, longitude) != (0.0, 0.0):
        st = sun_times(today, latitude, longitude)
        if st.sunrise is not None and st.sunset is not None:
            return (
                to_local_naive(st.civil_dawn, tz) if st.civil_dawn else None,
                to_local_naive(st.sunrise, tz),
                to_local_naive(st.sunset, tz),
                to_local_naive(st.civil_dusk, tz) if st.civil_dusk else None,
            )
    if weather is not None and weather.sunrise is not None and weather.sunset is not None:
        sr = to_local_naive(weather.sunrise, tz)
        ss = to_local_naive(weather.sunset, tz)
        return (sr - timedelta(minutes=30), sr, ss, ss + timedelta(minutes=30))
    return (None, None, None, None)


# ---------------------------------------------------------------------------
# Sky
# ---------------------------------------------------------------------------


def _sky_marks(axis: TimeAxis) -> tuple[int, int, int, int, int]:
    """Return the x positions the sky gradient ramps between."""
    if axis.sunrise is None or axis.sunset is None:
        # No usable sun data: flatten the ramp so the whole band is one tone.
        return (axis.x0, axis.x0, axis.x0, axis.x1, axis.x1)
    x_sr = axis.x_for(axis.sunrise)
    x_ss = axis.x_for(axis.sunset)
    x_dawn = axis.x_for(axis.civil_dawn) if axis.civil_dawn else x_sr
    x_dusk = axis.x_for(axis.civil_dusk) if axis.civil_dusk else x_ss
    return (min(x_dawn, x_sr), x_sr, (x_sr + x_ss) // 2, x_ss, max(x_dusk, x_ss))


def _ramp(x: int, a: int, b: int, va: int, vb: int) -> int:
    if b <= a:
        return vb
    t = (x - a) / (b - a)
    return int(round(va + (vb - va) * t))


def sky_tone_at(
    x: int,
    marks: tuple[int, int, int, int, int],
    *,
    storm: bool = False,
    night: bool = False,
) -> int:
    """Sky value 0–255 at canvas column *x*. Pure — unit-tested for monotonicity.

    *night* dims the whole ramp rather than flattening it. After sunset the
    ribbon should read as dark at a glance, but the day's shape is the theme's
    whole point — collapsing it to a flat field would throw that away, so the
    arc survives at reduced contrast.
    """
    x_dawn, x_sr, x_mid, x_ss, x_dusk = marks
    peak = _SKY_NOON - (_SKY_STORM_DROP if storm else 0)
    horizon = _SKY_HORIZON
    floor = _SKY_NIGHT
    if night:
        peak = int(peak * _NIGHT_DIM)
        horizon = int(horizon * _NIGHT_DIM)
        floor = int(floor * _NIGHT_DIM)
    if x < x_dawn:
        v = floor
    elif x < x_sr:
        v = _ramp(x, x_dawn, x_sr, floor, horizon)
    elif x <= x_mid:
        v = _ramp(x, x_sr, x_mid, horizon, peak)
    elif x <= x_ss:
        v = _ramp(x, x_mid, x_ss, peak, horizon)
    elif x <= x_dusk:
        v = _ramp(x, x_ss, x_dusk, horizon, floor)
    else:
        v = floor
    return max(0, min(255, v))


def _draw_sky_ribbon(
    image: Image.Image,
    axis: TimeAxis,
    rect: tuple[int, int, int, int],
    *,
    storm: bool = False,
    night: bool = False,
) -> None:
    """Paint the horizontal day gradient into *rect*.

    Built as a 1-px-tall strip then ``NEAREST``-resized to full height — the
    same trick the vertical skies use, and much faster on a Pi than a nested
    per-pixel loop.
    """
    x0, y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - y0
    marks = _sky_marks(axis)
    strip = Image.new("L", (w, 1))
    for i in range(w):
        strip.putpixel((i, 0), sky_tone_at(x0 + i, marks, storm=storm, night=night))
    full = strip.resize((w, h), Image.Resampling.NEAREST)
    if image.mode == "RGB":
        full = full.convert("RGB")
    image.paste(full, (x0, y0))


def _draw_margin_stars(
    image: Image.Image,
    axis: TimeAxis,
    rect: tuple[int, int, int, int],
    today: date,
    *,
    night: bool = False,
) -> None:
    """Scatter stars into the dark parts of the ribbon.

    By day that means only the pre-dawn and post-dusk margins; after sunset the
    whole ribbon has dimmed, so the field spans it end to end.
    """
    x0, y0, x1, y1 = rect
    marks = _sky_marks(axis)
    bands = [(x0, x1)] if night else [(x0, marks[0]), (marks[4], x1)]
    draw = ImageDraw.Draw(image)
    rng = random.Random(today.toordinal() ^ _STAR_SALT)
    mode = image.mode
    bright = _grey(245, mode)
    medium = _grey(200, mode)
    for bx0, bx1 in bands:
        span = bx1 - bx0
        if span < 8:
            continue
        for _ in range(max(4, span // 6)):
            x = rng.randint(bx0 + 2, bx1 - 2)
            y = rng.randint(y0 + 6, y1 - 14)
            size = rng.choice((0, 0, 0, 1))
            fill = bright if size else medium
            if size == 0:
                draw.point((x, y), fill=fill)
            else:
                draw.rectangle((x, y, x + 1, y + 1), fill=fill)


# ---------------------------------------------------------------------------
# Ribbon artwork
# ---------------------------------------------------------------------------


def _disc_centre(axis: TimeAxis, now: datetime, y0: int) -> tuple[int, int]:
    """Return the sun/moon disc centre for *now* on the arc.

    The x is nudged inboard so a disc at the very start or end of the axis
    (the small hours, when the ribbon is showing night) still renders whole
    rather than being sliced by the canvas edge. The NOW caret on the axis
    strip below is never nudged, so the truthful time marker is unaffected.
    """
    cx = axis.x_for(now)
    cy = DISC_BASE_Y
    if axis.sunrise is not None and axis.sunset is not None and axis.sunrise <= now <= axis.sunset:
        span = (axis.sunset - axis.sunrise).total_seconds()
        t = (now - axis.sunrise).total_seconds() / max(1.0, span)
        cy = DISC_BASE_Y - int(DISC_ARC_RISE * math.sin(math.pi * t))
    cy = max(DISC_R + 20, min(cy, SKY_H - DISC_R - 6))
    margin = DISC_R + 6
    cx = max(axis.x0 + margin, min(cx, axis.x1 - margin))
    return (cx, y0 + cy)


def _draw_sun_disc(image: Image.Image, cx: int, cy: int, radius: int) -> None:
    """Sun with proportional rays.

    Deliberately not ``skyart.draw_sun``: that one adds a fixed 90 px to the
    radius for its long rays, which is right for halftone's 92 px hero disc but
    would spray 124 px rays out of a 168 px ribbon at this size.
    """
    mode = image.mode
    draw = ImageDraw.Draw(image)
    for i in range(12):
        angle = (i / 12) * 2 * math.pi - math.pi / 2
        long_ray = i % 2 == 0
        length = radius * (1.9 if long_ray else 1.45)
        half_w = math.radians(7 if long_ray else 5)
        inner_r = radius + 3
        pts = [
            (cx + math.cos(angle) * length, cy + math.sin(angle) * length),
            (cx + math.cos(angle - half_w) * inner_r, cy + math.sin(angle - half_w) * inner_r),
            (cx + math.cos(angle + half_w) * inner_r, cy + math.sin(angle + half_w) * inner_r),
        ]
        draw.polygon(pts, fill=_grey(252, mode))

    disc = radial_gradient_disc(radius * 2 + 1, inner_v=255, outer_v=210)
    body = disc.convert("RGB") if mode == "RGB" else disc
    image.paste(body, (cx - radius, cy - radius), disc.split()[1])
    if mode == "RGB":
        ring_r = radius - 3
        draw.ellipse(
            (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
            outline=_accent_yellow(mode),
            width=2,
        )


def _draw_moon_at(image: Image.Image, today: date, cx: int, cy: int, radius: int) -> None:
    """Real-phase moon disc via the shared lunar renderer."""
    mode = image.mode
    draw = ImageDraw.Draw(image)
    tones = MoonTones(lit=_grey(238, mode), dark=_grey(58, mode), edge=_grey(150, mode))
    render_moon_disc(image, draw, cx, cy, radius, moon_phase_age(today), tones)
    if mode == "RGB":
        ring_r = radius + 4
        draw.ellipse(
            (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
            outline=_accent_yellow(mode),
            width=2,
        )


def _draw_ribbon_fog(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    today: date,
) -> None:
    """Lay jittered pale bands over the lower ribbon for fog conditions."""
    x0, y0, x1, y1 = rect
    rng = random.Random(today.toordinal() ^ _FOG_SALT)
    mode = image.mode
    band_top = y0 + (y1 - y0) // 2
    band_h = max(6, (y1 - band_top) // 4)
    draw = ImageDraw.Draw(image)
    for i in range(4):
        tone = 170 + rng.randint(-15, 15)
        yy = band_top + i * band_h
        inset = rng.randint(0, 40)
        draw.rectangle(
            (x0 + inset, yy, x1 - inset, min(y1 - 1, yy + band_h - 2)),
            fill=_grey(tone, mode),
        )


def _draw_ribbon_art(
    image: Image.Image,
    axis: TimeAxis,
    rect: tuple[int, int, int, int],
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    is_dark: bool,
) -> None:
    """Sky, disc and weather overlay for the ribbon band."""
    icon = data.weather.current_icon if data.weather is not None else None
    kind, _ = illustration_kind(icon)
    storm = kind == "storm"

    _draw_sky_ribbon(image, axis, rect, storm=storm, night=is_dark)
    _draw_margin_stars(image, axis, rect, today, night=is_dark)

    cx, cy = _disc_centre(axis, now, rect[1])
    if is_dark:
        _draw_moon_at(image, today, cx, cy, DISC_R)
    else:
        _draw_sun_disc(image, cx, cy, DISC_R)

    if kind == "partly_cloudy":
        draw_cloud(image, rect, cx=cx + 66, cy=cy + 12, scale=0.50)
    elif kind == "overcast":
        draw_cloud(image, rect, cx=cx - 96, cy=cy, scale=0.55)
        draw_cloud(image, rect, cx=cx + 84, cy=cy + 14, scale=0.55)
    elif kind == "rain":
        draw_cloud(image, rect, cx=cx, cy=cy - 16, scale=0.60, dark=True)
        draw_precip(image, rect, today, kind="rain", count=110, top_inset=90, bottom_inset=4)
    elif kind == "storm":
        draw_cloud(image, rect, cx=cx, cy=cy - 16, scale=0.60, dark=True)
        draw_lightning(image, rect, cx=cx + 4, top_y=cy + 22, bottom_inset=4)
        draw_precip(image, rect, today, kind="rain", count=140, top_inset=90, bottom_inset=4)
    elif kind == "snow":
        draw_cloud(image, rect, cx=cx, cy=cy - 16, scale=0.55)
        draw_precip(image, rect, today, kind="snow", count=70, top_inset=90, bottom_inset=4)
    elif kind == "fog":
        _draw_ribbon_fog(image, rect, today)


# ---------------------------------------------------------------------------
# Event state
# ---------------------------------------------------------------------------


def _strip_tz(dt: datetime) -> datetime:
    """Drop tzinfo from an event datetime without converting.

    Fetchers already store ``CalendarEvent.start``/``end`` as naive local wall
    clock; this only guards the rare source that leaks an aware value through.
    """
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def event_state(event: CalendarEvent, now: datetime) -> str:
    """Classify *event* as ``"past"``, ``"now"`` or ``"next"``.

    All-day events are always ``"next"``: they have no meaningful instant to be
    "in progress" at, and the inverted treatment is reserved for the single
    timed event actually happening.
    """
    if event.is_all_day:
        return "next"
    start = _strip_tz(event.start)
    end = _strip_tz(event.end)
    if end <= now:
        return "past"
    if start <= now:
        return "now"
    return "next"


def agenda_day(
    events: list[CalendarEvent],
    today: date,
    now: datetime,
    sunset: datetime | None,
) -> tuple[date, bool]:
    """Return ``(day_to_show, is_tomorrow)``.

    Rolls over to tomorrow only when *both* hold:

      * every timed event on ``today`` has ended (a day with no timed events
        counts as "all ended"), and
      * it is past today's sunset — or past ``_FALLBACK_DUSK_HOUR`` when no
        sunset is available.

    Both conditions matter. Rolling over as soon as the last event ends would
    flip the board to TOMORROW at 10:30 on a one-meeting day, putting a
    tomorrow agenda under a bright midday ribbon. Rolling over on sunset alone
    would pull a 19:30 dinner off the screen while it was still happening.
    Gating on both makes the rollover coincide with the ribbon going dark, so
    the theme's two night adaptations read as a single gesture.
    """
    dusk = sunset
    if dusk is None:
        dusk = datetime.combine(today, time(hour=_FALLBACK_DUSK_HOUR))
    if now < dusk:
        return (today, False)
    timed = [e for e in events_for_day(events, today) if not e.is_all_day]
    if any(_strip_tz(e.end) > now for e in timed):
        return (today, False)
    return (today + timedelta(days=1), True)


# ---------------------------------------------------------------------------
# Axis strip
# ---------------------------------------------------------------------------


def _pip_points(cx: int, cy: int, half: int) -> list[tuple[int, int]]:
    """Diamond vertices for an event pip centred at ``(cx, cy)``."""
    return [(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)]


def _draw_axis_strip(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    axis: TimeAxis,
    events: list[CalendarEvent],
    now: datetime,
    style: ThemeStyle,
    *,
    x0: int,
    y0: int,
    w: int,
) -> None:
    """Baseline hairline, daylight bar, hour ticks, event pips and NOW caret.

    Each element is confined to its own row band (see the ``_AXIS_*`` constants)
    so no combination of clock time and event times can make two of them
    collide.
    """
    mode = image.mode
    ink = _ink(mode)
    label_font = (style.font_section_label or style.font_bold)(_AXIS_LABEL_PT)

    # Baseline: a solid rule the whole ribbon sits on.
    draw.rectangle((x0, y0, x0 + w - 1, y0), fill=ink)

    # Daylight bar — the axis's clearest "this part was daytime" mark, and the
    # natural home for the yellow accent on Inky.
    if axis.sunrise is not None and axis.sunset is not None:
        bar_x0 = axis.x_for(axis.sunrise)
        bar_x1 = axis.x_for(axis.sunset)
        if bar_x1 > bar_x0:
            draw.rectangle(
                (bar_x0, y0 + _AXIS_BAR_Y, bar_x1, y0 + _AXIS_BAR_Y + _AXIS_BAR_H - 1),
                fill=_accent_yellow(mode) if mode == "RGB" else ink,
            )

    # Hour ticks, with labels every third hour. The night margins compress
    # several hours into a narrow band, so both ticks and labels are dropped
    # once they would bunch — an unreadable comb is worse than a sparse axis.
    hour = _ceil_hour(axis.start)
    last_minor_x = -999
    last_label_right = -999
    while hour <= axis.end:
        x = axis.x_for(hour)
        major = hour.hour % 3 == 0
        if major:
            draw.line(
                (x, y0 + _AXIS_TICK_Y, x, y0 + _AXIS_TICK_Y + _AXIS_TICK_MAJOR_H),
                fill=ink,
            )
            label = fmt_time(hour)
            lw = text_width(draw, label, label_font)
            lx = x - lw // 2
            if lx > last_label_right + 8:
                draw.text((lx, y0 + _AXIS_LABEL_Y), label, font=label_font, fill=ink)
                last_label_right = lx + lw
        elif x - last_minor_x >= 9:
            draw.line(
                (x, y0 + _AXIS_TICK_Y, x, y0 + _AXIS_TICK_Y + _AXIS_TICK_MINOR_H),
                fill=ink,
            )
            last_minor_x = x
        hour += timedelta(hours=1)

    # Event pips, on their own row below the ticks. Past events are screened,
    # the in-progress one is solid, upcoming ones are hollow.
    pip_y = y0 + _AXIS_PIP_Y
    half = _AXIS_PIP_H // 2
    dur_y = y0 + _AXIS_DUR_Y
    placed: list[int] = []
    for ev in events:
        if ev.is_all_day:
            continue
        x = axis.x_for(_strip_tz(ev.start))
        if any(abs(x - p) < 3 for p in placed):
            continue
        placed.append(x)
        state = event_state(ev, now)
        pts = _pip_points(x, pip_y + half, half)
        if state == "past":
            # The tile is (_AXIS_PIP_H + 2) square, so the diamond centres on
            # (half + 1, half + 1) in its local coordinates.
            def _pip(d: ImageDraw.ImageDraw, h: int = half) -> None:
                d.polygon(_pip_points(h + 1, h + 1, h), fill=0)

            screened_paste(
                image,
                (x - half - 1, pip_y - 1, _AXIS_PIP_H + 2, _AXIS_PIP_H + 2),
                _pip,
                threshold=_PAST_SCREEN,
            )
        elif state == "now":
            draw.polygon(pts, fill=ink)
            # Duration bar gets its own band so it can't cut through a label.
            end_x = axis.x_for(_strip_tz(ev.end))
            if end_x > x:
                draw.rectangle((x, dur_y, end_x, dur_y + _AXIS_DUR_H - 1), fill=_accent_red(mode))
        else:
            draw.polygon(pts, outline=ink)

    # NOW caret, in the tick row so it reads against the timeline itself, plus a
    # faint beam running up through the sky.
    now_x = axis.x_for(now)
    draw.line((now_x, y0 - SKY_H + 1, now_x, y0 - 1), fill=_grey(230, mode))
    caret_top = y0 + _AXIS_TICK_Y
    caret_bot = caret_top + _AXIS_CARET_H
    draw.polygon(
        [
            (now_x, caret_top),
            (now_x + _AXIS_CARET_HALF_W, caret_bot),
            (now_x - _AXIS_CARET_HALF_W, caret_bot),
        ],
        fill=_accent_red(mode),
    )


# ---------------------------------------------------------------------------
# Agenda
# ---------------------------------------------------------------------------

# (max_rows, row_h, time_w, time_pt, title_pt, show_location)
_DENSITY_TIERS: tuple[tuple[int, int, int, int, int, bool], ...] = (
    (3, 64, 96, 22, 27, True),
    (4, 48, 96, 19, 23, True),
    (6, 32, 82, 16, 20, False),
    (7, 27, 74, 15, 18, False),
)


def agenda_metrics(n_events: int, avail_h: int) -> tuple[int, int, int, int, int, bool]:
    """Pick the roomiest density tier that shows *n_events* within *avail_h*.

    Tier capacity is tested against the space actually on hand rather than the
    tier's nominal ``max_rows``: a tier whose rows don't fit would otherwise be
    clamped down to one or two visible events and push the rest into
    "+N more", which is a far worse outcome than simply setting smaller type.

    A single wide column beats two narrow ones here: at 508 px of content
    width, splitting in two leaves ~158 px for the title, which truncates
    almost every real event name. Shrinking the type and paging the overflow
    into "+N more" keeps full-width titles legible instead.
    """
    for tier in _DENSITY_TIERS:
        if min(tier[0], avail_h // max(1, tier[1])) >= n_events:
            return tier
    return _DENSITY_TIERS[-1]


def _location_text(event: CalendarEvent) -> str:
    """First comma-segment of the location, whitespace-collapsed."""
    if not event.location:
        return ""
    return " ".join(event.location.split(",")[0].split())


def _draw_event_row(
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
) -> None:
    """Draw one agenda row in the treatment its *state* calls for."""
    mode = image.mode
    ink = _ink(mode)
    time_font = style.font_medium(time_pt)
    title_font = style.font_semibold(title_pt)
    loc_font = style.font_regular(max(12, time_pt - 2))

    time_str = "ALL DAY" if event.is_all_day else fmt_time(_strip_tz(event.start))
    title_x = x0 + time_w + 14
    title_w = max(20, w - (time_w + 14))
    bar_x = x0 + time_w
    bar_top = y + 2
    bar_bot = y + row_h - 6

    if state == "now":
        # The event happening right now is the one thing on the plate that
        # inverts — solid field, paper text.
        draw.rectangle((x0 - 6, bar_top - 2, x0 + w, bar_bot + 2), fill=_accent_red(mode))
        fill = style.bg
        draw.text((x0, y + 4), time_str, font=time_font, fill=fill)
        draw_text_truncated(draw, (title_x, y + 2), event.summary, title_font, title_w, fill=fill)
        return

    if state == "past":
        # Typeset offscreen, then perforate: the row reads as spent from across
        # the room but stays legible up close.
        def _render(d: ImageDraw.ImageDraw) -> None:
            d.text((0, 4), time_str, font=time_font, fill=0)
            draw_text_truncated(d, (time_w + 14, 2), event.summary, title_font, title_w, fill=0)

        screened_paste(image, (x0, y, w, row_h - 4), _render, threshold=_PAST_SCREEN)
        return

    # Upcoming: crisp.
    draw.text((x0, y + 4), time_str, font=time_font, fill=ink)
    if event.is_all_day:
        draw.rectangle((bar_x, bar_top, bar_x + 3, bar_bot), outline=ink)
    else:
        draw.rectangle((bar_x, bar_top, bar_x + 3, bar_bot), fill=ink)
    used = draw_text_truncated(draw, (title_x, y + 2), event.summary, title_font, title_w, fill=ink)
    if show_location and used:
        loc = _location_text(event)
        if loc:
            draw.text(
                (title_x, y + 2 + text_height(title_font) + 2),
                loc,
                font=loc_font,
                fill=ink,
            )


def _draw_agenda(
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
    """Header, rule and event rows for the agenda column."""
    mode = image.mode
    ink = _ink(mode)
    title_font = (style.font_title or style.font_bold)(19)
    count_font = style.font_medium(14)

    day_events = events_for_day(events, day)
    header_y = y0

    # Header: "TODAY · MON APR 6", or an inverted TOMORROW chip so a rolled-over
    # agenda can't be misread as today's.
    label_x = x0
    if is_tomorrow:
        chip = "TOMORROW"
        cw = text_width(draw, chip, title_font)
        ch = text_height(title_font)
        draw.rectangle((x0, header_y, x0 + cw + 12, header_y + ch + 6), fill=ink)
        draw.text((x0 + 6, header_y + 3), chip, font=title_font, fill=style.bg)
        label_x = x0 + cw + 20
        dateline = day.strftime("%a %b %-d").upper()
    else:
        dateline = "TODAY · " + day.strftime("%a %b %-d").upper()
    draw.text((label_x, header_y + 3), dateline, font=title_font, fill=ink)

    count = f"{len(day_events)} EVENT" + ("S" if len(day_events) != 1 else "")
    cw = text_width(draw, count, count_font)
    draw.text((x0 + w - cw, header_y + 8), count, font=count_font, fill=ink)

    rule_y = header_y + text_height(title_font) + 11
    draw_bayer_rule(image, x0, rule_y, w, 3, mode)

    rows_y = rule_y + 10
    rows_h = h - (rows_y - y0)

    if not day_events:
        empty_font = (style.font_title or style.font_bold)(24)
        msg = "Nothing scheduled tomorrow" if is_tomorrow else "Nothing scheduled"
        mw = text_width(draw, msg, empty_font)
        draw.text(
            (x0 + (w - mw) // 2, rows_y + (rows_h - text_height(empty_font)) // 2),
            msg,
            font=empty_font,
            fill=ink,
        )
        return

    max_rows, row_h, time_w, time_pt, title_pt, show_loc = agenda_metrics(len(day_events), rows_h)
    # The tier picks the type size; the actual row count comes from the space
    # on hand, so a tier whose nominal capacity doesn't fit the region can't
    # push the "+N more" line down into the footer.
    fits = max(1, min(max_rows, rows_h // row_h))
    if len(day_events) > fits:
        # Give the last slot to the "+N more" line instead of a truncated row.
        visible = day_events[: max(1, fits - 1)]
    else:
        visible = day_events
    overflow = len(day_events) - len(visible)

    y = rows_y
    for ev in visible:
        _draw_event_row(
            image,
            draw,
            ev,
            event_state(ev, now),
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
        more_font = style.font_medium(time_pt)
        text = f"+{overflow} more"

        def _render(d: ImageDraw.ImageDraw, t: str = text) -> None:
            d.text((0, 2), t, font=more_font, fill=0)

        # Screened like a past row so it reads as secondary, but at the same
        # threshold — the lighter cut used previously was too faint to read.
        screened_paste(
            image,
            (x0 + time_w + 14, y + 2, 200, text_height(more_font) + 10),
            _render,
            threshold=_MORE_SCREEN,
        )


# ---------------------------------------------------------------------------
# Supporting rail
# ---------------------------------------------------------------------------


def _fmt_temp(value: float | None) -> str:
    return "—" if value is None else f"{int(round(value))}°"


def _next_birthdays(
    birthdays: list[Birthday], today: date, limit: int = 3
) -> list[tuple[str, int]]:
    """Return up to *limit* ``(label, days_away)`` pairs, soonest first.

    Feb-29 birthdays roll to Feb 28 in non-leap years — the same convention
    ``birthday_bar`` uses, so a leap-day birthday neither drops nor crashes.
    """
    out: list[tuple[str, int]] = []
    for b in birthdays:
        try:
            nxt = b.date.replace(year=today.year)
        except ValueError:
            nxt = b.date.replace(year=today.year, day=28)
        if nxt < today:
            try:
                nxt = b.date.replace(year=today.year + 1)
            except ValueError:
                nxt = b.date.replace(year=today.year + 1, day=28)
        days = (nxt - today).days
        label = b.name if b.age is None else f"{b.name} · {b.age}"
        out.append((label, days))
    out.sort(key=lambda t: t[1])
    return out[:limit]


def _draw_rail(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    style: ThemeStyle,
    *,
    x0: int,
    y0: int,
    w: int,
    h: int,
) -> None:
    """Temperature, conditions and upcoming birthdays."""
    mode = image.mode
    ink = _ink(mode)
    weather = data.weather

    numeral_font = (style.font_date_number or style.font_title or style.font_bold)(66)
    small_font = style.font_regular(15)
    label_font = (style.font_section_label or style.font_bold)(13)
    cond_font = style.font_medium(15)

    temp = _fmt_temp(weather.current_temp if weather else None)
    tw = text_width(draw, temp, numeral_font)
    draw.text((x0 + (w - tw) // 2, y0), temp, font=numeral_font, fill=ink)
    y = y0 + text_height(numeral_font) + 12

    if weather is not None and weather.feels_like is not None:
        feels = f"feels {_fmt_temp(weather.feels_like)}"
        fw = text_width(draw, feels, small_font)
        draw.text((x0 + (w - fw) // 2, y), feels, font=small_font, fill=ink)
    y += text_height(small_font) + 14

    if weather is not None:
        draw_text_truncated(
            draw, (x0, y), weather.current_description.upper(), cond_font, w, fill=ink
        )
        y += text_height(cond_font) + 6
        hl = f"H {_fmt_temp(weather.high)}  ·  L {_fmt_temp(weather.low)}"
        draw.text((x0, y), hl, font=cond_font, fill=ink)
        y += text_height(cond_font) + 14
    else:
        draw_text_truncated(draw, (x0, y), "AWAITING DATA", cond_font, w, fill=ink)
        y += text_height(cond_font) + 14

    draw_bayer_rule(image, x0, y, w, 3, mode)
    y += 14

    draw.text((x0, y), "BIRTHDAYS", font=label_font, fill=ink)
    y += text_height(label_font) + 8

    upcoming = _next_birthdays(data.birthdays, today)
    if not upcoming:
        draw.text((x0, y), "none in view", font=small_font, fill=ink)
        return
    bottom = y0 + h
    for label, days in upcoming:
        if y + text_height(small_font) > bottom:
            break
        draw.polygon(
            [(x0 + 3, y + 7), (x0 + 6, y + 10), (x0 + 3, y + 13), (x0, y + 10)],
            fill=_accent_red(mode),
        )
        when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days}d")
        draw_text_truncated(draw, (x0 + 12, y), f"{label} · {when}", small_font, w - 12, fill=ink)
        y += text_height(small_font) + 8


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    style: ThemeStyle,
    sunrise: datetime | None,
    sunset: datetime | None,
    now: datetime,
    mode: str,
    *,
    x0: int,
    y0: int,
    w: int,
) -> None:
    """Sunrise/sunset on the left, render timestamp on the right."""
    ink = _ink(mode)
    font = style.font_regular(15)
    glyph_font = weather_icon(17)
    baseline = y0 + (FOOTER_H - text_height(font)) // 2

    x = x0
    for glyph, moment in ((_SUNRISE_GLYPH, sunrise), (_SUNSET_GLYPH, sunset)):
        if moment is None:
            continue
        draw.text(
            (x, y0 + (FOOTER_H - text_height(glyph_font)) // 2), glyph, font=glyph_font, fill=ink
        )
        x += text_width(draw, glyph, glyph_font) + 5
        label = fmt_time(moment)
        draw.text((x, baseline), label, font=font, fill=ink)
        x += text_width(draw, label, font) + 20

    stamp = f"updated {fmt_time(now)}"
    sw = text_width(draw, stamp, font)
    draw.text((x0 + w - sw, baseline), stamp, font=font, fill=ink)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_day_arc(
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
    """Draw the full ``day_arc`` plate into *region* of *image*."""
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

    civil_dawn, sunrise, sunset, civil_dusk = _resolve_day_bounds(
        today, data.weather, latitude, longitude, tz
    )
    axis_events = events_for_day(data.events, today)
    axis = build_time_axis(
        today,
        now_naive,
        axis_events,
        sunrise,
        sunset,
        civil_dawn,
        civil_dusk,
        x0,
        x0 + w - 1,
    )
    is_dark = sunset is not None and (
        now_naive >= sunset or (sunrise is not None and now_naive < sunrise)
    )

    sky_rect = (x0, y0, x0 + w, y0 + SKY_H)
    _draw_ribbon_art(image, axis, sky_rect, data, today, now_naive, is_dark=is_dark)

    # Paper strip behind the axis so every tick and label lands in solid ink.
    axis_y = y0 + AXIS_Y
    paper = Image.new("L", (w, AXIS_H), 255)
    if mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x0, axis_y))

    day, is_tomorrow = agenda_day(data.events, today, now_naive, sunset)
    _draw_axis_strip(image, draw, axis, axis_events, now_naive, style, x0=x0, y0=axis_y, w=w)

    draw_bayer_rule(image, x0, y0 + RIBBON_H, w, RULE_H, mode)

    # Solid paper under the whole body: the agenda's type has to sit on a clean
    # field so Floyd-Steinberg can't bleed the ribbon's dither into small text.
    body_y = y0 + BODY_Y
    body_h = h - BODY_Y
    body = Image.new("L", (w, body_h), 255)
    if mode == "RGB":
        body = body.convert("RGB")
    image.paste(body, (x0, body_y))

    inner_h = body_h - FOOTER_H
    _draw_agenda(
        image,
        draw,
        data.events,
        day,
        is_tomorrow,
        now_naive,
        style,
        x0=x0 + PAD_X,
        y0=body_y + 8,
        w=AGENDA_W - PAD_X * 2,
        h=inner_h - 16,
    )

    draw.line(
        (x0 + DIVIDER_X, body_y + 12, x0 + DIVIDER_X, body_y + inner_h - 8),
        fill=_grey(150, mode),
    )

    _draw_rail(
        image,
        draw,
        data,
        today,
        style,
        x0=x0 + RAIL_X,
        y0=body_y + 8,
        w=RAIL_W,
        h=inner_h - 16,
    )

    _draw_footer(
        draw,
        style,
        sunrise,
        sunset,
        now_naive,
        mode,
        x0=x0 + PAD_X,
        y0=y0 + h - FOOTER_H,
        w=w - PAD_X * 2,
    )
