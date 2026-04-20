"""Tests for the P2 config editor — config_editor.py and /api/config routes."""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.config import ConfigError
from src.web.app import create_app
from src.web.config_editor import (
    EDITABLE_FIELD_PATHS,
    _apply_to_raw,
    _load_raw_yaml,
    _write_raw_yaml,
    apply_patch,
    get_config_for_web,
    list_config_backups,
    restore_latest_backup,
)


def _csrf_headers(client):
    client.get("/config")
    with client.session_transaction() as sess:
        token = sess["csrf_token"]
    return {"X-CSRF-Token": token}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg_path(tmp_path):
    """Minimal config.yaml for testing."""
    p = tmp_path / "config.yaml"
    p.write_text("title: Test Dashboard\n")
    return p


@pytest.fixture()
def app(tmp_path):
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("port: 8080\n")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("title: Test Dashboard\n")

    application = create_app(str(web_yaml), str(cfg_yaml))
    application.config["TESTING"] = True
    application.config["STATE_DIR"] = str(tmp_path / "state")
    application.config["OUTPUT_DIR"] = str(tmp_path / "output")
    (tmp_path / "state").mkdir()
    (tmp_path / "output").mkdir()
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


# Patch target for validate_config inside config_editor to avoid PIL import.
_VALIDATE_PATCH = "src.web.config_editor.validate_config"


def _no_errors(_cfg, config_path=""):
    """Stub: validation passes with no errors or warnings."""
    return [], []


def _with_error(_cfg, config_path=""):
    """Stub: validation fails with one ConfigError."""
    return [ConfigError(field="theme", message="Unknown theme", hint="")], []


# ---------------------------------------------------------------------------
# EDITABLE_FIELD_PATHS allowlist
# ---------------------------------------------------------------------------


def test_sensitive_fields_not_in_allowlist():
    """Sensitive API keys must never appear in the editable fields allowlist."""
    sensitive_prefixes = ("weather.api_key", "purpleair.api_key", "google.service_account")
    for key in EDITABLE_FIELD_PATHS:
        for prefix in sensitive_prefixes:
            assert not key.startswith(prefix), f"Sensitive field in allowlist: {key!r}"


def test_all_editable_fields_have_yaml_paths():
    for key, path in EDITABLE_FIELD_PATHS.items():
        assert isinstance(path, tuple) and len(path) >= 1, f"Invalid path for {key!r}"


# YAML key path → dataclass attribute path on Config. Most entries map directly
# (e.g. ("display", "show_weather") → cfg.display.show_weather). Exceptions are
# listed explicitly. theme_schedule is verified separately because it's a list.
_YAML_TO_ATTR_OVERRIDES: dict[tuple, tuple] = {
    ("logging", "level"): ("log_level",),
}

# Sample values used to write each editable field and read it back. The values
# are intentionally distinct from the dataclass defaults so a silent dropout is
# detectable.
_SAMPLE_VALUES: dict[str, object] = {
    "title": "ZZZ-roundtrip-title",
    "theme": "minimalist",
    "timezone": "America/Los_Angeles",
    "log_level": "DEBUG",
    "display.show_weather": False,
    "display.show_birthdays": False,
    "display.show_info_panel": False,
    "display.week_days": 5,
    "display.enable_partial_refresh": True,
    "display.max_partials_before_full": 99,
    "schedule.quiet_hours_start": 21,
    "schedule.quiet_hours_end": 7,
    "weather.latitude": 37.7749,
    "weather.longitude": -122.4194,
    "weather.units": "metric",
    "birthdays.source": "calendar",
    "birthdays.lookahead_days": 60,
    "birthdays.calendar_keyword": "ZZZ-Birthday-Marker",
    "filters.exclude_calendars": ["ZZZ-cal-a"],
    "filters.exclude_keywords": ["ZZZ-kw-a"],
    "filters.exclude_all_day": True,
    "cache.weather_ttl_minutes": 11,
    "cache.events_ttl_minutes": 12,
    "cache.birthdays_ttl_minutes": 13,
    "cache.weather_fetch_interval": 14,
    "cache.events_fetch_interval": 15,
    "cache.birthdays_fetch_interval": 16,
    "cache.air_quality_ttl_minutes": 17,
    "cache.air_quality_fetch_interval": 18,
    "cache.max_failures": 19,
    "cache.cooldown_minutes": 20,
    "cache.quote_refresh": "hourly",
    "random_theme.include": ["minimalist"],
    "random_theme.exclude": ["fantasy"],
}


