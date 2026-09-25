"""load_config() reads plausible-but-wrong YAML shapes without crashing (#269).

Every case here used to escape as ``TypeError`` / ``AttributeError`` from
``load_config()`` or ``validate_config()`` — the two functions with no error
boundary above them — taking down every renderer run, ``--check-config`` and
both web pages. Now a readable value is coerced to its proper type, an
unreadable one keeps the default and is reported by ``validate_config()`` as
a ``ConfigError`` naming the field, and ``load_config()`` never raises.
"""

from __future__ import annotations

import pytest

from src.config import Config, load_config, validate_config


def _load(tmp_path, text: str) -> Config:
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return load_config(str(p))


def _error_fields(cfg: Config) -> set[str]:
    errors, _ = validate_config(cfg)
    return {e.field for e in errors}


# --- Readable values are coerced -------------------------------------------


@pytest.mark.parametrize(
    "yaml_text, getter, expected",
    [
        ('schedule:\n  quiet_hours_start: "23"\n', lambda c: c.schedule.quiet_hours_start, 23),
        ('schedule:\n  quiet_hours_end: "6"\n', lambda c: c.schedule.quiet_hours_end, 6),
        ('weather:\n  latitude: "40.7"\n', lambda c: c.weather.latitude, 40.7),
        ("weather:\n  longitude: -74\n", lambda c: c.weather.longitude, -74.0),
        ('cache:\n  weather_fetch_interval: "30"\n', lambda c: c.cache.weather_fetch_interval, 30),
        ('cache:\n  events_ttl_minutes: "120"\n', lambda c: c.cache.events_ttl_minutes, 120),
        ('birthdays:\n  lookahead_days: "30"\n', lambda c: c.birthdays.lookahead_days, 30),
        (
            'display:\n  min_refresh_interval_seconds: "60"\n',
            lambda c: c.display.min_refresh_interval_seconds,
            60,
        ),
        (
            'display:\n  max_partials_before_full: "20"\n',
            lambda c: c.display.max_partials_before_full,
            20,
        ),
        (
            'display:\n  width: "800"\n  height: "480"\n',
            lambda c: (c.display.width, c.display.height),
            (800, 480),
        ),
        ('google:\n  daily_quota_warning: "500"\n', lambda c: c.google.daily_quota_warning, 500),
        ("display:\n  week_days: 5.0\n", lambda c: c.display.week_days, 5),
    ],
)
def test_quoted_and_mistyped_numbers_are_coerced(tmp_path, yaml_text, getter, expected):
    cfg = _load(tmp_path, yaml_text)
    value = getter(cfg)
    assert value == expected
    assert type(value) is type(expected)
    assert cfg.unreadable == []
    errors, _ = validate_config(cfg)
    assert not [e for e in errors if "must be a number" in e.message]


def test_coerced_values_survive_validation_range_checks(tmp_path):
    """The range checks compare against ints; text there raised TypeError."""
    cfg = _load(tmp_path, 'schedule:\n  quiet_hours_start: "25"\n')
    assert cfg.schedule.quiet_hours_start == 25
    assert "schedule.quiet_hours_start" in _error_fields(cfg)


# --- Unreadable values keep the default and are reported ---------------------


