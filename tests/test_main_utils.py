"""Tests for utility functions in the refactored runtime modules."""

import zoneinfo
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from src.config import resolve_tz
from src.data_pipeline import retry_fetch
from src.dummy_data import generate_dummy_data
from src.services.run_policy import (
    in_quiet_hours,
    is_morning_startup_window,
    record_morning_refresh,
    should_force_full_refresh,
    should_skip_refresh,
)


class TestRetryFetch:
    def test_returns_value_on_first_success(self):
        fn = MagicMock(return_value=42)
        result = retry_fetch("test", fn)
        assert result == 42
        assert fn.call_count == 1

    def test_retries_on_first_failure(self):
        fn = MagicMock(side_effect=[Exception("oops"), 99])
        result = retry_fetch("test", fn)
        assert result == 99
        assert fn.call_count == 2

    def test_raises_on_second_failure(self):
        fn = MagicMock(side_effect=Exception("always fails"))
        with pytest.raises(Exception, match="always fails"):
            retry_fetch("test", fn)
        assert fn.call_count == 2

    def test_does_not_retry_on_runtime_error(self):
        fn = MagicMock(side_effect=RuntimeError("permanent failure"))
        with pytest.raises(RuntimeError, match="permanent failure"):
            retry_fetch("test", fn)
        assert fn.call_count == 1

    def test_label_included_in_warning_log(self, caplog):
        import logging

        fn = MagicMock(side_effect=[Exception("boom"), "ok"])
        with caplog.at_level(logging.WARNING, logger="src.data_pipeline"):
            retry_fetch("MyLabel", fn)
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
        expected_week_start = date(2025, 12, 22)
        event_dates = {e.start.date() for e in data.events if not e.is_all_day}
        for d in event_dates:
            assert d >= expected_week_start
            assert d < date(2025, 12, 29)

    def test_now_override_anchors_forecast_to_date(self):
        fixed = datetime(2025, 12, 25, 10, 0, 0)
        data = generate_dummy_data(now=fixed)
        assert data.weather.forecast[0].date == date(2025, 12, 26)


class TestInQuietHours:
    def _dt(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 3, 17, hour, minute)

    def test_inside_overnight_window(self):
        assert in_quiet_hours(self._dt(2), start_hour=23, end_hour=6) is True

    def test_at_start_of_window(self):
        assert in_quiet_hours(self._dt(23), start_hour=23, end_hour=6) is True

    def test_just_before_end_of_window(self):
        assert in_quiet_hours(self._dt(5), start_hour=23, end_hour=6) is True

    def test_at_end_of_window_is_active(self):
        assert in_quiet_hours(self._dt(6), start_hour=23, end_hour=6) is False

    def test_midday_is_active(self):
        assert in_quiet_hours(self._dt(12), start_hour=23, end_hour=6) is False

    def test_same_day_window(self):
        assert in_quiet_hours(self._dt(14), start_hour=13, end_hour=15) is True
        assert in_quiet_hours(self._dt(12), start_hour=13, end_hour=15) is False
        assert in_quiet_hours(self._dt(15), start_hour=13, end_hour=15) is False


class TestIsMorningStartupWindow:
    def _dt(self, hour: int, minute: int) -> datetime:
        return datetime(2026, 3, 17, hour, minute)

    def test_exactly_at_wake_hour(self):
        assert is_morning_startup_window(self._dt(6, 0), quiet_hours_end=6) is True

    def test_within_first_slot(self):
        assert is_morning_startup_window(self._dt(6, 15), quiet_hours_end=6) is True

    def test_at_minute_29(self):
        assert is_morning_startup_window(self._dt(6, 29), quiet_hours_end=6) is True

    def test_at_minute_30_is_not_morning(self):
        assert is_morning_startup_window(self._dt(6, 30), quiet_hours_end=6) is False

    def test_wrong_hour_is_not_morning(self):
        assert is_morning_startup_window(self._dt(7, 0), quiet_hours_end=6) is False

    def test_custom_wake_hour(self):
        assert is_morning_startup_window(self._dt(7, 10), quiet_hours_end=7) is True
        assert is_morning_startup_window(self._dt(6, 10), quiet_hours_end=7) is False