def _resolve_attr_path(yaml_path: tuple) -> tuple:
    return _YAML_TO_ATTR_OVERRIDES.get(yaml_path, yaml_path)


def _read_attr(cfg, attr_path: tuple):
    obj = cfg
    for segment in attr_path:
        obj = getattr(obj, segment)
    return obj


def test_editable_fields_round_trip_through_load_config(tmp_path):
    """Every EDITABLE_FIELD_PATHS entry must write to a YAML key that
    load_config() reads back into the corresponding dataclass attribute.

    Catches: a config field rename that leaves a stale entry pointing at an
    ignored YAML key (the silent-write-no-effect bug).
    """
    from src.config import load_config

    # Sanity: every editable field has a sample value (theme_schedule is special).
    skip_keys = {"theme_schedule"}
    missing = set(EDITABLE_FIELD_PATHS) - skip_keys - set(_SAMPLE_VALUES)
    assert not missing, f"Sample values missing for: {sorted(missing)}"

    p = tmp_path / "config.yaml"
    raw = _apply_to_raw({}, _SAMPLE_VALUES)
    p.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))

    cfg = load_config(str(p))

    for api_path, value in _SAMPLE_VALUES.items():
        yaml_path = EDITABLE_FIELD_PATHS[api_path]
        attr_path = _resolve_attr_path(yaml_path)
        actual = _read_attr(cfg, attr_path)
        assert actual == value, (
            f"{api_path!r} did not round-trip: wrote {value!r} via YAML "
            f"path {yaml_path}, read {actual!r} from cfg.{'.'.join(attr_path)}"
        )


def test_editable_field_theme_schedule_round_trips(tmp_path):
    """theme_schedule is a list-of-dicts and is handled separately by load_config."""
    from src.config import load_config

    p = tmp_path / "config.yaml"
    raw = _apply_to_raw(
        {},
        {"theme_schedule": [{"time": "06:00", "theme": "default"}]},
    )
    p.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))

    cfg = load_config(str(p))
    assert len(cfg.theme_schedule.entries) == 1
    assert cfg.theme_schedule.entries[0].time == "06:00"
    assert cfg.theme_schedule.entries[0].theme == "default"


# ---------------------------------------------------------------------------
# _load_raw_yaml
# ---------------------------------------------------------------------------


