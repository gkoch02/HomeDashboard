import logging
import re
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
class DisplayConfig:
    model: str = "epd7in5_V2"
    width: int = 800
    height: int = 480
    enable_partial_refresh: bool = False
    max_partials_before_full: int = 6
    week_days: int = 7
    show_weather: bool = True
    show_birthdays: bool = True
    show_info_panel: bool = True
    quantization_mode: str = "threshold"


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
    photo: PhotoConfig = field(default_factory=PhotoConfig)
    title: str = "Home Dashboard"
    theme: str = "default"
    output_dir: str = "output"
    state_dir: str = "state"
    log_level: str = "INFO"
    timezone: str = "local"


def resolve_tz(tz_name: str) -> tzinfo:
    """Return a tzinfo for the given IANA name, or the system local timezone for 'local'."""
    if tz_name == "local":
        tz = datetime.now().astimezone().tzinfo
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
        model = d.get("model", "epd7in5_V2")

        # Auto-derive native dimensions from model when not explicitly set in YAML
        default_w, default_h = 800, 480
        if "width" not in d or "height" not in d:
            from src.display.driver import WAVESHARE_MODELS

            if model in WAVESHARE_MODELS:
                default_w = WAVESHARE_MODELS[model][1]
                default_h = WAVESHARE_MODELS[model][2]

        cfg.display = DisplayConfig(
            model=model,
            width=d.get("width", default_w),
            height=d.get("height", default_h),
            enable_partial_refresh=d.get("enable_partial_refresh", False),
            max_partials_before_full=d.get("max_partials_before_full", 6),
            week_days=d.get("week_days", 7),
            show_weather=d.get("show_weather", True),
            show_birthdays=d.get("show_birthdays", True),
            show_info_panel=d.get("show_info_panel", True),
            quantization_mode=d.get("quantization_mode", "threshold"),
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

    if "photo" in raw:
        ph = raw["photo"]
        cfg.photo = PhotoConfig(
            path=ph.get("path", cfg.photo.path),
        )

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


@dataclass
class ConfigWarning:
    """A non-fatal configuration issue detected during validation."""

    field: str
    message: str
    hint: str = ""


@dataclass
class ConfigError:
    """A fatal configuration issue that will prevent the dashboard from running."""

    field: str
    message: str
    hint: str = ""


def validate_config(
    cfg: Config, config_path: str = ""
) -> tuple[list[ConfigError], list[ConfigWarning]]:
    """Validate a Config for common issues.

    Returns (errors, warnings) where errors are fatal and warnings are
    informational. An empty errors list means the config is usable.
    """
    errors: list[ConfigError] = []
    warnings: list[ConfigWarning] = []

    # --- Config file existence ---
    if config_path and not Path(config_path).exists():
        errors.append(
            ConfigError(
                field="config",
                message=f"Config file not found: {config_path}",
                hint="Copy the template:  cp config/config.example.yaml config/config.yaml",
            )
        )
        return errors, warnings  # Can't validate further without a config file

    # --- Google / Calendar ---
    using_ical = bool(cfg.google.ical_url)

    if using_ical:
        ical_url = cfg.google.ical_url
        if not ical_url.startswith(("http://", "https://")):
            errors.append(
                ConfigError(
                    field="google.ical_url",
                    message=f"ICS URL must start with http:// or https://, got: {ical_url!r}",
                    hint="Use the 'Secret address in iCal format' URL from Google Calendar settings.",
                )
            )
        sa_path = Path(cfg.google.service_account_path)
        if sa_path.exists():
            warnings.append(
                ConfigWarning(
                    field="google.ical_url",
                    message="Both ical_url and a service account file are configured; "
                    "ical_url takes precedence for calendar events.",
                    hint="Remove service_account_path from config if you only want ICS fetching.",
                )
            )
    else:
        sa_path = Path(cfg.google.service_account_path)
        if not sa_path.exists():
            warnings.append(
                ConfigWarning(
                    field="google.service_account_path",
                    message=f"Service account file not found: {sa_path}",
                    hint="Download a service account JSON key from Google Cloud Console "
                    "and place it at the configured path.",
                )
            )

        if cfg.google.calendar_id == "primary":
            warnings.append(
                ConfigWarning(
                    field="google.calendar_id",
                    message="Calendar ID is set to 'primary' (the default).",
                    hint="Set google.calendar_id to your calendar's ID "
                    "(Settings > Calendar > Integrate > Calendar ID).",
                )
            )

    # --- Weather ---
    if not cfg.weather.api_key:
        warnings.append(
            ConfigWarning(
                field="weather.api_key",
                message="Weather API key is not configured.",
                hint="Sign up at https://openweathermap.org/api and add your key "
                "to weather.api_key in config.yaml.",
            )
        )
    elif cfg.weather.api_key == "YOUR_OPENWEATHERMAP_API_KEY":
        warnings.append(
            ConfigWarning(
                field="weather.api_key",
                message="Weather API key is still the placeholder value.",
                hint="Replace with your actual OpenWeatherMap API key.",
            )
        )
    elif not re.fullmatch(r"[0-9a-fA-F]{32}", cfg.weather.api_key):
        warnings.append(
            ConfigWarning(
                field="weather.api_key",
                message="OpenWeatherMap API key doesn't match expected format (32 hex characters).",
                hint="Double-check your API key at https://home.openweathermap.org/api_keys",
            )
        )

    if cfg.weather.latitude == 0.0 and cfg.weather.longitude == 0.0:
        warnings.append(
            ConfigWarning(
                field="weather.latitude/longitude",
                message="Weather coordinates are at 0,0 (Gulf of Guinea).",
                hint="Set weather.latitude and weather.longitude to your location.",
            )
        )
    elif (
        abs(cfg.weather.latitude - 40.7128) < 0.001
        and abs(cfg.weather.longitude - (-74.0060)) < 0.001
    ):
        warnings.append(
            ConfigWarning(
                field="weather.latitude/longitude",
                message="Weather coordinates appear to be the example defaults (New York City).",
                hint="Update weather.latitude and weather.longitude to your actual location.",
            )
        )

    # --- Timezone ---
    if cfg.timezone != "local":
        try:
            zoneinfo.ZoneInfo(cfg.timezone)
        except (KeyError, zoneinfo.ZoneInfoNotFoundError):
            errors.append(
                ConfigError(
                    field="timezone",
                    message=f"Invalid IANA timezone: '{cfg.timezone}'",
                    hint="Use a valid name like 'America/Los_Angeles' or 'UTC'. "
                    "See: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
                )
            )

    # --- Theme ---
    from src.render.theme import AVAILABLE_THEMES

    if cfg.theme not in AVAILABLE_THEMES:
        warnings.append(
            ConfigWarning(
                field="theme",
                message=f"Unknown theme: '{cfg.theme}'",
                hint=f"Available themes: {', '.join(sorted(AVAILABLE_THEMES))}",
            )
        )

    if cfg.theme in ("random", "random_daily", "random_hourly"):
        real_themes = AVAILABLE_THEMES - {"random", "random_daily", "random_hourly"}
        for label, lst in [
            ("random_theme.include", cfg.random_theme.include),
            ("random_theme.exclude", cfg.random_theme.exclude),
        ]:
            invalid = set(lst) - real_themes
            if invalid:
                warnings.append(
                    ConfigWarning(
                        field=label,
                        message=f"Unknown theme(s): {', '.join(sorted(invalid))}",
                        hint=f"Available themes: {', '.join(sorted(real_themes))}",
                    )
                )
        from src.render.random_theme import eligible_themes

        pool = eligible_themes(cfg.random_theme.include, cfg.random_theme.exclude)
        if not pool:
            warnings.append(
                ConfigWarning(
                    field="random_theme",
                    message="Random theme pool is empty — all themes have been excluded.",
                    hint="Check your include/exclude lists; the dashboard will fall back to 'default'.",
                )
            )

    # --- Theme schedule ---
    real_themes = AVAILABLE_THEMES - {"random"}
    for i, entry in enumerate(cfg.theme_schedule.entries):
        try:
            parts = entry.time.split(":")
            if len(parts) != 2:
                raise ValueError
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            errors.append(
                ConfigError(
                    field=f"theme_schedule[{i}].time",
                    message=f"Invalid time '{entry.time}' — must be HH:MM (24-hour)",
                    hint="Example: '22:00' for 10 PM",
                )
            )
        if entry.theme not in real_themes:
            warnings.append(
                ConfigWarning(
                    field=f"theme_schedule[{i}].theme",
                    message=f"Unknown theme '{entry.theme}' in schedule",
                    hint=f"Available themes: {', '.join(sorted(real_themes))}",
                )
            )

    # --- Display quantization mode ---
    _VALID_QUANT = ("threshold", "floyd_steinberg", "ordered")
    if cfg.display.quantization_mode not in _VALID_QUANT:
        errors.append(
            ConfigError(
                field="display.quantization_mode",
                message=f"Unknown quantization mode: '{cfg.display.quantization_mode}'",
                hint=f"Valid modes: {', '.join(_VALID_QUANT)}",
            )
        )

    # --- Display model ---
    from src.display.driver import WAVESHARE_MODELS

    if cfg.display.model not in WAVESHARE_MODELS:
        warnings.append(
            ConfigWarning(
                field="display.model",
                message=f"Unknown display model: '{cfg.display.model}'",
                hint=f"Supported models: {', '.join(sorted(WAVESHARE_MODELS))}",
            )
        )

    # --- Birthdays ---
    if cfg.birthdays.source == "file":
        bday_path = Path(cfg.birthdays.file_path)
        if not bday_path.exists():
            warnings.append(
                ConfigWarning(
                    field="birthdays.file_path",
                    message=f"Birthday file not found: {bday_path}",
                    hint="Create the file or change birthdays.source to 'calendar' or 'contacts'.",
                )
            )
    elif cfg.birthdays.source == "contacts" and not cfg.google.contacts_email:
        errors.append(
            ConfigError(
                field="google.contacts_email",
                message="birthdays.source is 'contacts' but google.contacts_email is not set.",
                hint="Set google.contacts_email to the email address of the user "
                "whose contacts should be read.",
            )
        )

    if cfg.birthdays.source not in ("file", "calendar", "contacts"):
        errors.append(
            ConfigError(
                field="birthdays.source",
                message=f"Invalid birthday source: '{cfg.birthdays.source}'",
                hint="Must be one of: file, calendar, contacts",
            )
        )

    # --- Schedule ---
    for label, val in [
        ("schedule.quiet_hours_start", cfg.schedule.quiet_hours_start),
        ("schedule.quiet_hours_end", cfg.schedule.quiet_hours_end),
    ]:
        if not (0 <= val <= 23):
            errors.append(
                ConfigError(
                    field=label,
                    message=f"Invalid hour value: {val}",
                    hint="Must be an integer between 0 and 23.",
                )
            )

    # --- Quote refresh ---
    valid_quote_refresh = {"daily", "twice_daily", "hourly"}
    if cfg.cache.quote_refresh not in valid_quote_refresh:
        errors.append(
            ConfigError(
                field="cache.quote_refresh",
                message=f"Invalid quote_refresh value: '{cfg.cache.quote_refresh}'",
                hint=f"Must be one of: {', '.join(sorted(valid_quote_refresh))}",
            )
        )

    # --- Cache fetch intervals ---
    for label, val in [
        ("cache.weather_fetch_interval", cfg.cache.weather_fetch_interval),
        ("cache.events_fetch_interval", cfg.cache.events_fetch_interval),
        ("cache.birthdays_fetch_interval", cfg.cache.birthdays_fetch_interval),
    ]:
        if val <= 0:
            errors.append(
                ConfigError(
                    field=label,
                    message=f"Fetch interval must be positive, got {val}",
                    hint="Set a positive number of minutes.",
                )
            )

    # --- Weather units ---
    if cfg.weather.units not in ("imperial", "metric", "standard"):
        warnings.append(
            ConfigWarning(
                field="weather.units",
                message=f"Unknown weather units: '{cfg.weather.units}'",
                hint="Must be one of: imperial, metric, standard",
            )
        )

    # --- PurpleAir ---
    if cfg.purpleair.api_key and not cfg.purpleair.sensor_id:
        warnings.append(
            ConfigWarning(
                field="purpleair.sensor_id",
                message="PurpleAir api_key is set but sensor_id is missing.",
                hint=(
                    "Find your sensor_index at map.purpleair.com "
                    "(click your sensor — the ID appears in the URL as ?select=XXXXX)."
                ),
            )
        )
    if cfg.purpleair.sensor_id and not cfg.purpleair.api_key:
        warnings.append(
            ConfigWarning(
                field="purpleair.api_key",
                message="PurpleAir sensor_id is set but api_key is missing.",
                hint="Get a free API key at develop.purpleair.com.",
            )
        )

    return errors, warnings


def print_validation_report(errors: list[ConfigError], warnings: list[ConfigWarning]) -> None:
    """Print a human-readable validation report to stderr."""
    import sys

    if not errors and not warnings:
        print("Config OK — no issues found.", file=sys.stderr)
        return

    if errors:
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"  ERRORS ({len(errors)}) — must fix before running", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)
        for e in errors:
            print(f"\n  [{e.field}]", file=sys.stderr)
            print(f"    {e.message}", file=sys.stderr)
            if e.hint:
                print(f"    -> {e.hint}", file=sys.stderr)

    if warnings:
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"  WARNINGS ({len(warnings)}) — may cause issues", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)
        for w in warnings:
            print(f"\n  [{w.field}]", file=sys.stderr)
            print(f"    {w.message}", file=sys.stderr)
            if w.hint:
                print(f"    -> {w.hint}", file=sys.stderr)

    print(file=sys.stderr)
