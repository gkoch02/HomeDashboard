"""Tests for uncovered branches in src/data_pipeline.py."""

from concurrent.futures import Future
from datetime import timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.config import Config, PurpleAirConfig
from src.data.models import AirQualityData, StalenessLevel, WeatherData
from src.data_pipeline import DataPipeline, _merge_air_quality_with_weather_fallback

# ---------------------------------------------------------------------------
# fetched_at: always tz-aware (regression — naive raised TypeError when
# subtracted from aware cache timestamps in check_staleness).
# ---------------------------------------------------------------------------


class TestFetchedAtAlwaysAware:
    def test_default_tz_none_yields_aware_utc(self, tmp_path):
        cfg = Config()
        cfg.purpleair = PurpleAirConfig()
        pipeline = DataPipeline(cfg, cache_dir=str(tmp_path))
        assert pipeline.fetched_at.tzinfo is not None
        assert pipeline.fetched_at.utcoffset() == timezone.utc.utcoffset(None)

    def test_explicit_tz_preserved(self, tmp_path):
        cfg = Config()
        cfg.purpleair = PurpleAirConfig()
        tz = ZoneInfo("America/Los_Angeles")
        pipeline = DataPipeline(cfg, cache_dir=str(tmp_path), tz=tz)
        assert pipeline.fetched_at.tzinfo is tz


# ---------------------------------------------------------------------------
# Cache file is read at most once per fetch() (perf regression guard).
# ---------------------------------------------------------------------------


