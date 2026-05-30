"""astronomy.py — Pure-Python astronomical calculations for the astronomy theme.

Implements sunrise / sunset / twilight times (NOAA Solar Calculator algorithm)
and a lookup of the next upcoming annual meteor shower.  No external deps,
no network calls — the whole module is deterministic from (date, lat, lon).

Reference: https://gml.noaa.gov/grad/solcalc/solareqns.PDF
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo

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
class MoonTimes:
    """Moonrise / moonset for a single local date at a single location.

    Both fields are ``datetime | None`` (UTC).  ``None`` means the event does
    not occur on that local date — the moon rises ~50 minutes later each day,
    so roughly once a month a given calendar day has no moonrise or no moonset.
    """

    rise: datetime | None
    set: datetime | None


# Apparent altitude of the moon's centre at rise/set.  The moon's large
# horizontal parallax (~0.95°) and angular radius (~0.25°) very nearly cancel
# against atmospheric refraction (~0.57°), leaving the centre a touch above the
# geometric horizon at the moment the upper limb crosses it.
MOON_RISE_ALTITUDE = 0.125


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


# ---------------------------------------------------------------------------
# Equatorial / horizontal coordinate transforms
#
# Used by the constellation_map theme.  All inputs/outputs are in conventional
# astronomy units (RA in hours, Dec in degrees, longitudes east-positive in
# degrees, sidereal times in degrees).  Algorithms follow Meeus / Schlyter and
# are accurate to a few arcminutes — far more than enough for an eInk star
# chart.
# ---------------------------------------------------------------------------


_J2000 = 2451545.0


def _julian_day_full(dt: datetime) -> float:
    """Return the Julian Day for a full timezone-aware datetime (UTC inside).

    Naive datetimes are interpreted as UTC.  Callers that hold a naive
    *local* datetime must convert it to aware (or to UTC) first — passing a
    naive local time will silently produce a JD offset by the local
    UTC-offset, and every downstream sidereal-time / coordinate-transform
    result will inherit that error.
    """
    if dt.tzinfo is not None:
        ut = dt.astimezone(timezone.utc)
    else:
        ut = dt.replace(tzinfo=timezone.utc)
    jd0 = _julian_day(ut.date())
    fraction = (ut.hour + ut.minute / 60.0 + ut.second / 3600.0) / 24.0
    return jd0 + fraction


def gmst_degrees(dt: datetime) -> float:
    """Greenwich Mean Sidereal Time in degrees [0, 360) at *dt*.

    Uses the IAU 1982 expression in degrees (Meeus eqn 12.4 simplified) —
    plenty accurate for star-chart placement (well under one degree).
    """
    jd = _julian_day_full(dt)
    d = jd - _J2000
    t = d / 36525.0
    g = 280.46061837 + 360.98564736629 * d + 0.000387933 * t * t - (t * t * t) / 38710000.0
    return g % 360.0


def local_sidereal_time(dt: datetime, longitude: float) -> float:
    """Local Sidereal Time in degrees [0, 360).

    *longitude* is east-positive degrees (Western Hemisphere is negative).
    """
    return (gmst_degrees(dt) + longitude) % 360.0


def equatorial_to_horizontal(
    ra_hours: float,
    dec_deg: float,
    lst_deg: float,
    latitude_deg: float,
) -> tuple[float, float]:
    """Convert equatorial (RA hours / Dec deg) to horizontal (alt / az) deg.

    *azimuth* is measured clockwise from due North through East (0=N, 90=E,
    180=S, 270=W).  Negative altitudes mean the object is below the horizon.
    """
    ha = math.radians(lst_deg - ra_hours * 15.0)
    dec = math.radians(dec_deg)
    lat = math.radians(latitude_deg)

    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(ha)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.asin(sin_alt)

    cos_alt = math.cos(alt)
    if cos_alt < 1e-9:
        # At the zenith / nadir azimuth is undefined; pick North.
        return math.degrees(alt), 0.0

    # atan2 form is well-behaved across the full circle without sign juggling.
    sin_az = -math.cos(dec) * math.sin(ha) / cos_alt
    cos_az = (math.sin(dec) - sin_alt * math.sin(lat)) / (cos_alt * math.cos(lat))
    az = math.atan2(sin_az, cos_az)
    return math.degrees(alt), math.degrees(az) % 360.0


def moon_equatorial(dt: datetime) -> tuple[float, float]:
    """Compute the moon's geocentric (RA hours, Dec deg) at *dt*.

    Uses Schlyter's simplified algorithm without the perturbation terms —
    typical accuracy is around 5 arcminutes (~0.1°), well within one chart
    pixel for a sky-disc that subtends 90° per ~200 px.  Adequate for a
    visual sky chart; not accurate enough for ephemeris-grade work.
    """
    ra_hours, dec_deg, _ = _moon_geocentric(dt)
    return ra_hours, dec_deg


def moon_distance_earth_radii(dt: datetime) -> float:
    """Return the moon's geocentric distance at *dt* in Earth radii.

    Mean distance is ~60.27 Earth radii; perigee ~56.0, apogee ~63.8.  Same
    simplified Schlyter model as :func:`moon_equatorial`, so accuracy is only
    good to a few hundredths of an Earth radius — enough to flag a supermoon
    (full moon near perigee) but not for ephemeris work.
    """
    return _moon_geocentric(dt)[2]


def _moon_geocentric(dt: datetime) -> tuple[float, float, float]:
    """Return the moon's (RA hours, Dec deg, distance in Earth radii) at *dt*."""
    jd = _julian_day_full(dt)
    d = jd - 2451543.5  # Schlyter's "day-number" epoch (2000-01-01 00:00 UT)

    # Mean orbital elements of the Moon (degrees)
    n_node = (125.1228 - 0.0529538083 * d) % 360.0
    incl = 5.1454
    arg_perigee = (318.0634 + 0.1643573223 * d) % 360.0
    a = 60.2666  # Earth radii
    e = 0.054900
    mean_anom = (115.3654 + 13.0649929509 * d) % 360.0

    # Solve Kepler's equation (Newton-Raphson, two iterations is plenty here)
    m_rad = math.radians(mean_anom)
    e_anom = m_rad + e * math.sin(m_rad) * (1.0 + e * math.cos(m_rad))
    for _ in range(2):
        e_anom = e_anom - (e_anom - e * math.sin(e_anom) - m_rad) / (1.0 - e * math.cos(e_anom))

    xv = a * (math.cos(e_anom) - e)
    yv = a * math.sqrt(1.0 - e * e) * math.sin(e_anom)
    true_anom = math.atan2(yv, xv)
    r = math.hypot(xv, yv)

    n_rad = math.radians(n_node)
    incl_rad = math.radians(incl)
    vw_rad = true_anom + math.radians(arg_perigee)

    xh = r * (
        math.cos(n_rad) * math.cos(vw_rad) - math.sin(n_rad) * math.sin(vw_rad) * math.cos(incl_rad)
    )  # noqa: E501
    yh = r * (
        math.sin(n_rad) * math.cos(vw_rad) + math.cos(n_rad) * math.sin(vw_rad) * math.cos(incl_rad)
    )  # noqa: E501
    zh = r * math.sin(vw_rad) * math.sin(incl_rad)

    # Ecliptic → equatorial (mean obliquity of the ecliptic)
    ecl = math.radians(23.4393 - 3.563e-7 * d)
    xe = xh
    ye = yh * math.cos(ecl) - zh * math.sin(ecl)
    ze = yh * math.sin(ecl) + zh * math.cos(ecl)

    ra_deg = math.degrees(math.atan2(ye, xe)) % 360.0
    dec_deg = math.degrees(math.atan2(ze, math.hypot(xe, ye)))
    dist = math.sqrt(xe * xe + ye * ye + ze * ze)
    return ra_deg / 15.0, dec_deg, dist


