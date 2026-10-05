"""Tests for src/fetchers/cache.py"""

import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.data.models import (
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    StalenessLevel,
    WeatherData,
)
from src.fetchers.cache import (
    check_staleness,
    load_cache_blob,
    load_cached_source_from_blob,
    load_cached_source_with_metadata_from_blob,
    save_source,
)


def _load(source: str, cache_dir: str):
    return load_cached_source_from_blob(source, load_cache_blob(cache_dir))


def _load_with_metadata(source: str, cache_dir: str):
    return load_cached_source_with_metadata_from_blob(source, load_cache_blob(cache_dir))


def _make_data() -> DashboardData:
    return DashboardData(
        fetched_at=datetime(2024, 3, 15, 8, 0, 0),
        events=[
            CalendarEvent(
                summary="Standup",
                start=datetime(2024, 3, 15, 9, 0),
                end=datetime(2024, 3, 15, 9, 30),
                is_all_day=False,
                location=None,
                calendar_name="Work",
            )
        ],
        weather=WeatherData(
            current_temp=42.0,
            current_icon="01d",
            current_description="clear",
            high=50.0,
            low=35.0,
            humidity=60,
            feels_like=38.5,
            wind_speed=12.0,
            sunrise=datetime(2024, 3, 15, 6, 45),
            sunset=datetime(2024, 3, 15, 18, 30),
            forecast=[
                DayForecast(
                    date=date(2024, 3, 16),
                    high=48.0,
                    low=33.0,
                    icon="02d",
                    description="cloudy",
                    precip_chance=0.65,
                )
            ],
        ),
        birthdays=[Birthday(name="Alice", date=date(2024, 3, 20), age=30)],
    )


