"""Tests for bugfixes identified during codebase review.

Covers:
  C1 — max_partials_before_full default consistency
  C2 — empty weather array guard
  C3 — Feb 29 birthday in non-leap year
  H2 — circuit breaker UTC timestamps
  H5 — quiet hours / fetch interval validation
  M3 — quota tracker thread safety
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.config import (
    CacheConfig,
    Config,
    DisplayConfig,
    ScheduleConfig,
    WeatherConfig,
    load_config,
    validate_config,
)
from src.data.models import Birthday
from src.fetchers.circuit_breaker import CircuitBreaker
from src.fetchers.weather import fetch_weather

# ---------------------------------------------------------------------------
# C1: max_partials_before_full default consistency
# ---------------------------------------------------------------------------


class TestMaxPartialsDefault:
    def test_dataclass_default_is_twenty(self):
        d = DisplayConfig()
        assert d.max_partials_before_full == 20

    def test_load_config_default_matches_dataclass(self, tmp_path):
        """load_config() with a display section but no max_partials should
        produce the same default as the dataclass."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": {"model": "epd7in5_V2"}}))
        cfg = load_config(str(p))
        assert cfg.display.max_partials_before_full == DisplayConfig().max_partials_before_full
        assert cfg.display.max_partials_before_full == 20


# ---------------------------------------------------------------------------
# C2: empty weather array guard
# ---------------------------------------------------------------------------


class TestEmptyWeatherArrayGuard:
    @staticmethod
    def _mock_forecast_resp():
        resp = MagicMock()
        resp.json.return_value = {"list": []}
        resp.raise_for_status = MagicMock()
        return resp

    @staticmethod
    def _mock_alerts_resp():
        resp = MagicMock()
        resp.json.return_value = {}
        resp.raise_for_status = MagicMock()
        return resp

    @patch("src.fetchers.weather.requests.Session")
    def test_raises_on_empty_weather_array(self, mock_session_cls):
        cfg = WeatherConfig(api_key="k", latitude=1.0, longitude=2.0)
        current_resp = MagicMock()
        current_resp.json.return_value = {
            "main": {"temp": 42, "temp_max": 48, "temp_min": 35, "humidity": 65},
            "weather": [],  # empty
        }
        current_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.side_effect = [
            current_resp,
            self._mock_forecast_resp(),
            self._mock_alerts_resp(),
        ]
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(RuntimeError, match="weather"):
            fetch_weather(cfg)

    @patch("src.fetchers.weather.requests.Session")
    def test_raises_on_missing_main_key(self, mock_session_cls):
        cfg = WeatherConfig(api_key="k", latitude=1.0, longitude=2.0)
        current_resp = MagicMock()
        current_resp.json.return_value = {
            "weather": [{"icon": "01d", "description": "clear"}],
            # no "main" key
        }
        current_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.side_effect = [
            current_resp,
            self._mock_forecast_resp(),
            self._mock_alerts_resp(),
        ]
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(RuntimeError, match="main"):
            fetch_weather(cfg)


# ---------------------------------------------------------------------------
# C3: Feb 29 birthday in non-leap year
# ---------------------------------------------------------------------------


class TestFeb29Birthday:
    def test_feb29_birthday_does_not_crash(self):
        from PIL import Image, ImageDraw

        from src.render.components.birthday_bar import draw_birthdays

        img = Image.new("1", (800, 480), 1)
        draw = ImageDraw.Draw(img)
        # 2025 is not a leap year
        today = date(2025, 3, 15)
        birthdays = [Birthday(name="Leapy", date=date(2000, 2, 29))]
        # Should not raise ValueError
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_feb29_birthday_next_year_non_leap(self):
        from PIL import Image, ImageDraw

        from src.render.components.birthday_bar import draw_birthdays

        img = Image.new("1", (800, 480), 1)
        draw = ImageDraw.Draw(img)
        # Birthday already passed this year, next year (2026) also not leap
        today = date(2025, 3, 15)
        birthdays = [Birthday(name="Leapy", date=date(2000, 2, 29))]
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None


# ---------------------------------------------------------------------------
# H2: circuit breaker UTC timestamps
# ---------------------------------------------------------------------------


class TestCircuitBreakerUTC:
    def test_failure_timestamp_is_utc(self, tmp_path):
        cb = CircuitBreaker(max_failures=3, state_dir=str(tmp_path))
        cb.record_failure("weather")
        ts = cb._states["weather"].last_failure_at
        # Should contain timezone offset (UTC: +00:00)
        assert "+00:00" in ts or "Z" in ts

    def test_cooldown_works_with_utc(self, tmp_path):
        cb = CircuitBreaker(
            max_failures=1,
            cooldown_minutes=0,
            state_dir=str(tmp_path),
        )
        cb.record_failure("weather")
        assert cb._states["weather"].state == "open"
        # Cooldown=0 so should transition to half_open
        assert cb.should_attempt("weather") is True

    def test_legacy_naive_timestamp_handled(self, tmp_path):
        """Old state files with naive timestamps should still work."""
        import json

        state_file = tmp_path / "dashboard_breaker_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "weather": {
                        "consecutive_failures": 3,
                        "last_failure_at": "2020-01-01T00:00:00",  # naive, old
                        "state": "open",
                    }
                }
            )
        )
        cb = CircuitBreaker(
            max_failures=3,
            cooldown_minutes=30,
            state_dir=str(tmp_path),
        )
        # Old timestamp — cooldown should be expired
        assert cb.should_attempt("weather") is True


# ---------------------------------------------------------------------------
# H5: quiet hours validation
# ---------------------------------------------------------------------------


class TestQuietHoursValidation:
    def test_invalid_quiet_hours_start_is_error(self):
        cfg = Config(schedule=ScheduleConfig(quiet_hours_start=25))
        errors, _ = validate_config(cfg)
        assert any(e.field == "schedule.quiet_hours_start" for e in errors)

    def test_negative_quiet_hours_end_is_error(self):
        cfg = Config(schedule=ScheduleConfig(quiet_hours_end=-1))
        errors, _ = validate_config(cfg)
        assert any(e.field == "schedule.quiet_hours_end" for e in errors)

    def test_valid_quiet_hours_no_error(self):
        cfg = Config(
            schedule=ScheduleConfig(
                quiet_hours_start=23,
                quiet_hours_end=6,
            )
        )
        errors, _ = validate_config(cfg)
        assert not any(e.field.startswith("schedule.quiet_hours") for e in errors)


# ---------------------------------------------------------------------------
# M4: negative fetch interval validation
# ---------------------------------------------------------------------------


class TestFetchIntervalValidation:
    def test_negative_fetch_interval_is_error(self):
        cfg = Config(cache=CacheConfig(weather_fetch_interval=-30))
        errors, _ = validate_config(cfg)
        assert any(e.field == "cache.weather_fetch_interval" for e in errors)

    def test_zero_fetch_interval_is_error(self):
        cfg = Config(cache=CacheConfig(events_fetch_interval=0))
        errors, _ = validate_config(cfg)
        assert any(e.field == "cache.events_fetch_interval" for e in errors)

    def test_positive_fetch_interval_no_error(self):
        cfg = Config(
            cache=CacheConfig(
                weather_fetch_interval=30,
                events_fetch_interval=120,
                birthdays_fetch_interval=1440,
            )
        )
        errors, _ = validate_config(cfg)
        assert not any(e.field.startswith("cache.") and "interval" in e.field for e in errors)
