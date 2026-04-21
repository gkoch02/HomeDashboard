"""Tests for the create_app factory's defensive branches in src/web/app.py.

The happy path is exercised by tests/test_web_routes.py; this module fills in
the error-recovery and missing-config branches.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from src.config import Config
from src.web.app import _load_web_config, create_app

# ---------------------------------------------------------------------------
# _load_web_config
# ---------------------------------------------------------------------------


def test_load_web_config_returns_empty_when_path_is_none():
    assert _load_web_config(None) == {}


def test_load_web_config_returns_empty_when_path_missing(tmp_path):
    assert _load_web_config(str(tmp_path / "missing.yaml")) == {}


def test_load_web_config_returns_empty_when_path_empty_string():
    assert _load_web_config("") == {}


def test_load_web_config_warns_on_unparseable_yaml(tmp_path, caplog):
    """A malformed YAML file is logged and an empty dict is returned (line 42-44)."""
    bad = tmp_path / "web.yaml"
    bad.write_text("not: valid: : yaml: : :")
    with caplog.at_level(logging.WARNING):
        result = _load_web_config(str(bad))
    assert result == {}
    assert any("Could not load web config" in rec.message for rec in caplog.records)


def test_load_web_config_returns_empty_dict_for_empty_file(tmp_path):
    """yaml.safe_load on empty file returns None — must coerce to {}."""
    f = tmp_path / "web.yaml"
    f.write_text("")
    assert _load_web_config(str(f)) == {}


# ---------------------------------------------------------------------------
# create_app — defensive branches
# ---------------------------------------------------------------------------


def test_create_app_uses_default_config_when_app_path_missing(tmp_path):
    """Missing app config → fall back to defaults from Config() (line 70-72)."""
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("")
    # Point at a non-existent app config — factory must fall through to Config().
    app = create_app(
        web_config_path=str(web_yaml),
        app_config_path=str(tmp_path / "missing.yaml"),
    )
    assert isinstance(app.config["DASH_CFG"], Config)


def test_create_app_uses_defaults_when_load_config_raises(tmp_path, caplog):
    """If load_config raises, factory falls back to Config() and warns (line 66-67)."""
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")  # exists, but we'll patch load_config to raise

    with (
        patch("src.web.app.load_config", side_effect=RuntimeError("broken config")),
        caplog.at_level(logging.WARNING),
    ):
        app = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))

    assert isinstance(app.config["DASH_CFG"], Config)
    assert any("Could not load dashboard config" in rec.message for rec in caplog.records)


def test_create_app_marks_auth_disabled_when_no_credentials(tmp_path):
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("port: 8080\n")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")

    app = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
    assert app.config["WEB_AUTH_ENABLED"] is False


def test_create_app_marks_auth_enabled_when_credentials_present(tmp_path):
    from src.web.auth import hash_password

    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text(f"auth:\n  username: u\n  password_hash: '{hash_password('p')}'\n")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")
    app = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
    assert app.config["WEB_AUTH_ENABLED"] is True


def test_create_app_uses_secret_key_from_web_config(tmp_path):
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("secret_key: super-secret-string\n")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")

    app = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
    assert app.secret_key == "super-secret-string"


def test_create_app_falls_back_to_dev_secret_when_unset(tmp_path):
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")
    app = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
    assert app.secret_key == "dashboard-web-dev-secret"


def test_create_app_derives_source_ttl_map(tmp_path):
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")
    app = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
    ttls = app.config["SOURCE_TTLS"]
    for source in ("events", "weather", "birthdays", "air_quality"):
        assert source in ttls
        assert isinstance(ttls[source], int)
