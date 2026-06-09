from __future__ import annotations

import logging
import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path

import yaml  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass
class GoogleConfig:
    service_account_path: str = "credentials/service_account.json"
    calendar_id: str = "primary"
    additional_calendars: list[str] = field(default_factory=list)
    # Email of the user to impersonate via domain-wide delegation for Contacts access.
    # Required when birthdays.source is "contacts".
    contacts_email: str = ""
    daily_quota_warning: int = 500  # warn when daily API calls exceed this
    # ICS feed alternative — when set, calendar events are fetched from this URL
    # instead of the Google Calendar API (no GCP project or credentials required).
    # Get the URL from Google Calendar → Settings → [calendar] → "Secret address in iCal format".
    ical_url: str = ""
    additional_ical_urls: list[str] = field(default_factory=list)
    # CalDAV alternative — when ``caldav_url`` is set, events are fetched from a
    # CalDAV server (Nextcloud, Radicale, Apple iCloud, …) instead of Google API
    # or ICS. ``caldav_password_file`` points at a one-line file containing the
    # account password (never inline secrets in YAML).
    caldav_url: str = ""
    caldav_username: str = ""
    caldav_password_file: str = ""
    caldav_calendar_url: str = ""  # optional specific calendar; default = first


@dataclass
class WeatherConfig:
    api_key: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    units: str = "imperial"


@dataclass
class BirthdayConfig:
    source: str = "file"  # "file", "calendar", or "contacts"
    file_path: str = "config/birthdays.json"
    calendar_keyword: str = "Birthday"
    lookahead_days: int = 30


@dataclass
class PurpleAirConfig:
    api_key: str = ""
    sensor_id: int = 0  # numeric sensor_index (shown in map.purpleair.com URL)


@dataclass
class PhotoConfig:
    path: str = ""  # absolute or relative path to image file (JPEG/PNG/etc.)


@dataclass
class CountdownEvent:
    """A single user-defined countdown target for the countdown theme."""

    name: str
    date: str  # ISO "YYYY-MM-DD"


@dataclass
class ThemeRuleCondition:
    """Conditions that make a theme rule fire.  Each field is optional —
    when the field is unset (None / empty), the rule does not constrain on it.
    All set fields must match (AND semantics).
    """

    # OWM current-weather main category (case-insensitive), e.g. "clear",
    # "clouds", "rain", "snow", "thunderstorm", "drizzle", "fog", "mist".
    # Accepts a single value or a list of alternatives (OR).
    weather: str | list[str] | None = None
    # When True, matches only if at least one weather alert is present.
    # When False, matches only when no alerts are present.  None = no constraint.
    weather_alert_present: bool | None = None
    # "dawn"  (sunrise ±90min),
    # "day"   (after dawn until sunset−60min),
    # "dusk"  (sunset−60min through sunset),
    # "night" (after sunset until the next dawn).
    # Accepts a single value or a list.
    daypart: str | list[str] | None = None
    # "spring" / "summer" / "fall" / "winter" (N-hemisphere by month).
    season: str | list[str] | None = None
    # "weekend", "weekday", or a specific weekday name ("monday".."sunday").
    weekday: str | list[str] | None = None
    # Calendar state for today.  Accepts a single value or list:
    #   "empty"          — zero events scheduled today
    #   "done"           — events exist but all have already ended
    #   "active"         — currently inside an event
    #   "upcoming_soon"  — next event starts within the next 30 minutes
    #   "busy"           — 5+ events scheduled today
    #   "birthday_today" — at least one birthday falls on today
    # Rules using this condition skip when calendar data is unavailable
    # (e.g. pre-fetch theme resolution).
    calendar: str | list[str] | None = None


@dataclass
class ThemeRule:
    """A single (condition → theme) pairing for the theme_rules auto-theme system."""

    when: ThemeRuleCondition = field(default_factory=ThemeRuleCondition)
    theme: str = ""


@dataclass
class ThemeRulesConfig:
    """Ordered list of theme rules.  First match wins.

    Evaluated after the CLI override and before ``theme_schedule`` / ``cfg.theme``.
    Rules whose conditions reference weather data silently skip evaluation when
    weather data is unavailable (first boot, circuit breaker open).
    """

    rules: list[ThemeRule] = field(default_factory=list)


