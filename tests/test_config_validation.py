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