def test_load_raw_yaml_returns_dict(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("title: hello\n")
    result = _load_raw_yaml(str(p))
    assert result == {"title": "hello"}


def test_load_raw_yaml_missing_file(tmp_path):
    result = _load_raw_yaml(str(tmp_path / "nonexistent.yaml"))
    assert result == {}


# ---------------------------------------------------------------------------
# _apply_to_raw
# ---------------------------------------------------------------------------


def test_apply_to_raw_sets_root_field():
    raw = {"title": "Old"}
    updated = _apply_to_raw(raw, {"title": "New"})
    assert updated["title"] == "New"
    # Original not mutated
    assert raw["title"] == "Old"


def test_apply_to_raw_sets_nested_field():
    raw = {"display": {"show_weather": True}}
    updated = _apply_to_raw(raw, {"display.show_weather": False})
    assert updated["display"]["show_weather"] is False


def test_apply_to_raw_creates_nested_dict_if_absent():
    raw = {}
    updated = _apply_to_raw(raw, {"weather.latitude": 37.7})
    assert updated["weather"]["latitude"] == 37.7


def test_apply_to_raw_theme_schedule():
    raw = {}
    schedule = [{"time": "08:00", "theme": "default"}]
    updated = _apply_to_raw(raw, {"theme_schedule": schedule})
    assert updated["theme_schedule"] == schedule


def test_apply_to_raw_ignores_unknown_fields():
    raw = {"title": "X"}
    updated = _apply_to_raw(raw, {"__hacked__": "evil", "title": "Y"})
    assert "__hacked__" not in updated
    assert updated["title"] == "Y"


# ---------------------------------------------------------------------------
# get_config_for_web
# ---------------------------------------------------------------------------


def test_get_config_for_web_returns_dict(cfg_path):
    result = get_config_for_web(str(cfg_path))
    assert isinstance(result, dict)


def test_get_config_for_web_sensitive_fields_are_booleans(cfg_path):
    result = get_config_for_web(str(cfg_path))
    # Sensitive fields should be _*_set booleans, never plaintext strings
    assert isinstance(result["weather"]["_api_key_set"], bool)
    assert isinstance(result["purpleair"]["_api_key_set"], bool)
    assert isinstance(result["google"]["_service_account_set"], bool)


def test_get_config_for_web_no_raw_api_key(cfg_path):
    """No 'api_key' key should appear at any nesting level in the response."""
    result = get_config_for_web(str(cfg_path))
    result_str = json.dumps(result)
    # api_key and service_account_path must not appear as real values
    assert '"api_key"' not in result_str
    assert '"service_account_path"' not in result_str


def test_get_config_for_web_contains_expected_sections(cfg_path):
    result = get_config_for_web(str(cfg_path))
    for section in (
        "display",
        "schedule",
        "weather",
        "birthdays",
        "filters",
        "cache",
        "random_theme",
        "theme_schedule",
    ):
        assert section in result, f"Missing section: {section}"


def test_get_config_for_web_title_field(cfg_path):
    result = get_config_for_web(str(cfg_path))
    assert result["title"] == "Test Dashboard"


def test_get_config_for_web_includes_backups(cfg_path):
    bak = cfg_path.with_suffix(".yaml.bak")
    bak.write_text("title: Older\n")
    result = get_config_for_web(str(cfg_path))
    assert "backups" in result
    assert result["backups"][0]["name"].startswith("config.yaml.bak")


# ---------------------------------------------------------------------------
# apply_patch — mock validate_config to avoid PIL dependency in test env
# ---------------------------------------------------------------------------


def test_apply_patch_saves_valid_change(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("title: Old\n")
    with patch(_VALIDATE_PATCH, _no_errors):
        saved, errors, warnings = apply_patch(str(p), {"title": "New"})
    assert saved is True
    assert errors == []
    raw = yaml.safe_load(p.read_text())
    assert raw["title"] == "New"


def test_apply_patch_rejects_unsafe_field(tmp_path):
    """Patching a field not in EDITABLE_FIELD_PATHS is silently ignored."""
    p = tmp_path / "config.yaml"
    p.write_text("title: Keep\n")
    with patch(_VALIDATE_PATCH, _no_errors):
        saved, errors, warnings = apply_patch(str(p), {"weather.api_key": "HACKED"})
    assert saved is True
    raw = yaml.safe_load(p.read_text())
    weather = raw.get("weather", {})
    assert "api_key" not in weather


def test_apply_patch_validates_bad_value(tmp_path):
    """An invalid value should produce errors and not save."""
    p = tmp_path / "config.yaml"
    p.write_text("title: Test\n")
    with patch(_VALIDATE_PATCH, _with_error):
        saved, errors, warnings = apply_patch(str(p), {"theme": "nonexistent_theme_xyz"})
    assert saved is False
    assert len(errors) > 0


def test_apply_patch_atomic_write(tmp_path):
    """File should be fully written after apply_patch."""
    p = tmp_path / "config.yaml"
    p.write_text("title: Original\n")
    with patch(_VALIDATE_PATCH, _no_errors):
        saved, _, _ = apply_patch(str(p), {"title": "Updated"})
    assert saved
    content = p.read_text()
    assert "Updated" in content
    assert "Original" not in content


def test_apply_patch_does_not_clobber_untouched_fields(tmp_path):
    """Fields not in the patch must survive the write."""
    p = tmp_path / "config.yaml"
    p.write_text("title: Keep\ntimezone: US/Eastern\n")
    with patch(_VALIDATE_PATCH, _no_errors):
        saved, _, _ = apply_patch(str(p), {"title": "Changed"})
    assert saved
    raw = yaml.safe_load(p.read_text())
    assert raw["timezone"] == "US/Eastern"


def test_apply_patch_rotates_existing_backup(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("title: Original\n")
    bak = tmp_path / "config.yaml.bak"
    bak.write_text("title: Older\n")
    with patch(_VALIDATE_PATCH, _no_errors):
        saved, _, _ = apply_patch(str(p), {"title": "Updated"})
    assert saved
    backups = list_config_backups(str(p), limit=5)
    assert any(item["name"] == "config.yaml.bak" for item in backups)
    assert any(item["name"].startswith("config.yaml.bak.") for item in backups)


def test_restore_latest_backup(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("title: Current\n")
    bak = tmp_path / "config.yaml.bak"
    bak.write_text("title: Backup\n")
    restored, message = restore_latest_backup(str(p))
    assert restored is True
    assert "Restored" in message
    raw = yaml.safe_load(p.read_text())
    assert raw["title"] == "Backup"


# ---------------------------------------------------------------------------
# /api/config HTTP routes — also mock validate_config
# ---------------------------------------------------------------------------


def test_get_api_config_returns_200(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "title" in data


def test_post_api_config_valid_patch(client, app):
    config_path = app.config["APP_CONFIG_PATH"]
    with patch(_VALIDATE_PATCH, _no_errors):
        resp = client.post(
            "/api/config",
            data=json.dumps({"title": "WebUpdated"}),
            content_type="application/json",
            headers=_csrf_headers(client),
        )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["saved"] is True
    assert data["errors"] == []
    raw = yaml.safe_load(Path(config_path).read_text())
    assert raw["title"] == "WebUpdated"


def test_post_api_config_bad_patch_returns_errors(client):
    with patch(_VALIDATE_PATCH, _with_error):
        resp = client.post(
            "/api/config",
            data=json.dumps({"theme": "totally_invalid_theme_9999"}),
            content_type="application/json",
            headers=_csrf_headers(client),
        )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["saved"] is False
    assert len(data["errors"]) > 0


def test_post_api_config_empty_patch_saves(client):
    with patch(_VALIDATE_PATCH, _no_errors):
        resp = client.post(
            "/api/config",
            data=json.dumps({}),
            content_type="application/json",
            headers=_csrf_headers(client),
        )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["saved"] is True
    assert "backups" in data


def test_get_api_config_backups(client, app):
    config_path = Path(app.config["APP_CONFIG_PATH"])
    config_path.with_suffix(".yaml.bak").write_text("title: Backup\n")
    resp = client.get("/api/config/backups")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "backups" in data
    assert len(data["backups"]) >= 1


def test_restore_latest_backup_route(client, app):
    config_path = Path(app.config["APP_CONFIG_PATH"])
    config_path.write_text("title: Current\n")
    config_path.with_suffix(".yaml.bak").write_text("title: Backup\n")
    resp = client.post("/api/config/restore-latest", headers=_csrf_headers(client))
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["restored"] is True
    raw = yaml.safe_load(config_path.read_text())
    assert raw["title"] == "Backup"


def test_config_page_returns_html(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    # Config page uses JS for submission — check for the save flow and card structure
    assert b"openSavePreview" in resp.data
    assert b"save-preview-confirm" in resp.data
    assert b"cfg-result" in resp.data
    assert b"Change Summary" in resp.data
    assert b"Config Backups" in resp.data
    assert b"Review changes before save" in resp.data
    assert b"save-preview-dialog" in resp.data
    assert b"Basic" in resp.data
    assert b"Advanced" in resp.data


def test_post_config_requires_csrf(client):
    resp = client.post(
        "/api/config",
        data=json.dumps({"title": "Nope"}),
        content_type="application/json",
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Failure-mode tests for internal helpers
# ---------------------------------------------------------------------------


def test_load_raw_yaml_returns_empty_on_missing_file(tmp_path):
    assert _load_raw_yaml(str(tmp_path / "does-not-exist.yaml")) == {}


def test_load_raw_yaml_returns_empty_for_empty_file(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    assert _load_raw_yaml(str(p)) == {}


def test_load_raw_yaml_swallows_parse_error(tmp_path, caplog):
    p = tmp_path / "broken.yaml"
    p.write_text(":::not valid yaml:::\n- [unbalanced\n")

    with caplog.at_level(logging.WARNING, logger="src.web.config_editor"):
        result = _load_raw_yaml(str(p))
    assert result == {}
    assert any("Could not load" in rec.message for rec in caplog.records)


def test_apply_to_raw_silently_drops_unknown_fields():
    out = _apply_to_raw({}, {"nonexistent.field": 42, "title": "Kept"})
    assert out == {"title": "Kept"}


def test_apply_to_raw_theme_schedule_non_list_resets_to_empty():
    out = _apply_to_raw({"theme_schedule": [1, 2, 3]}, {"theme_schedule": "not a list"})
    assert out["theme_schedule"] == []


def test_apply_to_raw_rebuilds_nested_dict_when_leaf_is_scalar():
    """If an existing value at a non-leaf path is not a dict, it must be replaced."""
    raw = {"display": "broken-scalar"}
    out = _apply_to_raw(raw, {"display.show_weather": True})
    assert out["display"] == {"show_weather": True}


def test_apply_patch_rejects_invalid_theme_schedule_time(tmp_path):
    """theme_schedule entries with a malformed time are a hard validation error."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("title: T\n")
    saved, errors, _warnings = apply_patch(
        str(cfg_path),
        {"theme_schedule": [{"time": "not-a-time", "theme": "default"}]},
    )
    assert saved is False
    assert errors
    assert any("Invalid time" in e["message"] for e in errors)
    # File must NOT have changed on validation failure.
    assert yaml.safe_load(cfg_path.read_text()) == {"title": "T"}


def test_apply_patch_warnings_do_not_block_save(tmp_path):
    """Unknown theme names are warnings — save should proceed and persist."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("title: T\n")
    saved, errors, warnings = apply_patch(str(cfg_path), {"theme": "not-a-real-theme"})
    assert saved is True
    assert errors == []
    assert warnings  # warning emitted
    assert yaml.safe_load(cfg_path.read_text())["theme"] == "not-a-real-theme"


def test_write_raw_yaml_creates_backup_timestamp_on_repeat_save(tmp_path):
    """A second save with an existing .bak should rotate it to a timestamped file."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("title: Original\n")

    # First save: creates .bak from the original.
    _write_raw_yaml(str(cfg_path), {"title": "First"})
    bak = cfg_path.with_suffix(".yaml.bak")
    assert bak.exists()
    assert yaml.safe_load(bak.read_text())["title"] == "Original"

    # Second save: previous .bak must be rotated to a timestamped copy.
    _write_raw_yaml(str(cfg_path), {"title": "Second"})
    timestamped = list(tmp_path.glob("config.yaml.bak.*"))
    assert len(timestamped) == 1
    assert yaml.safe_load(timestamped[0].read_text())["title"] == "Original"
    # Fresh .bak reflects the first-saved content.
    assert yaml.safe_load(bak.read_text())["title"] == "First"


def test_write_raw_yaml_cleans_up_tempfile_on_yaml_dump_failure(tmp_path):
    """If yaml.dump raises during the atomic write, the .tmp file must be removed."""
    cfg_path = tmp_path / "config.yaml"

    def _boom(*args, **kwargs):
        raise RuntimeError("yaml exploded")

    with patch("src.web.config_editor.yaml.dump", side_effect=_boom):
        with pytest.raises(RuntimeError):
            _write_raw_yaml(str(cfg_path), {"title": "X"})

    # No stale .tmp files left behind, target file not created.
    assert not any(p.suffix == ".tmp" for p in tmp_path.iterdir())
    assert not cfg_path.exists()


def test_write_raw_yaml_backup_io_error_is_non_fatal(tmp_path, caplog):
    """A failing backup step should log a warning but allow the save to proceed."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("title: Original\n")

    # Force Path.read_bytes (the backup copy step) to raise — the save must still
    # succeed after logging a warning.
    with caplog.at_level(logging.WARNING, logger="src.web.config_editor"):
        with patch(
            "src.web.config_editor.Path.read_bytes",
            side_effect=OSError("cannot read source for backup"),
        ):
            _write_raw_yaml(str(cfg_path), {"title": "After"})

    # The target file was still updated despite the backup failure.
    assert yaml.safe_load(cfg_path.read_text())["title"] == "After"
    assert any("Could not write config backup" in rec.message for rec in caplog.records)


def test_restore_latest_backup_no_backup_returns_false(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("title: T\n")
    ok, msg = restore_latest_backup(str(cfg_path))
    assert ok is False
    assert "No backup" in msg


def test_restore_latest_backup_rejects_invalid_backup(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("title: Original\n")
    bak = cfg_path.with_suffix(".yaml.bak")
    # A bad quantization_mode is a hard validation error (not just a warning).
    bak.write_text("display:\n  quantization_mode: bogus-mode\n")

    ok, msg = restore_latest_backup(str(cfg_path))
    assert ok is False
    assert "failed validation" in msg
    # Original config must remain untouched.
    assert yaml.safe_load(cfg_path.read_text())["title"] == "Original"


def test_list_config_backups_missing_parent_returns_empty(tmp_path):
    assert list_config_backups(str(tmp_path / "nope" / "config.yaml")) == []
