"""Tests for config validation (validate_config, print_validation_report)."""

from src.config import (
    BirthdayConfig,
    Config,
    ConfigError,
    ConfigWarning,
    DisplayConfig,
    GoogleConfig,
    WeatherConfig,
    load_config,
    print_validation_report,
    validate_config,
)


class TestValidateConfigErrors:
    def test_missing_config_file_is_error(self, tmp_path):
        cfg = Config()
        errors, warnings = validate_config(cfg, config_path=str(tmp_path / "nope.yaml"))
        assert len(errors) == 1
        assert errors[0].field == "config"
        assert "not found" in errors[0].message

    def test_invalid_timezone_is_error(self):
        cfg = Config(timezone="America/Los Angles")
        errors, _ = validate_config(cfg)
        assert any(e.field == "timezone" for e in errors)

    def test_contacts_source_without_email_is_error(self):
        cfg = Config(
            birthdays=BirthdayConfig(source="contacts"),
            google=GoogleConfig(contacts_email=""),
        )
        errors, _ = validate_config(cfg)
        assert any(e.field == "google.contacts_email" for e in errors)

    def test_invalid_birthday_source_is_error(self):
        cfg = Config(birthdays=BirthdayConfig(source="magic"))
        errors, _ = validate_config(cfg)
        assert any(e.field == "birthdays.source" for e in errors)

    def test_unknown_display_provider_is_error(self):
        cfg = Config(display=DisplayConfig(provider="future", model="whatever"))
        errors, _ = validate_config(cfg)
        assert any(e.field == "display.provider" for e in errors)


class TestValidateConfigWarnings:
    def test_missing_service_account_file(self, tmp_path):
        cfg = Config(google=GoogleConfig(service_account_path=str(tmp_path / "missing.json")))
        _, warnings = validate_config(cfg)
        assert any(w.field == "google.service_account_path" for w in warnings)

    def test_default_calendar_id_warns(self):
        cfg = Config()
        _, warnings = validate_config(cfg)
        assert any(w.field == "google.calendar_id" for w in warnings)

    def test_empty_weather_api_key_warns(self):
        cfg = Config(weather=WeatherConfig(api_key=""))
        _, warnings = validate_config(cfg)
        assert any(w.field == "weather.api_key" for w in warnings)

    def test_placeholder_weather_api_key_warns(self):
        cfg = Config(weather=WeatherConfig(api_key="YOUR_OPENWEATHERMAP_API_KEY"))
        _, warnings = validate_config(cfg)
        assert any("placeholder" in w.message for w in warnings)

    def test_example_default_coordinates_warns(self):
        """New York City example defaults from config.example.yaml should warn."""
        cfg = Config(weather=WeatherConfig(latitude=40.7128, longitude=-74.0060, api_key="x"))
        _, warnings = validate_config(cfg)
        assert any(
            w.field == "weather.latitude/longitude" and "example defaults" in w.message
            for w in warnings
        )

    def test_zero_coordinates_warns(self):
        cfg = Config(weather=WeatherConfig(latitude=0.0, longitude=0.0))
        _, warnings = validate_config(cfg)
        assert any("0,0" in w.message for w in warnings)

    def test_nonzero_coordinates_no_warning(self):
        cfg = Config(weather=WeatherConfig(api_key="abc", latitude=40.7, longitude=-74.0))
        _, warnings = validate_config(cfg)
        assert not any("0,0" in w.message for w in warnings)

    def test_unknown_display_model_warns(self):
        cfg = Config(display=DisplayConfig(model="epd_fake"))
        _, warnings = validate_config(cfg)
        assert any(w.field == "display.model" for w in warnings)

    def test_known_display_model_no_warning(self):
        cfg = Config(display=DisplayConfig(model="epd7in5_V2"))
        _, warnings = validate_config(cfg)
        assert not any(w.field == "display.model" for w in warnings)

    def test_known_inky_model_no_warning(self):
        cfg = Config(display=DisplayConfig(provider="inky", model="impression_7_3_2025"))
        _, warnings = validate_config(cfg)
        assert not any(w.field == "display.model" for w in warnings)

    def test_inky_partial_refresh_warns(self):
        cfg = Config(
            display=DisplayConfig(
                provider="inky",
                model="impression_7_3_2025",
                enable_partial_refresh=True,
            )
        )
        _, warnings = validate_config(cfg)
        assert any(w.field == "display.enable_partial_refresh" for w in warnings)

    def test_missing_birthday_file_warns(self, tmp_path):
        cfg = Config(birthdays=BirthdayConfig(source="file", file_path=str(tmp_path / "nope.json")))
        _, warnings = validate_config(cfg)
        assert any(w.field == "birthdays.file_path" for w in warnings)

    def test_invalid_weather_units_warns(self):
        cfg = Config(weather=WeatherConfig(units="kelvin"))
        _, warnings = validate_config(cfg)
        assert any(w.field == "weather.units" for w in warnings)


