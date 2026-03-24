import argparse
import logging
import zoneinfo
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, tzinfo
from pathlib import Path

from src._version import __version__
from src.config import load_config, validate_config, print_validation_report
from src.filters import filter_events
from src.data.models import (
    AirQualityData, DashboardData, CalendarEvent, StalenessLevel, WeatherData, Birthday,
)
from src.dummy_data import generate_dummy_data
from src.fetchers.cache import check_staleness, load_cached_source, save_source
from src.fetchers.circuit_breaker import CircuitBreaker
from src.fetchers.quota_tracker import QuotaTracker
from src.fetchers.calendar import fetch_events, fetch_birthdays
from src.fetchers.purpleair import fetch_air_quality
from src.fetchers.weather import fetch_weather
from src.render.canvas import render_dashboard
from src.render.theme import load_theme
from src.display.driver import DryRunDisplay, image_changed


logger = logging.getLogger(__name__)


def _resolve_tz(tz_name: str) -> tzinfo:
    """Return a tzinfo for the given IANA name, or the system local timezone for 'local'."""
    if tz_name == "local":
        return datetime.now().astimezone().tzinfo
    return zoneinfo.ZoneInfo(tz_name)


def _retry_fetch(label: str, fn):
    """Attempt fn() twice immediately to handle transient network errors."""
    try:
        return fn()
    except Exception as exc:
        logger.warning("%s failed, retrying: %s", label, exc)
    return fn()  # let the exception propagate on second failure


def _in_quiet_hours(now: datetime, start_hour: int, end_hour: int) -> bool:
    """Return True if `now` falls in the quiet window [start_hour, end_hour).

    Handles windows that cross midnight (e.g. start=23, end=6).
    """
    h = now.hour
    if start_hour > end_hour:  # crosses midnight
        return h >= start_hour or h < end_hour
    return start_hour <= h < end_hour


def _is_morning_startup(now: datetime, quiet_hours_end: int) -> bool:
    """Return True on the first 30-minute run after quiet hours end.

    Triggers a forced full refresh to start the day with a clean display.
    """
    return now.hour == quiet_hours_end and now.minute < 30


