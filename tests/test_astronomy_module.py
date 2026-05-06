"""Tests for src/astronomy.py — sun/twilight math and meteor-shower lookup."""

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from src.astronomy import (
    METEOR_SHOWERS,
    SUNRISE_ALTITUDE,
    _event_utc,
    _julian_day,
    _julian_day_full,
    day_length,
    day_length_delta,
    equatorial_to_horizontal,
    gmst_degrees,
    local_sidereal_time,
    moon_equatorial,
    next_meteor_shower,
    sun_times,
)

# NYC reference coordinates
NYC_LAT = 40.7128
NYC_LON = -74.0060


class TestJulianDay:
    def test_j2000(self):
        """J2000.0 is Jan 1 2000 12:00 UTC → JD 2451545.0."""
        # Our helper returns JD at 00:00 UTC, so Jan 1 2000 → 2451544.5.
        assert _julian_day(date(2000, 1, 1)) == pytest.approx(2451544.5)

    def test_monotonic(self):
        assert _julian_day(date(2026, 4, 24)) == _julian_day(date(2026, 4, 23)) + 1


class TestSunTimes:
    def test_nyc_sunrise_matches_known_value(self):
        """NYC sunrise on 2026-04-23 is ~6:05 AM EDT (10:05 UTC)."""
        t = sun_times(date(2026, 4, 23), NYC_LAT, NYC_LON)
        assert t.sunrise is not None
        # Within 3 minutes of the NOAA reference
        assert 600 <= t.sunrise.hour * 60 + t.sunrise.minute <= 610

    def test_all_fields_populated_for_temperate_latitude(self):
        t = sun_times(date(2026, 6, 21), NYC_LAT, NYC_LON)
        assert t.sunrise is not None
        assert t.sunset is not None
        assert t.civil_dawn is not None
        assert t.civil_dusk is not None
        assert t.nautical_dawn is not None
        assert t.nautical_dusk is not None
        assert t.astronomical_dawn is not None
        assert t.astronomical_dusk is not None
        assert t.solar_noon is not None

    def test_sunrise_before_sunset(self):
        t = sun_times(date(2026, 4, 23), NYC_LAT, NYC_LON)
        assert t.sunrise < t.sunset

    def test_civil_dawn_before_sunrise(self):
        t = sun_times(date(2026, 4, 23), NYC_LAT, NYC_LON)
        assert t.civil_dawn < t.sunrise

    def test_astronomical_dusk_after_sunset(self):
        t = sun_times(date(2026, 4, 23), NYC_LAT, NYC_LON)
        assert t.astronomical_dusk > t.sunset

    def test_polar_day_returns_none_for_sun_events(self):
        """Above the Arctic Circle in summer the sun never sets — returns None."""
        # Alert, Nunavut: 82.5° N, June solstice
        t = sun_times(date(2026, 6, 21), 82.5, -62.3)
        assert t.sunrise is None
        assert t.sunset is None

    def test_polar_night_returns_none(self):
        """Above the Arctic Circle in winter the sun never rises."""
        t = sun_times(date(2026, 12, 21), 82.5, -62.3)
        assert t.sunrise is None
        assert t.sunset is None

    def test_sun_times_are_utc(self):
        t = sun_times(date(2026, 4, 23), NYC_LAT, NYC_LON)
        assert t.sunrise.tzinfo == timezone.utc

    def test_event_utc_polar_returns_none(self):
        # Polar day on Jun 21 at 85° N
        assert _event_utc(date(2026, 6, 21), 85.0, 0.0, SUNRISE_ALTITUDE, morning=True) is None


class TestDayLength:
    def test_day_length_summer_longer_than_winter(self):
        summer = sun_times(date(2026, 6, 21), NYC_LAT, NYC_LON)
        winter = sun_times(date(2026, 12, 21), NYC_LAT, NYC_LON)
        assert day_length(summer) > day_length(winter)

    def test_day_length_none_when_no_sunrise(self):
        t = sun_times(date(2026, 6, 21), 85.0, 0.0)
        assert day_length(t) is None

    def test_day_length_delta_positive_in_spring(self):
        """Days grow longer in the northern spring."""
        d = day_length_delta(date(2026, 4, 23), NYC_LAT, NYC_LON)
        assert d is not None
        assert d > timedelta(0)

    def test_day_length_delta_negative_in_autumn(self):
        d = day_length_delta(date(2026, 10, 15), NYC_LAT, NYC_LON)
        assert d is not None
        assert d < timedelta(0)

    def test_day_length_delta_none_at_polar_day(self):
        assert day_length_delta(date(2026, 6, 21), 85.0, 0.0) is None


