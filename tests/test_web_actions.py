"""Tests for P2 action routes — trigger-refresh, reset-breaker, clear-cache."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.web.app import create_app


def _csrf_headers(client):
    client.get("/")
    with client.session_transaction() as sess:
        token = sess["csrf_token"]
    return {"X-CSRF-Token": token}


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

    resp = client.post("/api/trigger-refresh", headers=_csrf_headers(client))
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ok"] is True
    assert trigger.exists()


def test_trigger_refresh_idempotent(client, app):
    """Calling trigger-refresh twice should not fail."""
    client.post("/api/trigger-refresh", headers=_csrf_headers(client))
    resp = client.post("/api/trigger-refresh", headers=_csrf_headers(client))
    assert resp.status_code == 200
    assert json.loads(resp.data)["ok"] is True


def test_post_actions_require_csrf(client):
    resp = client.post("/api/trigger-refresh")
    assert resp.status_code == 403


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
        headers=_csrf_headers(client),
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ok"] is True

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
        headers=_csrf_headers(client),
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
        headers=_csrf_headers(client),
    )
    assert resp.status_code == 400
    assert json.loads(resp.data)["ok"] is False


def test_reset_breaker_missing_source_returns_400(client):
    resp = client.post(
        "/api/reset-breaker",
        data=json.dumps({}),
        content_type="application/json",
        headers=_csrf_headers(client),
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
        headers=_csrf_headers(client),
    )

    raw = json.loads(breaker_path.read_text())
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
        headers=_csrf_headers(client),
    )
    assert resp.status_code == 200
    assert json.loads(resp.data)["ok"] is True

    raw = json.loads(cache_path.read_text())
    assert "weather" not in raw
    assert "events" in raw


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
        headers=_csrf_headers(client),
    )
    assert resp.status_code == 200
    raw = json.loads(cache_path.read_text())
    assert set(raw.keys()) == {"schema_version"}


def test_clear_cache_missing_file_ok(client, app):
    """Clear cache should work even if the cache file doesn't exist yet."""
    resp = client.post(
        "/api/clear-cache",
        data=json.dumps({"source": "birthdays"}),
        content_type="application/json",
        headers=_csrf_headers(client),
    )
    assert resp.status_code == 200
    assert json.loads(resp.data)["ok"] is True


def test_clear_cache_unknown_source_returns_400(client):
    resp = client.post(
        "/api/clear-cache",
        data=json.dumps({"source": "unknown_xyz"}),
        content_type="application/json",
        headers=_csrf_headers(client),
    )
    assert resp.status_code == 400
    assert json.loads(resp.data)["ok"] is False