class TestValidateConfigClean:
    def test_valid_config_no_issues(self, tmp_path):
        """A fully configured config produces no errors."""
        # Create a fake service account file and birthday file
        sa_file = tmp_path / "sa.json"
        sa_file.write_text("{}")
        bday_file = tmp_path / "birthdays.json"
        bday_file.write_text("[]")

        cfg = Config(
            google=GoogleConfig(
                service_account_path=str(sa_file),
                calendar_id="abc@group.calendar.google.com",
            ),
            weather=WeatherConfig(api_key="a" * 32, latitude=40.7, longitude=-74.0),
            birthdays=BirthdayConfig(source="file", file_path=str(bday_file)),
            display=DisplayConfig(model="epd7in5_V2"),
            timezone="America/New_York",
        )
        errors, warnings = validate_config(cfg)
        assert errors == []
        assert warnings == []


class TestPrintValidationReport:
    def test_no_issues_prints_ok(self, capsys):
        print_validation_report([], [])
        captured = capsys.readouterr()
        assert "OK" in captured.err

    def test_errors_printed(self, capsys):
        errors = [ConfigError(field="test", message="bad value", hint="fix it")]
        print_validation_report(errors, [])
        captured = capsys.readouterr()
        assert "ERRORS" in captured.err
        assert "bad value" in captured.err
        assert "fix it" in captured.err

    def test_warnings_printed(self, capsys):
        warnings = [ConfigWarning(field="test", message="maybe wrong")]
        print_validation_report([], warnings)
        captured = capsys.readouterr()
        assert "WARNINGS" in captured.err
        assert "maybe wrong" in captured.err

    def test_warning_hint_printed(self, capsys):
        warnings = [ConfigWarning(field="test", message="maybe wrong", hint="try this")]
        print_validation_report([], warnings)
        captured = capsys.readouterr()
        assert "try this" in captured.err


class TestIcalUrlValidation:
    def test_ical_url_bad_scheme_is_error(self):
        from src.config import GoogleConfig

        cfg = Config(google=GoogleConfig(ical_url="webcal://calendar.google.com/abc"))
        errors, _ = validate_config(cfg)
        assert any(e.field == "google.ical_url" for e in errors)

    def test_ical_url_https_is_valid(self):
        from src.config import GoogleConfig

        cfg = Config(google=GoogleConfig(ical_url="https://calendar.google.com/abc"))
        errors, _ = validate_config(cfg)
        assert not any(e.field == "google.ical_url" for e in errors)

    def test_ical_url_with_existing_service_account_warns(self, tmp_path):
        from src.config import GoogleConfig

        sa = tmp_path / "sa.json"
        sa.write_text("{}")
        cfg = Config(
            google=GoogleConfig(
                ical_url="https://calendar.google.com/abc",
                service_account_path=str(sa),
            )
        )
        _, warnings = validate_config(cfg)
        assert any(w.field == "google.ical_url" for w in warnings)


