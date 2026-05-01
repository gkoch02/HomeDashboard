from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date
from typing import cast

from src._time import now_local
from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DashboardData,
    HostData,
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

# Re-exported so the existing test convention of
# ``patch("src.data_pipeline.fetch_events", ...)`` keeps working — the
# registered fetcher adapters in each fetcher module dispatch back through
# these names so a patch applied here flows through to the live call site.
from src.fetchers.calendar import fetch_birthdays, fetch_events  # noqa: F401
from src.fetchers.circuit_breaker import CircuitBreaker
from src.fetchers.host import fetch_host_data
from src.fetchers.purpleair import fetch_air_quality  # noqa: F401
from src.fetchers.quota_tracker import QuotaTracker
from src.fetchers.registry import FetchContext, all_fetchers, get_fetcher
from src.fetchers.weather import fetch_weather  # noqa: F401

logger = logging.getLogger(__name__)


def _merge_air_quality_with_weather_fallback(
    air_quality: AirQualityData | None,
    weather: WeatherData | None,
) -> AirQualityData | None:
    """Fill missing air_quality sensor fields from weather data.

    When PurpleAir sensor lacks ambient readings (temp/humidity/pressure),
    fallback to OWM data if available. Tracks which fields came from fallback
    so the renderer can hide them if desired.

    Args:
        air_quality: AirQualityData from PurpleAir, or None.
        weather: WeatherData from OWM, or None.

    Returns:
        AirQualityData with fallback fields filled, or original if no merge needed.
    """
    if air_quality is None or weather is None:
        return air_quality

    # Only merge if at least one field is missing
    if (
        air_quality.temperature is not None
        and air_quality.humidity is not None
        and air_quality.pressure is not None
    ):
        return air_quality

    # Track which fields are filled from fallback
    fallback_fields: set[str] = set()

    # Build fallback values
    temperature = air_quality.temperature
    if temperature is None:
        temperature = weather.current_temp
        fallback_fields.add("temperature")

    humidity = air_quality.humidity
    if humidity is None:
        humidity = float(weather.humidity)
        fallback_fields.add("humidity")

    pressure = air_quality.pressure
    if pressure is None and weather.pressure is not None:
        pressure = weather.pressure
        fallback_fields.add("pressure")

    # Return new AirQualityData with merged values and fallback tracking
    return AirQualityData(
        aqi=air_quality.aqi,
        category=air_quality.category,
        pm25=air_quality.pm25,
        pm10=air_quality.pm10,
        sensor_id=air_quality.sensor_id,
        pm1=air_quality.pm1,
        temperature=temperature,
        humidity=humidity,
        pressure=pressure,
        fallback_fields=fallback_fields,
    )


def retry_fetch(label: str, fn):
    """Attempt fn() twice only for likely transient failures."""
    try:
        return fn()
    except Exception as exc:
        if isinstance(exc, (RuntimeError, ValueError, TypeError, KeyError)):
            raise
        logger.warning("%s failed, retrying: %s", label, exc)
    try:
        return fn()
    except Exception as exc:
        logger.error("%s retry also failed: %s", label, exc)
        raise