class TestMeteorShowers:
    def test_all_showers_have_valid_peak_date(self):
        for shower in METEOR_SHOWERS:
            # Constructor check — raises ValueError for bad date
            date(2026, shower.peak_month, shower.peak_day)

    def test_next_shower_returns_zero_days_on_peak(self):
        # Perseids peak Aug 12
        shower, days = next_meteor_shower(date(2026, 8, 12))
        assert shower.name == "Perseids"
        assert days == 0

    def test_next_shower_returns_future_date(self):
        shower, days = next_meteor_shower(date(2026, 4, 23))
        assert days >= 0
        # Next shower in late April → Eta Aquariids on May 6
        assert shower.name == "Eta Aquariids"

    def test_next_shower_wraps_across_year_end(self):
        """Asking after December's Ursids (Dec 22) returns January's Quadrantids."""
        shower, days = next_meteor_shower(date(2026, 12, 23))
        assert shower.name == "Quadrantids"
        assert days > 0

    def test_next_shower_skips_always_invalid_peak_dates(self, monkeypatch):
        """A shower with an impossible (month, day) — e.g. Feb 30 — is skipped.

        Exercises the first-arm ValueError path: ``date(year, peak_month, peak_day)``
        raises immediately and the loop ``continue``s without reaching the rollover.
        """
        from src import astronomy

        bogus = astronomy.MeteorShower("Imaginarids", 2, 30, 999)
        monkeypatch.setattr(astronomy, "METEOR_SHOWERS", [bogus, *METEOR_SHOWERS])

        shower, days = astronomy.next_meteor_shower(date(2026, 4, 23))
        # Bogus entry was skipped silently; real lookup still works.
        assert shower.name == "Eta Aquariids"
        assert days >= 0

    def test_next_shower_handles_leap_day_rollover(self, monkeypatch):
        """A Feb-29 shower in a leap year correctly skips the non-leap rollover.

        Exercises the rollover-arm ValueError path: ``date(year, 2, 29)`` succeeds
        in the current (leap) year, but its peak is in the past so the loop tries
        ``date(year + 1, 2, 29)`` — which fails because year+1 is not a leap year.
        """
        from src import astronomy

        leap_only = astronomy.MeteorShower("Leapids", 2, 29, 999)
        monkeypatch.setattr(astronomy, "METEOR_SHOWERS", [leap_only, *METEOR_SHOWERS])

        # 2024 is leap, 2025 is not. Today is past Feb 29 2024 so the year-N
        # peak is in the past → triggers the year-(N+1) rollover, which fails.
        shower, days = astronomy.next_meteor_shower(date(2024, 3, 15))
        # Leapids was skipped on rollover; nearest real shower is Lyrids (Apr 22).
        assert shower.name == "Lyrids"
        assert days >= 0


# ---------------------------------------------------------------------------
# Equatorial / horizontal coordinate transforms (constellation_map theme)
# ---------------------------------------------------------------------------


class TestJulianDayFull:
    def test_j2000_noon(self):
        """J2000.0 = JD 2451545.0 = 2000-01-01 12:00 UTC."""
        dt = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert _julian_day_full(dt) == pytest.approx(2451545.0, abs=1e-6)

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2000, 1, 1, 12, 0, 0)
        assert _julian_day_full(dt) == pytest.approx(2451545.0, abs=1e-6)

    def test_local_tz_converted_correctly(self):
        from zoneinfo import ZoneInfo

        # 7am EST = 12 UTC
        est = datetime(2000, 1, 1, 7, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert _julian_day_full(est) == pytest.approx(2451545.0, abs=1e-6)


class TestGmst:
    def test_j2000_value(self):
        """At 2000-01-01 12:00 UTC, GMST is 18h 41m 50s ≈ 280.46°."""
        dt = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        gmst = gmst_degrees(dt)
        # Reference value 280.46061837° per IAU 1982 mean sidereal time
        assert gmst == pytest.approx(280.46, abs=0.01)

    def test_advances_by_about_15_degrees_per_hour(self):
        """Sidereal day is ~23h 56m so the apparent rate is ~15.04°/hr."""
        a = gmst_degrees(datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc))
        b = gmst_degrees(datetime(2026, 4, 23, 1, 0, tzinfo=timezone.utc))
        diff = (b - a) % 360.0
        assert diff == pytest.approx(15.04, abs=0.05)