class TestRandomThemeValidation:
    def test_invalid_theme_in_include_warns(self):
        cfg = Config()
        cfg.theme = "random"
        cfg.random_theme.include = ["nonexistent_xyz"]
        _, warnings = validate_config(cfg)
        assert any(w.field == "random_theme.include" for w in warnings)

    def test_invalid_theme_in_exclude_warns(self):
        cfg = Config()
        cfg.theme = "random"
        cfg.random_theme.exclude = ["nonexistent_xyz"]
        _, warnings = validate_config(cfg)
        assert any(w.field == "random_theme.exclude" for w in warnings)

    def test_empty_pool_warns(self):
        from src.render.theme import AVAILABLE_THEMES

        cfg = Config()
        cfg.theme = "random"
        # Exclude every real theme to empty the pool
        cfg.random_theme.exclude = list(AVAILABLE_THEMES - {"random"})
        _, warnings = validate_config(cfg)
        assert any(w.field == "random_theme" for w in warnings)


class TestThemeScheduleValidation:
    """Covers theme_schedule time-format and unknown-theme validation branches."""

    def _cfg_with_schedule(self, *entries) -> Config:
        from src.config import ThemeScheduleConfig, ThemeScheduleEntry

        cfg = Config()
        cfg.theme_schedule = ThemeScheduleConfig(
            entries=[ThemeScheduleEntry(time=t, theme=th) for t, th in entries]
        )
        return cfg

    def test_valid_schedule_has_no_issues(self):
        cfg = self._cfg_with_schedule(("06:00", "default"), ("22:00", "fuzzyclock"))
        errors, warnings = validate_config(cfg)
        assert not any(e.field.startswith("theme_schedule") for e in errors)
        assert not any(w.field.startswith("theme_schedule") for w in warnings)

    def test_malformed_time_no_colon_is_error(self):
        cfg = self._cfg_with_schedule(("0600", "default"))
        errors, _ = validate_config(cfg)
        assert any(e.field == "theme_schedule[0].time" for e in errors)

    def test_hour_out_of_range_is_error(self):
        cfg = self._cfg_with_schedule(("25:00", "default"))
        errors, _ = validate_config(cfg)
        assert any(e.field == "theme_schedule[0].time" for e in errors)

    def test_minute_out_of_range_is_error(self):
        cfg = self._cfg_with_schedule(("12:99", "default"))
        errors, _ = validate_config(cfg)
        assert any(e.field == "theme_schedule[0].time" for e in errors)

    def test_non_integer_time_is_error(self):
        cfg = self._cfg_with_schedule(("ab:cd", "default"))
        errors, _ = validate_config(cfg)
        assert any(e.field == "theme_schedule[0].time" for e in errors)

    def test_unknown_theme_in_schedule_warns(self):
        cfg = self._cfg_with_schedule(("06:00", "nonexistent_theme_xyz"))
        errors, warnings = validate_config(cfg)
        # Time is valid — no error
        assert not any(e.field == "theme_schedule[0].time" for e in errors)
        assert any(w.field == "theme_schedule[0].theme" for w in warnings)

    def test_invalid_time_and_invalid_theme_both_reported(self):
        cfg = self._cfg_with_schedule(("bad", "also_bad"))
        errors, warnings = validate_config(cfg)
        assert any(e.field == "theme_schedule[0].time" for e in errors)
        assert any(w.field == "theme_schedule[0].theme" for w in warnings)


class TestPurpleAirValidation:
    def test_api_key_without_sensor_id_warns(self):
        from src.config import PurpleAirConfig

        cfg = Config()
        cfg.purpleair = PurpleAirConfig(api_key="mykey", sensor_id=0)
        _, warnings = validate_config(cfg)
        assert any(w.field == "purpleair.sensor_id" for w in warnings)

    def test_sensor_id_without_api_key_warns(self):
        from src.config import PurpleAirConfig

        cfg = Config()
        cfg.purpleair = PurpleAirConfig(api_key="", sensor_id=99999)
        _, warnings = validate_config(cfg)
        assert any(w.field == "purpleair.api_key" for w in warnings)

    def test_both_configured_no_purpleair_warning(self):
        from src.config import PurpleAirConfig

        cfg = Config()
        cfg.purpleair = PurpleAirConfig(api_key="mykey", sensor_id=99999)
        _, warnings = validate_config(cfg)
        assert not any(w.field.startswith("purpleair") for w in warnings)