def test_clear_cache_missing_source_returns_400(client):
    resp = client.post(
        "/api/clear-cache",
        data=json.dumps({}),
        content_type="application/json",
        headers=_csrf_headers(client),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Failure-path tests: each endpoint's ``except Exception`` branch returns 500.
# ---------------------------------------------------------------------------


def test_trigger_refresh_returns_500_on_io_error(client):
    headers = _csrf_headers(client)
    with patch("src.web.routes.actions.Path.touch", side_effect=OSError("disk full")):
        resp = client.post("/api/trigger-refresh", headers=headers)
    assert resp.status_code == 500
    body = json.loads(resp.data)
    assert body["ok"] is False
    assert "disk full" in body["error"]


def test_reset_breaker_returns_500_on_write_failure(client):
    headers = _csrf_headers(client)
    with patch(
        "src.web.routes.actions.locked_update_json",
        side_effect=OSError("no space left"),
    ):
        resp = client.post(
            "/api/reset-breaker",
            data=json.dumps({"source": "weather"}),
            content_type="application/json",
            headers=headers,
        )
    assert resp.status_code == 500
    body = json.loads(resp.data)
    assert body["ok"] is False
    assert "no space" in body["error"]


def test_clear_cache_returns_500_on_write_failure(client):
    headers = _csrf_headers(client)
    with patch(
        "src.web.routes.actions.locked_update_json",
        side_effect=OSError("io broke"),
    ):
        resp = client.post(
            "/api/clear-cache",
            data=json.dumps({"source": "all"}),
            content_type="application/json",
            headers=headers,
        )
    assert resp.status_code == 500
    body = json.loads(resp.data)
    assert body["ok"] is False
    assert "io broke" in body["error"]


def test_actions_uses_the_shared_locked_update_helper():
    """One implementation of the locked read-modify-write, not a web-layer copy.

    Was #213 (no private atomic-write copy); since #242 the shared helper is
    ``locked_update_json``, which also covers the read.
    """
    from src import _io
    from src.web.routes import actions

    assert actions.locked_update_json is _io.locked_update_json
    assert not hasattr(actions, "_atomic_write_json")
    assert not hasattr(actions, "atomic_write_json")


def test_atomic_write_json_cleans_up_tempfile_on_failure(tmp_path):
    """If json.dump raises, the tempfile should be unlinked and the exception re-raised."""
    from src._io import atomic_write_json

    target = tmp_path / "out.json"

    # Something that json can't serialise should trigger cleanup.
    unserialisable = {"bad": {object()}}
    with pytest.raises(TypeError):
        atomic_write_json(target, unserialisable)

    # No .tmp leftovers in the directory.
    assert not any(p.suffix == ".tmp" for p in tmp_path.iterdir())
    assert not target.exists()


# ---------------------------------------------------------------------------
# Registry-derived source lists (#213)
# ---------------------------------------------------------------------------


@pytest.fixture()
def synthetic_source():
    """Register a throwaway fetcher for the duration of one test."""
    from src.fetchers.registry import Fetcher, register_fetcher, unregister_fetcher

    name = "synthetic_source"
    register_fetcher(
        Fetcher(
            name=name,
            fetch=lambda ctx: None,
            serialize=lambda v: {},
            deserialize=lambda b: None,
            ttl_minutes=lambda cfg: 60,
            interval_minutes=lambda cfg: 60,
        )
    )
    try:
        yield name
    finally:
        unregister_fetcher(name)


class TestSourcesDeriveFromRegistry:
    def test_source_names_cover_every_registered_fetcher(self):
        from src.fetchers.registry import registered_names
        from src.web.sources import source_names

        assert set(registered_names()) == set(source_names())

    def test_builtin_sources_keep_their_familiar_order(self):
        from src.web.sources import source_names

        assert source_names()[:4] == ("events", "weather", "birthdays", "air_quality")

    def test_new_fetcher_appears_without_web_layer_edits(self, synthetic_source):
        from src.web.sources import is_known_source, source_names

        assert synthetic_source in source_names()
        assert is_known_source(synthetic_source)

    def test_new_fetcher_sorts_after_the_builtins(self, synthetic_source):
        from src.web.sources import source_names

        names = source_names()
        assert names[:4] == ("events", "weather", "birthdays", "air_quality")
        assert names[-1] == synthetic_source

    def test_unregistered_source_is_still_rejected(self):
        from src.web.sources import is_known_source

        assert not is_known_source("not_a_source")
        assert not is_known_source("")

    def test_new_fetcher_is_accepted_by_reset_breaker(self, client, synthetic_source):
        headers = _csrf_headers(client)
        resp = client.post(
            "/api/reset-breaker",
            data=json.dumps({"source": synthetic_source}),
            content_type="application/json",
            headers=headers,
        )
        assert resp.status_code == 200
        assert json.loads(resp.data)["ok"] is True

    def test_new_fetcher_is_accepted_by_clear_cache(self, client, synthetic_source):
        headers = _csrf_headers(client)
        resp = client.post(
            "/api/clear-cache",
            data=json.dumps({"source": synthetic_source}),
            content_type="application/json",
            headers=headers,
        )
        assert resp.status_code == 200
        assert json.loads(resp.data)["ok"] is True

    def test_new_fetcher_appears_in_api_status(self, client, synthetic_source):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert synthetic_source in json.loads(resp.data)["sources"]

    def test_ttls_come_from_the_registry(self, synthetic_source):
        """A plugin's own TTL, not read_cache_ages' 60-minute fallback."""
        from src.config import Config
        from src.web.sources import source_ttls

        ttls = source_ttls(Config())
        assert ttls[synthetic_source] == 60  # the synthetic fetcher declares 60

    def test_every_registered_source_has_a_ttl(self, synthetic_source):
        from src.config import Config
        from src.fetchers.registry import registered_names
        from src.web.sources import source_ttls

        assert set(source_ttls(Config())) == set(registered_names())

    def test_builtin_ttls_match_the_config(self):
        from src.config import Config
        from src.web.sources import source_ttls

        cfg = Config()
        cfg.cache.weather_ttl_minutes = 123
        cfg.cache.events_ttl_minutes = 456
        ttls = source_ttls(cfg)
        assert ttls["weather"] == 123
        assert ttls["events"] == 456

    def test_a_plugin_with_a_distinct_ttl_is_reported_with_it(self, client):
        """The status page must not call a source stale that the pipeline calls fresh."""
        from src.fetchers.registry import Fetcher, register_fetcher, unregister_fetcher

        register_fetcher(
            Fetcher(
                name="slow_source",
                fetch=lambda ctx: None,
                serialize=lambda v: {},
                deserialize=lambda b: None,
                ttl_minutes=lambda cfg: 10_080,  # a week
                interval_minutes=lambda cfg: 60,
            )
        )
        try:
            from src.config import Config
            from src.web.sources import source_ttls

            assert source_ttls(Config())["slow_source"] == 10_080
        finally:
            unregister_fetcher("slow_source")

    def test_a_plugin_whose_ttl_lookup_raises_is_skipped(self):
        """A broken plugin must not take down the status page."""
        from src.config import Config
        from src.fetchers.registry import Fetcher, register_fetcher, unregister_fetcher
        from src.web.sources import source_ttls

        def _boom(cfg):
            raise AttributeError("no such config section")

        register_fetcher(
            Fetcher(
                name="broken_source",
                fetch=lambda ctx: None,
                serialize=lambda v: {},
                deserialize=lambda b: None,
                ttl_minutes=_boom,
                interval_minutes=lambda cfg: 60,
            )
        )
        try:
            ttls = source_ttls(Config())
            assert "broken_source" not in ttls
            assert "weather" in ttls
        finally:
            unregister_fetcher("broken_source")

    def test_unknown_source_still_rejected_by_actions(self, client):
        headers = _csrf_headers(client)
        resp = client.post(
            "/api/reset-breaker",
            data=json.dumps({"source": "nope"}),
            content_type="application/json",
            headers=headers,
        )
        assert resp.status_code == 400