class TestCacheRoundtrip:
    def test_save_and_load(self):
        data = _make_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            for source in ("events", "weather", "birthdays"):
                save_source(source, getattr(data, source), data.fetched_at, tmpdir)
            events, fetched_at = _load("events", tmpdir)
            weather, _ = _load("weather", tmpdir)
            birthdays, _ = _load("birthdays", tmpdir)

        assert fetched_at == data.fetched_at.replace(tzinfo=timezone.utc)

        assert len(events) == 1
        assert events[0].summary == "Standup"
        assert events[0].is_all_day is False
        assert events[0].calendar_name == "Work"

        assert weather.current_temp == 42.0
        assert weather.humidity == 60
        assert len(weather.forecast) == 1
        assert weather.forecast[0].date == date(2024, 3, 16)

        assert len(birthdays) == 1
        assert birthdays[0].name == "Alice"
        assert birthdays[0].age == 30

    def test_weather_detail_fields_round_trip_per_source(self):
        data = _make_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", data.weather, data.fetched_at, tmpdir)
            result = _load("weather", tmpdir)

        assert result is not None
        w, _ = result
        assert w.feels_like == 38.5
        assert w.wind_speed == 12.0
        assert w.sunrise == datetime(2024, 3, 15, 6, 45)
        assert w.sunset == datetime(2024, 3, 15, 18, 30)
        assert w.forecast[0].precip_chance == 0.65

    def test_events_source_metadata_round_trip(self):
        data = _make_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source(
                "events",
                data.events,
                data.fetched_at,
                tmpdir,
                metadata={"window_start": "2024-03-10", "window_days": 35},
            )
            result = _load_with_metadata("events", tmpdir)

        assert result is not None
        events, fetched_at, metadata = result
        # Naive timestamps written to disk are normalised to UTC on read-back.
        assert fetched_at == data.fetched_at.replace(tzinfo=timezone.utc)
        assert len(events) == 1
        assert metadata == {"window_start": "2024-03-10", "window_days": 35}

    def test_weather_none_optional_fields_round_trip(self):
        """Fields that were None before this fix should still deserialise as None."""
        weather = WeatherData(
            current_temp=42.0,
            current_icon="01d",
            current_description="clear",
            high=50.0,
            low=35.0,
            humidity=60,
            forecast=[
                DayForecast(
                    date=date(2024, 3, 16),
                    high=48.0,
                    low=33.0,
                    icon="02d",
                    description="cloudy",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", weather, datetime(2024, 3, 15, 8, 0), tmpdir)
            result = _load("weather", tmpdir)

        assert result is not None
        w, _ = result
        assert w.feels_like is None
        assert w.wind_speed is None
        assert w.sunrise is None
        assert w.sunset is None
        assert w.forecast[0].precip_chance is None

    def test_location_name_round_trips(self):
        """location_name is serialised and deserialised correctly."""
        weather = WeatherData(
            current_temp=55.0,
            current_icon="01d",
            current_description="clear",
            high=60.0,
            low=45.0,
            humidity=50,
            location_name="San Francisco",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", weather, datetime(2024, 3, 15, 8, 0), tmpdir)
            result = _load("weather", tmpdir)

        assert result is not None
        w, _ = result
        assert w.location_name == "San Francisco"

    def test_location_name_none_when_absent_in_old_cache(self):
        """Old cache files without location_name deserialise safely as None."""
        import json

        raw_cache = {
            "schema_version": 2,
            "weather": {
                "fetched_at": "2024-03-15T08:00:00",
                "data": {
                    "current_temp": 42.0,
                    "current_icon": "01d",
                    "current_description": "clear",
                    "high": 50.0,
                    "low": 35.0,
                    "humidity": 60,
                    "forecast": [],
                    "alerts": [],
                    # deliberately omit "location_name"
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "dashboard_cache.json"
            cache_path.write_text(json.dumps(raw_cache))
            result = _load("weather", tmpdir)

        assert result is not None
        w, _ = result
        assert w.location_name is None

    def test_save_handles_none_weather(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", None, datetime(2024, 3, 15, 8), tmpdir)
            weather, _ = _load("weather", tmpdir)
        assert weather is None

    def test_save_handles_empty_collections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("events", [], datetime(2024, 3, 15, 8), tmpdir)
            save_source("birthdays", [], datetime(2024, 3, 15, 8), tmpdir)
            assert _load("events", tmpdir)[0] == []
            assert _load("birthdays", tmpdir)[0] == []


class TestLoadCachedSourceEdgeCases:
    def _make_weather(self) -> WeatherData:
        return WeatherData(
            current_temp=50.0,
            current_icon="01d",
            current_description="clear",
            high=55.0,
            low=40.0,
            humidity=55,
        )

    def test_returns_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert _load("events", tmpdir) is None

    def test_returns_none_on_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "dashboard_cache.json"
            cache_path.write_text("{ not json }")
            assert _load("events", tmpdir) is None

    def test_returns_none_when_source_block_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", self._make_weather(), datetime(2024, 3, 15, 9), tmpdir)
            # 'birthdays' key not yet written
            assert _load("birthdays", tmpdir) is None

    def test_loads_birthdays_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bdays = [Birthday(name="Eve", date=date(2024, 5, 1), age=28)]
            ts = datetime(2024, 3, 15, 9)
            save_source("birthdays", bdays, ts, tmpdir)
            result = _load("birthdays", tmpdir)
            assert result is not None
            data, fetched_at = result
            assert len(data) == 1
            assert data[0].name == "Eve"

    def test_returns_none_for_unknown_source(self):
        """Unknown source name should return None even in a valid v2 file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("events", [], datetime(2024, 3, 15, 9), tmpdir)
            assert _load("unknown_source", tmpdir) is None

    def test_returns_none_on_source_decode_failure(self):
        """Corrupt data in a source block should return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a valid v2 file but with malformed event data
            bad_data = {
                "schema_version": 2,
                "events": {
                    "fetched_at": "2024-03-15T09:00:00",
                    "data": [
                        {"summary": "Evt", "start": "NOT_A_DATE", "end": "2024-03-15T10:00:00"},
                    ],
                },
            }
            cache_path = Path(tmpdir) / "dashboard_cache.json"
            cache_path.write_text(json.dumps(bad_data))
            assert _load("events", tmpdir) is None

    def test_v1_fallback_returns_weather(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            v1 = {
                "fetched_at": "2024-03-15T08:00:00",
                "events": [],
                "weather": {
                    "current_temp": 50.0,
                    "current_icon": "01d",
                    "current_description": "clear",
                    "high": 55.0,
                    "low": 40.0,
                    "humidity": 55,
                    "forecast": [],
                    "alerts": [],
                },
                "birthdays": [],
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(v1))
            result = _load("weather", tmpdir)
            assert result is not None
            w, _ = result
            assert w.current_temp == 50.0

    def test_v1_fallback_returns_birthdays(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            v1 = {
                "fetched_at": "2024-03-15T08:00:00",
                "events": [],
                "weather": None,
                "birthdays": [{"name": "Bob", "date": "2024-06-01", "age": None}],
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(v1))
            result = _load("birthdays", tmpdir)
            assert result is not None
            data, _ = result
            assert data[0].name == "Bob"

    def test_v1_fallback_returns_none_on_exception(self):
        """Completely broken v1 file returns None rather than crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = {"some_random": "garbage"}
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(bad))
            assert _load("events", tmpdir) is None


class TestSaveSourceEdgeCases:
    def _make_weather(self) -> WeatherData:
        return WeatherData(
            current_temp=50.0,
            current_icon="01d",
            current_description="clear",
            high=55.0,
            low=40.0,
            humidity=55,
        )

    def test_unknown_source_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("unknown", [], datetime(2024, 3, 15, 9), tmpdir)
            cache_path = Path(tmpdir) / "dashboard_cache.json"
            assert not cache_path.exists()

    def test_starts_fresh_when_existing_file_corrupt(self):
        """If the existing cache file is corrupt, save_source should overwrite it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "dashboard_cache.json"
            cache_path.write_text("{ bad json }")
            weather = self._make_weather()
            save_source("weather", weather, datetime(2024, 3, 15, 9), tmpdir)
            # Should have written a valid new file
            result = _load("weather", tmpdir)
            assert result is not None

    def test_write_failure_logs_warning(self, caplog):
        import logging

        with tempfile.TemporaryDirectory() as tmpdir:
            with caplog.at_level(logging.WARNING, logger="src.fetchers.cache"):
                with patch(
                    "src.fetchers.cache.locked_update_json",
                    side_effect=OSError("disk full"),
                ):
                    save_source("events", [], datetime(2024, 3, 15, 9), tmpdir)
        assert "disk full" in caplog.text or "Cache write failed" in caplog.text


class TestDeserialiseV1Fallback:
    def test_v1_format_events(self):
        """Legacy v1 flat files still decode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            v1 = {
                "fetched_at": "2024-03-15T08:00:00",
                "events": [
                    {
                        "summary": "Old Meeting",
                        "start": "2024-03-15T09:00:00",
                        "end": "2024-03-15T10:00:00",
                        "is_all_day": False,
                        "location": None,
                        "calendar_name": None,
                    }
                ],
                "weather": None,
                "birthdays": [],
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(v1))
            events, _ = _load("events", tmpdir)
            assert events[0].summary == "Old Meeting"


_V2_CUSTOM_BLOCK = {
    "schema_version": 2,
    "custom": {"fetched_at": "2024-03-15T08:00:00", "data": []},
}
_V1_EMPTY = {
    "fetched_at": "2024-03-15T08:00:00",
    "events": [],
    "weather": None,
    "birthdays": [],
}


class TestLoadCachedSourceUnknownSourcePaths:
    @pytest.mark.parametrize(
        ("payload", "source"),
        [(_V2_CUSTOM_BLOCK, "custom"), (_V1_EMPTY, "custom_source")],
        ids=["v2_block_present", "v1_fallback"],
    )
    def test_unknown_source_returns_none(self, payload, source):
        """A non-standard source name returns None, both when a v2 file holds a
        block under that key and through the v1 fallback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(payload))
            assert _load(source, tmpdir) is None


class TestLoadCachedSourceWithMetadata:
    """Cover the branches of load_cached_source_with_metadata_from_blob()."""

    def test_returns_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert _load_with_metadata("weather", tmpdir) is None

    def test_returns_none_on_unreadable_json(self, caplog):
        import logging

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "dashboard_cache.json").write_text("{not valid json")
            with caplog.at_level(logging.WARNING, logger="src.fetchers.cache"):
                result = _load_with_metadata("weather", tmpdir)
        assert result is None
        assert "Cache read failed" in caplog.text

    def test_events_block_returns_metadata(self):
        """v2 events block with extra metadata returns (events, fetched_at, metadata)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            v2 = {
                "schema_version": 2,
                "events": {
                    "fetched_at": "2024-03-15T08:00:00",
                    "data": [],
                    "sync_token": "token-abc",
                },
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(v2))
            result = _load_with_metadata("events", tmpdir)
        assert result is not None
        events, fetched_at, metadata = result
        assert events == []
        # Naive timestamps written to disk are normalised to UTC on read-back.
        assert fetched_at == datetime(2024, 3, 15, 8, 0, 0, tzinfo=timezone.utc)
        assert metadata == {"sync_token": "token-abc"}

    @pytest.mark.parametrize("source", ["weather", "air_quality"])
    def test_empty_data_block_returns_none_data(self, source):
        """A v2 block whose data is null → (None, fetched_at, {})."""
        with tempfile.TemporaryDirectory() as tmpdir:
            v2 = {
                "schema_version": 2,
                source: {"fetched_at": "2024-03-15T08:00:00", "data": None},
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(v2))
            result = _load_with_metadata(source, tmpdir)
        assert result is not None
        data, _, metadata = result
        assert data is None
        assert metadata == {}

    def test_air_quality_block_round_trips(self):
        """Covers the air_quality deserialisation branch in the with-metadata loader."""
        from src.data.models import AirQualityData

        with tempfile.TemporaryDirectory() as tmpdir:
            aq = AirQualityData(aqi=42, category="Good", pm25=9.0, pm10=12.0, sensor_id=123)
            save_source("air_quality", aq, datetime(2024, 3, 15, 8, 0, 0), tmpdir)
            result = _load_with_metadata("air_quality", tmpdir)
        assert result is not None
        loaded, _, _ = result
        assert loaded.aqi == 42
        assert loaded.category == "Good"

    @pytest.mark.parametrize(
        ("payload", "source"),
        [
            (_V2_CUSTOM_BLOCK, "custom"),
            (_V1_EMPTY, "air_quality"),
            (
                {
                    "fetched_at": "totally-broken",
                    "events": "not-a-list",
                    "weather": None,
                    "birthdays": [],
                },
                "events",
            ),
        ],
        ids=["unknown_source_in_v2", "v1_fallback_unknown_source", "v1_fallback_parse_error"],
    )
    def test_unloadable_source_returns_none(self, payload, source):
        """An unknown v2 source, a source v1 files never held, and a v1 file the
        legacy decoder cannot parse all return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(payload))
            assert _load_with_metadata(source, tmpdir) is None

    def test_block_with_bad_timestamp_logs_and_returns_none(self, caplog):
        import logging

        with tempfile.TemporaryDirectory() as tmpdir:
            v2 = {
                "schema_version": 2,
                "weather": {"fetched_at": "NOT_A_TIMESTAMP", "data": {"x": "y"}},
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(v2))
            with caplog.at_level(logging.WARNING, logger="src.fetchers.cache"):
                result = _load_with_metadata("weather", tmpdir)
        assert result is None
        assert "decode failed" in caplog.text

    def test_v1_fallback_returns_events_with_empty_metadata(self):
        """Legacy v1 cache files produce an empty metadata dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            v1 = {
                "fetched_at": "2024-03-15T08:00:00",
                "events": [
                    {
                        "summary": "Old",
                        "start": "2024-03-15T09:00:00",
                        "end": "2024-03-15T10:00:00",
                        "is_all_day": False,
                        "location": None,
                        "calendar_name": None,
                    }
                ],
                "weather": None,
                "birthdays": [],
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(v1))
            result = _load_with_metadata("events", tmpdir)
        assert result is not None
        events, _, metadata = result
        assert len(events) == 1
        assert metadata == {}


class TestAtomicWriteCleanup:
    def test_temp_file_cleaned_up_on_write_failure(self):
        """If json.dump fails, the temp file should be removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            # Patch os.fdopen to raise an exception after mkstemp
            created_fds = []

            def patched_fdopen(fd, *args, **kwargs):
                created_fds.append(fd)
                raise OSError("write failed")

            with patch("os.fdopen", side_effect=patched_fdopen):
                from src._io import atomic_write_json

                with pytest.raises(OSError):
                    atomic_write_json(path, {"key": "value"})
            # The temp file should not remain (was cleaned up)
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            assert len(tmp_files) == 0

    def test_temp_file_cleaned_up_on_base_exception(self):
        """BaseException (e.g. KeyboardInterrupt) mid-write still unlinks the temp file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"

            def patched_fdopen(fd, *args, **kwargs):
                raise KeyboardInterrupt

            with patch("os.fdopen", side_effect=patched_fdopen):
                from src._io import atomic_write_json

                with pytest.raises(KeyboardInterrupt):
                    atomic_write_json(path, {"key": "value"})
            assert list(Path(tmpdir).glob("*.tmp")) == []

    def test_unlink_oserror_during_cleanup_is_swallowed(self):
        """If unlinking the temp file also fails, the original error still propagates.

        Exercises the OSError-on-cleanup arm in atomic_write_json: the primary write
        fails, then the cleanup unlink raises OSError too — the helper swallows the
        cleanup failure and re-raises the original exception.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"

            def patched_fdopen(fd, *args, **kwargs):
                raise OSError("write failed")

            def patched_unlink(*args, **kwargs):
                raise OSError("unlink failed too")

            with patch("os.fdopen", side_effect=patched_fdopen):
                with patch("os.unlink", side_effect=patched_unlink):
                    from src._io import atomic_write_json

                    # Original write error propagates; the unlink OSError is swallowed.
                    with pytest.raises(OSError, match="write failed"):
                        atomic_write_json(path, {"key": "value"})


class TestLoadCachedSourceAirQuality:
    """Cover the air_quality branch in load_cached_source_from_blob (non-metadata variant)."""

    def test_loads_air_quality_source(self):
        from src.data.models import AirQualityData

        with tempfile.TemporaryDirectory() as tmpdir:
            aq = AirQualityData(aqi=58, category="Moderate", pm25=15.0, pm10=20.0, sensor_id=9)
            save_source("air_quality", aq, datetime(2024, 3, 15, 9), tmpdir)
            result = _load("air_quality", tmpdir)
        assert result is not None
        data, fetched_at = result
        assert data.aqi == 58
        assert fetched_at == datetime(2024, 3, 15, 9, tzinfo=timezone.utc)

    def test_air_quality_empty_data_returns_none(self):
        """v2 air_quality block with data=None deserialises to None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            v2 = {
                "schema_version": 2,
                "air_quality": {"fetched_at": "2024-03-15T08:00:00", "data": None},
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(v2))
            result = _load("air_quality", tmpdir)
        assert result is not None
        data, _ = result
        assert data is None


class TestLoadCachedSourceWithMetadataV2Branches:
    """Cover the v2-format source branches in load_cached_source_with_metadata_from_blob."""

    def test_birthdays_block_returns_metadata(self):
        """The v2 birthdays branch — data list + extra metadata round-trips."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bdays = [Birthday(name="Dana", date=date(2024, 8, 12), age=35)]
            save_source(
                "birthdays",
                bdays,
                datetime(2024, 3, 15, 9),
                tmpdir,
                metadata={"source_count": 3},
            )
            result = _load_with_metadata("birthdays", tmpdir)
        assert result is not None
        data, fetched_at, metadata = result
        assert len(data) == 1 and data[0].name == "Dana"
        assert fetched_at == datetime(2024, 3, 15, 9, tzinfo=timezone.utc)
        assert metadata == {"source_count": 3}


class TestLoadCachedSourceWithMetadataV1Fallback:
    """Cover the weather/birthdays v1-fallback branches in the with-metadata loader."""

    def _v1_payload(self) -> dict:
        return {
            "fetched_at": "2024-03-15T08:00:00",
            "events": [],
            "weather": {
                "current_temp": 44.0,
                "current_icon": "01d",
                "current_description": "clear",
                "high": 50.0,
                "low": 40.0,
                "humidity": 55,
                "forecast": [],
                "alerts": [],
            },
            "birthdays": [{"name": "Carol", "date": "2024-07-01", "age": 30}],
        }

    def test_v1_fallback_returns_weather_with_empty_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(self._v1_payload()))
            result = _load_with_metadata("weather", tmpdir)
        assert result is not None
        weather, _, metadata = result
        assert weather.current_temp == 44.0
        assert metadata == {}

    def test_v1_fallback_returns_birthdays_with_empty_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(self._v1_payload()))
            result = _load_with_metadata("birthdays", tmpdir)
        assert result is not None
        bdays, _, metadata = result
        assert len(bdays) == 1 and bdays[0].name == "Carol"
        assert metadata == {}


# ---------------------------------------------------------------------------
# check_staleness — TTL gradation
# ---------------------------------------------------------------------------


class TestCheckStaleness:
    _BASE = datetime(2024, 3, 15, 10, 0, 0)
    _TTL = 60  # minutes

    def _stale(self, age_minutes: float) -> StalenessLevel:
        fetched_at = self._BASE - timedelta(minutes=age_minutes)
        return check_staleness(fetched_at, self._TTL, now=self._BASE)

    @pytest.mark.parametrize(
        ("age_minutes", "level"),
        [
            (0, StalenessLevel.FRESH),
            (30, StalenessLevel.FRESH),
            (60, StalenessLevel.FRESH),
            (61, StalenessLevel.AGING),
            (120, StalenessLevel.AGING),
            (121, StalenessLevel.STALE),
            (240, StalenessLevel.STALE),
            (241, StalenessLevel.EXPIRED),
            (10000, StalenessLevel.EXPIRED),
        ],
        ids=[
            "fresh_at_zero_age",
            "fresh_within_ttl",
            "fresh_at_exact_ttl",
            "aging_just_over_ttl",
            "aging_at_2x_ttl",
            "stale_just_over_2x_ttl",
            "stale_at_4x_ttl",
            "expired_just_over_4x_ttl",
            "expired_very_old",
        ],
    )
    def test_level_by_age(self, age_minutes, level):
        """FRESH up to the TTL, AGING to 2x, STALE to 4x, EXPIRED beyond;
        each boundary is inclusive of the lower level."""
        assert self._stale(age_minutes) == level

    # --- Uses datetime.now() when now=None ---
    def test_defaults_to_now(self):
        # Data fetched 1 second ago — must be FRESH
        fetched_at = datetime.now() - timedelta(seconds=1)
        result = check_staleness(fetched_at, ttl_minutes=60)
        assert result == StalenessLevel.FRESH

    # --- Different TTL values ---
    @pytest.mark.parametrize(
        ("age_minutes", "level"),
        [(3, StalenessLevel.FRESH), (25, StalenessLevel.EXPIRED)],
        ids=["fresh", "expired"],
    )
    def test_five_minute_ttl(self, age_minutes, level):
        """The gradation scales with the TTL passed in, not the class default."""
        fetched_at = self._BASE - timedelta(minutes=age_minutes)
        assert check_staleness(fetched_at, 5, now=self._BASE) == level


# ---------------------------------------------------------------------------
# Enhanced weather fields (wind_deg, uv_index, pressure) cache round-trip
# ---------------------------------------------------------------------------


class TestEnhancedWeatherFieldsCache:
    def _make_full_weather(self) -> WeatherData:
        return WeatherData(
            current_temp=55.0,
            current_icon="01d",
            current_description="clear",
            high=60.0,
            low=45.0,
            humidity=50,
            wind_deg=270.0,
            uv_index=7.5,
            pressure=1015.0,
        )

    @pytest.mark.parametrize(
        ("field", "expected"),
        [("wind_deg", 270.0), ("uv_index", 7.5), ("pressure", 1015.0)],
    )
    def test_field_round_trips_via_save_source(self, field, expected):
        """Each enhanced weather field survives save_source and reload."""
        weather = self._make_full_weather()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_source("weather", weather, datetime(2024, 3, 15, 8), tmpdir)
            result = _load("weather", tmpdir)
        assert result is not None
        w, _ = result
        assert getattr(w, field) == expected

    def test_none_enhanced_fields_deserialise_as_none(self):
        """Fields absent in the cache file deserialise to None (backward compat)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a v2 cache file missing the new fields
            raw = {
                "schema_version": 2,
                "weather": {
                    "fetched_at": "2024-03-15T08:00:00",
                    "data": {
                        "current_temp": 42.0,
                        "current_icon": "01d",
                        "current_description": "clear",
                        "high": 50.0,
                        "low": 35.0,
                        "humidity": 60,
                        "forecast": [],
                        "alerts": [],
                        # wind_deg, uv_index, pressure intentionally absent
                    },
                },
            }
            (Path(tmpdir) / "dashboard_cache.json").write_text(json.dumps(raw))
            result = _load("weather", tmpdir)
        assert result is not None
        w, _ = result
        assert w.wind_deg is None
        assert w.uv_index is None
        assert w.pressure is None
