"""Tests for src/web/csrf.py

Covers: get_csrf_token (mints new token, reuses existing), csrf_protect
(passes with matching header, aborts 403 on mismatch/missing).
"""

from __future__ import annotations

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
# get_csrf_token
# ---------------------------------------------------------------------------


class TestGetCsrfToken:
    def test_token_minted_on_first_request(self, app):
        with app.test_request_context("/"):
            from src.web.csrf import get_csrf_token

            token = get_csrf_token()
            assert token  # non-empty
            assert len(token) > 10

    def test_token_reused_across_calls(self, app):
        with app.test_request_context("/"):
            from src.web.csrf import get_csrf_token

            t1 = get_csrf_token()
            t2 = get_csrf_token()
            assert t1 == t2

    def test_different_sessions_get_different_tokens(self, client):
        # Two separate requests → separate sessions → separate tokens
        client.get("/")
        with client.session_transaction() as s1:
            tok1 = s1.get("csrf_token")

        # Re-create a fresh client (new session)
        import pathlib
        import tempfile

        from src.web.app import create_app

        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            (p / "web.yaml").write_text("port: 8080\n")
            (p / "config.yaml").write_text("")
            app2 = create_app(str(p / "web.yaml"), str(p / "config.yaml"))
            app2.config["TESTING"] = True
            (p / "state").mkdir()
            (p / "output").mkdir()
            app2.config["STATE_DIR"] = str(p / "state")
            app2.config["OUTPUT_DIR"] = str(p / "output")
            c2 = app2.test_client()
            c2.get("/")
            with c2.session_transaction() as s2:
                tok2 = s2.get("csrf_token")

        # These should be different (probabilistically certain with 32-byte tokens)
        assert tok1 != tok2


# ---------------------------------------------------------------------------
# csrf_protect (via mutating endpoints)
# ---------------------------------------------------------------------------


class TestCsrfProtect:
    def _get_token(self, client) -> str:
        client.get("/")
        with client.session_transaction() as sess:
            return sess["csrf_token"]

    def test_post_with_valid_token_succeeds(self, client):
        token = self._get_token(client)
        resp = client.post("/api/trigger-refresh", headers={"X-CSRF-Token": token})
        assert resp.status_code == 200

    def test_post_without_token_returns_403(self, client):
        self._get_token(client)  # ensure session initialised
        resp = client.post("/api/trigger-refresh")
        assert resp.status_code == 403

    def test_post_with_wrong_token_returns_403(self, client):
        self._get_token(client)
        resp = client.post("/api/trigger-refresh", headers={"X-CSRF-Token": "totally-wrong-token"})
        assert resp.status_code == 403

    def test_get_request_not_protected(self, client):
        # GET /api/status should not require a CSRF token
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_token_in_session_after_get(self, client):
        client.get("/")
        with client.session_transaction() as sess:
            assert "csrf_token" in sess