@pytest.mark.parametrize(
    "yaml_text, field, getter, default",
    [
        (
            "schedule:\n  quiet_hours_start: late\n",
            "schedule.quiet_hours_start",
            lambda c: c.schedule.quiet_hours_start,
            23,
        ),
        (
            "schedule:\n  quiet_hours_start: yes\n",
            "schedule.quiet_hours_start",
            lambda c: c.schedule.quiet_hours_start,
            23,
        ),
        ("weather:\n  latitude: here\n", "weather.latitude", lambda c: c.weather.latitude, 0.0),
        ("weather:\n  latitude: [1, 2]\n", "weather.latitude", lambda c: c.weather.latitude, 0.0),
        (
            "cache:\n  weather_fetch_interval: 30m\n",
            "cache.weather_fetch_interval",
            lambda c: c.cache.weather_fetch_interval,
            30,
        ),
        (
            "cache:\n  weather_ttl_minutes: 7.5\n",
            "cache.weather_ttl_minutes",
            lambda c: c.cache.weather_ttl_minutes,
            60,
        ),
        (
            "birthdays:\n  lookahead_days: {a: 1}\n",
            "birthdays.lookahead_days",
            lambda c: c.birthdays.lookahead_days,
            30,
        ),
        (
            "display:\n  min_refresh_interval_seconds: soon\n",
            "display.min_refresh_interval_seconds",
            lambda c: c.display.min_refresh_interval_seconds,
            None,
        ),
        (
            "google:\n  additional_ical_urls: {a: b}\n",
            "google.additional_ical_urls",
            lambda c: c.google.additional_ical_urls,
            [],
        ),
        (
            "random_theme:\n  include: {a: b}\n",
            "random_theme.include",
            lambda c: c.random_theme.include,
            [],
        ),
    ],
)
def test_unreadable_values_keep_default_and_are_named(tmp_path, yaml_text, field, getter, default):
    cfg = _load(tmp_path, yaml_text)
    assert getter(cfg) == default
    assert [path for path, _ in cfg.unreadable] == [field]
    assert field in _error_fields(cfg)


# --- Empty list keys ---------------------------------------------------------


@pytest.mark.parametrize(
    "yaml_text, getter",
    [
        ("google:\n  additional_calendars:\n", lambda c: c.google.additional_calendars),
        ("google:\n  additional_ical_urls:\n", lambda c: c.google.additional_ical_urls),
        ("random_theme:\n  include:\n  exclude:\n", lambda c: c.random_theme.include),
        ("random_theme:\n  include:\n  exclude:\n", lambda c: c.random_theme.exclude),
        ("filters:\n  exclude_calendars:\n", lambda c: c.filters.exclude_calendars),
        ("filters:\n  exclude_keywords:\n", lambda c: c.filters.exclude_keywords),
    ],
)
def test_empty_list_key_reads_as_empty_list(tmp_path, yaml_text, getter):
    """``additional_ical_urls:`` with nothing under it parsed as None, and
    ``list(None)`` raised TypeError on every calendar fetch."""
    cfg = _load(tmp_path, yaml_text)
    assert getter(cfg) == []
    assert list(getter(cfg)) == []
    assert cfg.unreadable == []


def test_lone_scalar_reads_as_one_item_list(tmp_path):
    cfg = _load(tmp_path, "filters:\n  exclude_keywords: standup\n")
    assert cfg.filters.exclude_keywords == ["standup"]
    assert cfg.unreadable == []


# --- theme_schedule entries --------------------------------------------------


@pytest.mark.parametrize("yaml_text", ["theme_schedule:\n  - morning\n", "theme_schedule:\n  -\n"])
def test_non_mapping_theme_schedule_entry_is_skipped_and_named(tmp_path, yaml_text):
    cfg = _load(tmp_path, yaml_text)
    assert cfg.theme_schedule.entries == []
    assert [path for path, _ in cfg.unreadable] == ["theme_schedule[0]"]
    assert "theme_schedule[0]" in _error_fields(cfg)


def test_mapping_theme_schedule_entries_still_parse_around_a_bad_one(tmp_path):
    cfg = _load(
        tmp_path,
        "theme_schedule:\n  - time: '07:00'\n    theme: default\n  - oops\n  - time: '22:00'\n    theme: qotd\n",
    )
    assert [(e.time, e.theme) for e in cfg.theme_schedule.entries] == [
        ("07:00", "default"),
        ("22:00", "qotd"),
    ]
    assert [path for path, _ in cfg.unreadable] == ["theme_schedule[1]"]


# --- Config() itself ---------------------------------------------------------


def test_fresh_config_has_no_unreadable_entries_and_they_are_per_instance():
    a, b = Config(), Config()
    assert a.unreadable == [] and b.unreadable == []
    a.unreadable.append(("x", "y"))
    assert b.unreadable == []


def test_unreadable_is_not_a_dataclass_field():
    """The web schema and the example-config check walk dataclasses.fields(Config)."""
    import dataclasses

    assert "unreadable" not in {f.name for f in dataclasses.fields(Config)}
