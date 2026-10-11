"""Moon phase calculation — pure math, no external API needed.

The phase, age and illumination come from the Moon's true elongation from the
Sun (Meeus, *Astronomical Algorithms*, ch. 47-48, principal terms); the dates
of new and full moons come from Meeus ch. 49, accurate to a few minutes.  A
mean-lunation count from a reference new moon drifts by up to a day against
the real sky, which put the new moon of 2026-10-10 on Oct 11.
"""

import math
from datetime import date, datetime, timedelta, timezone, tzinfo

# Mean synodic month in days (new moon to new moon).  Ages are expressed in
# mean-month days (true phase fraction × this) so renderers can keep dividing by it.
_SYNODIC_MONTH = 29.53059

_J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
# TT − UT, close enough for this decade; a minute either way moves nothing drawn.
_DELTA_T_DAYS = 69.0 / 86400.0

# Weather Icons font has 28 moon phase glyphs: \uf095 (new) through \uf0B0 (waning crescent)
# Index 0 = new moon, 14 = full moon
_MOON_GLYPHS = [
    "\uf095",  # 0  new moon
    "\uf096",  # 1  waxing crescent
    "\uf097",  # 2
    "\uf098",  # 3
    "\uf099",  # 4
    "\uf09a",  # 5
    "\uf09b",  # 6  first quarter
    "\uf09c",  # 7
    "\uf09d",  # 8
    "\uf09e",  # 9
    "\uf09f",  # 10
    "\uf0a0",  # 11
    "\uf0a1",  # 12
    "\uf0a2",  # 13 waxing gibbous
    "\uf0a3",  # 14 full moon
    "\uf0a4",  # 15
    "\uf0a5",  # 16
    "\uf0a6",  # 17
    "\uf0a7",  # 18
    "\uf0a8",  # 19
    "\uf0a9",  # 20
    "\uf0aa",  # 21 third quarter
    "\uf0ab",  # 22
    "\uf0ac",  # 23
    "\uf0ad",  # 24
    "\uf0ae",  # 25
    "\uf0af",  # 26
    "\uf0b0",  # 27 waning crescent
]

# Human-readable phase names (8-phase system)
_PHASE_NAMES = [
    "New Moon",
    "Waxing Crescent",
    "First Quarter",
    "Waxing Gibbous",
    "Full Moon",
    "Waning Gibbous",
    "Third Quarter",
    "Waning Crescent",
]


def _sin(deg: float) -> float:
    return math.sin(math.radians(deg))


def _noon_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=timezone.utc)


def _phase_angle(when: datetime) -> float:
    """Return the Moon's phase angle in degrees, in (-180, 180].

    180 is new, 0 is full; positive while waxing.  Meeus eq. 48.4 on the mean
    elongation and anomalies of eq. 47.2-47.4.
    """
    t = ((when - _J2000).total_seconds() / 86400.0 + _DELTA_T_DAYS) / 36525.0
    elong = 297.8501921 + 445267.1114034 * t - 0.0018819 * t * t
    sun_anom = 357.5291092 + 35999.0502909 * t - 0.0001536 * t * t
    moon_anom = 134.9633964 + 477198.8675055 * t + 0.0087414 * t * t
    i = (
        180.0
        - elong
        - 6.289 * _sin(moon_anom)
        + 2.100 * _sin(sun_anom)
        - 1.274 * _sin(2 * elong - moon_anom)
        - 0.658 * _sin(2 * elong)
        - 0.214 * _sin(2 * moon_anom)
        - 0.110 * _sin(elong)
    )
    return 180.0 - (180.0 - i) % 360.0


def _phase_fraction(d: date) -> float:
    """Return the fraction of the lunation at noon UTC on *d*: 0 new, 0.5 full."""
    return (180.0 - _phase_angle(_noon_utc(d))) / 360.0 % 1.0


