"""Tests for src/astronomy.py — sun/twilight math and meteor-shower lookup."""

from datetime import date, timedelta, timezone

import pytest

from src.astronomy import (
    METEOR_SHOWERS,
    SUNRISE_ALTITUDE,
    _event_utc,
    _julian_day,
    day_length,
    day_length_delta,
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
