"""Unit tests for src._time — sanctioned aware-datetime helpers."""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timezone

import pytest

from src._time import assert_aware, now_local, now_utc, to_aware


class TestNowUtc:
    def test_returns_aware_datetime(self):
        dt = now_utc()
        assert dt.tzinfo is not None

    def test_timezone_is_utc(self):
        dt = now_utc()
        assert dt.utcoffset().total_seconds() == 0


class TestNowLocal:
    def test_returns_aware_datetime_with_no_tz_arg(self):
        dt = now_local()
        assert dt.tzinfo is not None

    def test_falls_back_to_utc_when_tz_is_none(self):
        dt = now_local(None)
        assert dt.utcoffset().total_seconds() == 0

    def test_honours_explicit_timezone(self):
        ny = zoneinfo.ZoneInfo("America/New_York")
        dt = now_local(ny)
        assert dt.tzinfo is not None
        assert dt.tzinfo is ny or str(dt.tzinfo) == "America/New_York"


class TestToAware:
    def test_naive_datetime_gets_utc_when_no_tz(self):
        naive = datetime(2026, 5, 5, 12, 0)
        result = to_aware(naive)
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0
        assert result.replace(tzinfo=None) == naive

    def test_naive_datetime_gets_supplied_tz(self):
        ny = zoneinfo.ZoneInfo("America/New_York")
        naive = datetime(2026, 5, 5, 12, 0)
        result = to_aware(naive, tz=ny)
        assert result.tzinfo is not None
        assert result.replace(tzinfo=None) == naive

    def test_aware_datetime_passes_through_unchanged(self):
        """Already-aware value must be returned as-is — no tz conversion."""
        aware = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
        result = to_aware(aware)
        assert result is aware

    def test_aware_datetime_with_explicit_tz_still_passes_through(self):
        """Even when tz is given, an already-aware value is never re-wrapped."""
        ny = zoneinfo.ZoneInfo("America/New_York")
        aware = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
        result = to_aware(aware, tz=ny)
        assert result is aware
        assert result.tzinfo is timezone.utc


class TestAssertAware:
    def test_aware_datetime_returned_unchanged(self):
        aware = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
        result = assert_aware(aware)
        assert result is aware

    def test_naive_datetime_raises_value_error(self):
        naive = datetime(2026, 5, 5, 12, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            assert_aware(naive)

    def test_error_message_includes_custom_name(self):
        naive = datetime(2026, 5, 5, 12, 0)
        with pytest.raises(ValueError, match="fetched_at"):
            assert_aware(naive, name="fetched_at")


class TestDayStartUtc:
    """Regression tests for issue #203 — fetch-window boundaries must be built
    in the *configured* timezone, not the host machine's."""

    def test_configured_tz_midnight_ignores_host_tz(self, monkeypatch):
        import time as _time_mod
        from datetime import date

        from src._time import day_start_utc

        # Host tz pinned to UTC (the default Pi setup); configured tz is Eastern.
        monkeypatch.setenv("TZ", "UTC")
        _time_mod.tzset()
        ny = zoneinfo.ZoneInfo("America/New_York")
        result = day_start_utc(date(2026, 6, 15), ny)
        # Midnight EDT (UTC-4) on Jun 15 is 04:00 UTC — NOT 00:00 UTC.
        assert result == datetime(2026, 6, 15, 4, 0, tzinfo=timezone.utc)

    def test_configured_tz_midnight_in_winter_offset(self, monkeypatch):
        import time as _time_mod
        from datetime import date

        from src._time import day_start_utc

        monkeypatch.setenv("TZ", "UTC")
        _time_mod.tzset()
        ny = zoneinfo.ZoneInfo("America/New_York")
        result = day_start_utc(date(2026, 1, 15), ny)
        # Midnight EST (UTC-5) on Jan 15 is 05:00 UTC.
        assert result == datetime(2026, 1, 15, 5, 0, tzinfo=timezone.utc)

    def test_none_tz_uses_host_timezone(self, monkeypatch):
        import time as _time_mod
        from datetime import date

        from src._time import day_start_utc

        # With no configured tz the fetchers derive `today` from the host clock,
        # so the boundary must stay host-tz-consistent (historical behaviour).
        monkeypatch.setenv("TZ", "America/Los_Angeles")
        _time_mod.tzset()
        result = day_start_utc(date(2026, 6, 15), None)
        # Midnight PDT (UTC-7) on Jun 15 is 07:00 UTC.
        assert result == datetime(2026, 6, 15, 7, 0, tzinfo=timezone.utc)

    def test_result_is_aware_utc(self):
        from datetime import date

        from src._time import day_start_utc

        result = day_start_utc(date(2026, 3, 1), timezone.utc)
        assert result.tzinfo is timezone.utc
        assert result == datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