def fetch_live_data(
    cfg, cache_dir: str, tz: tzinfo | None = None,
    force_refresh: bool = False,
) -> DashboardData:
    """Fetch live data from all APIs in parallel, falling back to per-source cache on failure.

    When *force_refresh* is True, fetch intervals are bypassed and all sources
    are fetched fresh.
    """
    events: list[CalendarEvent] = []
    weather: WeatherData | None = None
    birthdays: list[Birthday] = []
    air_quality: AirQualityData | None = None

    stale_sources: list[str] = []
    source_staleness: dict[str, StalenessLevel] = {}
    fetched_at = datetime.now(tz) if tz is not None else datetime.now()

    cache_cfg = cfg.cache
    quota = QuotaTracker(state_dir=cache_dir)
    breaker = CircuitBreaker(
        max_failures=cache_cfg.max_failures,
        cooldown_minutes=cache_cfg.cooldown_minutes,
        state_dir=cache_dir,
    )
    ttl_map = {
        "events": cache_cfg.events_ttl_minutes,
        "weather": cache_cfg.weather_ttl_minutes,
        "birthdays": cache_cfg.birthdays_ttl_minutes,
        "air_quality": cache_cfg.air_quality_ttl_minutes,
    }
    interval_map = {
        "events": cache_cfg.events_fetch_interval,
        "weather": cache_cfg.weather_fetch_interval,
        "birthdays": cache_cfg.birthdays_fetch_interval,
        "air_quality": cache_cfg.air_quality_fetch_interval,
    }

    def _use_cache(source: str):
        """Try to load cached data; apply TTL-based staleness check."""
        cached = load_cached_source(source, cache_dir)
        if cached is None:
            return None
        data, cached_at = cached
        level = check_staleness(cached_at, ttl_map[source], now=fetched_at)
        if level == StalenessLevel.EXPIRED:
            logger.warning("Cached %s is expired (>%dx TTL), discarding",
                           source, 4)
            return None
        source_staleness[source] = level
        stale_sources.append(source)
        return data

    def _cache_is_recent(source: str) -> tuple:
        """Check if cached data is young enough to skip fetching.

        Returns ``(data, True)`` when the source can be reused, or
        ``(None, False)`` when a fresh fetch is needed.
        """
        if force_refresh:
            return None, False
        cached = load_cached_source(source, cache_dir)
        if cached is None:
            return None, False
        data, cached_at = cached
        age_minutes = (fetched_at - cached_at).total_seconds() / 60
        interval = interval_map[source]
        if age_minutes < interval:
            logger.info(
                "%s data is %.0fm old (interval: %dm), skipping fetch",
                source, age_minutes, interval,
            )
            source_staleness[source] = StalenessLevel.FRESH
            return data, True
        return None, False

    # Check fetch intervals and circuit breaker — skip sources as needed
    def _should_skip(source: str) -> tuple:
        """Determine if a source should be skipped (interval or breaker).

        Returns ``(data, True)`` to skip, ``(None, False)`` to fetch.
        """
        # Check fetch interval first
        data, recent = _cache_is_recent(source)
        if recent:
            return data, True
        # Check circuit breaker
        if not breaker.should_attempt(source):
            logger.info("Circuit breaker OPEN for %s, using cache", source)
            cached_data = _use_cache(source)
            return cached_data, True
        return None, False

    events_cached, events_skip = _should_skip("events")
    weather_cached, weather_skip = _should_skip("weather")
    birthdays_cached, birthdays_skip = _should_skip("birthdays")

    # PurpleAir is optional — only participate when both key and sensor are configured
    purpleair_enabled = bool(cfg.purpleair.api_key and cfg.purpleair.sensor_id)
    if purpleair_enabled:
        aq_cached, aq_skip = _should_skip("air_quality")
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

    # Launch fetchers only for sources that need refreshing
    events_future: Future | None = None
    weather_future: Future | None = None
    birthdays_future: Future | None = None
    aq_future: Future | None = None

    needs_fetch = (
        not events_skip or not weather_skip or not birthdays_skip
        or (purpleair_enabled and not aq_skip)
    )
    if needs_fetch:
        max_workers = 4 if purpleair_enabled and not aq_skip else 3
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            if not events_skip:
                events_future = pool.submit(
                    _retry_fetch, "Calendar",
                    lambda: fetch_events(cfg.google, tz=tz, cache_dir=cache_dir),
                )
            if not weather_skip:
                weather_future = pool.submit(
                    _retry_fetch, "Weather",
                    lambda: fetch_weather(cfg.weather, tz=tz),
                )
            if not birthdays_skip:
                birthdays_future = pool.submit(
                    _retry_fetch, "Birthdays",
                    lambda: fetch_birthdays(cfg.google, cfg.birthdays, tz=tz),
                )
            if purpleair_enabled and not aq_skip:
                aq_future = pool.submit(
                    _retry_fetch, "AirQuality",
                    lambda: fetch_air_quality(cfg.purpleair),
                )

    # --- Calendar events ---
    if events_future is not None:
        try:
            events = events_future.result(timeout=120)
            save_source("events", events, fetched_at, cache_dir)
            source_staleness["events"] = StalenessLevel.FRESH
            breaker.record_success("events")
            quota.record_call("events")
            logger.info("Fetched %d calendar events", len(events))
        except Exception as exc:
            logger.error("Calendar fetch failed: %s", exc)
            breaker.record_failure("events")
            cached_data = _use_cache("events")
            if cached_data is not None:
                events = cached_data
                logger.warning("Using cached events (%s)",
                               source_staleness["events"].value)

    # --- Weather ---
    if weather_future is not None:
        try:
            weather = weather_future.result(timeout=120)
            save_source("weather", weather, fetched_at, cache_dir)
            source_staleness["weather"] = StalenessLevel.FRESH
            breaker.record_success("weather")
            quota.record_call("weather")
            logger.info("Fetched weather: %.1f°", weather.current_temp)
        except Exception as exc:
            logger.error("Weather fetch failed: %s", exc)
            breaker.record_failure("weather")
            cached_data = _use_cache("weather")
            if cached_data is not None:
                weather = cached_data
                logger.warning("Using cached weather (%s)",
                               source_staleness["weather"].value)

    # --- Birthdays ---
    if birthdays_future is not None:
        try:
            birthdays = birthdays_future.result(timeout=120)
            save_source("birthdays", birthdays, fetched_at, cache_dir)
            source_staleness["birthdays"] = StalenessLevel.FRESH
            breaker.record_success("birthdays")
            quota.record_call("birthdays")
            logger.info("Fetched %d upcoming birthdays", len(birthdays))
        except Exception as exc:
            logger.error("Birthday fetch failed: %s", exc)
            breaker.record_failure("birthdays")
            cached_data = _use_cache("birthdays")
            if cached_data is not None:
                birthdays = cached_data
                logger.warning("Using cached birthdays (%s)",
                               source_staleness["birthdays"].value)

    # --- Air Quality (PurpleAir) ---
    if aq_future is not None:
        try:
            air_quality = aq_future.result(timeout=120)
            save_source("air_quality", air_quality, fetched_at, cache_dir)
            source_staleness["air_quality"] = StalenessLevel.FRESH
            breaker.record_success("air_quality")
            logger.info(
                "Fetched air quality: AQI=%d (%s)", air_quality.aqi, air_quality.category,
            )
        except Exception as exc:
            logger.error("Air quality fetch failed: %s", exc)
            breaker.record_failure("air_quality")
            cached_data = _use_cache("air_quality")
            if cached_data is not None:
                air_quality = cached_data  # type: ignore[assignment]
                logger.warning(
                    "Using cached air quality (%s)",
                    source_staleness.get("air_quality", StalenessLevel.STALE).value,
                )

    # Check quota warnings
    quota_threshold = cfg.google.daily_quota_warning
    for src in ("events", "weather", "birthdays"):
        quota.check_warning(src, quota_threshold)

    return DashboardData(
        events=events,
        weather=weather,
        birthdays=birthdays,
        air_quality=air_quality,
        fetched_at=fetched_at,
        is_stale=bool(stale_sources),
        stale_sources=stale_sources,
        source_staleness=source_staleness,
    )