class DataPipeline:
    """Orchestrate concurrent fetches across all registered data sources.

    The pipeline iterates the fetcher registry (``src.fetchers.registry``)
    rather than naming sources directly. Adding a new data source is a
    single new ``register_fetcher`` call.

    Each instance is single-use: ``stale_sources`` and ``source_staleness``
    accumulate during one ``fetch()`` call and are baked into the returned
    ``DashboardData``.
    """

    def __init__(
        self,
        cfg,
        cache_dir: str,
        tz=None,
        force_refresh: bool = False,
        ignore_breakers: bool = False,
        event_window_start: date | None = None,
        event_window_days: int = 7,
    ):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.tz = tz
        self.force_refresh = force_refresh
        self.ignore_breakers = ignore_breakers
        self.event_window_start = event_window_start
        self.event_window_days = event_window_days
        # Always construct an aware datetime — naive `fetched_at` raises TypeError
        # when subtracted from aware cache timestamps in check_staleness.
        self.fetched_at = now_local(tz)

        cache_cfg = cfg.cache
        self.quota = QuotaTracker(state_dir=cache_dir)
        self.breaker = CircuitBreaker(
            max_failures=cache_cfg.max_failures,
            cooldown_minutes=cache_cfg.cooldown_minutes,
            state_dir=cache_dir,
        )
        # TTLs and intervals are pulled per-source from the registry so adding
        # a new fetcher does not require editing this map.
        self.ttl_map: dict[str, int] = {f.name: f.ttl_minutes(cfg) for f in all_fetchers()}
        self.interval_map: dict[str, int] = {
            f.name: f.interval_minutes(cfg) for f in all_fetchers()
        }
        self.stale_sources: list[str] = []
        self.source_staleness: dict[str, StalenessLevel] = {}
        self._cache_blob: dict | None = None

    # ---- public ----

    def fetch(self) -> DashboardData:
        """Fetch all enabled data sources and return a ``DashboardData`` snapshot."""
        # Read the cache file once — _should_skip / _use_cache decode out of
        # this in-memory dict instead of re-opening (perf-tested).
        self._cache_blob = load_cache_blob(self.cache_dir)

        enabled = [f for f in all_fetchers() if f.enabled(self.cfg)]

        # Phase 1: decide which sources to skip (cache hit or breaker open).
        skip_decisions: dict[str, tuple] = {}
        cached_values: dict[str, object] = {}
        for f in enabled:
            cached, skip = self._should_skip(f.name)
            skip_decisions[f.name] = (cached, skip)
            if skip:
                cached_values[f.name] = cached

        # Phase 2: launch concurrent fetches for the rest. Old-style five-param
        # signature is preserved for tests that exercise this method directly.
        events_skip = skip_decisions.get("events", (None, True))[1]
        weather_skip = skip_decisions.get("weather", (None, True))[1]
        birthdays_skip = skip_decisions.get("birthdays", (None, True))[1]
        purpleair_enabled = bool(self.cfg.purpleair.api_key and self.cfg.purpleair.sensor_id)
        aq_skip = skip_decisions.get("air_quality", (None, True))[1] if purpleair_enabled else True
        futures = self._launch_fetches(
            events_skip, weather_skip, birthdays_skip, purpleair_enabled, aq_skip
        )

        # Phase 3: resolve each source, falling back to cache on failure.
        results: dict[str, object] = {}
        for f in enabled:
            current = cached_values.get(f.name)
            if current is None and f.name in {"events", "birthdays"}:
                current = []
            success_log_fn = self._make_success_log(f)
            results[f.name] = self._resolve_source(
                f.name, futures.get(f.name), current, success_log_fn
            )

        # Post-processing: fill missing PurpleAir ambient readings from OWM.
        weather_value = results.get("weather")
        aq_value = results.get("air_quality")
        if isinstance(aq_value, AirQualityData) or aq_value is None:
            results["air_quality"] = _merge_air_quality_with_weather_fallback(
                aq_value if isinstance(aq_value, AirQualityData) else None,
                weather_value if isinstance(weather_value, WeatherData) else None,
            )

        quota_threshold = self.cfg.google.daily_quota_warning
        for src in ("events", "weather", "birthdays"):
            self.quota.check_warning(src, quota_threshold)

        host_data: HostData | None = fetch_host_data()

        events_value = results.get("events")
        weather_value = results.get("weather")
        birthdays_value = results.get("birthdays")
        air_quality_value = results.get("air_quality")

        return DashboardData(
            events=cast(list[CalendarEvent], events_value)
            if isinstance(events_value, list)
            else [],
            weather=weather_value if isinstance(weather_value, WeatherData) else None,
            birthdays=cast(list[Birthday], birthdays_value)
            if isinstance(birthdays_value, list)
            else [],
            air_quality=air_quality_value
            if isinstance(air_quality_value, AirQualityData)
            else None,
            host_data=host_data,
            fetched_at=self.fetched_at,
            is_stale=bool(self.stale_sources),
            stale_sources=self.stale_sources,
            source_staleness=self.source_staleness,
        )

    # ---- private ----

    def _fetch_context(self) -> FetchContext:
        return FetchContext(
            cfg=self.cfg,
            tz=self.tz,
            cache_dir=self.cache_dir,
            fetched_at=self.fetched_at,
            event_window_start=self.event_window_start,
            event_window_days=self.event_window_days,
        )

    def _make_success_log(self, fetcher):
        def _log(value):
            msg = fetcher.log_success(value)
            if msg:
                logger.info("%s", msg)

        return _log

    def _use_cache(self, source: str):
        cached = load_cached_source_from_blob(source, self._cache_blob)
        if cached is None:
            return None
        data, cached_at = cached
        level = check_staleness(cached_at, self.ttl_map[source], now=self.fetched_at)
        if level == StalenessLevel.EXPIRED:
            logger.warning("Cached %s is expired (>%dx TTL), discarding", source, 4)
            return None
        self.source_staleness[source] = level
        self.stale_sources.append(source)
        return data

    def _cache_is_recent(self, source: str) -> tuple:
        if self.force_refresh:
            return None, False
        fetcher = get_fetcher(source)
        if fetcher is not None and fetcher.save_metadata is not None:
            cached_with_meta = load_cached_source_with_metadata_from_blob(source, self._cache_blob)
            if cached_with_meta is None:
                return None, False
            data, cached_at, metadata = cached_with_meta
            if not fetcher.cache_metadata_valid(metadata, self._fetch_context()):
                # Events-style window mismatch — log helpful detail without
                # forcing every fetcher to surface its own log.
                if source == "events":
                    requested_start = (
                        self.event_window_start.isoformat()
                        if self.event_window_start is not None
                        else None
                    )
                    logger.info(
                        "events cache window mismatch; cached=(%s, %s) requested=(%s, %s), "
                        "refetching",
                        metadata.get("window_start"),
                        metadata.get("window_days"),
                        requested_start,
                        self.event_window_days,
                    )
                return None, False
        else:
            cached = load_cached_source_from_blob(source, self._cache_blob)
            if cached is None:
                return None, False
            data, cached_at = cached
        age_minutes = (self.fetched_at - cached_at).total_seconds() / 60
        interval = self.interval_map[source]
        if age_minutes < interval:
            logger.info(
                "%s data is %.0fm old (interval: %dm), skipping fetch",
                source,
                age_minutes,
                interval,
            )
            self.source_staleness[source] = StalenessLevel.FRESH
            return data, True
        return None, False

    def _should_skip(self, source: str) -> tuple:
        data, recent = self._cache_is_recent(source)
        if recent:
            return data, True
        if not self.ignore_breakers and not self.breaker.should_attempt(source):
            logger.info("Circuit breaker OPEN for %s, using cache", source)
            cached_data = self._use_cache(source)
            return cached_data, True
        return None, False

    def _launch_fetches(
        self, events_skip, weather_skip, birthdays_skip, purpleair_enabled, aq_skip
    ):
        """Submit retry-wrapped fetch jobs for each non-skipped source.

        The argument shape is preserved verbatim from v4 so existing tests
        that exercise this private method continue to work. Internally each
        job is dispatched via the registry's ``fetch`` callable, so adding
        a new source no longer requires editing this method.
        """
        skip_by_name = {
            "events": events_skip,
            "weather": weather_skip,
            "birthdays": birthdays_skip,
            "air_quality": aq_skip if purpleair_enabled else True,
        }
        ctx = self._fetch_context()
        fetchers = all_fetchers()
        runnable: list = []
        for f in fetchers:
            if not f.enabled(self.cfg):
                continue
            if skip_by_name.get(f.name, False):
                continue
            runnable.append(f)

        futures: dict[str, Future | None] = {f.name: None for f in fetchers}
        if not runnable:
            return futures

        max_workers = max(1, len(runnable))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for f in runnable:
                label = f.name.replace("_", " ").title().replace(" ", "")
                futures[f.name] = pool.submit(
                    retry_fetch, label, lambda fetcher=f: fetcher.fetch(ctx)
                )
        return futures

    def _resolve_source(self, source: str, future: Future | None, current, success_log_fn=None):
        """Resolve a single data source from its future, falling back to cache.

        Args:
            source: Cache/breaker key (e.g. "events", "weather").
            future: Future from the thread pool, or None if the fetch was skipped.
            current: Current value to return if both fetch and cache fail.
            success_log_fn: Optional callable(data) to log on successful fetch.
        """
        if future is None:
            return current
        try:
            data = future.result(timeout=120)
            metadata = self._cache_metadata_for(source)
            save_source(source, data, self.fetched_at, self.cache_dir, metadata=metadata)
            self.source_staleness[source] = StalenessLevel.FRESH
            self.breaker.record_success(source)
            self.quota.record_call(source)
            if success_log_fn:
                success_log_fn(data)
            return data
        except Exception as exc:
            logger.error("%s fetch failed: %s", source.capitalize(), exc)
            self.breaker.record_failure(source)
            cached_data = self._use_cache(source)
            if cached_data is not None:
                logger.warning(
                    "Using cached %s (%s)",
                    source,
                    self.source_staleness.get(source, StalenessLevel.STALE).value,
                )
                return cached_data
            return current

    def _cache_metadata_for(self, source: str) -> dict | None:
        """Return per-source cache metadata to persist alongside the value."""
        fetcher = get_fetcher(source)
        if fetcher is None:
            return None
        metadata = fetcher.save_metadata(self._fetch_context())
        return metadata or None
