"""Tests for data pipeline cache fallback logic."""

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.config import Config
from src.data.models import Birthday, CalendarEvent, DashboardData, StalenessLevel, WeatherData
from src.data_pipeline import DataPipeline
from src.fetchers.cache import save_cache, save_source


def fetch_live_data(cfg, cache_dir, tz=None, force_refresh=False, ignore_breakers=False):
    return DataPipeline(
        cfg,
        cache_dir=cache_dir,
        tz=tz,
        force_refresh=force_refresh,
        ignore_breakers=ignore_breakers,
    ).fetch()


def _make_cached(tmpdir: str) -> DashboardData:
    """Write a minimal cache file and return the data written."""
    from datetime import date

    recent = datetime.now(timezone.utc) - timedelta(hours=3)
    cached = DashboardData(
        fetched_at=recent,
        events=[
            CalendarEvent(
                summary="Cached Event",
                start=datetime(2024, 3, 14, 9, 0),
                end=datetime(2024, 3, 14, 9, 30),
            )
        ],
        weather=WeatherData(
            current_temp=55.0,
            current_icon="01d",
            current_description="clear",
            high=60.0,
            low=45.0,
            humidity=50,
        ),
        birthdays=[Birthday(name="Cached Person", date=date(2024, 3, 20))],
    )
    save_cache(cached, tmpdir)
    return cached