class TestLoadConfigWarnsOnMissingFile:
    def test_missing_file_logs_warning(self, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="src.config"):
            load_config(str(tmp_path / "nonexistent.yaml"))
        assert "not found" in caplog.text.lower()


# ---------------------------------------------------------------------------
# CalDAV validation
# ---------------------------------------------------------------------------


class TestCalDAVValidation:
    def test_caldav_bad_scheme_is_error(self):
        cfg = Config(
            google=GoogleConfig(
                caldav_url="caldavs://example.com/dav/",
                caldav_username="alice",
                caldav_password_file="/some/file",
            )
        )
        errors, _ = validate_config(cfg)
        assert any(e.field == "google.caldav_url" for e in errors)

    def test_caldav_missing_username_is_error(self):
        cfg = Config(
            google=GoogleConfig(
                caldav_url="https://example.com/dav/",
                caldav_username="",
                caldav_password_file="/some/file",
            )
        )
        errors, _ = validate_config(cfg)
        assert any(e.field == "google.caldav_username" for e in errors)

    def test_caldav_missing_password_file_is_error(self):
        cfg = Config(
            google=GoogleConfig(
                caldav_url="https://example.com/dav/",
                caldav_username="alice",
                caldav_password_file="",
            )
        )
        errors, _ = validate_config(cfg)
        assert any(e.field == "google.caldav_password_file" for e in errors)

    def test_caldav_password_file_not_on_disk_warns(self, tmp_path):
        cfg = Config(
            google=GoogleConfig(
                caldav_url="https://example.com/dav/",
                caldav_username="alice",
                caldav_password_file=str(tmp_path / "missing_pw.txt"),
            )
        )
        _, warnings = validate_config(cfg)
        assert any(w.field == "google.caldav_password_file" for w in warnings)

    def test_caldav_and_ical_both_set_warns(self, tmp_path):
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")
        cfg = Config(
            google=GoogleConfig(
                caldav_url="https://example.com/dav/",
                caldav_username="alice",
                caldav_password_file=str(pw),
                ical_url="https://example.com/calendar.ics",
            )
        )
        _, warnings = validate_config(cfg)
        assert any(w.field == "google.caldav_url" for w in warnings)


# ---------------------------------------------------------------------------
# theme_rules validation
# ---------------------------------------------------------------------------


