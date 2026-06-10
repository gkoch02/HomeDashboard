"""Configuration validation — errors, warnings, and the report printer.

Split out of ``src/config.py`` so the dataclass/YAML-parsing module stays
focused. ``validate_config`` checks a loaded :class:`~src.config.Config` for
fatal problems (missing files, malformed values, unknown themes/models) and
non-fatal ones (suspicious-but-workable combinations), returning
``(errors, warnings)``.

For backwards compatibility every public name here is re-exported from
``src.config``, so ``from src.config import validate_config`` keeps working.
"""

from __future__ import annotations

import re
import zoneinfo
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Annotation-only: importing src.config at runtime would deadlock the
    # circular bottom-of-module re-export in config.py when this module is
    # imported first.
    from src.config import Config


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
    using_caldav = bool(cfg.google.caldav_url)
    using_ical = bool(cfg.google.ical_url)

    if using_caldav:
        caldav_url = cfg.google.caldav_url
        if not caldav_url.startswith(("http://", "https://")):
            errors.append(
                ConfigError(
                    field="google.caldav_url",
                    message=f"CalDAV URL must start with http:// or https://, got: {caldav_url!r}",
                    hint="Set google.caldav_url to your server's CalDAV endpoint.",
                )
            )
        if not cfg.google.caldav_username:
            errors.append(
                ConfigError(
                    field="google.caldav_username",
                    message="CalDAV username is required when caldav_url is set.",
                    hint="Set google.caldav_username to your account login.",
                )
            )
        if not cfg.google.caldav_password_file:
            errors.append(
                ConfigError(
                    field="google.caldav_password_file",
                    message="CalDAV password_file is required when caldav_url is set.",
                    hint="Point google.caldav_password_file at a one-line file containing the password.",
                )
            )
        elif not Path(cfg.google.caldav_password_file).is_file():
            warnings.append(
                ConfigWarning(
                    field="google.caldav_password_file",
                    message=(f"CalDAV password file not found: {cfg.google.caldav_password_file}"),
                    hint="Create the file with the account's password (one line).",
                )
            )
        if using_ical:
            warnings.append(
                ConfigWarning(
                    field="google.caldav_url",
                    message=(
                        "Both caldav_url and ical_url are configured; "
                        "caldav_url takes precedence for calendar events."
                    ),
                    hint="Remove google.ical_url if you intend to use CalDAV.",
                )
            )
    elif using_ical:
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

    # --- Display provider/model ---
    from src.display.driver import get_display_spec, supported_display_models

    valid_providers = {"waveshare", "inky"}
    if cfg.display.provider not in valid_providers:
        errors.append(
            ConfigError(
                field="display.provider",
                message=f"Unknown display provider: '{cfg.display.provider}'",
                hint=f"Supported providers: {', '.join(sorted(valid_providers))}",
            )
        )
    elif get_display_spec(cfg.display.provider, cfg.display.model) is None:
        warnings.append(
            ConfigWarning(
                field="display.model",
                message=(
                    f"Unknown display model: '{cfg.display.model}' "
                    f"for provider '{cfg.display.provider}'"
                ),
                hint=(
                    f"Supported models: {', '.join(supported_display_models(cfg.display.provider))}"
                ),
            )
        )
    else:
        spec = get_display_spec(cfg.display.provider, cfg.display.model)
        if (
            spec is not None
            and not spec.supports_partial_refresh
            and cfg.display.enable_partial_refresh
        ):
            warnings.append(
                ConfigWarning(
                    field="display.enable_partial_refresh",
                    message=(
                        f"Partial refresh is not supported for "
                        f"{cfg.display.provider}:{cfg.display.model}."
                    ),
                    hint="Set display.enable_partial_refresh to false.",
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

    # --- Theme rules ---
    _VALID_DAYPARTS = {"dawn", "day", "dusk", "night"}
    _VALID_SEASONS = {"spring", "summer", "fall", "autumn", "winter"}
    _VALID_WEEKDAYS = {
        "weekend",
        "weekday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    _VALID_CALENDAR_STATES = {
        "empty",
        "done",
        "active",
        "upcoming_soon",
        "busy",
        "birthday_today",
    }

    def _as_list(v) -> list:
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    for i, rule in enumerate(cfg.theme_rules.rules):
        if rule.theme not in AVAILABLE_THEMES:
            warnings.append(
                ConfigWarning(
                    field=f"theme_rules[{i}].theme",
                    message=f"Unknown theme '{rule.theme}' in rule",
                    hint=f"Available themes: {', '.join(sorted(AVAILABLE_THEMES))}",
                )
            )
        for val in _as_list(rule.when.daypart):
            if str(val).lower() not in _VALID_DAYPARTS:
                warnings.append(
                    ConfigWarning(
                        field=f"theme_rules[{i}].when.daypart",
                        message=f"Unknown daypart '{val}'",
                        hint=f"Must be one of: {', '.join(sorted(_VALID_DAYPARTS))}",
                    )
                )
        for val in _as_list(rule.when.season):
            if str(val).lower() not in _VALID_SEASONS:
                warnings.append(
                    ConfigWarning(
                        field=f"theme_rules[{i}].when.season",
                        message=f"Unknown season '{val}'",
                        hint=f"Must be one of: {', '.join(sorted(_VALID_SEASONS))}",
                    )
                )
        for val in _as_list(rule.when.weekday):
            if str(val).lower() not in _VALID_WEEKDAYS:
                warnings.append(
                    ConfigWarning(
                        field=f"theme_rules[{i}].when.weekday",
                        message=f"Unknown weekday '{val}'",
                        hint=f"Must be one of: {', '.join(sorted(_VALID_WEEKDAYS))}",
                    )
                )
        for val in _as_list(rule.when.calendar):
            if str(val).lower() not in _VALID_CALENDAR_STATES:
                warnings.append(
                    ConfigWarning(
                        field=f"theme_rules[{i}].when.calendar",
                        message=f"Unknown calendar state '{val}'",
                        hint=f"Must be one of: {', '.join(sorted(_VALID_CALENDAR_STATES))}",
                    )
                )

    # --- Countdown events ---
    for i, ev in enumerate(cfg.countdown.events):
        if not ev.name:
            warnings.append(
                ConfigWarning(
                    field=f"countdown.events[{i}].name",
                    message="Countdown event has no name — the entry will be skipped.",
                    hint="Set a descriptive name like 'Paris trip' or 'Anniversary'.",
                )
            )
        try:
            datetime.strptime(ev.date, "%Y-%m-%d")
        except (ValueError, TypeError):
            errors.append(
                ConfigError(
                    field=f"countdown.events[{i}].date",
                    message=f"Invalid countdown date '{ev.date}' — must be YYYY-MM-DD",
                    hint="Example: '2026-07-14' for Bastille Day 2026.",
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