@dataclass
class CountdownConfig:
    """User-configured countdown events for the ``countdown`` theme.

    ``events`` is sorted by date at render time; past entries are dropped.
    """

    events: list[CountdownEvent] = field(default_factory=list)


@dataclass
class DisplayConfig:
    provider: str = "waveshare"
    model: str = "epd7in5_V2"
    width: int = 800
    height: int = 480
    enable_partial_refresh: bool = False
    max_partials_before_full: int = 20
    week_days: int = 7
    show_weather: bool = True
    show_birthdays: bool = True
    show_info_panel: bool = True
    quantization_mode: str = "threshold"
    # Minimum seconds between hardware refreshes. None ⇒ provider default
    # (60 for Inky, 0 for Waveshare). Set 3600 on Inky to restore the v4
    # "exactly once an hour" hourly throttle.
    min_refresh_interval_seconds: int | None = None


@dataclass
class ScheduleConfig:
    quiet_hours_start: int = 23  # hour (0-23) when quiet period begins
    quiet_hours_end: int = 6  # hour (0-23) when active period resumes


@dataclass
class CacheConfig:
    weather_ttl_minutes: int = 60
    events_ttl_minutes: int = 120
    birthdays_ttl_minutes: int = 1440
    # Per-source fetch intervals: skip fetching if cached data is younger
    weather_fetch_interval: int = 30  # minutes between weather API calls
    events_fetch_interval: int = 120  # minutes between calendar API calls
    birthdays_fetch_interval: int = 1440  # minutes between birthday API calls
    # Circuit breaker: stop hitting an API after repeated failures
    max_failures: int = 3  # consecutive failures before opening breaker
    cooldown_minutes: int = 30  # minutes to wait before retrying
    # PurpleAir air quality cache settings
    air_quality_ttl_minutes: int = 30
    air_quality_fetch_interval: int = 15
    # Quote rotation frequency: "daily" (default), "twice_daily" (AM/PM), or "hourly"
    quote_refresh: str = "daily"


@dataclass
class FilterConfig:
    exclude_calendars: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    exclude_all_day: bool = False


@dataclass
class RandomThemeConfig:
    """Controls which themes are eligible when ``theme: random`` is configured.

    - ``include``: if non-empty, only these themes are candidates.
    - ``exclude``: themes to always skip (applied after include).
    """

    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass
class ThemeScheduleEntry:
    """A single time → theme mapping for the time-of-day theme schedule."""

    time: str  # "HH:MM" in 24-hour format
    theme: str  # concrete theme name (not "random")


@dataclass
class ThemeScheduleConfig:
    """Time-of-day theme schedule — switches themes at configured times.

    Entries are sorted by time. The active theme is the last entry whose
    ``time`` is <= the current local time. When no entry applies (e.g. all
    entries start after the current time), returns None and the normal
    theme/random logic applies. Ignored when ``--theme`` is passed via CLI.
    """

    entries: list[ThemeScheduleEntry] = field(default_factory=list)


