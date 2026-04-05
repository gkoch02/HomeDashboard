import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime

from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DashboardData,
    HostData,
    StalenessLevel,
    WeatherData,
)
from src.fetchers.cache import check_staleness, load_cached_source, save_source
from src.fetchers.calendar import fetch_birthdays, fetch_events
from src.fetchers.circuit_breaker import CircuitBreaker
from src.fetchers.host import fetch_host_data
from src.fetchers.purpleair import fetch_air_quality
from src.fetchers.quota_tracker import QuotaTracker
from src.fetchers.weather import fetch_weather

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
    def __init__(
        self,
        cfg,
        cache_dir: str,
        tz=None,
        force_refresh: bool = False,
        ignore_breakers: bool = False,
    ):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.tz = tz
        self.force_refresh = force_refresh
        self.ignore_breakers = ignore_breakers
        self.fetched_at = datetime.now(tz) if tz is not None else datetime.now()

        cache_cfg = cfg.cache
        self.quota = QuotaTracker(state_dir=cache_dir)
        self.breaker = CircuitBreaker(
            max_failures=cache_cfg.max_failures,
            cooldown_minutes=cache_cfg.cooldown_minutes,
            state_dir=cache_dir,
        )
        self.ttl_map = {
            "events": cache_cfg.events_ttl_minutes,
            "weather": cache_cfg.weather_ttl_minutes,
            "birthdays": cache_cfg.birthdays_ttl_minutes,
            "air_quality": cache_cfg.air_quality_ttl_minutes,
        }
        self.interval_map = {
            "events": cache_cfg.events_fetch_interval,
            "weather": cache_cfg.weather_fetch_interval,
            "birthdays": cache_cfg.birthdays_fetch_interval,
            "air_quality": cache_cfg.air_quality_fetch_interval,
        }
        self.stale_sources: list[str] = []
        self.source_staleness: dict[str, StalenessLevel] = {}

    def fetch(self) -> DashboardData:
        """Fetch all data sources and return a DashboardData snapshot.

        Each DataPipeline instance is single-use: stale_sources and
        source_staleness accumulate during this call and are baked into the
        returned DashboardData. Do not call fetch() more than once per instance.
        """
        events: list[CalendarEvent] = []
        weather: WeatherData | None = None
        birthdays: list[Birthday] = []
        air_quality: AirQualityData | None = None

        events_cached, events_skip = self._should_skip("events")
        weather_cached, weather_skip = self._should_skip("weather")
        birthdays_cached, birthdays_skip = self._should_skip("birthdays")

        purpleair_enabled = bool(self.cfg.purpleair.api_key and self.cfg.purpleair.sensor_id)
        if purpleair_enabled:
            aq_cached, aq_skip = self._should_skip("air_quality")
        else:
            aq_cached, aq_skip = None, True

        if events_skip:
            events = events_cached
        if weather_skip:
            weather = weather_cached
        if birthdays_skip:
            birthdays = birthdays_cached
        if aq_skip and aq_cached is not None:
            air_quality = aq_cached

        futures = self._launch_fetches(
            events_skip,
            weather_skip,
            birthdays_skip,
            purpleair_enabled,
            aq_skip,
        )

        events = self._resolve_source(
            "events",
            futures.get("events"),
            events,
            lambda d: logger.info("Fetched %d calendar events", len(d)),
        )
        weather = self._resolve_source(
            "weather",
            futures.get("weather"),
            weather,
            lambda d: logger.info("Fetched weather: %.1f°", d.current_temp),
        )
        birthdays = self._resolve_source(
            "birthdays",
            futures.get("birthdays"),
            birthdays,
            lambda d: logger.info("Fetched %d upcoming birthdays", len(d)),
        )
        air_quality = self._resolve_source(
            "air_quality",
            futures.get("air_quality"),
            air_quality,
            lambda d: logger.info("Fetched air quality: AQI=%d (%s)", d.aqi, d.category),
        )

        # Merge missing air quality sensor fields from weather fallback
        air_quality = _merge_air_quality_with_weather_fallback(air_quality, weather)

        quota_threshold = self.cfg.google.daily_quota_warning
        for src in ("events", "weather", "birthdays"):
            self.quota.check_warning(src, quota_threshold)

        host_data: HostData | None = fetch_host_data()

        return DashboardData(
            events=events,
            weather=weather,
            birthdays=birthdays,
            air_quality=air_quality,
            host_data=host_data,
            fetched_at=self.fetched_at,
            is_stale=bool(self.stale_sources),
            stale_sources=self.stale_sources,
            source_staleness=self.source_staleness,
        )

    def _use_cache(self, source: str):
        cached = load_cached_source(source, self.cache_dir)
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
        cached = load_cached_source(source, self.cache_dir)
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
        futures: dict[str, Future | None] = {
            "events": None,
            "weather": None,
            "birthdays": None,
            "air_quality": None,
        }
        needs_fetch = (
            not events_skip
            or not weather_skip
            or not birthdays_skip
            or (purpleair_enabled and not aq_skip)
        )
        if not needs_fetch:
            return futures

        max_workers = 4 if purpleair_enabled and not aq_skip else 3
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            if not events_skip:
                futures["events"] = pool.submit(
                    retry_fetch,
                    "Calendar",
                    lambda: fetch_events(self.cfg.google, tz=self.tz, cache_dir=self.cache_dir),
                )
            if not weather_skip:
                futures["weather"] = pool.submit(
                    retry_fetch,
                    "Weather",
                    lambda: fetch_weather(self.cfg.weather, tz=self.tz),
                )
            if not birthdays_skip:
                futures["birthdays"] = pool.submit(
                    retry_fetch,
                    "Birthdays",
                    lambda: fetch_birthdays(self.cfg.google, self.cfg.birthdays, tz=self.tz),
                )
            if purpleair_enabled and not aq_skip:
                futures["air_quality"] = pool.submit(
                    retry_fetch,
                    "AirQuality",
                    lambda: fetch_air_quality(self.cfg.purpleair),
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
            save_source(source, data, self.fetched_at, self.cache_dir)
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
