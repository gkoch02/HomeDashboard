"""Tests for the P2 config editor — config_editor.py and /api/config routes."""

import json
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
    apply_patch,
    get_config_for_web,
)

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
        )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["saved"] is True


def test_config_page_returns_html(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    # Config page uses JS for submission — check for the save button and card structure
    assert b"saveConfig" in resp.data
    assert b"cfg-result" in resp.data