@dataclass
class Config:
    google: GoogleConfig = field(default_factory=GoogleConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    birthdays: BirthdayConfig = field(default_factory=BirthdayConfig)
    purpleair: PurpleAirConfig = field(default_factory=PurpleAirConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    random_theme: RandomThemeConfig = field(default_factory=RandomThemeConfig)
    theme_schedule: ThemeScheduleConfig = field(default_factory=ThemeScheduleConfig)
    theme_rules: ThemeRulesConfig = field(default_factory=ThemeRulesConfig)
    photo: PhotoConfig = field(default_factory=PhotoConfig)
    countdown: CountdownConfig = field(default_factory=CountdownConfig)
    title: str = "Home Dashboard"
    theme: str = "default"
    output_dir: str = "output"
    state_dir: str = "state"
    log_level: str = "INFO"
    timezone: str = "local"


def resolve_tz(tz_name: str) -> tzinfo:
    """Return a tzinfo for the given IANA name, or the system local timezone for 'local'."""
    if tz_name == "local":
        tz = datetime.now().astimezone().tzinfo  # allow-naive-datetime — extracting local tzinfo
        if tz is None:
            logger.warning("Could not determine local timezone; falling back to UTC")
            return zoneinfo.ZoneInfo("UTC")
        return tz
    return zoneinfo.ZoneInfo(tz_name)


def load_config(path: str = "config/config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.exists():
        logger.warning(
            "Config file not found: %s — using defaults. "
            "Run 'make setup' or copy config/config.example.yaml to config/config.yaml.",
            path,
        )
        return Config()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    # v5: upgrade older config shapes in-memory before parsing into dataclasses.
    # This is non-destructive — the on-disk file is only rewritten by the
    # explicit ``write_pre_migration_backup`` path used by the bootstrap.
    from src.config_migrations import migrate_in_memory, needs_migration

    if needs_migration(raw):
        raw = migrate_in_memory(raw)

    cfg = Config()

    if "google" in raw:
        g = raw["google"]
        cfg.google = GoogleConfig(
            service_account_path=g.get("service_account_path", cfg.google.service_account_path),
            calendar_id=g.get("calendar_id", cfg.google.calendar_id),
            additional_calendars=g.get("additional_calendars", []),
            contacts_email=g.get("contacts_email", ""),
            daily_quota_warning=g.get("daily_quota_warning", 500),
            ical_url=g.get("ical_url", ""),
            additional_ical_urls=g.get("additional_ical_urls", []),
            caldav_url=g.get("caldav_url", ""),
            caldav_username=g.get("caldav_username", ""),
            caldav_password_file=g.get("caldav_password_file", ""),
            caldav_calendar_url=g.get("caldav_calendar_url", ""),
        )

    if "weather" in raw:
        w = raw["weather"]
        cfg.weather = WeatherConfig(
            api_key=w.get("api_key", ""),
            latitude=w.get("latitude", 0.0),
            longitude=w.get("longitude", 0.0),
            units=w.get("units", "imperial"),
        )

    if "birthdays" in raw:
        b = raw["birthdays"]
        cfg.birthdays = BirthdayConfig(
            source=b.get("source", "file"),
            file_path=b.get("file_path", "config/birthdays.json"),
            calendar_keyword=b.get("calendar_keyword", "Birthday"),
            lookahead_days=b.get("lookahead_days", 30),
        )

    if "display" in raw:
        d = raw["display"]
        provider = str(d.get("provider", "waveshare"))
        model = d.get("model", "epd7in5_V2")

        # Auto-derive native dimensions from provider/model when not explicitly set in YAML
        default_w, default_h = 800, 480
        if "width" not in d or "height" not in d:
            from src.display.driver import get_display_spec

            spec = get_display_spec(provider, model)
            if spec is not None:
                default_w = spec.width
                default_h = spec.height

        cfg.display = DisplayConfig(
            provider=provider,
            model=model,
            width=d.get("width", default_w),
            height=d.get("height", default_h),
            enable_partial_refresh=d.get("enable_partial_refresh", False),
            max_partials_before_full=d.get("max_partials_before_full", 20),
            week_days=d.get("week_days", 7),
            show_weather=d.get("show_weather", True),
            show_birthdays=d.get("show_birthdays", True),
            show_info_panel=d.get("show_info_panel", True),
            quantization_mode=d.get("quantization_mode", "threshold"),
            min_refresh_interval_seconds=d.get("min_refresh_interval_seconds"),
        )

    if "schedule" in raw:
        s = raw["schedule"]
        cfg.schedule = ScheduleConfig(
            quiet_hours_start=s.get("quiet_hours_start", 23),
            quiet_hours_end=s.get("quiet_hours_end", 6),
        )

    if "cache" in raw:
        ca = raw["cache"]
        cfg.cache = CacheConfig(
            weather_ttl_minutes=ca.get("weather_ttl_minutes", 60),
            events_ttl_minutes=ca.get("events_ttl_minutes", 120),
            birthdays_ttl_minutes=ca.get("birthdays_ttl_minutes", 1440),
            weather_fetch_interval=ca.get("weather_fetch_interval", 30),
            events_fetch_interval=ca.get("events_fetch_interval", 120),
            birthdays_fetch_interval=ca.get("birthdays_fetch_interval", 1440),
            max_failures=ca.get("max_failures", 3),
            cooldown_minutes=ca.get("cooldown_minutes", 30),
            air_quality_ttl_minutes=ca.get("air_quality_ttl_minutes", 30),
            air_quality_fetch_interval=ca.get("air_quality_fetch_interval", 15),
            quote_refresh=ca.get("quote_refresh", "daily"),
        )

    if "filters" in raw:
        fl = raw["filters"]
        cfg.filters = FilterConfig(
            exclude_calendars=fl.get("exclude_calendars", []),
            exclude_keywords=fl.get("exclude_keywords", []),
            exclude_all_day=fl.get("exclude_all_day", False),
        )

    if "purpleair" in raw:
        pa = raw["purpleair"]
        cfg.purpleair = PurpleAirConfig(
            api_key=pa.get("api_key", ""),
            sensor_id=int(pa.get("sensor_id", 0)),
        )

    if "random_theme" in raw:
        rt = raw["random_theme"]
        cfg.random_theme = RandomThemeConfig(
            include=rt.get("include", []),
            exclude=rt.get("exclude", []),
        )

    if "theme_schedule" in raw:
        raw_entries = raw["theme_schedule"]
        entries = []
        if isinstance(raw_entries, list):
            for item in raw_entries:
                entries.append(
                    ThemeScheduleEntry(
                        time=str(item.get("time", "")),
                        theme=str(item.get("theme", "")),
                    )
                )
        cfg.theme_schedule = ThemeScheduleConfig(entries=entries)

    if "theme_rules" in raw:
        raw_rules = raw["theme_rules"]
        rules: list[ThemeRule] = []
        if isinstance(raw_rules, list):
            for item in raw_rules:
                if not isinstance(item, dict):
                    continue
                when_raw = item.get("when", {}) or {}
                if not isinstance(when_raw, dict):
                    when_raw = {}
                cond = ThemeRuleCondition(
                    weather=when_raw.get("weather"),
                    weather_alert_present=when_raw.get("weather_alert_present"),
                    daypart=when_raw.get("daypart"),
                    season=when_raw.get("season"),
                    weekday=when_raw.get("weekday"),
                    calendar=when_raw.get("calendar"),
                )
                rules.append(ThemeRule(when=cond, theme=str(item.get("theme", ""))))
        cfg.theme_rules = ThemeRulesConfig(rules=rules)

    if "photo" in raw:
        ph = raw["photo"]
        cfg.photo = PhotoConfig(
            path=ph.get("path", cfg.photo.path),
        )

    if "countdown" in raw:
        cd = raw["countdown"]
        raw_events = cd.get("events", []) if isinstance(cd, dict) else []
        events: list[CountdownEvent] = []
        if isinstance(raw_events, list):
            for item in raw_events:
                if not isinstance(item, dict):
                    continue
                events.append(
                    CountdownEvent(
                        name=str(item.get("name", "")),
                        date=str(item.get("date", "")),
                    )
                )
        cfg.countdown = CountdownConfig(events=events)

    if "output" in raw:
        cfg.output_dir = raw["output"].get("dry_run_dir", "output")

    if "state_dir" in raw:
        cfg.state_dir = str(raw["state_dir"])

    if "logging" in raw:
        cfg.log_level = raw["logging"].get("level", "INFO")

    if "title" in raw:
        cfg.title = raw["title"]

    if "theme" in raw:
        cfg.theme = str(raw["theme"])

    if "timezone" in raw:
        cfg.timezone = raw["timezone"]

    return cfg


# --- Backwards-compatible re-exports -------------------------------------
# validate_config and friends moved to src.config_validation; import at the
# bottom so the validation module can import the dataclasses above without a
# circular-import failure.
from src.config_validation import (  # noqa: E402, F401
    ConfigError,
    ConfigWarning,
    print_validation_report,
    validate_config,
)
