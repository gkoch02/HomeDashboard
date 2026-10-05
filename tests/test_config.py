"""Tests for src/config.py — load_config() and default values."""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.config import (
    BirthdayConfig,
    Config,
    DisplayConfig,
    GoogleConfig,
    ScheduleConfig,
    WeatherConfig,
    load_config,
)


class TestDefaults:
    def test_config_defaults(self):
        cfg = Config()
        assert cfg.output_dir == "output"
        assert cfg.log_level == "INFO"

    def test_google_defaults(self):
        g = GoogleConfig()
        assert g.service_account_path == "credentials/service_account.json"
        assert g.calendar_id == "primary"
        assert g.additional_calendars == []

    def test_weather_defaults(self):
        w = WeatherConfig()
        assert w.api_key == ""
        assert w.latitude == 0.0
        assert w.longitude == 0.0
        assert w.units == "imperial"

    def test_birthday_defaults(self):
        b = BirthdayConfig()
        assert b.source == "file"
        assert b.lookahead_days == 30

    def test_display_defaults(self):
        d = DisplayConfig()
        assert d.provider == "waveshare"
        assert d.model == "epd7in5_V2"
        assert d.width == 800
        assert d.height == 480
        assert d.enable_partial_refresh is False
        assert d.max_partials_before_full == 20
        assert d.show_weather is True
        assert not hasattr(d, "week_days")
        assert d.show_birthdays is True
        assert d.show_info_panel is True
        assert d.quantization_mode == "threshold"

    def test_schedule_defaults(self):
        s = ScheduleConfig()
        assert s.quiet_hours_start == 23
        assert s.quiet_hours_end == 6

    def test_timezone_default(self):
        cfg = Config()
        assert cfg.timezone == "local"


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = load_config(str(tmp_path / "nonexistent.yaml"))
        assert isinstance(cfg, Config)
        assert cfg.display.width == 800

    def test_empty_yaml_returns_defaults(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("")
        cfg = load_config(str(p))
        assert cfg.display.width == 800
        assert cfg.log_level == "INFO"

    def test_full_config(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(
            yaml.dump(
                {
                    "google": {
                        "service_account_path": "creds/sa.json",
                        "calendar_id": "my@cal.com",
                        "additional_calendars": ["work@cal.com"],
                    },
                    "weather": {
                        "api_key": "abc123",
                        "latitude": 37.7749,
                        "longitude": -122.4194,
                        "units": "metric",
                    },
                    "birthdays": {
                        "source": "calendar",
                        "calendar_keyword": "🎂",
                        "lookahead_days": 14,
                    },
                    "display": {
                        "enable_partial_refresh": True,
                        "max_partials_before_full": 3,
                        "show_weather": False,
                    },
                    "output": {"dry_run_dir": "/tmp/dash"},
                    "logging": {"level": "DEBUG"},
                }
            )
        )
        cfg = load_config(str(p))

        assert cfg.google.service_account_path == "creds/sa.json"
        assert cfg.google.calendar_id == "my@cal.com"
        assert cfg.google.additional_calendars == ["work@cal.com"]

        assert cfg.weather.api_key == "abc123"
        assert cfg.weather.latitude == pytest.approx(37.7749)
        assert cfg.weather.units == "metric"

        assert cfg.birthdays.source == "calendar"
        assert cfg.birthdays.calendar_keyword == "🎂"
        assert cfg.birthdays.lookahead_days == 14

        assert cfg.display.enable_partial_refresh is True
        assert cfg.display.max_partials_before_full == 3
        assert cfg.display.show_weather is False

        assert cfg.output_dir == "/tmp/dash"
        assert cfg.log_level == "DEBUG"

    def test_partial_config_preserves_defaults(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"weather": {"api_key": "key999"}}))
        cfg = load_config(str(p))
        # Weather key overridden
        assert cfg.weather.api_key == "key999"
        # Everything else still defaults
        assert cfg.display.width == 800
        assert cfg.google.calendar_id == "primary"
        assert cfg.birthdays.lookahead_days == 30

    def test_additional_calendars_default_empty(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"google": {"calendar_id": "x@y.com"}}))
        cfg = load_config(str(p))
        assert cfg.google.additional_calendars == []

    def test_display_boolean_flags(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(
            yaml.dump(
                {
                    "display": {
                        "show_weather": False,
                        "show_birthdays": False,
                        "show_info_panel": False,
                    }
                }
            )
        )
        cfg = load_config(str(p))
        assert cfg.display.show_weather is False
        assert cfg.display.show_birthdays is False
        assert cfg.display.show_info_panel is False

    @pytest.mark.parametrize(
        "display,provider,model,width,height",
        [
            ({"model": "epd7in5_HD"}, "waveshare", "epd7in5_HD", 880, 528),
            ({"model": "epd13in3k"}, "waveshare", "epd13in3k", 960, 680),
            (
                {"provider": "inky", "model": "impression_7_3_2025"},
                "inky",
                "impression_7_3_2025",
                800,
                480,
            ),
            ({"model": "epd_future_model"}, "waveshare", "epd_future_model", 800, 480),
        ],
        ids=["waveshare_hd", "waveshare_13in3k", "inky", "unknown_model"],
    )
    def test_model_derives_dimensions(self, display, provider, model, width, height, tmp_path):
        """A known model sets the panel's width and height; an unknown model name is
        stored as given and keeps 800x480, leaving the driver to raise at runtime."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": display}))
        cfg = load_config(str(p))
        assert cfg.display.provider == provider
        assert cfg.display.model == model
        assert (cfg.display.width, cfg.display.height) == (width, height)

    def test_model_explicit_dimensions_override(self, tmp_path):
        """Explicit width/height in YAML take precedence over model defaults."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": {"model": "epd7in5_HD", "width": 600, "height": 400}}))
        cfg = load_config(str(p))
        assert cfg.display.width == 600
        assert cfg.display.height == 400

    @pytest.mark.parametrize("mode", ["floyd_steinberg", "ordered"])
    def test_quantization_mode_from_yaml(self, mode, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": {"quantization_mode": mode}}))
        cfg = load_config(str(p))
        assert cfg.display.quantization_mode == mode

    @pytest.mark.parametrize(
        "doc,attr,expected",
        [
            ({"timezone": "America/Los_Angeles"}, "timezone", "America/Los_Angeles"),
            ({"weather": {"api_key": "x"}}, "timezone", "local"),
            ({"title": "My Custom Dashboard"}, "title", "My Custom Dashboard"),
        ],
        ids=["timezone_set", "timezone_absent", "title_set"],
    )
    def test_top_level_scalar_loaded(self, doc, attr, expected, tmp_path):
        """A top-level scalar key is stored as written, and keeps its default when absent."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(doc))
        cfg = load_config(str(p))
        assert getattr(cfg, attr) == expected

    @pytest.mark.parametrize(
        "doc,start,end",
        [
            ({"schedule": {"quiet_hours_start": 22, "quiet_hours_end": 7}}, 22, 7),
            ({"weather": {"api_key": "x"}}, 23, 6),
        ],
        ids=["set", "absent"],
    )
    def test_schedule_quiet_hours(self, doc, start, end, tmp_path):
        """The schedule section sets quiet hours; without it they default to 23-6."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(doc))
        cfg = load_config(str(p))
        assert cfg.schedule.quiet_hours_start == start
        assert cfg.schedule.quiet_hours_end == end

    def test_cache_section_loaded(self, tmp_path):
        """load_config() parses the cache: section into CacheConfig."""
        p = tmp_path / "config.yaml"
        p.write_text(
            yaml.dump(
                {
                    "cache": {
                        "weather_ttl_minutes": 30,
                        "events_ttl_minutes": 90,
                        "birthdays_ttl_minutes": 720,
                        "weather_fetch_interval": 15,
                        "events_fetch_interval": 60,
                        "birthdays_fetch_interval": 480,
                        "max_failures": 5,
                        "cooldown_minutes": 15,
                    }
                }
            )
        )
        cfg = load_config(str(p))
        assert cfg.cache.weather_ttl_minutes == 30
        assert cfg.cache.events_ttl_minutes == 90
        assert cfg.cache.max_failures == 5
        assert cfg.cache.cooldown_minutes == 15

    def test_filters_section_loaded(self, tmp_path):
        """load_config() parses the filters: section into FilterConfig."""
        p = tmp_path / "config.yaml"
        p.write_text(
            yaml.dump(
                {
                    "filters": {
                        "exclude_calendars": ["Holidays"],
                        "exclude_keywords": ["standup"],
                        "exclude_all_day": True,
                    }
                }
            )
        )
        cfg = load_config(str(p))
        assert cfg.filters.exclude_calendars == ["Holidays"]
        assert cfg.filters.exclude_keywords == ["standup"]
        assert cfg.filters.exclude_all_day is True

    def test_purpleair_section_parsed(self, tmp_path):
        """load_config() parses the purpleair: section into PurpleAirConfig."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"purpleair": {"api_key": "abc123", "sensor_id": 99999}}))
        cfg = load_config(str(p))
        assert cfg.purpleair.api_key == "abc123"
        assert cfg.purpleair.sensor_id == 99999

    def test_random_theme_section_parsed(self, tmp_path):
        """load_config() parses the random_theme: section into RandomThemeConfig."""
        p = tmp_path / "config.yaml"
        p.write_text(
            yaml.dump(
                {
                    "theme": "random",
                    "random_theme": {
                        "include": ["minimalist", "today"],
                        "exclude": ["terminal"],
                    },
                }
            )
        )
        cfg = load_config(str(p))
        assert cfg.theme == "random"
        assert cfg.random_theme.include == ["minimalist", "today"]
        assert cfg.random_theme.exclude == ["terminal"]

    def test_theme_schedule_section_parsed(self, tmp_path):
        """load_config() parses theme_schedule entries into ThemeScheduleConfig."""
        p = tmp_path / "config.yaml"
        p.write_text(
            yaml.dump(
                {
                    "theme_schedule": [
                        {"time": "06:00", "theme": "default"},
                        {"time": "22:00", "theme": "fuzzyclock_invert"},
                    ],
                }
            )
        )
        cfg = load_config(str(p))
        assert len(cfg.theme_schedule.entries) == 2
        assert cfg.theme_schedule.entries[0].time == "06:00"
        assert cfg.theme_schedule.entries[0].theme == "default"
        assert cfg.theme_schedule.entries[1].time == "22:00"
        assert cfg.theme_schedule.entries[1].theme == "fuzzyclock_invert"

    def test_theme_schedule_defaults_to_empty(self, tmp_path):
        """theme_schedule is empty by default when absent from YAML."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"weather": {"api_key": "x"}}))
        cfg = load_config(str(p))
        assert cfg.theme_schedule.entries == []


class TestLoadConfigOptionalSections:
    """Cover the optional top-level sections (photo, state_dir) in load_config."""

    @pytest.mark.parametrize(
        "photo,expected",
        [({"path": "/home/pi/family.jpg"}, "/home/pi/family.jpg"), ({}, "")],
        ids=["path_set", "empty_keeps_default"],
    )
    def test_photo_section_path(self, photo, expected, tmp_path):
        """``photo.path`` is stored as given; a ``photo:`` key with no fields keeps
        the PhotoConfig default of an empty path."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"photo": photo}))
        cfg = load_config(str(p))
        assert cfg.photo.path == expected

    def test_state_dir_override(self, tmp_path):
        p = tmp_path / "config.yaml"
        custom = tmp_path / "custom_state"
        p.write_text(yaml.dump({"state_dir": str(custom)}))
        cfg = load_config(str(p))
        assert cfg.state_dir == str(custom)

    def test_state_dir_default_when_absent(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"title": "x"}))
        cfg = load_config(str(p))
        assert cfg.state_dir == "state"


class TestResolveTz:
    """Cover resolve_tz including the local-tz-unknown fallback."""

    def test_named_timezone(self):
        import zoneinfo

        from src.config import resolve_tz

        tz = resolve_tz("America/Los_Angeles")
        assert isinstance(tz, zoneinfo.ZoneInfo)
        assert str(tz) == "America/Los_Angeles"

    def test_local_returns_system_tz(self):
        from src.config import resolve_tz

        tz = resolve_tz("local")
        # System tz should always resolve on CI/Linux (UTC at worst).
        assert tz is not None

    def test_local_falls_back_to_utc_when_system_tz_missing(self, caplog):
        """When datetime.now().astimezone().tzinfo is None, fall back to UTC."""
        import logging
        import zoneinfo
        from datetime import datetime as real_datetime

        from src.config import resolve_tz

        fake_now = MagicMock()
        fake_now.astimezone.return_value = MagicMock(tzinfo=None)
        with patch("src.config.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            # Keep other datetime attributes intact for any collateral callers
            mock_dt.side_effect = real_datetime
            with caplog.at_level(logging.WARNING, logger="src.config"):
                tz = resolve_tz("local")

        assert tz == zoneinfo.ZoneInfo("UTC")
        assert "Could not determine local timezone" in caplog.text


class TestEmptySections:
    """A section header with nothing under it parses as None (#236).

    Commenting a section's keys out one by one is exactly what a user does
    while trying things, and ``load_config()`` has no error boundary above it —
    an AttributeError here took down the renderer, ``--check-config`` and both
    web pages at once.
    """

    SECTIONS = [
        "google",
        "weather",
        "birthdays",
        "display",
        "schedule",
        "cache",
        "filters",
        "purpleair",
        "random_theme",
        "photo",
        "quotes",
        "countdown",
        "output",
        "logging",
        "theme_schedule",
        "theme_rules",
    ]

    @pytest.mark.parametrize("value", ["", " nonsense"], ids=["empty", "non_mapping"])
    @pytest.mark.parametrize("section", SECTIONS)
    def test_unusable_section_falls_back_to_defaults(self, section, value, tmp_path):
        """A section that is empty or not a mapping parses as all defaults."""
        p = tmp_path / "config.yaml"
        p.write_text(f"{section}:{value}\n")
        cfg = load_config(str(p))
        assert cfg == Config()

    def test_every_section_empty_at_once(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("".join(f"{name}:\n" for name in self.SECTIONS))
        cfg = load_config(str(p))
        assert cfg == Config()

    def test_empty_display_still_derives_model_dimensions(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("display:\n")
        cfg = load_config(str(p))
        assert (cfg.display.width, cfg.display.height) == (800, 480)

    @pytest.mark.parametrize(
        "key,attr,default",
        [
            ("title", "title", "Home Dashboard"),
            ("theme", "theme", "default"),
            ("timezone", "timezone", "local"),
            ("state_dir", "state_dir", "state"),
        ],
    )
    def test_empty_scalar_key_keeps_default(self, key, attr, default, tmp_path):
        """``title:`` with nothing after it parses as None.

        ``str(None)`` would put the literal text "None" on the panel, and a
        bare None title crashes the header component outright.
        """
        p = tmp_path / "config.yaml"
        p.write_text(f"{key}:\n")
        cfg = load_config(str(p))
        assert getattr(cfg, attr) == default


class TestPurpleAirSensorId:
    @pytest.mark.parametrize(
        "raw,sensor_id,invalid",
        [
            ("", 0, ""),
            (" abc", 0, "'abc'"),
            (" on", 0, "True"),
            (" 12345", 12345, ""),
        ],
        ids=["empty_reads_as_unset", "non_numeric_recorded", "boolean_rejected", "valid"],
    )
    def test_sensor_id_parsing(self, raw, sensor_id, invalid, tmp_path):
        """An empty sensor_id reads as unset; an unreadable one keeps 0 and records the
        raw value instead of raising. YAML 1.1 reads ``on`` as True, and int(True) is a
        plausible 1, so a boolean is rejected too."""
        p = tmp_path / "config.yaml"
        p.write_text(f"purpleair:\n  api_key: k\n  sensor_id:{raw}\n")
        cfg = load_config(str(p))
        assert cfg.purpleair.sensor_id == sensor_id
        assert cfg.purpleair.sensor_id_invalid == invalid


class TestMaxPartialsDefault:
    def test_dataclass_default_is_twenty(self):
        d = DisplayConfig()
        assert d.max_partials_before_full == 20

    def test_load_config_default_matches_dataclass(self, tmp_path):
        """load_config() with a display section but no max_partials should
        produce the same default as the dataclass."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": {"model": "epd7in5_V2"}}))
        cfg = load_config(str(p))
        assert cfg.display.max_partials_before_full == DisplayConfig().max_partials_before_full
        assert cfg.display.max_partials_before_full == 20