class TestCacheReadOncePerFetch:
    """Perf regression guard.

    The original implementation re-opened and re-parsed dashboard_cache.json
    once per source per code path (_cache_is_recent and _use_cache each
    called load_cached_source). With 3-4 sources this added up to 4-8
    redundant reads per tick. The blob-based path opens the file exactly
    once at the top of fetch().
    """

    @staticmethod
    def _count_opens(target: str):
        """Return (counter_dict, side_effect_callable) for patching builtins.open."""
        import builtins

        counter = {"opens": 0}
        real_open = builtins.open

        def _side_effect(file, *args, **kwargs):
            if str(file) == target:
                counter["opens"] += 1
            return real_open(file, *args, **kwargs)

        return counter, _side_effect

    def test_fresh_cache_path_one_open(self, tmp_path):
        """All sources cache-fresh → one open for the initial blob load."""
        import json
        from datetime import datetime, timedelta, timezone

        recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        cache_payload = {
            "schema_version": 2,
            "events": {
                "fetched_at": recent,
                "data": [],
                "window_start": None,
                "window_days": 7,
            },
            "weather": {"fetched_at": recent, "data": None},
            "birthdays": {"fetched_at": recent, "data": []},
        }
        (tmp_path / "dashboard_cache.json").write_text(json.dumps(cache_payload))

        cfg = Config()
        cfg.purpleair = PurpleAirConfig()
        pipeline = DataPipeline(cfg, cache_dir=str(tmp_path), tz=timezone.utc)

        target = str(tmp_path / "dashboard_cache.json")
        counter, side_effect = self._count_opens(target)

        with patch("builtins.open", side_effect=side_effect):
            pipeline.fetch()

        assert counter["opens"] == 1, (
            f"dashboard_cache.json was opened {counter['opens']}× — expected 1"
        )

    def test_legacy_naive_cached_timestamps_do_not_crash_fetch(self, tmp_path):
        """A pre-fix cache file with naive `fetched_at` strings must not crash fetch().

        DataPipeline now always uses an aware UTC `self.fetched_at`. Without
        the deserialiser-level normalisation, subtracting a naive cached_at
        in _cache_is_recent / _use_cache raises TypeError and aborts fetch()
        before cache/breaker fallback can engage — leaving users with legacy
        cache files unable to render at all until they manually delete
        dashboard_cache.json.
        """
        import json
        from datetime import datetime, timedelta

        # Naive timestamps — what the old code wrote when tz was unset (dummy
        # mode, tests, or any pipeline created with tz=None).
        naive_ts = (datetime.now() - timedelta(minutes=10)).isoformat()
        cache_payload = {
            "schema_version": 2,
            "events": {
                "fetched_at": naive_ts,
                "data": [],
                "window_start": None,
                "window_days": 7,
            },
            "weather": {"fetched_at": naive_ts, "data": None},
            "birthdays": {"fetched_at": naive_ts, "data": []},
        }
        (tmp_path / "dashboard_cache.json").write_text(json.dumps(cache_payload))

        cfg = Config()
        cfg.purpleair = PurpleAirConfig()
        # Force the breaker-open fallback path so _use_cache() (and therefore
        # check_staleness on the naive cached_at) is exercised — that's the
        # exact site that raised TypeError before the fix.
        cfg.cache.events_fetch_interval = 1
        cfg.cache.weather_fetch_interval = 1
        cfg.cache.birthdays_fetch_interval = 1
        cfg.cache.events_ttl_minutes = 1440
        cfg.cache.weather_ttl_minutes = 1440
        cfg.cache.birthdays_ttl_minutes = 1440

        breaker_payload = {
            src: {
                "consecutive_failures": 5,
                "last_failure_at": datetime.now(timezone.utc).isoformat(),
                "state": "open",
            }
            for src in ("events", "weather", "birthdays")
        }
        (tmp_path / "dashboard_breaker_state.json").write_text(json.dumps(breaker_payload))

        pipeline = DataPipeline(cfg, cache_dir=str(tmp_path))
        # Must not raise TypeError on naive-vs-aware subtraction.
        data = pipeline.fetch()

        # Cache fallback engaged for every source — naive cached values surfaced.
        assert "events" in data.stale_sources
        assert "weather" in data.stale_sources
        assert "birthdays" in data.stale_sources

    def test_breaker_open_path_one_open(self, tmp_path):
        """Stale cache + open breakers force _use_cache fallback for every source.

        Pre-fix this took 2 opens per source (one in _cache_is_recent, one in
        _use_cache) for a total of 6+. With the blob cached on the pipeline,
        all decoders share the single initial open.
        """
        import json
        from datetime import datetime, timedelta, timezone

        # Cache is older than fetch_interval but well inside TTL — so
        # _cache_is_recent returns False AND _use_cache surfaces the data
        # without discarding it.
        cached_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        cache_payload = {
            "schema_version": 2,
            "events": {
                "fetched_at": cached_at,
                "data": [],
                "window_start": None,
                "window_days": 7,
            },
            "weather": {"fetched_at": cached_at, "data": None},
            "birthdays": {"fetched_at": cached_at, "data": []},
        }
        (tmp_path / "dashboard_cache.json").write_text(json.dumps(cache_payload))

        # Force every source's breaker OPEN with a recent failure timestamp so
        # the cooldown is in effect.
        recent_failure = datetime.now(timezone.utc).isoformat()
        breaker_payload = {
            src: {
                "consecutive_failures": 5,
                "last_failure_at": recent_failure,
                "state": "open",
            }
            for src in ("events", "weather", "birthdays")
        }
        (tmp_path / "dashboard_breaker_state.json").write_text(json.dumps(breaker_payload))

        cfg = Config()
        cfg.purpleair = PurpleAirConfig()
        # Tight intervals + generous TTLs so a 5-minute-old cache is past the
        # interval (triggers the breaker-fallback path) but FRESH on the TTL
        # scale (avoids the EXPIRED-discard branch).
        cfg.cache.events_fetch_interval = 1
        cfg.cache.weather_fetch_interval = 1
        cfg.cache.birthdays_fetch_interval = 1
        cfg.cache.events_ttl_minutes = 1440
        cfg.cache.weather_ttl_minutes = 1440
        cfg.cache.birthdays_ttl_minutes = 1440
        pipeline = DataPipeline(cfg, cache_dir=str(tmp_path), tz=timezone.utc)

        target = str(tmp_path / "dashboard_cache.json")
        counter, side_effect = self._count_opens(target)

        with patch("builtins.open", side_effect=side_effect):
            data = pipeline.fetch()

        assert counter["opens"] == 1, (
            f"dashboard_cache.json was opened {counter['opens']}× — expected 1 "
            "(breaker-open fallback must reuse the cached blob)"
        )
        # Sanity: the cached values were actually surfaced via the fallback.
        assert "events" in data.stale_sources
        assert "weather" in data.stale_sources
        assert "birthdays" in data.stale_sources


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
        and returns fetched AQ data with OWM fallback for missing fields."""
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

        # AQ data is merged with OWM fallback for missing sensor fields
        assert data.air_quality.aqi == 42
        assert data.air_quality.category == "Good"
        assert data.air_quality.pm25 == 8.0
        assert data.air_quality.temperature == 68.0  # From OWM fallback
        assert data.air_quality.humidity == 40.0  # From OWM fallback

    def test_purpleair_enabled_cached_aq_used_when_skipped(self, tmp_path):
        """When purpleair enabled and AQ should be skipped with cached data,
        the cached value is used and merged with OWM fallback (line 94)."""
        pipeline = _make_pipeline(tmp_path, api_key="key", sensor_id=123)
        cached_aq = AirQualityData(aqi=30, category="Good", pm25=6.0)

        def skip_side_effect(source):
            if source == "air_quality":
                return cached_aq, True  # skip=True, cached data available
            return None, False  # other sources: fetch

        with (
            patch.object(pipeline, "_should_skip", side_effect=skip_side_effect),
            patch("src.data_pipeline.fetch_events", return_value=[]),
            patch("src.data_pipeline.fetch_weather", return_value=_make_weather()),
            patch("src.data_pipeline.fetch_birthdays", return_value=[]),
            patch("src.data_pipeline.fetch_host_data", return_value=None),
            patch("src.data_pipeline.save_source"),
        ):
            data = pipeline.fetch()

        # Cached AQ data is merged with OWM fallback for missing sensor fields
        assert data.air_quality.aqi == 30
        assert data.air_quality.category == "Good"
        assert data.air_quality.pm25 == 6.0
        assert data.air_quality.temperature == 68.0  # From OWM fallback
        assert data.air_quality.humidity == 40.0  # From OWM fallback


# ---------------------------------------------------------------------------
# _merge_air_quality_with_weather_fallback: OWM fallback integration
# ---------------------------------------------------------------------------


class TestMergeAirQualityWithWeatherFallback:
    """Test OWM fallback for missing PurpleAir sensor fields."""

    def test_no_merge_when_air_quality_is_none(self):
        """Returns None when air_quality is None (no merge needed)."""
        weather = _make_weather()
        result = _merge_air_quality_with_weather_fallback(None, weather)
        assert result is None

    def test_no_merge_when_weather_is_none(self):
        """Returns original air_quality when weather is None."""
        aq = AirQualityData(aqi=50, category="Good", pm25=10.0)
        result = _merge_air_quality_with_weather_fallback(aq, None)
        assert result is aq

    def test_no_merge_when_all_fields_present(self):
        """Returns original when all AQ fields are already present."""
        aq = AirQualityData(
            aqi=50,
            category="Good",
            pm25=10.0,
            temperature=72.0,
            humidity=45.0,
            pressure=1013.0,
        )
        weather = _make_weather()
        result = _merge_air_quality_with_weather_fallback(aq, weather)
        # Should return same object since no merge was needed
        assert result is aq

    def test_merge_all_missing_fields_from_weather(self):
        """Fills all missing AQ fields from weather data."""
        aq = AirQualityData(aqi=50, category="Good", pm25=10.0)
        weather = WeatherData(
            current_temp=72.0,
            current_icon="01d",
            current_description="clear sky",
            high=75.0,
            low=55.0,
            humidity=45,
            pressure=1013.0,
        )
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert result.temperature == 72.0
        assert result.humidity == 45.0  # int converted to float
        assert result.pressure == 1013.0
        # Other fields unchanged
        assert result.aqi == 50
        assert result.category == "Good"
        assert result.pm25 == 10.0

    def test_merge_partial_missing_fields(self):
        """Only fills the specific missing fields."""
        aq = AirQualityData(
            aqi=50,
            category="Good",
            pm25=10.0,
            temperature=70.0,  # Present
            # humidity and pressure missing
        )
        weather = _make_weather()
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert result.temperature == 70.0  # Kept from AQ
        assert result.humidity == 40.0  # Filled from weather
        assert result.pressure is None  # weather.pressure is None, stays None

    def test_preserves_other_fields(self):
        """Preserves pm10, pm1, sensor_id when merging."""
        aq = AirQualityData(
            aqi=50,
            category="Good",
            pm25=10.0,
            pm10=15.0,
            pm1=5.0,
            sensor_id=12345,
        )
        weather = _make_weather()
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert result.pm10 == 15.0
        assert result.pm1 == 5.0
        assert result.sensor_id == 12345

    def test_weather_pressure_none_does_not_overwrite(self):
        """Does not use weather.pressure if None."""
        aq = AirQualityData(
            aqi=50,
            category="Good",
            pm25=10.0,
            pressure=1010.0,  # Present
        )
        weather = WeatherData(
            current_temp=68.0,
            current_icon="01d",
            current_description="clear sky",
            high=75.0,
            low=55.0,
            humidity=40,
            pressure=None,  # Explicitly None
        )
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert result.pressure == 1010.0  # Kept from AQ, not overwritten

    def test_weather_pressure_none_missing_aq_pressure_stays_none(self):
        """When both AQ and weather pressure are missing, stays None."""
        aq = AirQualityData(aqi=50, category="Good", pm25=10.0)
        weather = WeatherData(
            current_temp=68.0,
            current_icon="01d",
            current_description="clear sky",
            high=75.0,
            low=55.0,
            humidity=40,
            pressure=None,
        )
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert result.pressure is None

    def test_fallback_fields_tracks_filled_temperature(self):
        """Fallback_fields tracks when temperature is filled from OWM."""
        aq = AirQualityData(aqi=50, category="Good", pm25=10.0)
        weather = _make_weather()
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert "temperature" in result.fallback_fields

    def test_fallback_fields_tracks_filled_humidity(self):
        """Fallback_fields tracks when humidity is filled from OWM."""
        aq = AirQualityData(aqi=50, category="Good", pm25=10.0)
        weather = _make_weather()
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert "humidity" in result.fallback_fields

    def test_fallback_fields_tracks_filled_pressure(self):
        """Fallback_fields tracks when pressure is filled from OWM."""
        aq = AirQualityData(aqi=50, category="Good", pm25=10.0)
        weather = WeatherData(
            current_temp=68.0,
            current_icon="01d",
            current_description="clear sky",
            high=75.0,
            low=55.0,
            humidity=40,
            pressure=1013.0,
        )
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert "pressure" in result.fallback_fields

    def test_fallback_fields_empty_when_no_merge_needed(self):
        """Fallback_fields is empty when all fields are from sensor."""
        aq = AirQualityData(
            aqi=50,
            category="Good",
            pm25=10.0,
            temperature=72.0,
            humidity=45.0,
            pressure=1013.0,
        )
        weather = _make_weather()
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert len(result.fallback_fields) == 0

    def test_fallback_fields_only_for_missing_fields(self):
        """Fallback_fields only contains fields that were actually filled."""
        aq = AirQualityData(
            aqi=50,
            category="Good",
            pm25=10.0,
            temperature=72.0,  # Present
            # humidity and pressure missing
        )
        weather = _make_weather()
        result = _merge_air_quality_with_weather_fallback(aq, weather)

        assert "temperature" not in result.fallback_fields
        assert "humidity" in result.fallback_fields
        assert "pressure" not in result.fallback_fields  # weather.pressure is None
