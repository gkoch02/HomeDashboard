"""Tests for P2 action routes — trigger-refresh, reset-breaker, clear-cache."""

import json
from pathlib import Path

import pytest

from src.web.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path):
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("port: 8080\n")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text("")

    application = create_app(str(web_yaml), str(cfg_yaml))
    application.config["TESTING"] = True
    state_dir = tmp_path / "state"
    output_dir = tmp_path / "output"
    state_dir.mkdir()
    output_dir.mkdir()
    application.config["STATE_DIR"] = str(state_dir)
    application.config["OUTPUT_DIR"] = str(output_dir)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# /api/trigger-refresh
# ---------------------------------------------------------------------------


def test_trigger_refresh_creates_file(client, app):
    state_dir = Path(app.config["STATE_DIR"])
    trigger = state_dir / "web_trigger"
    assert not trigger.exists()

    resp = client.post("/api/trigger-refresh")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ok"] is True
    assert trigger.exists()


def test_trigger_refresh_idempotent(client, app):
    """Calling trigger-refresh twice should not fail."""
    client.post("/api/trigger-refresh")
    resp = client.post("/api/trigger-refresh")
    assert resp.status_code == 200
    assert json.loads(resp.data)["ok"] is True


# ---------------------------------------------------------------------------
# /api/reset-breaker
# ---------------------------------------------------------------------------


def test_reset_breaker_known_source(client, app):
    state_dir = Path(app.config["STATE_DIR"])
    breaker_path = state_dir / "dashboard_breaker_state.json"
    breaker_path.write_text(
        json.dumps(
            {"weather": {"state": "open", "consecutive_failures": 5, "last_failure_at": None}}
        )
    )

    resp = client.post(
        "/api/reset-breaker",
        data=json.dumps({"source": "weather"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ok"] is True

    # File should reflect closed state
    raw = json.loads(breaker_path.read_text())
    assert raw["weather"]["state"] == "closed"
    assert raw["weather"]["consecutive_failures"] == 0


def test_reset_breaker_creates_entry_if_absent(client, app):
    """Reset should work even if the breaker file or source key doesn't exist."""
    state_dir = Path(app.config["STATE_DIR"])
    resp = client.post(
        "/api/reset-breaker",
        data=json.dumps({"source": "events"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert json.loads(resp.data)["ok"] is True

    breaker_path = state_dir / "dashboard_breaker_state.json"
    raw = json.loads(breaker_path.read_text())
    assert raw["events"]["state"] == "closed"


def test_reset_breaker_unknown_source_returns_400(client):
    resp = client.post(
        "/api/reset-breaker",
        data=json.dumps({"source": "hacked_source"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert json.loads(resp.data)["ok"] is False


def test_reset_breaker_missing_source_returns_400(client):
    resp = client.post(
        "/api/reset-breaker",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_reset_breaker_preserves_other_sources(client, app):
    state_dir = Path(app.config["STATE_DIR"])
    breaker_path = state_dir / "dashboard_breaker_state.json"
    initial = {
        "weather": {"state": "open", "consecutive_failures": 3, "last_failure_at": None},
        "events": {"state": "closed", "consecutive_failures": 0, "last_failure_at": None},
    }
    breaker_path.write_text(json.dumps(initial))

    client.post(
        "/api/reset-breaker",
        data=json.dumps({"source": "weather"}),
        content_type="application/json",
    )

    raw = json.loads(breaker_path.read_text())
    # events must be untouched
    assert raw["events"]["state"] == "closed"
    assert raw["events"]["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# /api/clear-cache
# ---------------------------------------------------------------------------


def test_clear_cache_single_source(client, app):
    state_dir = Path(app.config["STATE_DIR"])
    cache_path = state_dir / "dashboard_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "weather": {"fetched_at": "2026-04-06T10:00:00", "data": {}},
                "events": {"fetched_at": "2026-04-06T10:00:00", "data": []},
            }
        )
    )

    resp = client.post(
        "/api/clear-cache",
        data=json.dumps({"source": "weather"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert json.loads(resp.data)["ok"] is True

    raw = json.loads(cache_path.read_text())
    assert "weather" not in raw
    assert "events" in raw  # untouched


def test_clear_cache_all(client, app):
    state_dir = Path(app.config["STATE_DIR"])
    cache_path = state_dir / "dashboard_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "weather": {"fetched_at": "2026-04-06T10:00:00"},
                "events": {"fetched_at": "2026-04-06T10:00:00"},
            }
        )
    )

    resp = client.post(
        "/api/clear-cache",
        data=json.dumps({"source": "all"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    raw = json.loads(cache_path.read_text())
    # Only schema_version key should remain
    assert set(raw.keys()) == {"schema_version"}


def test_clear_cache_missing_file_ok(client, app):
    """Clear cache should work even if the cache file doesn't exist yet."""
    resp = client.post(
        "/api/clear-cache",
        data=json.dumps({"source": "birthdays"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert json.loads(resp.data)["ok"] is True


def test_clear_cache_unknown_source_returns_400(client):
    resp = client.post(
        "/api/clear-cache",
        data=json.dumps({"source": "unknown_xyz"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert json.loads(resp.data)["ok"] is False


def test_clear_cache_missing_source_returns_400(client):
    resp = client.post(
        "/api/clear-cache",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400
