"""Tests for cache + circuit breaker interaction scenarios in DataPipeline."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from src.config import Config
from src.data.models import (
    CalendarEvent,
    StalenessLevel,
    WeatherData,
)
from src.data_pipeline import DataPipeline


def _make_weather():
    return WeatherData(
        current_temp=68.0,
        current_icon="01d",
        current_description="clear",
        high=75.0,
        low=55.0,
        humidity=40,
    )


def _make_events():
    return [
        CalendarEvent(
            summary="Meeting",
            start=datetime(2024, 3, 15, 10, 0),
            end=datetime(2024, 3, 15, 11, 0),
        )
    ]


# ---------------------------------------------------------------------------
# Stale cache + breaker OPEN scenarios
# ---------------------------------------------------------------------------


class TestStaleCacheBreakerOpen:
    @patch("src.data_pipeline.fetch_host_data", return_value=None)
    @patch("src.data_pipeline.fetch_weather", return_value=None)
    @patch("src.data_pipeline.fetch_events", return_value=[])
    @patch("src.data_pipeline.fetch_birthdays", return_value=[])
    def test_breaker_open_uses_stale_cache(
        self, mock_bdays, mock_events, mock_weather, mock_host, tmp_path
    ):
        """When breaker is OPEN, pipeline should return stale cached data."""
        cache_dir = str(tmp_path)

        # Seed cache with stale data
        weather = _make_weather()
        events = _make_events()
        stale_time = datetime.now() - timedelta(hours=3)
        _write_cache(cache_dir, events, weather, stale_time)

        # Create a breaker state that marks weather as OPEN
        _write_breaker_open(cache_dir, "weather")

        cfg = Config()
        pipeline = DataPipeline(cfg, cache_dir=cache_dir)
        data = pipeline.fetch()

        # Weather should be stale but present
        assert data.weather is not None
        assert data.weather.current_temp == 68.0
        assert "weather" in data.stale_sources

    @patch("src.data_pipeline.fetch_host_data", return_value=None)
    @patch("src.data_pipeline.fetch_weather", return_value=None)
    @patch("src.data_pipeline.fetch_events", return_value=[])
    @patch("src.data_pipeline.fetch_birthdays", return_value=[])
    def test_breaker_open_no_cache_returns_none(
        self, mock_bdays, mock_events, mock_weather, mock_host, tmp_path
    ):
        """When breaker is OPEN and no cache exists, weather should be None."""
        cache_dir = str(tmp_path)

        # No cache seeded — breaker open with nothing to fall back to
        _write_breaker_open(cache_dir, "weather")

        cfg = Config()
        pipeline = DataPipeline(cfg, cache_dir=cache_dir)
        data = pipeline.fetch()

        assert data.weather is None


# ---------------------------------------------------------------------------
# Breaker HALF_OPEN scenarios
# ---------------------------------------------------------------------------


class TestBreakerHalfOpen:
    @patch("src.data_pipeline.fetch_host_data", return_value=None)
    @patch("src.data_pipeline.fetch_weather")
    @patch("src.data_pipeline.fetch_events", return_value=[])
    @patch("src.data_pipeline.fetch_birthdays", return_value=[])
    def test_half_open_success_resets_breaker(
        self, mock_bdays, mock_events, mock_weather, mock_host, tmp_path
    ):
        """When breaker is HALF_OPEN and fetch succeeds, breaker resets to CLOSED."""
        cache_dir = str(tmp_path)
        weather = _make_weather()
        mock_weather.return_value = weather

        # Set breaker to open with 0 cooldown (immediately half_open)
        _write_breaker_open(cache_dir, "weather", cooldown=0)

        cfg = Config()
        pipeline = DataPipeline(cfg, cache_dir=cache_dir, ignore_breakers=True)
        data = pipeline.fetch()

        assert data.weather is not None
        assert data.source_staleness.get("weather") == StalenessLevel.FRESH

    @patch("src.data_pipeline.fetch_host_data", return_value=None)
    @patch("src.data_pipeline.fetch_weather")
    @patch("src.data_pipeline.fetch_events", return_value=[])
    @patch("src.data_pipeline.fetch_birthdays", return_value=[])
    def test_fetch_failure_with_cache_fallback(
        self, mock_bdays, mock_events, mock_weather, mock_host, tmp_path
    ):
        """When fetch fails, pipeline should fall back to cached data."""
        cache_dir = str(tmp_path)
        mock_weather.side_effect = ConnectionError("network down")

        # Seed cache
        stale_time = datetime.now() - timedelta(hours=1)
        _write_cache(cache_dir, [], _make_weather(), stale_time)

        cfg = Config()
        pipeline = DataPipeline(cfg, cache_dir=cache_dir, force_refresh=True)
        data = pipeline.fetch()

        # Should have fallen back to cache
        assert data.weather is not None
        assert "weather" in data.stale_sources


# ---------------------------------------------------------------------------
# Expired cache scenarios
# ---------------------------------------------------------------------------


class TestExpiredCache:
    @patch("src.data_pipeline.fetch_host_data", return_value=None)
    @patch("src.data_pipeline.fetch_weather", return_value=None)
    @patch("src.data_pipeline.fetch_events", return_value=[])
    @patch("src.data_pipeline.fetch_birthdays", return_value=[])
    def test_expired_cache_discarded_on_breaker_open(
        self, mock_bdays, mock_events, mock_weather, mock_host, tmp_path
    ):
        """Cache older than 4x TTL should be discarded, even with breaker open."""
        cache_dir = str(tmp_path)

        # Seed cache with very old data (>4x TTL)
        very_old = datetime.now() - timedelta(hours=24)
        _write_cache(cache_dir, [], _make_weather(), very_old)

        # Breaker open for weather
        _write_breaker_open(cache_dir, "weather")

        cfg = Config()
        pipeline = DataPipeline(cfg, cache_dir=cache_dir)
        data = pipeline.fetch()

        # Expired cache should be discarded — weather is None
        assert data.weather is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_cache(cache_dir: str, events, weather, fetched_at: datetime):
    """Write a v2 cache file for testing."""
    from pathlib import Path

    cache_data = {"schema_version": 2}
    if events:
        cache_data["events"] = {
            "fetched_at": fetched_at.isoformat(),
            "data": [
                {
                    "summary": e.summary,
                    "start": e.start.isoformat(),
                    "end": e.end.isoformat(),
                    "is_all_day": e.is_all_day,
                    "location": e.location,
                    "calendar_name": e.calendar_name,
                }
                for e in events
            ],
        }
    if weather:
        cache_data["weather"] = {
            "fetched_at": fetched_at.isoformat(),
            "data": {
                "current_temp": weather.current_temp,
                "current_icon": weather.current_icon,
                "current_description": weather.current_description,
                "high": weather.high,
                "low": weather.low,
                "humidity": weather.humidity,
            },
        }

    path = Path(cache_dir) / "dashboard_cache.json"
    path.write_text(json.dumps(cache_data))


def _write_breaker_open(cache_dir: str, source: str, cooldown: int = 9999):
    """Write a breaker state file with the given source OPEN."""
    from pathlib import Path

    state = {
        source: {
            "consecutive_failures": 5,
            "last_failure_at": datetime.now().isoformat(),
            "state": "open",
        }
    }
    path = Path(cache_dir) / "dashboard_breaker_state.json"
    path.write_text(json.dumps(state))
