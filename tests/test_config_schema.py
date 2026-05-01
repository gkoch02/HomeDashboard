"""Contract tests for ``src.config_schema``.

The schema is the v5 source of truth for which config fields are
editable, secret, or have enumerated choices. These tests guard the
public shape so adding a field doesn't silently regress the web UI's
allowlist or sensitive-field handling.
"""

from __future__ import annotations

from src.config_schema import (
    CURRENT_SCHEMA_VERSION,
    FieldSpec,
    SectionSpec,
    all_field_specs,
    editable_field_paths,
    field_spec_by_path,
    schema,
    secret_field_paths,
    to_json,
)


class TestSchemaShape:
    def test_current_schema_version_is_5(self):
        assert CURRENT_SCHEMA_VERSION == 5

    def test_schema_returns_section_specs(self):
        for section in schema():
            assert isinstance(section, SectionSpec)
            assert section.name
            assert section.title
            for field in section.fields:
                assert isinstance(field, FieldSpec)
                assert field.path
                assert field.yaml_path
                assert field.type in {
                    "str",
                    "int",
                    "float",
                    "bool",
                    "list[str]",
                    "list[dict]",
                    "enum",
                }

    def test_section_names_are_unique(self):
        names = [s.name for s in schema()]
        assert len(names) == len(set(names))

    def test_field_paths_are_unique(self):
        paths = [f.path for f in all_field_specs()]
        assert len(paths) == len(set(paths))

    def test_field_spec_by_path_lookup(self):
        spec = field_spec_by_path("weather.api_key")
        assert spec is not None
        assert spec.secret is True

    def test_field_spec_by_path_unknown_returns_none(self):
        assert field_spec_by_path("__never_registered__") is None


class TestEditableFieldPaths:
    def test_returns_yaml_path_tuples(self):
        paths = editable_field_paths()
        assert paths["weather.latitude"] == ("weather", "latitude")
        assert paths["display.show_weather"] == ("display", "show_weather")

    def test_secret_fields_are_excluded(self):
        paths = editable_field_paths()
        # api keys / passwords / service-account paths must NEVER appear in the
        # web-UI editable allowlist.
        assert "weather.api_key" not in paths
        assert "purpleair.api_key" not in paths
        assert "google.service_account_path" not in paths
        assert "google.caldav_password_file" not in paths
        assert "google.ical_url" not in paths

    def test_v4_baseline_fields_present(self):
        """The v4 EDITABLE_FIELD_PATHS keys must all still be present."""
        paths = editable_field_paths()
        v4_baseline = {
            "title",
            "theme",
            "timezone",
            "log_level",
            "display.show_weather",
            "display.show_birthdays",
            "schedule.quiet_hours_start",
            "schedule.quiet_hours_end",
            "weather.latitude",
            "weather.longitude",
            "weather.units",
            "birthdays.source",
            "filters.exclude_calendars",
            "cache.weather_ttl_minutes",
            "cache.quote_refresh",
            "random_theme.include",
            "theme_schedule",
        }
        missing = v4_baseline - set(paths)
        assert not missing, f"v4 baseline editable paths missing: {missing}"


class TestSecretFieldPaths:
    def test_known_secrets_are_marked(self):
        secrets = secret_field_paths()
        assert "weather.api_key" in secrets
        assert "purpleair.api_key" in secrets
        assert "google.service_account_path" in secrets
        assert "google.caldav_password_file" in secrets

    def test_no_overlap_with_editable_paths(self):
        assert not (secret_field_paths() & set(editable_field_paths()))


class TestToJson:
    def test_emits_schema_version_and_sections(self):
        out = to_json()
        assert out["schema_version"] == CURRENT_SCHEMA_VERSION
        assert isinstance(out["sections"], list)
        assert all("fields" in s for s in out["sections"])

    def test_secret_fields_get_has_value_not_value(self):
        out = to_json(values={"weather.api_key": "DEADBEEF"})
        api_key_field = _find_field(out, "weather.api_key")
        assert api_key_field is not None
        assert "value" not in api_key_field
        assert api_key_field["has_value"] is True

    def test_non_secret_fields_get_value(self):
        out = to_json(values={"weather.latitude": 40.7128})
        lat_field = _find_field(out, "weather.latitude")
        assert lat_field is not None
        assert lat_field["value"] == 40.7128

    def test_no_values_omits_value_keys(self):
        out = to_json()
        for section in out["sections"]:
            for f in section["fields"]:
                assert "value" not in f
                assert "has_value" not in f

    def test_choices_propagate(self):
        out = to_json()
        units_field = _find_field(out, "weather.units")
        assert units_field is not None
        assert "choices" in units_field
        assert "imperial" in units_field["choices"]


def _find_field(schema_json: dict, path: str) -> dict | None:
    for section in schema_json["sections"]:
        for f in section["fields"]:
            if f["path"] == path:
                return f
    return None
