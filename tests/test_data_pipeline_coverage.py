"""Tests for uncovered branches in src/data_pipeline.py."""

import tempfile
from concurrent.futures import Future
from datetime import datetime
from unittest.mock import patch

import pytest

from src.config import Config, PurpleAirConfig
from src.data.models import AirQualityData, DashboardData, StalenessLevel, WeatherData
from src.data_pipeline import DataPipeline


def _make_weather():
    return WeatherData(
        current_temp=68.0,
        current_icon="01d",
        current_description="clear sky",
        high=75.0,
        low=55.0,
        humidity=40,
    )


def _make_pipeline(tmp_path, api_key="", sensor_id=0):
    cfg = Config()
    cfg.purpleair = PurpleAirConfig(api_key=api_key, sensor_id=sensor_id)
    return DataPipeline(cfg, cache_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# _launch_fetches: early-return when everything is skipped (line 171)
# ---------------------------------------------------------------------------

class TestLaunchFetchesEarlyReturn:
    def test_all_sources_skipped_returns_none_futures(self, tmp_path):
        """When all sources are skipped and purpleair is disabled,
        _launch_fetches returns immediately with all-None futures (line 171)."""
        pipeline = _make_pipeline(tmp_path)
        futures = pipeline._launch_fetches(
            events_skip=True,
            weather_skip=True,
            birthdays_skip=True,
            purpleair_enabled=False,
            aq_skip=True,
        )
        assert all(v is None for v in futures.values())


# ---------------------------------------------------------------------------
# _launch_fetches: purpleair fetch submitted (line 191)
# ---------------------------------------------------------------------------

class TestLaunchFetchesPurpleair:
    def test_purpleair_future_submitted_when_not_skipped(self, tmp_path):
        """When purpleair is enabled and aq_skip=False, a Future is submitted (line 191)."""
        pipeline = _make_pipeline(tmp_path, api_key="key", sensor_id=123)
        aq = AirQualityData(aqi=50, category="Good", pm25=10.0)

        with patch("src.data_pipeline.retry_fetch", return_value=aq):
            futures = pipeline._launch_fetches(
                events_skip=True,
                weather_skip=True,
                birthdays_skip=True,
                purpleair_enabled=True,
                aq_skip=False,
            )
        assert futures["air_quality"] is not None
        assert futures["air_quality"].result() is aq


# ---------------------------------------------------------------------------
# _resolve_air_quality: exception path (lines 260-277)
# ---------------------------------------------------------------------------

class TestResolveAirQualityFailure:
    def test_exception_with_cached_fallback(self, tmp_path):
        """On fetch exception, _resolve_air_quality falls back to cache (lines 267-276)."""
        pipeline = _make_pipeline(tmp_path, api_key="key", sensor_id=123)
        cached = AirQualityData(aqi=25, category="Good", pm25=5.0)
        pipeline.source_staleness["air_quality"] = StalenessLevel.AGING

        future = Future()
        future.set_exception(RuntimeError("fetch failed"))

        with patch.object(pipeline, "_use_cache", return_value=cached):
            result = pipeline._resolve_source("air_quality", future, None)

        assert result is cached

    def test_exception_no_cache_returns_current(self, tmp_path):
        """On fetch exception with no cache, returns current value (line 277)."""
        pipeline = _make_pipeline(tmp_path, api_key="key", sensor_id=123)

        future = Future()
        future.set_exception(RuntimeError("fetch failed"))

        with patch.object(pipeline, "_use_cache", return_value=None):
            result = pipeline._resolve_source("air_quality", future, None)

        assert result is None

    def test_none_future_returns_current(self, tmp_path):
        """A None future (source skipped) returns current unchanged."""
        pipeline = _make_pipeline(tmp_path, api_key="key", sensor_id=123)
        result = pipeline._resolve_source("air_quality", None, None)
        assert result is None


# ---------------------------------------------------------------------------
# fetch(): purpleair-enabled path (lines 83 and 94)
# ---------------------------------------------------------------------------

class TestFetchWithPurpleair:
    def test_purpleair_enabled_aq_fetched(self, tmp_path):
        """With purpleair configured, fetch() checks air_quality skip (line 83)
        and returns fetched AQ data."""
        pipeline = _make_pipeline(tmp_path, api_key="key", sensor_id=123)
        aq = AirQualityData(aqi=42, category="Good", pm25=8.0)

        with (
            patch("src.data_pipeline.fetch_events", return_value=[]),
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            patch("src.data_pipeline.fetch_air_quality", return_value=aq),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
            patch("src.data_pipeline.save_source"),
        ):
            data = pipeline.fetch()

        assert data.air_quality is aq

    def test_purpleair_enabled_cached_aq_used_when_skipped(self, tmp_path):
        """When purpleair enabled and AQ should be skipped with cached data,
        the cached value is used (line 94)."""
        pipeline = _make_pipeline(tmp_path, api_key="key", sensor_id=123)
        cached_aq = AirQualityData(aqi=30, category="Good", pm25=6.0)

        def skip_side_effect(source):
            if source == "air_quality":
                return cached_aq, True   # skip=True, cached data available
            return None, False           # other sources: fetch

        with (
            patch.object(pipeline, "_should_skip", side_effect=skip_side_effect),
            patch("src.data_pipeline.fetch_events", return_value=[]),
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
            patch("src.data_pipeline.save_source"),
        ):
            data = pipeline.fetch()

        assert data.air_quality is cached_aq