class TestResolveThemeName:
    def test_explicit_theme_returned_unchanged(self):
        from src.config import Config
        from src.services.theme import resolve_theme_name

        cfg = Config()
        cfg.theme = "minimalist"
        assert resolve_theme_name(cfg, override_theme=None) == "minimalist"

    def test_override_takes_precedence_over_config(self):
        from src.config import Config
        from src.services.theme import resolve_theme_name

        cfg = Config()
        cfg.theme = "default"
        assert resolve_theme_name(cfg, override_theme="terminal") == "terminal"

    def test_random_theme_delegates_to_pick(self, tmp_path):
        """theme='random' calls pick_random_theme and returns a concrete name."""
        from unittest.mock import patch

        from src.config import Config
        from src.services.theme import resolve_theme_name

        cfg = Config()
        cfg.theme = "random"
        cfg.random_theme.include = []
        cfg.random_theme.exclude = []
        cfg.output_dir = str(tmp_path)
        with patch(
            "src.render.random_theme.pick_random_theme", return_value="minimalist"
        ) as mock_pick:
            result = resolve_theme_name(cfg, override_theme=None)
        assert result == "minimalist"
        mock_pick.assert_called_once()


class TestShouldSkipRefresh:
    def _dt(self, hour: int) -> datetime:
        return datetime(2026, 3, 17, hour, 0)

    def test_quiet_hours_and_not_dry_run_returns_true(self):
        # hour=2 is inside the 23:00–06:00 quiet window
        assert should_skip_refresh(self._dt(2), 23, 6, dry_run=False) is True

    def test_quiet_hours_but_dry_run_returns_false(self):
        assert should_skip_refresh(self._dt(2), 23, 6, dry_run=True) is False

    def test_outside_quiet_hours_returns_false(self):
        # hour=12 is outside the quiet window
        assert should_skip_refresh(self._dt(12), 23, 6, dry_run=False) is False


class TestShouldForceFullRefresh:
    def _dt(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 3, 17, hour, minute)

    def test_force_flag_true_returns_true(self, tmp_path):
        assert (
            should_force_full_refresh(
                self._dt(12),
                quiet_hours_end=6,
                force_full_refresh_flag=True,
                state_dir=str(tmp_path),
            )
            is True
        )

    def test_force_flag_wins_over_marker(self, tmp_path):
        # Marker present for today; CLI flag still forces a refresh
        record_morning_refresh(self._dt(6, 10), str(tmp_path))
        assert (
            should_force_full_refresh(
                self._dt(6, 10),
                quiet_hours_end=6,
                force_full_refresh_flag=True,
                state_dir=str(tmp_path),
            )
            is True
        )

    def test_morning_startup_no_marker_returns_true(self, tmp_path):
        # hour=6, minute=10 → morning startup window (quiet_hours_end=6), no marker
        assert (
            should_force_full_refresh(
                self._dt(6, 10),
                quiet_hours_end=6,
                force_full_refresh_flag=False,
                state_dir=str(tmp_path),
            )
            is True
        )

    def test_morning_startup_marker_today_returns_false(self, tmp_path):
        record_morning_refresh(self._dt(6, 5), str(tmp_path))
        assert (
            should_force_full_refresh(
                self._dt(6, 20),
                quiet_hours_end=6,
                force_full_refresh_flag=False,
                state_dir=str(tmp_path),
            )
            is False
        )

    def test_morning_startup_marker_yesterday_returns_true(self, tmp_path):
        yesterday = datetime(2026, 3, 16, 6, 5)
        record_morning_refresh(yesterday, str(tmp_path))
        assert (
            should_force_full_refresh(
                self._dt(6, 10),
                quiet_hours_end=6,
                force_full_refresh_flag=False,
                state_dir=str(tmp_path),
            )
            is True
        )

    def test_neither_flag_nor_morning_startup_returns_false(self, tmp_path):
        # hour=12 is not morning startup
        assert (
            should_force_full_refresh(
                self._dt(12),
                quiet_hours_end=6,
                force_full_refresh_flag=False,
                state_dir=str(tmp_path),
            )
            is False
        )


