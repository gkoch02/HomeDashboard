"""Tests for the P1 web routes — status, image, logs.

Uses Flask's built-in test client with a mocked app config so no real
filesystem paths are required.
"""

import base64
import json
from pathlib import Path

import pytest

from src.web.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path):
    """Create a test Flask app pointed at tmp_path directories."""
    # Write a minimal web.yaml with no auth (open access for tests)
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("port: 8080\n")

    # Write a minimal config.yaml
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")  # load_config returns defaults for empty file

    application = create_app(
        web_config_path=str(web_yaml),
        app_config_path=str(cfg_yaml),
    )
    application.config["TESTING"] = True
    # Point dirs at tmp_path
    application.config["STATE_DIR"] = str(tmp_path / "state")
    application.config["OUTPUT_DIR"] = str(tmp_path / "output")
    (tmp_path / "state").mkdir()
    (tmp_path / "output").mkdir()
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Status routes
# ---------------------------------------------------------------------------


def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data


def test_api_status_shape(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "last_run" in data
    assert "sources" in data
    assert "host" in data
    assert "overall" in data
    assert "web_auth_enabled" in data
    assert "theme_info" in data
    assert "integrations" in data
    assert "recent_events" in data
    for source in ("events", "weather", "birthdays", "air_quality"):
        assert source in data["sources"]
        s = data["sources"][source]
        assert "breaker_state" in s
        assert "staleness" in s
        assert "cache_age_minutes" in s
        assert "summary" in s
        assert "message" in s["summary"]


def test_api_status_reports_theme_resolution(client, app):
    config_path = Path(app.config["APP_CONFIG_PATH"])
    config_path.write_text(
        "theme: random_daily\ntheme_schedule:\n  - time: '06:00'\n    theme: terminal\n"
    )
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert data["theme_info"]["mode"] in ("scheduled", "randomized", "fixed")
    assert "effective_theme" in data["theme_info"]
    assert "configured_theme" in data["theme_info"]


def test_api_status_reflects_open_breaker(client, app, tmp_path):
    state_dir = Path(app.config["STATE_DIR"])
    breaker_data = {
        "weather": {"state": "open", "consecutive_failures": 3, "last_failure_at": None}
    }
    (state_dir / "dashboard_breaker_state.json").write_text(json.dumps(breaker_data))
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert data["sources"]["weather"]["breaker_state"] == "open"
    assert data["sources"]["weather"]["summary"]["severity"] == "bad"
    assert data["overall"]["status"] in ("needs_attention", "degraded")


def test_api_status_returns_recent_events(client, app):
    state_dir = Path(app.config["STATE_DIR"])
    (state_dir / "web_events.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-04-06T16:00:00+00:00",
                "kind": "config_saved",
                "message": "Configuration saved from web UI",
                "details": {"fields": ["title"]},
            }
        )
        + "\n"
    )
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert len(data["recent_events"]) == 1
    assert data["recent_events"][0]["kind"] == "config_saved"


def test_api_status_returns_integration_readiness(client):
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert isinstance(data["integrations"], list)
    assert any(item["name"] == "OpenWeather" for item in data["integrations"])


# ---------------------------------------------------------------------------
# Image routes
# ---------------------------------------------------------------------------


def test_image_latest_404_when_missing(client):
    resp = client.get("/image/latest")
    assert resp.status_code == 404


def test_image_latest_serves_png(client, app, tmp_path):
    output_dir = Path(app.config["OUTPUT_DIR"])
    # Write a minimal valid 1x1 PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (output_dir / "latest.png").write_bytes(png_bytes)
    resp = client.get("/image/latest")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert "no-store" in resp.headers.get("Cache-Control", "")


def test_image_latest_resolves_project_relative_output_dir(tmp_path):
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("port: 8080\n")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("output_dir: output\n")

    app = create_app(str(web_yaml), str(cfg_yaml))
    app.config["TESTING"] = True
    (tmp_path / "state").mkdir()
    (tmp_path / "output").mkdir()
    app.config["STATE_DIR"] = str(tmp_path / "state")
    app.config["OUTPUT_DIR"] = "output"

    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (tmp_path / "output" / "latest.png").write_bytes(png_bytes)

    client = app.test_client()
    resp = client.get("/image/latest")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"


def test_image_theme_rejects_path_traversal(client):
    resp = client.get("/image/theme/../etc/passwd")
    assert resp.status_code in (404, 400)


def test_image_theme_404_when_missing(client):
    resp = client.get("/image/theme/default")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Log routes
# ---------------------------------------------------------------------------


def test_api_logs_empty_when_no_file(client):
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["lines"] == []


def test_api_logs_returns_lines(client, app, tmp_path):
    output_dir = Path(app.config["OUTPUT_DIR"])
    log_content = "\n".join(f"2026-04-06 INFO src.app: line {i}" for i in range(20))
    (output_dir / "dashboard.log").write_text(log_content)
    resp = client.get("/api/logs?lines=10")
    data = json.loads(resp.data)
    assert len(data["lines"]) == 10
    assert data["lines"][-1].endswith("line 19")


def test_api_logs_caps_at_max(client, app, tmp_path):
    output_dir = Path(app.config["OUTPUT_DIR"])
    (output_dir / "dashboard.log").write_text("\n".join(["x"] * 600))
    resp = client.get("/api/logs?lines=999")
    data = json.loads(resp.data)
    assert len(data["lines"]) <= 500  # hard cap


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_auth_enforced_when_configured(tmp_path):
    from src.web.auth import hash_password

    web_yaml = tmp_path / "web.yaml"
    pw_hash = hash_password("secret")
    web_yaml.write_text(f"port: 8080\nauth:\n  username: admin\n  password_hash: '{pw_hash}'\n")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")

    app = create_app(str(web_yaml), str(cfg_yaml))
    app.config["TESTING"] = True
    app.config["STATE_DIR"] = str(tmp_path / "state")
    app.config["OUTPUT_DIR"] = str(tmp_path / "output")
    (tmp_path / "state").mkdir()
    (tmp_path / "output").mkdir()

    client = app.test_client()

    # No credentials → 401
    assert client.get("/").status_code == 401

    # Wrong password → 401
    bad_creds = base64.b64encode(b"admin:wrong").decode()
    assert client.get("/", headers={"Authorization": f"Basic {bad_creds}"}).status_code == 401

    # Correct credentials → 200
    good_creds = base64.b64encode(b"admin:secret").decode()
    assert client.get("/", headers={"Authorization": f"Basic {good_creds}"}).status_code == 200


def test_api_status_marks_auth_disabled_when_open_access(client):
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert data["web_auth_enabled"] is False
