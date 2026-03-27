import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime

from src.data.models import (
    AirQualityData, Birthday, CalendarEvent, DashboardData, HostData, StalenessLevel, WeatherData,
)
from src.fetchers.cache import check_staleness, load_cached_source, save_source
from src.fetchers.calendar import fetch_birthdays, fetch_events
from src.fetchers.circuit_breaker import CircuitBreaker
from src.fetchers.host import fetch_host_data
from src.fetchers.purpleair import fetch_air_quality
from src.fetchers.quota_tracker import QuotaTracker
from src.fetchers.weather import fetch_weather

logger = logging.getLogger(__name__)


def retry_fetch(label: str, fn):
    """Attempt fn() twice only for likely transient failures."""
    try:
        return fn()
    except Exception as exc:
        if isinstance(exc, (RuntimeError, ValueError, TypeError, KeyError)):
            raise
        logger.warning("%s failed, retrying: %s", label, exc)
    return fn()


class DataPipeline:
    def __init__(
        self, cfg, cache_dir: str, tz=None,
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

        futures = self._launch_fetches(events_skip, weather_skip, birthdays_skip, purpleair_enabled, aq_skip)

        events = self._resolve_events(futures.get("events"), events)
        weather = self._resolve_weather(futures.get("weather"), weather)
        birthdays = self._resolve_birthdays(futures.get("birthdays"), birthdays)
        air_quality = self._resolve_air_quality(futures.get("air_quality"), air_quality)

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
            logger.info("%s data is %.0fm old (interval: %dm), skipping fetch", source, age_minutes, interval)
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

    def _launch_fetches(self, events_skip, weather_skip, birthdays_skip, purpleair_enabled, aq_skip):
        futures: dict[str, Future | None] = {
            "events": None,
            "weather": None,
            "birthdays": None,
            "air_quality": None,
        }
        needs_fetch = (
            not events_skip or not weather_skip or not birthdays_skip
            or (purpleair_enabled and not aq_skip)
        )
        if not needs_fetch:
            return futures

        max_workers = 4 if purpleair_enabled and not aq_skip else 3
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            if not events_skip:
                futures["events"] = pool.submit(
                    retry_fetch, "Calendar",
                    lambda: fetch_events(self.cfg.google, tz=self.tz, cache_dir=self.cache_dir),
                )
            if not weather_skip:
                futures["weather"] = pool.submit(
                    retry_fetch, "Weather",
                    lambda: fetch_weather(self.cfg.weather, tz=self.tz),
                )
            if not birthdays_skip:
                futures["birthdays"] = pool.submit(
                    retry_fetch, "Birthdays",
                    lambda: fetch_birthdays(self.cfg.google, self.cfg.birthdays, tz=self.tz),
                )
            if purpleair_enabled and not aq_skip:
                futures["air_quality"] = pool.submit(
                    retry_fetch, "AirQuality",
                    lambda: fetch_air_quality(self.cfg.purpleair),
                )
        return futures

    def _resolve_events(self, future: Future | None, current):
        if future is None:
            return current
        try:
            events = future.result(timeout=120)
            save_source("events", events, self.fetched_at, self.cache_dir)
            self.source_staleness["events"] = StalenessLevel.FRESH
            self.breaker.record_success("events")
            self.quota.record_call("events")
            logger.info("Fetched %d calendar events", len(events))
            return events
        except Exception as exc:
            logger.error("Calendar fetch failed: %s", exc)
            self.breaker.record_failure("events")
            cached_data = self._use_cache("events")
            if cached_data is not None:
                logger.warning("Using cached events (%s)", self.source_staleness["events"].value)
                return cached_data
            return current

    def _resolve_weather(self, future: Future | None, current):
        if future is None:
            return current
        try:
            weather = future.result(timeout=120)
            save_source("weather", weather, self.fetched_at, self.cache_dir)
            self.source_staleness["weather"] = StalenessLevel.FRESH
            self.breaker.record_success("weather")
            self.quota.record_call("weather")
            logger.info("Fetched weather: %.1f°", weather.current_temp)
            return weather
        except Exception as exc:
            logger.error("Weather fetch failed: %s", exc)
            self.breaker.record_failure("weather")
            cached_data = self._use_cache("weather")
            if cached_data is not None:
                logger.warning("Using cached weather (%s)", self.source_staleness["weather"].value)
                return cached_data
            return current

    def _resolve_birthdays(self, future: Future | None, current):
        if future is None:
            return current
        try:
            birthdays = future.result(timeout=120)
            save_source("birthdays", birthdays, self.fetched_at, self.cache_dir)
            self.source_staleness["birthdays"] = StalenessLevel.FRESH
            self.breaker.record_success("birthdays")
            self.quota.record_call("birthdays")
            logger.info("Fetched %d upcoming birthdays", len(birthdays))
            return birthdays
        except Exception as exc:
            logger.error("Birthday fetch failed: %s", exc)
            self.breaker.record_failure("birthdays")
            cached_data = self._use_cache("birthdays")
            if cached_data is not None:
                logger.warning("Using cached birthdays (%s)", self.source_staleness["birthdays"].value)
                return cached_data
            return current

    def _resolve_air_quality(self, future: Future | None, current):
        if future is None:
            return current
        try:
            air_quality = future.result(timeout=120)
            save_source("air_quality", air_quality, self.fetched_at, self.cache_dir)
            self.source_staleness["air_quality"] = StalenessLevel.FRESH
            self.breaker.record_success("air_quality")
            logger.info("Fetched air quality: AQI=%d (%s)", air_quality.aqi, air_quality.category)
            return air_quality
        except Exception as exc:
            logger.error("Air quality fetch failed: %s", exc)
            self.breaker.record_failure("air_quality")
            cached_data = self._use_cache("air_quality")
            if cached_data is not None:
                logger.warning(
                    "Using cached air quality (%s)",
                    self.source_staleness.get("air_quality", StalenessLevel.STALE).value,
                )
                return cached_data
            return current
