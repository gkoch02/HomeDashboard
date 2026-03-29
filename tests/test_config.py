"""Tests for src/config.py — load_config() and default values."""

import pytest
import yaml

from src.config import (
    BirthdayConfig, Config, DisplayConfig, GoogleConfig, ScheduleConfig,
    WeatherConfig, load_config,
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
        assert d.model == "epd7in5_V2"
        assert d.width == 800
        assert d.height == 480
        assert d.enable_partial_refresh is True
        assert d.max_partials_before_full == 6
        assert d.week_days == 7
        assert d.show_weather is True
        assert d.show_birthdays is True
        assert d.show_info_panel is True

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
        p.write_text(yaml.dump({
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
        }))
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
        p.write_text(yaml.dump({
            "display": {
                "show_weather": False,
                "show_birthdays": False,
                "show_info_panel": False,
            }
        }))
        cfg = load_config(str(p))
        assert cfg.display.show_weather is False
        assert cfg.display.show_birthdays is False
        assert cfg.display.show_info_panel is False

    def test_model_auto_derives_dimensions(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": {"model": "epd9in7"}}))
        cfg = load_config(str(p))
        assert cfg.display.model == "epd9in7"
        assert cfg.display.width == 1200
        assert cfg.display.height == 825

    def test_model_explicit_dimensions_override(self, tmp_path):
        """Explicit width/height in YAML take precedence over model defaults."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": {"model": "epd9in7", "width": 600, "height": 400}}))
        cfg = load_config(str(p))
        assert cfg.display.width == 600
        assert cfg.display.height == 400

    def test_unknown_model_falls_back_to_defaults(self, tmp_path):
        """An unknown model name keeps 800×480 and lets the driver raise at runtime."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": {"model": "epd_future_model"}}))
        cfg = load_config(str(p))
        assert cfg.display.model == "epd_future_model"
        assert cfg.display.width == 800
        assert cfg.display.height == 480

    def test_model_field_stored_in_config(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"display": {"model": "epd13in3k"}}))
        cfg = load_config(str(p))
        assert cfg.display.model == "epd13in3k"
        assert cfg.display.width == 1600
        assert cfg.display.height == 1200

    def test_timezone_loaded_from_config(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"timezone": "America/Los_Angeles"}))
        cfg = load_config(str(p))
        assert cfg.timezone == "America/Los_Angeles"

    def test_timezone_defaults_when_absent(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"weather": {"api_key": "x"}}))
        cfg = load_config(str(p))
        assert cfg.timezone == "local"

    def test_schedule_loaded_from_config(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"schedule": {"quiet_hours_start": 22, "quiet_hours_end": 7}}))
        cfg = load_config(str(p))
        assert cfg.schedule.quiet_hours_start == 22
        assert cfg.schedule.quiet_hours_end == 7

    def test_schedule_defaults_when_absent(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"weather": {"api_key": "x"}}))
        cfg = load_config(str(p))
        assert cfg.schedule.quiet_hours_start == 23
        assert cfg.schedule.quiet_hours_end == 6

    def test_cache_section_loaded(self, tmp_path):
        """load_config() parses the cache: section into CacheConfig (lines 169-170)."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({
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
        }))
        cfg = load_config(str(p))
        assert cfg.cache.weather_ttl_minutes == 30
        assert cfg.cache.events_ttl_minutes == 90
        assert cfg.cache.max_failures == 5
        assert cfg.cache.cooldown_minutes == 15

    def test_filters_section_loaded(self, tmp_path):
        """load_config() parses the filters: section into FilterConfig (lines 182-183)."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({
            "filters": {
                "exclude_calendars": ["Holidays"],
                "exclude_keywords": ["standup"],
                "exclude_all_day": True,
            }
        }))
        cfg = load_config(str(p))
        assert cfg.filters.exclude_calendars == ["Holidays"]
        assert cfg.filters.exclude_keywords == ["standup"]
        assert cfg.filters.exclude_all_day is True

    def test_title_loaded_from_config(self, tmp_path):
        """load_config() stores the top-level title field (line 196)."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({"title": "My Custom Dashboard"}))
        cfg = load_config(str(p))
        assert cfg.title == "My Custom Dashboard"

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
        p.write_text(yaml.dump({
            "theme": "random",
            "random_theme": {
                "include": ["minimalist", "today"],
                "exclude": ["terminal"],
            },
        }))
        cfg = load_config(str(p))
        assert cfg.theme == "random"
        assert cfg.random_theme.include == ["minimalist", "today"]
        assert cfg.random_theme.exclude == ["terminal"]

    def test_theme_schedule_section_parsed(self, tmp_path):
        """load_config() parses theme_schedule entries into ThemeScheduleConfig."""
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump({
            "theme_schedule": [
                {"time": "06:00", "theme": "default"},
                {"time": "22:00", "theme": "fuzzyclock_invert"},
            ],
        }))
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