class TestRecordMorningRefresh:
    def _dt(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 3, 17, hour, minute)

    def test_writes_marker_file(self, tmp_path):
        import json

        record_morning_refresh(self._dt(6, 5), str(tmp_path))
        marker = tmp_path / "morning_refresh_state.json"
        assert marker.exists()
        payload = json.loads(marker.read_text())
        assert payload == {"last_refresh_date": "2026-03-17"}

    def test_overwrites_existing_marker(self, tmp_path):
        import json

        record_morning_refresh(datetime(2026, 3, 16, 6, 5), str(tmp_path))
        record_morning_refresh(self._dt(6, 10), str(tmp_path))
        payload = json.loads((tmp_path / "morning_refresh_state.json").read_text())
        assert payload == {"last_refresh_date": "2026-03-17"}

    def test_creates_parent_directory(self, tmp_path):
        state_dir = tmp_path / "nested" / "state"
        record_morning_refresh(self._dt(6, 5), str(state_dir))
        assert (state_dir / "morning_refresh_state.json").exists()

    def test_os_error_logged_not_raised(self, tmp_path, caplog):
        import logging
        from unittest.mock import patch

        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            with caplog.at_level(logging.WARNING, logger="src.services.run_policy"):
                record_morning_refresh(self._dt(6, 5), str(tmp_path))
        assert "Failed to write morning refresh state" in caplog.text


class TestLoadLastMorningRefresh:
    def _dt(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 3, 17, hour, minute)

    def test_missing_file_returns_none(self, tmp_path):
        from src.services.run_policy import _load_last_morning_refresh

        assert _load_last_morning_refresh(str(tmp_path)) is None

    def test_malformed_json_returns_none(self, tmp_path):
        from src.services.run_policy import _load_last_morning_refresh

        (tmp_path / "morning_refresh_state.json").write_text("not json")
        assert _load_last_morning_refresh(str(tmp_path)) is None

    def test_non_object_json_returns_none(self, tmp_path):
        from src.services.run_policy import _load_last_morning_refresh

        # Valid JSON but not a dict — must not raise AttributeError
        (tmp_path / "morning_refresh_state.json").write_text("[]")
        assert _load_last_morning_refresh(str(tmp_path)) is None
        (tmp_path / "morning_refresh_state.json").write_text('"2026-04-23"')
        assert _load_last_morning_refresh(str(tmp_path)) is None

    def test_missing_key_returns_none(self, tmp_path):
        from src.services.run_policy import _load_last_morning_refresh

        (tmp_path / "morning_refresh_state.json").write_text("{}")
        assert _load_last_morning_refresh(str(tmp_path)) is None

    def test_non_string_value_returns_none(self, tmp_path):
        import json

        from src.services.run_policy import _load_last_morning_refresh

        (tmp_path / "morning_refresh_state.json").write_text(
            json.dumps({"last_refresh_date": 12345})
        )
        assert _load_last_morning_refresh(str(tmp_path)) is None

    def test_bad_date_format_returns_none(self, tmp_path):
        import json

        from src.services.run_policy import _load_last_morning_refresh

        (tmp_path / "morning_refresh_state.json").write_text(
            json.dumps({"last_refresh_date": "not-a-date"})
        )
        assert _load_last_morning_refresh(str(tmp_path)) is None

    def test_valid_marker_returns_date(self, tmp_path):
        from datetime import date

        from src.services.run_policy import _load_last_morning_refresh

        record_morning_refresh(self._dt(6, 5), str(tmp_path))
        assert _load_last_morning_refresh(str(tmp_path)) == date(2026, 3, 17)


class TestResolveTz:
    def test_local_returns_tzinfo(self):
        tz = resolve_tz("local")
        assert tz is not None

    def test_iana_name_returns_zone_info(self):
        tz = resolve_tz("America/Los_Angeles")
        assert isinstance(tz, zoneinfo.ZoneInfo)

    def test_utc_name(self):
        tz = resolve_tz("UTC")
        assert isinstance(tz, zoneinfo.ZoneInfo)
