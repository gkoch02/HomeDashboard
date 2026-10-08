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

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ({}, "theme"),
            ({"theme": "__never__"}, "Unknown theme"),
            ({"theme": "random"}, "Pseudo-themes"),
        ],
        ids=["missing-theme", "unknown-theme", "pseudo-theme"],
    )
    def test_rejects_unrenderable_theme(self, client, payload, message):
        """A missing, unregistered or pseudo theme name is a 400 naming the problem."""
        resp = _post_with_csrf(client, "/api/preview", payload)
        assert resp.status_code == 400
        assert message in resp.get_json()["error"]

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


class TestPreviewMatchesTheRenderer:
    """The preview must render what the renderer will (#240).

    It used to pass a subset of the renderer's arguments, so ``photo``
    previewed with no photo, ``countdown`` with no events, a custom quote store
    was ignored, and the ``(0.0, 0.0)`` unset-coordinates sentinel was passed
    through raw — making the sun/moon themes compute geometry for the Gulf of
    Guinea instead of showing their unset-coordinates fallback.
    """

    def _client(self, tmp_path, config_body):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(config_body)
        return create_app(app_config_path=str(config_yaml)).test_client()

    def _render_kwargs(self, client, theme, monkeypatch):
        captured = {}

        def fake_render(data, config, **kwargs):
            captured.update(kwargs)
            return Image.new("1", (800, 480), 1)

        monkeypatch.setattr("src.web.routes.preview.render_dashboard", fake_render)
        resp = _post_with_csrf(client, "/api/preview", {"theme": theme})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        return captured

    def test_photo_theme_gets_the_configured_photo_path(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, "photo:\n  path: /photos/hero.jpg\n")
        kwargs = self._render_kwargs(client, "photo", monkeypatch)
        assert kwargs["theme"].style.photo_path == "/photos/hero.jpg"

    def test_countdown_theme_gets_the_configured_events(self, tmp_path, monkeypatch):
        client = self._client(
            tmp_path,
            "countdown:\n  events:\n    - name: Trip\n      date: '2026-12-01'\n",
        )
        kwargs = self._render_kwargs(client, "countdown", monkeypatch)
        assert [e.name for e in kwargs["countdown_events"]] == ["Trip"]

    def test_custom_quote_store_is_forwarded(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, "quotes:\n  path: /etc/quotes.json\n")
        kwargs = self._render_kwargs(client, "qotd", monkeypatch)
        assert kwargs["quotes_path"] == "/etc/quotes.json"

    @pytest.mark.parametrize(
        ("lat", "lon", "expected"),
        [(0.0, 0.0, (None, None)), (37.8, -122.4, (37.8, -122.4))],
        ids=["unset-origin-is-not-gulf-of-guinea", "configured-coordinates-pass-through"],
    )
    def test_coordinates_reach_the_render(self, tmp_path, monkeypatch, lat, lon, expected):
        """``(0.0, 0.0)`` means unset and is forwarded as ``None``; real coordinates
        reach the render unchanged."""
        client = self._client(tmp_path, f"weather:\n  latitude: {lat}\n  longitude: {lon}\n")
        kwargs = self._render_kwargs(client, "astronomy", monkeypatch)
        assert (kwargs["latitude"], kwargs["longitude"]) == expected

    def test_preview_clock_is_in_the_configured_zone(self, tmp_path, monkeypatch):
        """A naive clock would print the sun times computed from the coordinates as UTC."""
        client = self._client(tmp_path, "timezone: America/Chicago\n")
        captured = {}

        def fake_render(data, config, **kwargs):
            captured["data"] = data
            return Image.new("1", (800, 480), 1)

        monkeypatch.setattr("src.web.routes.preview.render_dashboard", fake_render)
        resp = _post_with_csrf(client, "/api/preview", {"theme": "astronomy"})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert str(captured["data"].fetched_at.tzinfo) == "America/Chicago"

    def test_preview_still_persists_no_pressure_history(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, f"state_dir: {tmp_path / 'state'}\n")
        kwargs = self._render_kwargs(client, "weatherglass", monkeypatch)
        assert kwargs["state_dir"] is None

    def test_a_patch_is_previewed_through_the_same_assembly(self, tmp_path, monkeypatch):
        """The candidate config's values must reach the render, not the saved ones."""
        client = self._client(tmp_path, "weather:\n  latitude: 0.0\n  longitude: 0.0\n")
        captured = {}

        def fake_render(data, config, **kwargs):
            captured.update(kwargs)
            return Image.new("1", (800, 480), 1)

        monkeypatch.setattr("src.web.routes.preview.render_dashboard", fake_render)
        resp = _post_with_csrf(
            client,
            "/api/preview",
            {
                "theme": "astronomy",
                "patch": {"weather.latitude": 37.8, "weather.longitude": -122.4},
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert (captured["latitude"], captured["longitude"]) == (37.8, -122.4)


class TestPreviewRealRenderStillWorks:
    def test_photo_theme_renders_end_to_end_without_a_photo_file(self, tmp_path):
        """A path that does not exist must not 500 the preview."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(f"photo:\n  path: {tmp_path / 'missing.jpg'}\n")
        client = create_app(app_config_path=str(config_yaml)).test_client()

        resp = _post_with_csrf(client, "/api/preview", {"theme": "photo"})

        assert resp.status_code == 200
        assert Image.open(io.BytesIO(resp.data)).size == (800, 480)

    def test_countdown_theme_renders_end_to_end_with_events(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "countdown:\n  events:\n    - name: Trip\n      date: '2099-12-01'\n"
        )
        client = create_app(app_config_path=str(config_yaml)).test_client()

        resp = _post_with_csrf(client, "/api/preview", {"theme": "countdown"})

        assert resp.status_code == 200
        assert Image.open(io.BytesIO(resp.data)).size == (800, 480)