class TestThemeRulesValidation:
    def _cfg_with_rule(self, theme, **when_kwargs):
        from src.config import ThemeRule, ThemeRuleCondition, ThemeRulesConfig

        cfg = Config()
        cfg.theme_rules = ThemeRulesConfig(
            rules=[ThemeRule(when=ThemeRuleCondition(**when_kwargs), theme=theme)]
        )
        return cfg

    def test_unknown_theme_in_rule_warns(self):
        cfg = self._cfg_with_rule("nonexistent_theme_xyz")
        _, warnings = validate_config(cfg)
        assert any("theme_rules[0].theme" in w.field for w in warnings)

    def test_valid_theme_in_rule_no_warning(self):
        cfg = self._cfg_with_rule("agenda")
        _, warnings = validate_config(cfg)
        assert not any("theme_rules" in w.field for w in warnings)

    def test_invalid_daypart_warns(self):
        cfg = self._cfg_with_rule("agenda", daypart="noon")
        _, warnings = validate_config(cfg)
        assert any("theme_rules[0].when.daypart" in w.field for w in warnings)

    def test_valid_daypart_no_warning(self):
        cfg = self._cfg_with_rule("agenda", daypart="morning")
        _, warnings = validate_config(cfg)
        assert not any("daypart" in w.field for w in warnings)

    def test_daypart_list_with_one_bad_value_warns(self):
        cfg = self._cfg_with_rule("agenda", daypart=["morning", "noon"])
        _, warnings = validate_config(cfg)
        assert any("daypart" in w.field for w in warnings)

    def test_invalid_season_warns(self):
        cfg = self._cfg_with_rule("agenda", season="monsoon")
        _, warnings = validate_config(cfg)
        assert any("theme_rules[0].when.season" in w.field for w in warnings)

    def test_valid_season_no_warning(self):
        cfg = self._cfg_with_rule("agenda", season="winter")
        _, warnings = validate_config(cfg)
        assert not any("season" in w.field for w in warnings)

    def test_invalid_weekday_warns(self):
        cfg = self._cfg_with_rule("agenda", weekday="funday")
        _, warnings = validate_config(cfg)
        assert any("theme_rules[0].when.weekday" in w.field for w in warnings)

    def test_valid_weekday_no_warning(self):
        cfg = self._cfg_with_rule("agenda", weekday="weekend")
        _, warnings = validate_config(cfg)
        assert not any("weekday" in w.field for w in warnings)

    def test_invalid_calendar_state_warns(self):
        cfg = self._cfg_with_rule("agenda", calendar="partying")
        _, warnings = validate_config(cfg)
        assert any("theme_rules[0].when.calendar" in w.field for w in warnings)

    def test_valid_calendar_state_no_warning(self):
        cfg = self._cfg_with_rule("agenda", calendar="active")
        _, warnings = validate_config(cfg)
        assert not any("when.calendar" in w.field for w in warnings)

    def test_multiple_rules_indexed_correctly(self):
        from src.config import ThemeRule, ThemeRuleCondition, ThemeRulesConfig

        cfg = Config()
        cfg.theme_rules = ThemeRulesConfig(
            rules=[
                ThemeRule(when=ThemeRuleCondition(daypart="morning"), theme="agenda"),
                ThemeRule(when=ThemeRuleCondition(season="monsoon"), theme="agenda"),
            ]
        )
        _, warnings = validate_config(cfg)
        assert any("theme_rules[1].when.season" in w.field for w in warnings)
        assert not any("theme_rules[0]" in w.field for w in warnings)


# ---------------------------------------------------------------------------
# countdown.events validation
# ---------------------------------------------------------------------------


class TestCountdownValidation:
    def _cfg_with_countdown(self, *events):
        from src.config import CountdownConfig, CountdownEvent

        cfg = Config()
        cfg.countdown = CountdownConfig(events=[CountdownEvent(name=n, date=d) for n, d in events])
        return cfg

    def test_valid_countdown_event_no_issues(self):
        cfg = self._cfg_with_countdown(("Trip", "2027-01-01"))
        errors, warnings = validate_config(cfg)
        assert not any("countdown" in e.field for e in errors)
        assert not any("countdown" in w.field for w in warnings)

    def test_missing_event_name_warns(self):
        cfg = self._cfg_with_countdown(("", "2027-01-01"))
        _, warnings = validate_config(cfg)
        assert any("countdown.events[0].name" in w.field for w in warnings)

    def test_malformed_date_is_error(self):
        cfg = self._cfg_with_countdown(("Trip", "01-01-2027"))
        errors, _ = validate_config(cfg)
        assert any("countdown.events[0].date" in e.field for e in errors)

    def test_completely_invalid_date_string_is_error(self):
        cfg = self._cfg_with_countdown(("Trip", "not-a-date"))
        errors, _ = validate_config(cfg)
        assert any("countdown.events[0].date" in e.field for e in errors)

    def test_multiple_events_indexed_correctly(self):
        cfg = self._cfg_with_countdown(("Trip", "2027-01-01"), ("Party", "not-valid"))
        errors, _ = validate_config(cfg)
        assert any("countdown.events[1].date" in e.field for e in errors)
        assert not any("countdown.events[0].date" in e.field for e in errors)
