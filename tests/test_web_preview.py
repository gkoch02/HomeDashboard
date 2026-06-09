"""End-to-end tests for the live theme preview endpoint."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.web.app import create_app


@pytest.fixture
def client(tmp_path):
    """Spin up the Flask app with the example config so all blueprints load."""
    config_yaml = tmp_path / "config.yaml"
    # Minimal valid config — defaults populate everything else.
    config_yaml.write_text(
        "title: 'Preview Test'\n"
        "theme: agenda\n"
        "timezone: 'UTC'\n"
        "weather:\n"
        "  latitude: 0.0\n"
        "  longitude: 0.0\n"
    )
    app = create_app(app_config_path=str(config_yaml))
    return app.test_client()


def _csrf_token(client) -> str:
    """Initialise the session and return the CSRF token Flask issues for it."""
    client.get("/")
    with client.session_transaction() as sess:
        return sess["csrf_token"]


def _post_with_csrf(client, path: str, payload: dict):
    """POST helper that wires up the X-CSRF-Token header automatically."""
    token = _csrf_token(client)
    return client.post(path, json=payload, headers={"X-CSRF-Token": token})


class TestPreviewEndpoint:
    def test_returns_png_for_valid_theme(self, client):
        resp = _post_with_csrf(client, "/api/preview", {"theme": "agenda"})
        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
        # PNG signature is 89 50 4E 47 0D 0A 1A 0A — confirm we got a real image.
        body = resp.get_data()
        assert body.startswith(b"\x89PNG\r\n\x1a\n")
        # And that PIL can re-decode it.
        Image.open(io.BytesIO(body)).verify()

    def test_rejects_missing_theme_param(self, client):
        resp = _post_with_csrf(client, "/api/preview", {})
        assert resp.status_code == 400
        assert "theme" in resp.get_json()["error"]

    def test_rejects_unknown_theme(self, client):
        resp = _post_with_csrf(client, "/api/preview", {"theme": "__never__"})
        assert resp.status_code == 400
        assert "Unknown theme" in resp.get_json()["error"]

    def test_rejects_pseudo_theme(self, client):
        resp = _post_with_csrf(client, "/api/preview", {"theme": "random"})
        assert resp.status_code == 400
        assert "Pseudo-themes" in resp.get_json()["error"]

    def test_render_failure_returns_500(self, client, monkeypatch):
        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr("src.web.routes.preview.render_dashboard", _boom)
        resp = _post_with_csrf(client, "/api/preview", {"theme": "agenda"})
        assert resp.status_code == 500
        assert "Render failed" in resp.get_json()["error"]


class TestSchemaEndpoint:
    def test_returns_schema_with_values(self, client):
        resp = client.get("/api/config/schema")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["schema_version"] == 5
        assert any(s["name"] == "weather" for s in body["sections"])

    def test_schema_response_omits_secret_plaintext(self, client):
        resp = client.get("/api/config/schema")
        body = resp.get_json()
        for section in body["sections"]:
            for field in section["fields"]:
                if field["secret"]:
                    assert "value" not in field, f"secret field {field['path']!r} leaked plaintext"

    def test_schema_response_preserves_non_secret_underscored_values(self, client):
        resp = client.get("/api/config/schema")
        body = resp.get_json()
        google_fields = next(s for s in body["sections"] if s["name"] == "google")["fields"]
        calendar_id = next(f for f in google_fields if f["path"] == "google.calendar_id")
        assert calendar_id["value"] == "primary"


class TestPatchPreview:
    def test_patch_must_be_a_dict(self, client):
        resp = _post_with_csrf(client, "/api/preview", {"theme": "agenda", "patch": "nope"})
        assert resp.status_code == 400
        assert "patch" in resp.get_json()["error"]

    def test_valid_patch_renders_png_without_persisting(self, client, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        before = config_yaml.read_text()
        resp = _post_with_csrf(
            client,
            "/api/preview",
            {"theme": "agenda", "patch": {"title": "Candidate Title"}},
        )
        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
        assert resp.get_data().startswith(b"\x89PNG\r\n\x1a\n")
        # Nothing written: the YAML on disk is untouched.
        assert config_yaml.read_text() == before

    def test_patch_changes_the_rendered_output(self, client):
        base = _post_with_csrf(client, "/api/preview", {"theme": "agenda"}).get_data()
        patched = _post_with_csrf(
            client,
            "/api/preview",
            {"theme": "agenda", "patch": {"title": "A Very Different Title"}},
        ).get_data()
        assert base != patched

    def test_invalid_patch_returns_validation_errors(self, client):
        resp = _post_with_csrf(
            client,
            "/api/preview",
            {"theme": "agenda", "patch": {"schedule.quiet_hours_start": 99}},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "Config patch failed validation."
        assert any("quiet_hours_start" in e["field"] for e in data["validation_errors"])

    def test_empty_patch_behaves_like_no_patch(self, client):
        resp = _post_with_csrf(client, "/api/preview", {"theme": "agenda", "patch": {}})
        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
