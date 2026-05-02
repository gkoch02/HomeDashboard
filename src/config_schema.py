"""v5 declarative config schema.

Mirrors the dataclasses in :mod:`src.config` with extra metadata the web UI
needs (labels, descriptions, secret/editable flags, enum choices). The
schema is the single source of truth for:

- Which fields the web ``/api/config`` endpoint may patch (replaces the
  hand-rolled ``EDITABLE_FIELD_PATHS`` allowlist in ``web.config_editor``).
- Which fields are secret (api keys, passwords) and must therefore never
  be returned to the browser as plaintext.
- Which fields should render with a select/dropdown vs a free-form input.
- Human-readable labels and descriptions used by the editor template.

Adding a new editable field is a single ``FieldSpec`` entry. Adding a
brand-new section is a single ``SectionSpec`` entry. Validation of the
underlying values still flows through ``src.config.validate_config``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CURRENT_SCHEMA_VERSION = 5


@dataclass(frozen=True)
class FieldSpec:
    """Declarative metadata for one editable config field."""

    path: str
    yaml_path: tuple[str, ...]
    type: str  # "str" | "int" | "float" | "bool" | "list[str]" | "enum"
    label: str
    description: str = ""
    choices: tuple[str, ...] | None = None
    secret: bool = False
    editable: bool = True


@dataclass(frozen=True)
class SectionSpec:
    """One top-level YAML section, e.g. ``weather`` or ``display``."""

    name: str
    title: str
    fields: tuple[FieldSpec, ...]


def _f(
    path: str,
    yaml_path: tuple[str, ...],
    type_: str,
    label: str,
    *,
    description: str = "",
    choices: tuple[str, ...] | None = None,
    secret: bool = False,
    editable: bool = True,
) -> FieldSpec:
    return FieldSpec(
        path=path,
        yaml_path=yaml_path,
        type=type_,
        label=label,
        description=description,
        choices=choices,
        secret=secret,
        editable=editable,
    )


def schema() -> tuple[SectionSpec, ...]:
    """Return the v5 config schema.

    Sections are ordered to match the natural reading order in
    ``config.example.yaml``. Field order within each section is the same.
    """
    return (
        SectionSpec(
            name="root",
            title="General",
            fields=(
                _f("title", ("title",), "str", "Dashboard title"),
                _f("theme", ("theme",), "str", "Theme"),
                _f("timezone", ("timezone",), "str", "Timezone (IANA name or 'local')"),
                _f(
                    "log_level",
                    ("logging", "level"),
                    "enum",
                    "Log level",
                    choices=("DEBUG", "INFO", "WARNING", "ERROR"),
                ),
            ),
        ),
        SectionSpec(
            name="display",
            title="Display",
            fields=(
                _f(
                    "display.show_weather",
                    ("display", "show_weather"),
                    "bool",
                    "Show weather panel",
                ),
                _f(
                    "display.show_birthdays",
                    ("display", "show_birthdays"),
                    "bool",
                    "Show birthdays panel",
                ),
                _f(
                    "display.show_info_panel",
                    ("display", "show_info_panel"),
                    "bool",
                    "Show info / quote panel",
                ),
                _f("display.week_days", ("display", "week_days"), "int", "Days shown in week view"),
                _f(
                    "display.enable_partial_refresh",
                    ("display", "enable_partial_refresh"),
                    "bool",
                    "Enable partial refresh (Waveshare)",
                ),
                _f(
                    "display.max_partials_before_full",
                    ("display", "max_partials_before_full"),
                    "int",
                    "Partials before forced full refresh",
                ),
                _f(
                    "display.min_refresh_interval_seconds",
                    ("display", "min_refresh_interval_seconds"),
                    "int",
                    "Minimum seconds between hardware refreshes",
                    description=(
                        "0 = no cooldown. Inky default 60s; set 3600 to restore the v4 hourly "
                        "throttle."
                    ),
                ),
            ),
        ),
        SectionSpec(
            name="schedule",
            title="Quiet hours",
            fields=(
                _f(
                    "schedule.quiet_hours_start",
                    ("schedule", "quiet_hours_start"),
                    "int",
                    "Quiet hours start (0-23)",
                ),
                _f(
                    "schedule.quiet_hours_end",
                    ("schedule", "quiet_hours_end"),
                    "int",
                    "Quiet hours end (0-23)",
                ),
            ),
        ),
        SectionSpec(
            name="weather",
            title="Weather",
            fields=(
                _f(
                    "weather.api_key",
                    ("weather", "api_key"),
                    "str",
                    "OpenWeatherMap API key",
                    secret=True,
                ),
                _f("weather.latitude", ("weather", "latitude"), "float", "Latitude"),
                _f("weather.longitude", ("weather", "longitude"), "float", "Longitude"),
                _f(
                    "weather.units",
                    ("weather", "units"),
                    "enum",
                    "Units",
                    choices=("imperial", "metric", "standard"),
                ),
            ),
        ),
        SectionSpec(
            name="purpleair",
            title="PurpleAir",
            fields=(
                _f(
                    "purpleair.api_key",
                    ("purpleair", "api_key"),
                    "str",
                    "PurpleAir API key",
                    secret=True,
                ),
                _f("purpleair.sensor_id", ("purpleair", "sensor_id"), "int", "Sensor ID"),
            ),
        ),
        SectionSpec(
            name="google",
            title="Google / Calendar",
            fields=(
                _f(
                    "google.service_account_path",
                    ("google", "service_account_path"),
                    "str",
                    "Service account JSON path",
                    secret=True,
                ),
                _f("google.calendar_id", ("google", "calendar_id"), "str", "Calendar ID"),
                _f(
                    "google.contacts_email",
                    ("google", "contacts_email"),
                    "str",
                    "Contacts email (for birthdays.source=contacts)",
                ),
                _f(
                    "google.ical_url",
                    ("google", "ical_url"),
                    "str",
                    "ICS feed URL (alternative to Google API)",
                    secret=True,
                ),
                _f(
                    "google.caldav_url",
                    ("google", "caldav_url"),
                    "str",
                    "CalDAV server URL (alternative to Google API / ICS)",
                ),
                _f(
                    "google.caldav_username",
                    ("google", "caldav_username"),
                    "str",
                    "CalDAV username",
                ),
                _f(
                    "google.caldav_password_file",
                    ("google", "caldav_password_file"),
                    "str",
                    "CalDAV password file path",
                    secret=True,
                ),
                _f(
                    "google.caldav_calendar_url",
                    ("google", "caldav_calendar_url"),
                    "str",
                    "Specific CalDAV calendar URL (default: first)",
                ),
            ),
        ),
        SectionSpec(
            name="birthdays",
            title="Birthdays",
            fields=(
                _f(
                    "birthdays.source",
                    ("birthdays", "source"),
                    "enum",
                    "Source",
                    choices=("file", "calendar", "contacts"),
                ),
                _f(
                    "birthdays.lookahead_days",
                    ("birthdays", "lookahead_days"),
                    "int",
                    "Lookahead days",
                ),
                _f(
                    "birthdays.calendar_keyword",
                    ("birthdays", "calendar_keyword"),
                    "str",
                    "Keyword (for source=calendar)",
                ),
            ),
        ),
        SectionSpec(
            name="filters",
            title="Event filters",
            fields=(
                _f(
                    "filters.exclude_calendars",
                    ("filters", "exclude_calendars"),
                    "list[str]",
                    "Excluded calendars",
                ),
                _f(
                    "filters.exclude_keywords",
                    ("filters", "exclude_keywords"),
                    "list[str]",
                    "Excluded title keywords",
                ),
                _f(
                    "filters.exclude_all_day",
                    ("filters", "exclude_all_day"),
                    "bool",
                    "Hide all-day events",
                ),
            ),
        ),
        SectionSpec(
            name="cache",
            title="Cache & throttling",
            fields=(
                _f(
                    "cache.weather_ttl_minutes",
                    ("cache", "weather_ttl_minutes"),
                    "int",
                    "Weather TTL (min)",
                ),
                _f(
                    "cache.events_ttl_minutes",
                    ("cache", "events_ttl_minutes"),
                    "int",
                    "Events TTL (min)",
                ),
                _f(
                    "cache.birthdays_ttl_minutes",
                    ("cache", "birthdays_ttl_minutes"),
                    "int",
                    "Birthdays TTL (min)",
                ),
                _f(
                    "cache.air_quality_ttl_minutes",
                    ("cache", "air_quality_ttl_minutes"),
                    "int",
                    "Air quality TTL (min)",
                ),
                _f(
                    "cache.weather_fetch_interval",
                    ("cache", "weather_fetch_interval"),
                    "int",
                    "Weather fetch interval (min)",
                ),
                _f(
                    "cache.events_fetch_interval",
                    ("cache", "events_fetch_interval"),
                    "int",
                    "Events fetch interval (min)",
                ),
                _f(
                    "cache.birthdays_fetch_interval",
                    ("cache", "birthdays_fetch_interval"),
                    "int",
                    "Birthdays fetch interval (min)",
                ),
                _f(
                    "cache.air_quality_fetch_interval",
                    ("cache", "air_quality_fetch_interval"),
                    "int",
                    "Air quality fetch interval (min)",
                ),
                _f(
                    "cache.max_failures",
                    ("cache", "max_failures"),
                    "int",
                    "Circuit breaker — failures before open",
                ),
                _f(
                    "cache.cooldown_minutes",
                    ("cache", "cooldown_minutes"),
                    "int",
                    "Circuit breaker — cooldown (min)",
                ),
                _f(
                    "cache.quote_refresh",
                    ("cache", "quote_refresh"),
                    "enum",
                    "Quote rotation cadence",
                    choices=("daily", "twice_daily", "hourly"),
                ),
            ),
        ),
        SectionSpec(
            name="random_theme",
            title="Random theme",
            fields=(
                _f(
                    "random_theme.include",
                    ("random_theme", "include"),
                    "list[str]",
                    "Theme allowlist",
                ),
                _f(
                    "random_theme.exclude",
                    ("random_theme", "exclude"),
                    "list[str]",
                    "Theme denylist",
                ),
            ),
        ),
        SectionSpec(
            name="theme_schedule",
            title="Theme schedule",
            fields=(
                _f(
                    "theme_schedule",
                    ("theme_schedule",),
                    "list[dict]",
                    "Time-of-day theme schedule",
                    description="List of {time: 'HH:MM', theme: 'name'} entries.",
                ),
            ),
        ),
    )


def all_field_specs() -> tuple[FieldSpec, ...]:
    """Return every :class:`FieldSpec` across all sections, in order."""
    return tuple(field for section in schema() for field in section.fields)


def field_spec_by_path(path: str) -> FieldSpec | None:
    """Return the :class:`FieldSpec` for *path*, or ``None``."""
    for spec in all_field_specs():
        if spec.path == path:
            return spec
    return None


def editable_field_paths() -> dict[str, tuple[str, ...]]:
    """Return ``{flat_path: yaml_path}`` for every editable, non-secret field.

    Drop-in replacement for the hand-rolled
    ``src.web.config_editor.EDITABLE_FIELD_PATHS`` constant.
    """
    return {
        spec.path: spec.yaml_path for spec in all_field_specs() if spec.editable and not spec.secret
    }


def secret_field_paths() -> set[str]:
    """Set of dotted paths that must never be sent to the client as plaintext."""
    return {spec.path for spec in all_field_specs() if spec.secret}


@dataclass(frozen=True)
class SchemaJSON:
    """JSON-friendly view of one section + field for the web UI."""

    sections: list[dict]
    schema_version: int = CURRENT_SCHEMA_VERSION


def to_json(values: dict[str, Any] | None = None) -> dict:
    """Render the schema as JSON, optionally interleaving current values.

    Secret fields never carry their values — only a boolean ``has_value``
    flag derived from *values*. The web UI uses that to render an
    "(unset)" / "(set)" indicator without leaking secrets.

    Args:
        values: Optional flat mapping of dotted ``path → current value``.
            Pass ``None`` to omit values entirely.
    """
    sections_json: list[dict] = []
    for section in schema():
        fields_json: list[dict] = []
        for spec in section.fields:
            entry = {
                "path": spec.path,
                "type": spec.type,
                "label": spec.label,
                "description": spec.description,
                "secret": spec.secret,
                "editable": spec.editable,
            }
            if spec.choices is not None:
                entry["choices"] = list(spec.choices)
            if values is not None:
                if spec.secret:
                    entry["has_value"] = bool(values.get(spec.path))
                else:
                    entry["value"] = values.get(spec.path)
            fields_json.append(entry)
        sections_json.append({"name": section.name, "title": section.title, "fields": fields_json})
    return {"schema_version": CURRENT_SCHEMA_VERSION, "sections": sections_json}
