from __future__ import annotations

import logging
import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

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
    # Which One Call product supplies alerts + the UV index: "3.0", "4.0", or
    # "off" to skip the request entirely. An account can hold only one
    # One Call subscription, so this cannot be auto-detected — calling the
    # version you are not subscribed to 401s exactly like having none.
    one_call_version: str = "3.0"


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
    # repr() of a configured sensor_id that could not be parsed as an integer,
    # empty when the value was absent or read cleanly. Set by load_config() so
    # validate_config() can report the typo rather than the parser crashing on it.
    sensor_id_invalid: str = ""


@dataclass
class PhotoConfig:
    path: str = ""  # absolute or relative path to image file (JPEG/PNG/etc.)


@dataclass
class QuotesConfig:
    """Where the daily-quote store lives.

    Empty means the bundled ``config/quotes.json``. Point this outside the
    repository to keep a customised store from being overwritten by
    ``make deploy``.
    """

    path: str = ""


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
    # Current temperature bounds, in the configured ``weather.units`` (so °F
    # for imperial, °C for metric — the same number the dashboard shows).
    # Both are inclusive; setting both makes a band.  Rules using either skip
    # when weather data is unavailable, same as ``weather``.
    temp_at_least: float | None = None
    temp_at_most: float | None = None
    # Minimum EPA AQI (inclusive).  Rules using it skip when air-quality data
    # is unavailable — which includes every install without PurpleAir
    # configured, since the source is then never fetched.
    aqi_at_least: int | None = None


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
    quotes: QuotesConfig = field(default_factory=QuotesConfig)
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


def _named_level(name: object) -> int | None:
    """Return the logging level for *name*, or ``None`` if it isn't a level name.

    ``getLevelName`` maps a known name to its int and returns a ``"Level <x>"``
    string otherwise, which is the not-a-level signal. It also knows the
    aliases ``FATAL`` and ``WARN``, so anything derived from it stays in step
    with what ``setLevel`` will actually accept.
    """
    level = logging.getLevelName(str(name).strip().upper())
    return level if isinstance(level, int) else None


def resolve_log_level(name: object) -> int:
    """Return the logging level for *name*, falling back to INFO.

    ``getattr(logging, name)`` is not safe here: a lowercase level resolves to
    the *function* of that name (``logging.info``), which ``setLevel`` rejects
    with ``TypeError`` — so ``level: info`` in config.yaml crashed every run
    before the renderer started.
    """
    level = _named_level(name)
    return logging.INFO if level is None else level


def is_known_log_level(name: object) -> bool:
    """True when *name* is a level name ``resolve_log_level`` will honour.

    Shares ``_named_level`` with the resolver on purpose: a separately
    maintained allowlist drifts from it, and did — it omitted the ``FATAL``
    alias, so a working ``level: FATAL`` was reported as unknown and as
    falling back to INFO while the root logger was in fact set to CRITICAL.
    """
    return _named_level(name) is not None