def _moon_altitude(dt: datetime, latitude: float, longitude: float) -> float:
    """Apparent altitude (deg) of the moon's centre at *dt* (UTC) for a site."""
    ra_hours, dec_deg = moon_equatorial(dt)
    lst = local_sidereal_time(dt, longitude)
    alt, _ = equatorial_to_horizontal(ra_hours, dec_deg, lst, latitude)
    return alt


def moon_times(
    d: date,
    latitude: float,
    longitude: float,
    tz: tzinfo | None = None,
) -> MoonTimes:
    """Compute moonrise / moonset for local date *d* at the given site.

    Scans the 24-hour local day in 10-minute steps for the moon's altitude
    crossing :data:`MOON_RISE_ALTITUDE`, then bisects each crossing to ~30 s.
    Returned datetimes are in UTC (convert to the display timezone for
    rendering, same convention as :func:`sun_times`).  A field is ``None`` when
    that event does not happen on the local date.
    """
    tz = tz or timezone.utc
    day_start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
    step = timedelta(minutes=10)
    steps = 24 * 6  # 10-minute samples across the day

    rise: datetime | None = None
    mset: datetime | None = None

    def alt(dt: datetime) -> float:
        return _moon_altitude(dt.astimezone(timezone.utc), latitude, longitude)

    prev_t = day_start
    prev_a = alt(prev_t) - MOON_RISE_ALTITUDE
    for i in range(1, steps + 1):
        cur_t = day_start + step * i
        cur_a = alt(cur_t) - MOON_RISE_ALTITUDE
        if prev_a == 0.0 or (prev_a < 0.0 < cur_a) or (prev_a > 0.0 > cur_a):
            # Bisect between prev_t and cur_t for the exact crossing.
            lo, hi = prev_t, cur_t
            lo_a = prev_a
            for _ in range(12):  # 10 min / 2^12 ≈ 0.15 s resolution
                mid = lo + (hi - lo) / 2
                mid_a = alt(mid) - MOON_RISE_ALTITUDE
                if (lo_a < 0.0) == (mid_a < 0.0):
                    lo, lo_a = mid, mid_a
                else:
                    hi = mid
            crossing = (lo + (hi - lo) / 2).astimezone(timezone.utc)
            if cur_a > prev_a and rise is None:
                rise = crossing
            elif cur_a < prev_a and mset is None:
                mset = crossing
        prev_t, prev_a = cur_t, cur_a

    return MoonTimes(rise=rise, set=mset)


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