class TestLocalSiderealTime:
    def test_lst_increases_with_eastern_longitude(self):
        dt = datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc)
        west = local_sidereal_time(dt, NYC_LON)  # ~ -74°
        east = local_sidereal_time(dt, NYC_LON + 90.0)  # 90° further east
        diff = (east - west) % 360.0
        assert diff == pytest.approx(90.0, abs=1e-6)

    def test_in_zero_to_360(self):
        dt = datetime(2026, 4, 23, 17, 30, tzinfo=timezone.utc)
        lst = local_sidereal_time(dt, NYC_LON)
        assert 0.0 <= lst < 360.0


class TestEquatorialToHorizontal:
    def test_polaris_is_always_at_altitude_equal_to_latitude(self):
        """Polaris is at Dec ~+89.26 — at NYC its altitude must equal latitude."""
        dt = datetime(2026, 4, 23, 5, 0, tzinfo=timezone.utc)
        lst = local_sidereal_time(dt, NYC_LON)
        alt, az = equatorial_to_horizontal(2.530, 89.264, lst, NYC_LAT)
        # Polaris is offset ~0.74° from the true pole, so allow ±1° tolerance.
        assert alt == pytest.approx(NYC_LAT, abs=1.0)
        # Azimuth should be near due North (0° / 360°) within a few degrees.
        assert min(az, 360.0 - az) < 5.0

    def test_object_below_horizon_returns_negative_alt(self):
        """A star at the antipode of zenith must have a negative altitude."""
        dt = datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc)
        lst = local_sidereal_time(dt, NYC_LON)
        # Pick a southern-hemisphere star at low Dec opposite the LST direction
        # so it must be below the horizon for an NYC observer.
        opposite_ra_hours = (lst + 180.0) / 15.0 % 24.0
        alt, _ = equatorial_to_horizontal(opposite_ra_hours, -60.0, lst, NYC_LAT)
        assert alt < 0.0

    def test_zenith_object_has_alt_90(self):
        """An object at RA = LST and Dec = latitude lands at the zenith."""
        dt = datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc)
        lst = local_sidereal_time(dt, NYC_LON)
        alt, _ = equatorial_to_horizontal(lst / 15.0, NYC_LAT, lst, NYC_LAT)
        assert alt == pytest.approx(90.0, abs=0.5)

    def test_azimuth_in_zero_to_360(self):
        """Azimuth must always be in [0, 360)."""
        dt = datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc)
        lst = local_sidereal_time(dt, NYC_LON)
        for ra in (0.0, 6.0, 12.0, 18.0):
            for dec in (-30.0, 0.0, 30.0, 60.0):
                _, az = equatorial_to_horizontal(ra, dec, lst, NYC_LAT)
                assert 0.0 <= az < 360.0


class TestMoonEquatorial:
    def test_returns_finite_within_plausible_range(self):
        ra, dec = moon_equatorial(datetime(2026, 4, 23, 5, 0, tzinfo=timezone.utc))
        assert 0.0 <= ra < 24.0
        assert -90.0 <= dec <= 90.0
        # Moon's geocentric Dec is bounded by ~|28.6°| (5° lunar inclination on
        # top of the 23.4° obliquity).
        assert abs(dec) < 30.0

    def test_moves_about_13_degrees_per_day_in_ra(self):
        """Moon traverses ~360°/27.3 days ≈ 13.2°/day in RA."""
        a_ra, _ = moon_equatorial(datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc))
        b_ra, _ = moon_equatorial(datetime(2026, 4, 24, 0, 0, tzinfo=timezone.utc))
        # Convert delta to degrees and wrap into a signed step
        delta = ((b_ra - a_ra) * 15.0 + 360.0) % 360.0
        if delta > 180.0:
            delta -= 360.0
        assert 8.0 <= delta <= 18.0  # generous to allow elliptical-orbit speed-up

    def test_alt_az_at_known_time(self):
        """Smoke-check: moon round-trips through alt/az without raising."""
        dt = datetime(2026, 4, 23, 5, 0, tzinfo=timezone.utc)
        ra, dec = moon_equatorial(dt)
        lst = local_sidereal_time(dt, NYC_LON)
        alt, az = equatorial_to_horizontal(ra, dec, lst, NYC_LAT)
        assert -90.0 <= alt <= 90.0
        assert 0.0 <= az < 360.0
        # Ensure no NaN sneaks in
        assert not math.isnan(alt) and not math.isnan(az)