def _optional_number(block: dict, key: str, cast):
    """Read an optional numeric ``when:`` threshold, or ``None`` when absent.

    Raises ``ValueError`` for a present-but-unreadable value so the caller can
    drop the rule rather than silently widen it. Booleans are rejected outright:
    YAML 1.1 reads ``yes``/``on`` as ``True``, and ``int(True)`` is a perfectly
    valid 1 that would read as a real threshold.

    Every unreadable shape has to arrive as ``ValueError``, including the ones
    ``int()``/``float()`` reject with ``TypeError`` — a YAML list or mapping.
    Letting that escape would crash ``load_config()`` itself, taking down every
    renderer run and both web pages over one malformed rule.
    """
    value = block.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number, got {value!r}")
    try:
        return cast(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number, got {value!r}") from exc


def _section(raw: dict, key: str) -> dict:
    """Return ``raw[key]`` as a mapping, or ``{}`` when it is not one.

    A section header with nothing under it (``google:`` followed only by
    commented-out keys) parses as ``None``, and every parser below then calls
    ``.get()`` on it. That ``AttributeError`` escapes ``load_config()``, which
    is the one function with no error boundary above it — it took down the
    renderer, ``--check-config`` (so the flag could not diagnose the very
    problem it exists for), and both web pages, leaving the user unable to use
    the editor to fix the file that broke the editor. Commenting a section out
    key by key is exactly what a user does while trying things, so treat it as
    "nothing configured here" rather than a crash.
    """
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _optional_int(value: Any) -> int | None:
    """Parse an optional integer, or ``None`` when it cannot be read.

    Booleans are rejected for the same reason ``_optional_number`` rejects
    them: YAML 1.1 reads ``yes``/``on`` as ``True`` and ``int(True)`` is a
    plausible-looking 1.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalise_one_call_version(value: object) -> str:
    """Coerce a raw weather.one_call_version YAML value to its canonical string.

    Unquoted YAML is full of traps here: ``one_call_version: 3.0`` parses as a
    float, ``one_call_version: 3`` as an int, and ``one_call_version: off`` as
    the *boolean* ``False`` (YAML 1.1 spells booleans ``off``/``on``).  None of
    those compare equal to the strings the dispatcher looks for.  Coerce to
    text and fold each onto the version it obviously means.

    An absent or empty value is the default, not a typo: ``one_call_version:``
    with nothing after it parses as None, and warning about ``'None'`` would be
    noise on every run.  Values that are merely unrecognised *are* returned
    unchanged, so validate_config() can name the actual typo while the
    dispatcher falls back to the default.
    """
    if value is None:
        return "3.0"
    text = str(value).strip()
    if not text:
        return "3.0"
    return {"3": "3.0", "4": "4.0", "False": "off"}.get(text, text)


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
        g = _section(raw, "google")
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
        w = _section(raw, "weather")
        cfg.weather = WeatherConfig(
            api_key=w.get("api_key", ""),
            latitude=w.get("latitude", 0.0),
            longitude=w.get("longitude", 0.0),
            units=w.get("units", "imperial"),
            one_call_version=_normalise_one_call_version(w.get("one_call_version", "3.0")),
        )

    if "birthdays" in raw:
        b = _section(raw, "birthdays")
        cfg.birthdays = BirthdayConfig(
            source=b.get("source", "file"),
            file_path=b.get("file_path", "config/birthdays.json"),
            calendar_keyword=b.get("calendar_keyword", "Birthday"),
            lookahead_days=b.get("lookahead_days", 30),
        )

    if "display" in raw:
        d = _section(raw, "display")
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
        s = _section(raw, "schedule")
        cfg.schedule = ScheduleConfig(
            quiet_hours_start=s.get("quiet_hours_start", 23),
            quiet_hours_end=s.get("quiet_hours_end", 6),
        )

    if "cache" in raw:
        ca = _section(raw, "cache")
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
        fl = _section(raw, "filters")
        cfg.filters = FilterConfig(
            exclude_calendars=fl.get("exclude_calendars", []),
            exclude_keywords=fl.get("exclude_keywords", []),
            exclude_all_day=fl.get("exclude_all_day", False),
        )

    if "purpleair" in raw:
        pa = _section(raw, "purpleair")
        raw_sensor = pa.get("sensor_id", 0)
        sensor_id = _optional_int(raw_sensor)
        cfg.purpleair = PurpleAirConfig(
            api_key=pa.get("api_key", ""),
            sensor_id=sensor_id or 0,
            # A sensor_id that will not parse used to raise straight out of
            # load_config() (TypeError on an empty value, ValueError on text).
            # Carry the offending value instead so validate_config() can name
            # it as a ConfigError, which is what the user needs to see.
            sensor_id_invalid=(
                "" if sensor_id is not None or raw_sensor is None else repr(raw_sensor)
            ),
        )

    if "random_theme" in raw:
        rt = _section(raw, "random_theme")
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
                try:
                    numeric = {
                        "temp_at_least": _optional_number(when_raw, "temp_at_least", float),
                        "temp_at_most": _optional_number(when_raw, "temp_at_most", float),
                        "aqi_at_least": _optional_number(when_raw, "aqi_at_least", int),
                    }
                except ValueError:
                    # A threshold we cannot read would otherwise become "no
                    # constraint", turning a narrow rule into one that fires on
                    # everything below it.  Drop the rule instead, matching how
                    # malformed entries are already handled here.
                    continue
                cond = ThemeRuleCondition(
                    weather=when_raw.get("weather"),
                    weather_alert_present=when_raw.get("weather_alert_present"),
                    daypart=when_raw.get("daypart"),
                    season=when_raw.get("season"),
                    weekday=when_raw.get("weekday"),
                    calendar=when_raw.get("calendar"),
                    **numeric,
                )
                rules.append(ThemeRule(when=cond, theme=str(item.get("theme", ""))))
        cfg.theme_rules = ThemeRulesConfig(rules=rules)

    if "quotes" in raw:
        q = _section(raw, "quotes")
        cfg.quotes = QuotesConfig(path=str(q.get("path", cfg.quotes.path) or ""))

    if "photo" in raw:
        ph = _section(raw, "photo")
        cfg.photo = PhotoConfig(
            path=ph.get("path", cfg.photo.path),
        )

    if "countdown" in raw:
        cd = _section(raw, "countdown")
        raw_events = cd.get("events", [])
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
        cfg.output_dir = _section(raw, "output").get("dry_run_dir", cfg.output_dir)

    if raw.get("state_dir") is not None:
        cfg.state_dir = str(raw["state_dir"])

    if "logging" in raw:
        cfg.log_level = _section(raw, "logging").get("level", cfg.log_level)

    if raw.get("title") is not None:
        cfg.title = str(raw["title"])

    if raw.get("theme") is not None:
        cfg.theme = str(raw["theme"])

    if raw.get("timezone") is not None:
        cfg.timezone = str(raw["timezone"])

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