def main():
    parser = argparse.ArgumentParser(description="Home Dashboard for eInk display")
    parser.add_argument(
        "--dry-run", action="store_true", help="Render to PNG instead of display",
    )
    parser.add_argument(
        "--config", default="config/config.yaml", help="Path to config file",
    )
    parser.add_argument(
        "--force-full-refresh", action="store_true", help="Force a full display refresh",
    )
    parser.add_argument(
        "--dummy", action="store_true",
        help="Use dummy data instead of fetching from APIs",
    )
    parser.add_argument(
        "--check-config", action="store_true",
        help="Validate config and exit without rendering",
    )
    parser.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Override 'today' for the dry-run preview (e.g. 2025-12-25). "
            "Only meaningful with --dry-run."
        ),
    )
    parser.add_argument(
        "--theme",
        choices=["default", "fantasy", "fuzzyclock", "minimalist", "old_fashioned", "qotd",
                 "random", "terminal", "today", "weather"],
        default=None,
        metavar="THEME",
        help=(
            "Override the theme from config. "
            "Choices: default, fantasy, fuzzyclock, minimalist, old_fashioned, qotd, random, "
            "terminal, today, weather"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args()

    # Validate --date usage early so we can give a clear error message.
    if args.date is not None and not args.dry_run:
        parser.error("--date requires --dry-run")

    # Configure logging before load_config so any import-time or config-loading
    # log records are formatted correctly (fix: logging order).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    logging.getLogger().setLevel(getattr(logging, cfg.log_level, logging.INFO))

    # --- Config validation ---
    errors, warnings = validate_config(cfg, config_path=args.config)
    if args.check_config:
        print_validation_report(errors, warnings)
        raise SystemExit(1 if errors else 0)
    if errors:
        print_validation_report(errors, warnings)
        logger.error("Config has fatal errors — fix them or run with --check-config for details.")
        raise SystemExit(1)
    if warnings and not args.dummy:
        print_validation_report(errors, warnings)

    tz = _resolve_tz(cfg.timezone)
    logger.info("Using timezone: %s", tz)

    # Quiet hours — skip refresh entirely between quiet_hours_start and quiet_hours_end
    now = datetime.now(tz)

    # --date: override the current date for dry-run previews
    if args.date is not None:
        try:
            from datetime import date as _date
            override_date = _date.fromisoformat(args.date)
        except ValueError:
            parser.error(f"--date must be in YYYY-MM-DD format, got: {args.date!r}")
        now = datetime.combine(override_date, now.timetz())
        logger.info("Dry-run date overridden to: %s", now.date())

    if not args.dry_run and _in_quiet_hours(now, cfg.schedule.quiet_hours_start, cfg.schedule.quiet_hours_end):
        logger.info(
            "Quiet hours (%02d:00–%02d:00) — skipping refresh",
            cfg.schedule.quiet_hours_start,
            cfg.schedule.quiet_hours_end,
        )
        return

    # Force a full refresh on the first run of the active day (morning wake-up)
    force_full = args.force_full_refresh or _is_morning_startup(now, cfg.schedule.quiet_hours_end)
    if force_full and not args.force_full_refresh:
        logger.info("Morning startup — forcing full refresh")

    # Fetch data
    if args.dummy:
        logger.info("Using dummy data")
        data = generate_dummy_data(tz=tz, now=now)
    else:
        data = fetch_live_data(
            cfg, cache_dir=cfg.output_dir, tz=tz,
            force_refresh=force_full,
        )

    # Apply event filters
    if cfg.filters.exclude_calendars or cfg.filters.exclude_keywords or cfg.filters.exclude_all_day:
        original_count = len(data.events)
        data.events = filter_events(data.events, cfg.filters)
        logger.info("Filtered events: %d -> %d", original_count, len(data.events))

    # Resolve "random" to a concrete theme name for today
    theme_name = args.theme if args.theme is not None else cfg.theme
    if theme_name == "random":
        from src.render.random_theme import pick_random_theme
        theme_name = pick_random_theme(
            include=cfg.random_theme.include,
            exclude=cfg.random_theme.exclude,
            output_dir=cfg.output_dir,
        )
        logger.info("Random theme resolved to: %s", theme_name)

    # Render
    logger.info("Rendering dashboard")
    theme = load_theme(theme_name)
    image = render_dashboard(data, cfg.display, title=cfg.title, theme=theme)

    # Conditional refresh — skip display update when the image hasn't changed.
    # Always write in dry-run mode (useful for dev); skip hardware refresh on
    # identical images to extend eInk display lifespan and save power.
    if args.dry_run:
        display = DryRunDisplay(output_dir=cfg.output_dir)
        display.show(image)
    elif not image_changed(image, cfg.output_dir) and not force_full:
        logger.info("Image unchanged — skipping display refresh")
    else:
        from src.display.driver import WaveshareDisplay
        display = WaveshareDisplay(
            model=cfg.display.model,
            enable_partial=cfg.display.enable_partial_refresh,
            max_partials=cfg.display.max_partials_before_full,
        )
        display.show(image, force_full=force_full)

    # Write health marker so external monitoring can detect a stuck display
    try:
        marker = Path(cfg.output_dir) / "last_success.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(datetime.now(tz).isoformat() + "\n")
    except Exception as exc:
        logger.warning("Could not write last_success.txt: %s", exc)

    logger.info("Done")


if __name__ == "__main__":
    main()