class TestFetchLiveData:
    def test_all_apis_succeed(self):
        cfg = Config()
        mock_events = [
            CalendarEvent(
                summary="Live Event",
                start=datetime(2024, 3, 15, 9, 0),
                end=datetime(2024, 3, 15, 10, 0),
            )
        ]
        mock_weather = WeatherData(
            current_temp=42.0,
            current_icon="02d",
            current_description="cloudy",
            high=48.0,
            low=35.0,
            humidity=65,
        )
        mock_birthdays = []

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("src.data_pipeline.fetch_events", return_value=mock_events),
                patch("src.data_pipeline.fetch_weather", return_value=mock_weather),
                patch("src.data_pipeline.fetch_birthdays", return_value=mock_birthdays),
            ):
                data = fetch_live_data(cfg, tmpdir)

        assert not data.is_stale
        assert data.events[0].summary == "Live Event"
        assert data.weather.current_temp == 42.0

    def test_weather_failure_uses_cache(self):
        cfg = Config()
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_cached(tmpdir)
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather", side_effect=RuntimeError("API down")),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                data = fetch_live_data(cfg, tmpdir)

        assert data.is_stale
        assert data.weather is not None
        assert data.weather.current_temp == 55.0

    def test_calendar_failure_uses_cache(self):
        cfg = Config()
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_cached(tmpdir)
            mock_weather = WeatherData(
                current_temp=42.0,
                current_icon="01d",
                current_description="clear",
                high=48.0,
                low=35.0,
                humidity=60,
            )
            with (
                patch("src.data_pipeline.fetch_events", side_effect=Exception("Auth failed")),
                patch("src.data_pipeline.fetch_weather", return_value=mock_weather),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                data = fetch_live_data(cfg, tmpdir)

        assert data.is_stale
        assert any(e.summary == "Cached Event" for e in data.events)

    def test_all_apis_fail_no_cache(self):
        cfg = Config()
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("src.data_pipeline.fetch_events", side_effect=Exception("down")),
                patch("src.data_pipeline.fetch_weather", side_effect=Exception("down")),
                patch("src.data_pipeline.fetch_birthdays", side_effect=Exception("down")),
            ):
                data = fetch_live_data(cfg, tmpdir)

        assert data.events == []
        assert data.weather is None
        assert data.birthdays == []

    def test_successful_run_writes_cache(self):
        import os

        cfg = Config()
        mock_weather = WeatherData(
            current_temp=42.0,
            current_icon="01d",
            current_description="clear",
            high=48.0,
            low=35.0,
            humidity=60,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather", return_value=mock_weather),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                fetch_live_data(cfg, tmpdir)
            assert os.path.exists(os.path.join(tmpdir, "dashboard_cache.json"))


def _make_weather() -> WeatherData:
    return WeatherData(
        current_temp=55.0,
        current_icon="01d",
        current_description="clear",
        high=60.0,
        low=45.0,
        humidity=50,
    )


class TestFetchIntervals:
    def test_weather_skipped_when_cache_is_fresh(self):
        cfg = Config()
        recent_ts = datetime.now(timezone.utc) - timedelta(minutes=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", _make_weather(), recent_ts, tmpdir)
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather") as mock_weather,
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                fetch_live_data(cfg, tmpdir)
            mock_weather.assert_not_called()

    def test_weather_fetched_when_cache_is_old(self):
        cfg = Config()
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=60)
        mock_w = _make_weather()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", mock_w, old_ts, tmpdir)
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather", return_value=mock_w) as mock_weather,
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                fetch_live_data(cfg, tmpdir)
            mock_weather.assert_called_once()

    def test_force_refresh_bypasses_interval(self):
        cfg = Config()
        recent_ts = datetime.now(timezone.utc) - timedelta(seconds=5)
        mock_w = _make_weather()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", mock_w, recent_ts, tmpdir)
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather", return_value=mock_w) as mock_weather,
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                fetch_live_data(cfg, tmpdir, force_refresh=True)
            mock_weather.assert_called_once()

    def test_fresh_interval_result_marked_fresh(self):
        cfg = Config()
        recent_ts = datetime.now(timezone.utc) - timedelta(minutes=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", _make_weather(), recent_ts, tmpdir)
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather"),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                data = fetch_live_data(cfg, tmpdir)
            assert data.source_staleness.get("weather") == StalenessLevel.FRESH

    def test_events_skipped_when_cache_is_fresh(self):
        cfg = Config()
        recent_ts = datetime.now(timezone.utc) - timedelta(minutes=5)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source(
                "events",
                [],
                recent_ts,
                tmpdir,
                metadata={"window_start": None, "window_days": 7},
            )
            with (
                patch("src.data_pipeline.fetch_events") as mock_events,
                patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                fetch_live_data(cfg, tmpdir)
            mock_events.assert_not_called()

    def test_birthdays_skipped_when_cache_is_fresh(self):
        cfg = Config()
        recent_ts = datetime.now(timezone.utc) - timedelta(hours=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("birthdays", [], recent_ts, tmpdir)
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
                patch("src.data_pipeline.fetch_birthdays") as mock_bdays,
            ):
                fetch_live_data(cfg, tmpdir)
            mock_bdays.assert_not_called()


class TestExpiredCache:
    def test_expired_cache_discarded_on_weather_failure(self):
        cfg = Config()
        very_old = datetime.now(timezone.utc) - timedelta(hours=24)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", _make_weather(), very_old, tmpdir)
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather", side_effect=RuntimeError("down")),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                data = fetch_live_data(cfg, tmpdir)
        assert data.weather is None

    def test_expired_cache_not_in_staleness_map(self):
        cfg = Config()
        very_old = datetime.now(timezone.utc) - timedelta(hours=24)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("events", [], very_old, tmpdir)
            with (
                patch("src.data_pipeline.fetch_events", side_effect=Exception("down")),
                patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                data = fetch_live_data(cfg, tmpdir)
        assert data.events == []


class TestCircuitBreakerOpenPath:
    def test_open_breaker_uses_cache_without_fetching(self):
        from src.fetchers.circuit_breaker import CircuitBreaker

        cfg = Config()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source(
                "weather", _make_weather(), datetime.now(timezone.utc) - timedelta(hours=3), tmpdir
            )
            breaker = CircuitBreaker(state_dir=tmpdir)
            for _ in range(cfg.cache.max_failures):
                breaker.record_failure("weather")

            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather") as mock_weather,
                patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            ):
                data = fetch_live_data(cfg, tmpdir)

            mock_weather.assert_not_called()
            assert data.weather is not None
            assert data.is_stale

    def test_ignore_breakers_fetches_even_when_open(self):
        from src.fetchers.circuit_breaker import CircuitBreaker

        cfg = Config()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Open all three breakers without pre-seeding per-source cache,
            # so _cache_is_recent returns (None, False) and the breaker check
            # is actually reached for all sources.
            breaker = CircuitBreaker(state_dir=tmpdir)
            for source in ("events", "weather", "birthdays"):
                for _ in range(cfg.cache.max_failures):
                    breaker.record_failure(source)

            with (
                patch("src.data_pipeline.fetch_events", return_value=[]) as mock_events,
                patch(
                    "src.data_pipeline.fetch_weather", return_value=_make_weather()
                ) as mock_weather,
                patch("src.data_pipeline.fetch_birthdays", return_value=[]) as mock_bdays,
            ):
                fetch_live_data(cfg, tmpdir, ignore_breakers=True)

        mock_events.assert_called_once()
        mock_weather.assert_called_once()
        mock_bdays.assert_called_once()


class TestBirthdayCacheFallback:
    """Birthday fetch failure should fall back to cached birthdays."""

    def test_birthday_failure_uses_cache(self):
        from datetime import date

        cfg = Config()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Cache must be older than birthdays_fetch_interval (default 1440 min)
            # so a fetch is actually attempted. Use 25 hours (1500 min > 1440 min).
            old_ts = datetime.now(timezone.utc) - timedelta(hours=25)
            cached_birthday = Birthday(name="Cached Person", date=date(2024, 3, 20))
            save_source("birthdays", [cached_birthday], old_ts, tmpdir)
            mock_weather = WeatherData(
                current_temp=42.0,
                current_icon="01d",
                current_description="clear",
                high=48.0,
                low=35.0,
                humidity=60,
            )
            with (
                patch("src.data_pipeline.fetch_events", return_value=[]),
                patch("src.data_pipeline.fetch_weather", return_value=mock_weather),
                patch(
                    "src.data_pipeline.fetch_birthdays", side_effect=Exception("contacts API down")
                ),
            ):
                data = fetch_live_data(cfg, tmpdir)

        assert data.is_stale
        assert any(b.name == "Cached Person" for b in data.birthdays)
