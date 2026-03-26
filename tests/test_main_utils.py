"""Tests for utility functions in src/main.py."""

import zoneinfo
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from src.main import (
    _in_quiet_hours, _is_morning_startup, _retry_fetch, _resolve_tz, generate_dummy_data,
)


class TestRetryFetch:
    def test_returns_value_on_first_success(self):
        fn = MagicMock(return_value=42)
        result = _retry_fetch("test", fn)
        assert result == 42
        assert fn.call_count == 1

    def test_retries_on_first_failure(self):
        fn = MagicMock(side_effect=[Exception("oops"), 99])
        result = _retry_fetch("test", fn)
        assert result == 99
        assert fn.call_count == 2

    def test_raises_on_second_failure(self):
        fn = MagicMock(side_effect=Exception("always fails"))
        with pytest.raises(Exception, match="always fails"):
            _retry_fetch("test", fn)
        assert fn.call_count == 2

    def test_does_not_retry_on_runtime_error(self):
        fn = MagicMock(side_effect=RuntimeError("permanent failure"))
        with pytest.raises(RuntimeError, match="permanent failure"):
            _retry_fetch("test", fn)
        assert fn.call_count == 1

    def test_label_included_in_warning_log(self, caplog):
        import logging
        fn = MagicMock(side_effect=[Exception("boom"), "ok"])
        with caplog.at_level(logging.WARNING, logger="src.main"):
            _retry_fetch("MyLabel", fn)
        assert "MyLabel" in caplog.text


class TestGenerateDummyData:
    def test_returns_dashboard_data(self):
        from src.data.models import DashboardData
        data = generate_dummy_data()
        assert isinstance(data, DashboardData)

    def test_has_events(self):
        data = generate_dummy_data()
        assert len(data.events) > 0

    def test_has_weather(self):
        data = generate_dummy_data()
        assert data.weather is not None
        assert data.weather.current_temp != 0

    def test_weather_has_forecast(self):
        data = generate_dummy_data()
        assert len(data.weather.forecast) == 5

    def test_has_birthdays(self):
        data = generate_dummy_data()
        assert len(data.birthdays) >= 1

    def test_fetched_at_is_recent(self):
        before = datetime.now()
        data = generate_dummy_data()
        after = datetime.now()
        assert before <= data.fetched_at <= after

    def test_all_events_have_valid_times(self):
        data = generate_dummy_data()
        for event in data.events:
            assert event.start < event.end, f"Event '{event.summary}' has start >= end"

    def test_birthdays_in_future(self):
        today = date.today()
        data = generate_dummy_data()
        for bday in data.birthdays:
            assert bday.date >= today, f"Birthday '{bday.name}' is in the past"

    def test_is_not_stale(self):
        data = generate_dummy_data()
        assert data.is_stale is False

    def test_with_timezone_returns_aware_fetched_at(self):
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        data = generate_dummy_data(tz=tz)
        assert data.fetched_at.tzinfo is not None

    def test_with_timezone_today_matches_tz(self):
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        data = generate_dummy_data(tz=tz)
        expected_today = datetime.now(tz).date()
        assert data.fetched_at.date() == expected_today

    def test_now_override_sets_fetched_at(self):
        fixed = datetime(2025, 12, 25, 10, 0, 0)
        data = generate_dummy_data(now=fixed)
        assert data.fetched_at == fixed

    def test_now_override_anchors_events_to_date(self):
        fixed = datetime(2025, 12, 25, 10, 0, 0)
        data = generate_dummy_data(now=fixed)
        # Events are week-anchored; Monday of 2025-12-25's week is 2025-12-22
        from datetime import date
        expected_week_start = date(2025, 12, 22)
        event_dates = {e.start.date() for e in data.events if not e.is_all_day}
        # All timed events should fall within the week of 2025-12-22
        for d in event_dates:
            assert d >= expected_week_start
            assert d < date(2025, 12, 29)

    def test_now_override_anchors_forecast_to_date(self):
        fixed = datetime(2025, 12, 25, 10, 0, 0)
        data = generate_dummy_data(now=fixed)
        from datetime import date
        # First forecast day should be 2025-12-26 (today + 1)
        assert data.weather.forecast[0].date == date(2025, 12, 26)


class TestInQuietHours:
    def _dt(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 3, 17, hour, minute)

    def test_inside_overnight_window(self):
        # 23:00–06:00 window; 02:00 is inside
        assert _in_quiet_hours(self._dt(2), start_hour=23, end_hour=6) is True

    def test_at_start_of_window(self):
        assert _in_quiet_hours(self._dt(23), start_hour=23, end_hour=6) is True

    def test_just_before_end_of_window(self):
        assert _in_quiet_hours(self._dt(5), start_hour=23, end_hour=6) is True

    def test_at_end_of_window_is_active(self):
        # end_hour itself is not quiet (window is half-open [start, end))
        assert _in_quiet_hours(self._dt(6), start_hour=23, end_hour=6) is False

    def test_midday_is_active(self):
        assert _in_quiet_hours(self._dt(12), start_hour=23, end_hour=6) is False

    def test_same_day_window(self):
        # e.g. quiet from 13:00 to 15:00
        assert _in_quiet_hours(self._dt(14), start_hour=13, end_hour=15) is True
        assert _in_quiet_hours(self._dt(12), start_hour=13, end_hour=15) is False
        assert _in_quiet_hours(self._dt(15), start_hour=13, end_hour=15) is False


class TestIsMorningStartup:
    def _dt(self, hour: int, minute: int) -> datetime:
        return datetime(2026, 3, 17, hour, minute)

    def test_exactly_at_wake_hour(self):
        assert _is_morning_startup(self._dt(6, 0), quiet_hours_end=6) is True

    def test_within_first_slot(self):
        assert _is_morning_startup(self._dt(6, 15), quiet_hours_end=6) is True

    def test_at_minute_29(self):
        assert _is_morning_startup(self._dt(6, 29), quiet_hours_end=6) is True

    def test_at_minute_30_is_not_morning(self):
        assert _is_morning_startup(self._dt(6, 30), quiet_hours_end=6) is False

    def test_wrong_hour_is_not_morning(self):
        assert _is_morning_startup(self._dt(7, 0), quiet_hours_end=6) is False

    def test_custom_wake_hour(self):
        assert _is_morning_startup(self._dt(7, 10), quiet_hours_end=7) is True
        assert _is_morning_startup(self._dt(6, 10), quiet_hours_end=7) is False


class TestResolveTz:
    def test_local_returns_tzinfo(self):
        tz = _resolve_tz("local")
        assert tz is not None

    def test_iana_name_returns_zone_info(self):
        tz = _resolve_tz("America/Los_Angeles")
        assert isinstance(tz, zoneinfo.ZoneInfo)

    def test_utc_name(self):
        tz = _resolve_tz("UTC")
        assert isinstance(tz, zoneinfo.ZoneInfo)
