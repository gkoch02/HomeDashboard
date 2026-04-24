"""astronomy.py — Pure-Python astronomical calculations for the astronomy theme.

Implements sunrise / sunset / twilight times (NOAA Solar Calculator algorithm)
and a lookup of the next upcoming annual meteor shower.  No external deps,
no network calls — the whole module is deterministic from (date, lat, lon).

Reference: https://gml.noaa.gov/grad/solcalc/solareqns.PDF
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

# Standard solar altitudes used for key events (all negative; sun below horizon).
# -0.833° accounts for atmospheric refraction and the sun's apparent radius.
SUNRISE_ALTITUDE = -0.833
CIVIL_TWILIGHT_ALTITUDE = -6.0
NAUTICAL_TWILIGHT_ALTITUDE = -12.0
ASTRONOMICAL_TWILIGHT_ALTITUDE = -18.0


@dataclass
class SunTimes:
    """Sunrise/sunset/twilight times for a single date at a single location.

    All fields are ``datetime | None``. ``None`` means the event does not occur
    on that date at that latitude (polar day/night).  Times are returned in UTC;
    callers should convert to the dashboard's local timezone for display.
    """

    sunrise: datetime | None
    sunset: datetime | None
    civil_dawn: datetime | None
    civil_dusk: datetime | None
    nautical_dawn: datetime | None
    nautical_dusk: datetime | None
    astronomical_dawn: datetime | None
    astronomical_dusk: datetime | None
    solar_noon: datetime | None


@dataclass
class MeteorShower:
    """Annual meteor shower with peak date and approximate zenithal hourly rate."""

    name: str
    peak_month: int
    peak_day: int
    zhr: int  # Zenithal Hourly Rate — peak-night meteors visible per hour


# Source: IMO / American Meteor Society 2024 calendar, peak dates (UT).
# Kept in-module rather than as a JSON file — the list is ~dozen entries
# and never changes year-to-year.
METEOR_SHOWERS: list[MeteorShower] = [
    MeteorShower("Quadrantids", 1, 3, 110),
    MeteorShower("Lyrids", 4, 22, 18),
    MeteorShower("Eta Aquariids", 5, 6, 50),
    MeteorShower("Delta Aquariids", 7, 30, 25),
    MeteorShower("Perseids", 8, 12, 100),
    MeteorShower("Draconids", 10, 8, 10),
    MeteorShower("Orionids", 10, 21, 20),
    MeteorShower("Leonids", 11, 17, 15),
    MeteorShower("Geminids", 12, 14, 150),
    MeteorShower("Ursids", 12, 22, 10),
]


def _julian_day(d: date) -> float:
    """Return the Julian Day Number for 00:00 UT on *d* (Meeus, ch 7)."""
    y, m, day = d.year, d.month, d.day
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + b - 1524.5


def _solar_declination_and_eot(jd: float) -> tuple[float, float]:
    """Return (declination°, equation-of-time in minutes) for Julian Day *jd*.

    NOAA's simplified spreadsheet algorithm.
    """
    n = jd - 2451545.0  # days since J2000.0
    # Mean longitude and mean anomaly of the sun
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    # Ecliptic longitude
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    # Obliquity of the ecliptic
    eps = math.radians(23.439 - 0.0000004 * n)
    # Declination
    declination = math.degrees(math.asin(math.sin(eps) * math.sin(lam)))
    # Right ascension
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam)))
    # Equation of time (minutes)
    eot = 4 * (L - ra)
    # Normalize eot to (-720, 720)
    eot = ((eot + 720) % 1440) - 720
    return declination, eot


def _hour_angle(latitude: float, declination: float, altitude: float) -> float | None:
    """Return hour angle in degrees for the given altitude, or ``None`` when
    the sun never reaches that altitude on the date (polar day/night).
    """
    lat_rad = math.radians(latitude)
    dec_rad = math.radians(declination)
    alt_rad = math.radians(altitude)
    cos_h = (math.sin(alt_rad) - math.sin(lat_rad) * math.sin(dec_rad)) / (
        math.cos(lat_rad) * math.cos(dec_rad)
    )
    if cos_h > 1 or cos_h < -1:
        return None
    return math.degrees(math.acos(cos_h))


def _event_utc(
    d: date,
    latitude: float,
    longitude: float,
    altitude: float,
    morning: bool,
) -> datetime | None:
    """Compute a sun event (rise/dawn or set/dusk) in UTC for the given altitude.

    *morning* selects the ascending-sun branch (rise/dawn) vs descending (set/dusk).
    Returns ``None`` for polar day/night.
    """
    jd = _julian_day(d) + 0.5  # solar noon-ish reference
    declination, eot = _solar_declination_and_eot(jd)
    ha = _hour_angle(latitude, declination, altitude)
    if ha is None:
        return None
    solar_noon_utc_minutes = 720 - 4 * longitude - eot
    offset = ha * 4  # degrees → minutes
    minutes = solar_noon_utc_minutes - offset if morning else solar_noon_utc_minutes + offset
    # Normalize to [0, 1440) within the given date
    days_shift, minutes = divmod(minutes, 1440)
    base = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
    return base + timedelta(days=int(days_shift), minutes=minutes)


def sun_times(d: date, latitude: float, longitude: float) -> SunTimes:
    """Return all key sun events for the given date/location (all UTC).

    See ``SunTimes`` for the list of computed events.
    """

    def both(alt: float) -> tuple[datetime | None, datetime | None]:
        return (
            _event_utc(d, latitude, longitude, alt, morning=True),
            _event_utc(d, latitude, longitude, alt, morning=False),
        )

    sr, ss = both(SUNRISE_ALTITUDE)
    cd, cdk = both(CIVIL_TWILIGHT_ALTITUDE)
    nd, ndk = both(NAUTICAL_TWILIGHT_ALTITUDE)
    ad, adk = both(ASTRONOMICAL_TWILIGHT_ALTITUDE)

    # Solar noon
    jd = _julian_day(d) + 0.5
    _decl, eot = _solar_declination_and_eot(jd)
    noon_minutes = 720 - 4 * longitude - eot
    days_shift, noon_minutes = divmod(noon_minutes, 1440)
    noon_base = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
    solar_noon = noon_base + timedelta(days=int(days_shift), minutes=noon_minutes)

    return SunTimes(
        sunrise=sr,
        sunset=ss,
        civil_dawn=cd,
        civil_dusk=cdk,
        nautical_dawn=nd,
        nautical_dusk=ndk,
        astronomical_dawn=ad,
        astronomical_dusk=adk,
        solar_noon=solar_noon,
    )


def day_length(times: SunTimes) -> timedelta | None:
    """Return sunset − sunrise as a ``timedelta``, or ``None`` for polar day/night."""
    if times.sunrise is None or times.sunset is None:
        return None
    return times.sunset - times.sunrise


def day_length_delta(today: date, latitude: float, longitude: float) -> timedelta | None:
    """Return (today − yesterday) day length difference, or ``None`` if undefined."""
    today_t = sun_times(today, latitude, longitude)
    yesterday_t = sun_times(today - timedelta(days=1), latitude, longitude)
    today_len = day_length(today_t)
    yesterday_len = day_length(yesterday_t)
    if today_len is None or yesterday_len is None:
        return None
    return today_len - yesterday_len


def next_meteor_shower(today: date) -> tuple[MeteorShower, int]:
    """Return (next upcoming shower, days until its peak).

    ``days_until == 0`` means the peak is today.  The lookup wraps around the
    year, so after December's Ursids the next shower is January's Quadrantids.
    """
    year = today.year
    candidates: list[tuple[int, MeteorShower]] = []
    for shower in METEOR_SHOWERS:
        try:
            peak = date(year, shower.peak_month, shower.peak_day)
        except ValueError:
            continue
        days = (peak - today).days
        if days < 0:
            # Roll over to next year
            try:
                peak = date(year + 1, shower.peak_month, shower.peak_day)
                days = (peak - today).days
            except ValueError:
                continue
        candidates.append((days, shower))
    candidates.sort(key=lambda t: t[0])
    days, shower = candidates[0]
    return shower, days


def dark_sky_window(times: SunTimes) -> tuple[datetime, datetime] | None:
    """Return the (start, end) of the astronomical dark-sky window.

    Dark sky = end of astronomical dusk tonight → start of astronomical dawn
    tomorrow.  Returns ``None`` during polar-day periods when no astronomical
    twilight ends.
    """
    if times.astronomical_dusk is None or times.astronomical_dawn is None:
        return None
    # astronomical_dawn on the same date is today's pre-dawn — we want tomorrow's.
    # Caller should pass times for ``today`` and fetch tomorrow's astronomical_dawn separately.
    return times.astronomical_dusk, times.astronomical_dawn