def _principal_phase(k: float) -> datetime:
    """Return the instant (UTC) of lunation *k*: integer *k* new moon, *k* + 0.5 full.

    Meeus ch. 49; *k* counts lunations from the new moon of 2000-01-06.
    """
    t = k / 1236.85
    jde = (
        2451550.09766
        + 29.530588861 * k
        + 0.00015437 * t**2
        - 0.000000150 * t**3
        + 0.00000000073 * t**4
    )
    e = 1 - 0.002516 * t - 0.0000074 * t * t
    m = 2.5534 + 29.10535670 * k - 0.0000014 * t * t
    mp = 201.5643 + 385.81693528 * k + 0.0107582 * t * t + 0.00001238 * t**3
    f = 160.7108 + 390.67050284 * k - 0.0016118 * t * t - 0.00000227 * t**3
    om = 124.7746 - 1.56375588 * k + 0.0020672 * t * t
    # The two phases differ only in the first terms' coefficients.
    new = k == math.floor(k)
    c1, c2, c3, c4 = (
        (-0.40720, 0.17241, 0.01608, 0.01039)
        if new
        else (
            -0.40614,
            0.17302,
            0.01614,
            0.01043,
        )
    )
    c5, c6, c7 = (0.00739, -0.00514, 0.00208) if new else (0.00734, -0.00515, 0.00209)
    jde += (
        c1 * _sin(mp)
        + c2 * e * _sin(m)
        + c3 * _sin(2 * mp)
        + c4 * _sin(2 * f)
        + c5 * e * _sin(mp - m)
        + c6 * e * _sin(mp + m)
        + c7 * e * e * _sin(2 * m)
        - 0.00111 * _sin(mp - 2 * f)
        - 0.00057 * _sin(mp + 2 * f)
        + 0.00056 * e * _sin(2 * mp + m)
        - 0.00042 * _sin(3 * mp)
        + 0.00042 * e * _sin(m + 2 * f)
        + 0.00038 * e * _sin(m - 2 * f)
        - 0.00024 * e * _sin(2 * mp - m)
        - 0.00017 * _sin(om)
        - 0.00007 * _sin(mp + 2 * m)
        + 0.00004 * _sin(2 * mp - 2 * f)
        + 0.00004 * _sin(3 * m)
        + 0.00003 * _sin(mp + m - 2 * f)
        + 0.00003 * _sin(2 * mp + 2 * f)
        - 0.00003 * _sin(mp + m + 2 * f)
        + 0.00003 * _sin(mp - m + 2 * f)
        - 0.00002 * _sin(mp - m - 2 * f)
        - 0.00002 * _sin(3 * mp + m)
        + 0.00002 * _sin(4 * mp)
    )
    planetary = (
        (325, 299.77 + 0.107408 * k - 0.009173 * t * t),
        (165, 251.88 + 0.016321 * k),
        (164, 251.83 + 26.651886 * k),
        (126, 349.42 + 36.412478 * k),
        (110, 84.66 + 18.206239 * k),
        (62, 141.74 + 53.303771 * k),
        (60, 207.14 + 2.453732 * k),
        (56, 154.84 + 7.306860 * k),
        (47, 34.52 + 27.261239 * k),
        (42, 207.19 + 0.121824 * k),
        (40, 291.34 + 1.844379 * k),
        (37, 161.72 + 24.198154 * k),
        (35, 239.56 + 25.513099 * k),
        (23, 331.55 + 3.592518 * k),
    )
    jde += sum(w * 1e-6 * _sin(a) for w, a in planetary)
    return _J2000 + timedelta(days=jde - 2451545.0 - _DELTA_T_DAYS)


def _next_principal_date(d: date, offset: float, tz: tzinfo | None) -> date:
    """Return the first date after *d* on which the phase (*offset* 0 new, 0.5 full) falls.

    The date is taken in *tz*, or in UTC when it is ``None``.
    """
    k = math.floor((_noon_utc(d) - _J2000).days / _SYNODIC_MONTH) - 1 + offset
    while True:
        when = _principal_phase(k).astimezone(tz or timezone.utc).date()
        if when > d:
            return when
        k += 1


def moon_phase_age(d: date) -> float:
    """Return the moon's age at noon UTC on *d*, in days (0 = new, ~14.77 = full).

    The age is the true phase fraction in mean-month days, so a full moon is
    always ``_SYNODIC_MONTH / 2`` however long the actual lunation runs.
    """
    return _phase_fraction(d) * _SYNODIC_MONTH


def is_waxing(d: date) -> bool:
    """Return True if the moon is in the waxing half of its synodic cycle.

    Waxing = age in the first half of the synodic month (new moon → full moon)
    with the lit limb on the right; waning = second half (full → next new)
    with the lit limb on the left.
    """
    return moon_phase_age(d) < _SYNODIC_MONTH / 2


def moon_phase_name(d: date) -> str:
    """Return a human-readable phase name for the given date."""
    age = moon_phase_age(d)
    fraction = age / _SYNODIC_MONTH
    idx = int(fraction * 8 + 0.5) % 8
    return _PHASE_NAMES[idx]


def moon_illumination(d: date) -> float:
    """Return the illuminated percentage of the disc at noon UTC (0.0 new, 100.0 full)."""
    return (1 + math.cos(math.radians(_phase_angle(_noon_utc(d))))) / 2 * 100


def moon_phase_glyph(d: date) -> str:
    """Return the Weather Icons glyph character for the moon phase on *d*."""
    age = moon_phase_age(d)
    fraction = age / _SYNODIC_MONTH
    idx = int(fraction * 28 + 0.5) % 28
    return _MOON_GLYPHS[idx]


def next_full_moon(d: date, tz: tzinfo | None = None) -> tuple[date, int]:
    """Return the date of the first full moon after *d* and the day count until it.

    The date is the one in *tz* (UTC when ``None``) on which the full moon falls.
    """
    when = _next_principal_date(d, 0.5, tz)
    return when, (when - d).days


def next_new_moon(d: date, tz: tzinfo | None = None) -> tuple[date, int]:
    """Return the date of the first new moon after *d* and the day count until it.

    The date is the one in *tz* (UTC when ``None``) on which the new moon falls.
    """
    when = _next_principal_date(d, 0.0, tz)
    return when, (when - d).days


def next_phase_date(today: date, target_fraction: float, tz: tzinfo | None = None) -> date:
    """Return the date of the next new (``0.0``) or full (``0.5``) moon on or after *today*."""
    if target_fraction not in (0.0, 0.5):
        raise ValueError(f"only new (0.0) and full (0.5) moons are supported: {target_fraction}")
    return _next_principal_date(today - timedelta(days=1), target_fraction, tz)
