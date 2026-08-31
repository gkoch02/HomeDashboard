"""Tests for the P1 web routes — status, image, logs.

Uses Flask's built-in test client with a mocked app config so no real
filesystem paths are required.
"""

import base64
import json
from datetime import date, datetime, timedelta, timezone
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
    application.config["PREVIEW_DIR"] = str(tmp_path / "assets" / "previews")
    (tmp_path / "state").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "assets" / "previews").mkdir(parents=True)
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


def test_image_theme_serves_existing_preview(client, app, tmp_path):
    preview_dir = Path(app.config["PREVIEW_DIR"])
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (preview_dir / "theme_monthly.png").write_bytes(png_bytes)
    resp = client.get("/image/theme/monthly")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    # Theme previews are cacheable (max_age=3600).
    assert "max-age=3600" in resp.headers.get("Cache-Control", "")


def test_image_theme_rejects_uppercase_name(client):
    """The allowlist is lowercase-only — uppercase characters must be rejected."""
    resp = client.get("/image/theme/Default")
    assert resp.status_code == 404


def test_image_theme_rejects_special_chars(client):
    """Hyphens and dots are not in the [a-z0-9_] allowlist."""
    for name in ("foo-bar", "foo.bar", "foo bar"):
        resp = client.get(f"/image/theme/{name}")
        assert resp.status_code in (404, 400), f"Should reject {name!r}"


def test_image_theme_rejects_encoded_path_traversal(client, app, tmp_path):
    """URL-encoded traversal segments (..%2F) must not escape PREVIEW_DIR.

    The literal `..` form is covered by test_image_theme_rejects_path_traversal;
    this case ensures Werkzeug normalization + the safe-name regex together
    reject percent-encoded variants before they reach the filesystem.
    """
    # Drop a real PNG well outside PREVIEW_DIR.  If the route ever resolved
    # `..%2Fsibling` to that file, this test would surface it as a 200.
    sibling_png = tmp_path / "theme_sibling.png"
    sibling_png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    for encoded in ("..%2Fsibling", "%2E%2E%2Fsibling", "..%5Csibling"):
        resp = client.get(f"/image/theme/{encoded}")
        assert resp.status_code in (404, 400), (
            f"Encoded traversal {encoded!r} returned {resp.status_code}"
        )


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


def test_api_logs_invalid_lines_falls_back_to_default(client, app):
    """Non-integer ?lines= should be coerced to the default (100) — covers lines 23-24."""
    output_dir = Path(app.config["OUTPUT_DIR"])
    (output_dir / "dashboard.log").write_text("\n".join(f"line {i}" for i in range(150)))
    resp = client.get("/api/logs?lines=not-a-number")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    # Default _DEFAULT_LINES is 100
    assert len(data["lines"]) == 100


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


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


def _write_success(app, ts):
    Path(app.config["OUTPUT_DIR"], "last_success.txt").write_text(ts)


def _write_error(app, ts):
    Path(app.config["OUTPUT_DIR"], "last_error.txt").write_text(
        json.dumps({"timestamp": ts, "exception_type": "RuntimeError", "message": "boom"})
    )


def test_health_no_success_marker_is_unhealthy(client):
    resp = client.get("/api/health")
    assert resp.status_code == 503
    data = json.loads(resp.data)
    assert data["healthy"] is False
    assert data["last_success"] is None


def test_health_with_success_marker_is_healthy(app, client):
    _write_success(app, "2026-06-09T12:00:00+00:00")
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["healthy"] is True
    assert data["current_error"] is None


def test_health_error_newer_than_success_is_unhealthy(app, client):
    _write_success(app, "2026-06-09T12:00:00+00:00")
    _write_error(app, "2026-06-09T13:00:00+00:00")
    resp = client.get("/api/health")
    assert resp.status_code == 503
    data = json.loads(resp.data)
    assert data["healthy"] is False
    assert data["current_error"]["exception_type"] == "RuntimeError"


def test_health_error_older_than_success_is_healthy(app, client):
    _write_success(app, "2026-06-09T13:00:00+00:00")
    _write_error(app, "2026-06-09T12:00:00+00:00")
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_health_max_age_exceeded_is_unhealthy(app, client, monkeypatch):
    monkeypatch.setattr("src.web.routes.status.is_quiet_hours_now", lambda *a: False)
    _write_success(app, "2026-06-09T12:00:00+00:00")  # long past
    resp = client.get("/api/health?max_age=600")
    assert resp.status_code == 503


def test_health_max_age_skipped_during_quiet_hours(app, client, monkeypatch):
    monkeypatch.setattr("src.web.routes.status.is_quiet_hours_now", lambda *a: True)
    _write_success(app, "2026-06-09T12:00:00+00:00")
    resp = client.get("/api/health?max_age=600")
    assert resp.status_code == 200


def test_health_max_age_satisfied_is_healthy(app, client, monkeypatch):
    from src._time import now_utc

    monkeypatch.setattr("src.web.routes.status.is_quiet_hours_now", lambda *a: False)
    _write_success(app, now_utc().isoformat())
    resp = client.get("/api/health?max_age=600")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Integrations panel — calendar backend awareness (#214)
# ---------------------------------------------------------------------------


def _integrations_for(tmp_path, yaml_text: str) -> dict[str, dict]:
    """Build the integrations panel for a config, keyed by row name."""
    from src.config import load_config
    from src.web.routes.status import _build_integrations

    cfg_path = tmp_path / "integrations.yaml"
    cfg_path.write_text(yaml_text)
    rows = _build_integrations(load_config(str(cfg_path)))
    return {row["name"]: row for row in rows}


_CALDAV_YAML = """
google:
  caldav_url: "https://cloud.example.com/remote.php/dav"
  caldav_username: "alice"
  caldav_password_file: "/etc/dashboard/caldav.pass"
"""

_ICS_YAML = """
google:
  ical_url: "https://example.com/feed.ics"
"""

_GOOGLE_YAML = """
google:
  calendar_id: "team@example.com"
"""


class TestIntegrationsCalendarBackend:
    def test_caldav_reports_caldav_as_the_active_backend(self, tmp_path):
        rows = _integrations_for(tmp_path, _CALDAV_YAML)
        assert "Calendar (CalDAV)" in rows
        assert rows["Calendar (CalDAV)"]["status"] == "ok"
        assert "cloud.example.com" in rows["Calendar (CalDAV)"]["detail"]

    def test_caldav_suppresses_the_google_service_account_row(self, tmp_path):
        rows = _integrations_for(tmp_path, _CALDAV_YAML)
        assert "Google service account" not in rows

    def test_caldav_install_raises_no_warnings(self, tmp_path):
        """The whole point of #214: a healthy CalDAV install looks healthy."""
        rows = _integrations_for(tmp_path, _CALDAV_YAML)
        calendar_rows = {n: r for n, r in rows.items() if n.startswith("Calendar")}
        assert len(calendar_rows) == 1
        assert all(r["status"] == "ok" for r in calendar_rows.values())

    def test_caldav_detail_names_the_specific_calendar_when_set(self, tmp_path):
        rows = _integrations_for(
            tmp_path,
            _CALDAV_YAML + '  caldav_calendar_url: "https://cloud.example.com/cal/home"\n',
        )
        assert "cal/home" in rows["Calendar (CalDAV)"]["detail"]

    def test_caldav_detail_names_the_user(self, tmp_path):
        rows = _integrations_for(tmp_path, _CALDAV_YAML)
        assert "alice" in rows["Calendar (CalDAV)"]["detail"]

    def test_caldav_wins_over_ics_matching_fetch_dispatch(self, tmp_path):
        rows = _integrations_for(
            tmp_path,
            """
google:
  caldav_url: "https://cloud.example.com/remote.php/dav"
  caldav_username: "alice"
  caldav_password_file: "/etc/dashboard/caldav.pass"
  ical_url: "https://example.com/feed.ics"
""",
        )
        assert "Calendar (CalDAV)" in rows
        assert "Calendar (ICS)" not in rows

    def test_ics_reports_ics_and_suppresses_service_account(self, tmp_path):
        rows = _integrations_for(tmp_path, _ICS_YAML)
        assert rows["Calendar (ICS)"]["status"] == "ok"
        assert "feed.ics" in rows["Calendar (ICS)"]["detail"]
        assert "Google service account" not in rows

    def test_ics_detail_counts_additional_feeds(self, tmp_path):
        rows = _integrations_for(
            tmp_path,
            _ICS_YAML
            + '  additional_ical_urls:\n    - "https://example.com/b.ics"\n'
            + '    - "https://example.com/c.ics"\n',
        )
        assert "+2 additional feeds" in rows["Calendar (ICS)"]["detail"]

    def test_google_api_path_still_reports_the_service_account(self, tmp_path):
        rows = _integrations_for(tmp_path, _GOOGLE_YAML)
        assert "Google service account" in rows
        assert rows["Calendar (Google API)"]["status"] == "ok"
        assert "team@example.com" in rows["Calendar (Google API)"]["detail"]

    def test_google_api_default_calendar_id_still_warns(self, tmp_path):
        rows = _integrations_for(tmp_path, "google:\n  calendar_id: primary\n")
        assert rows["Calendar (Google API)"]["status"] == "warn"

    def test_contacts_birthdays_keep_the_service_account_row_on_caldav(self, tmp_path):
        """The People API needs the service account whatever the calendar backend."""
        rows = _integrations_for(
            tmp_path,
            _CALDAV_YAML + "\nbirthdays:\n  source: contacts\n",
        )
        assert "Google service account" in rows
        assert "Calendar (CalDAV)" in rows

    def test_unrelated_rows_are_unchanged_across_backends(self, tmp_path):
        for yaml_text in (_CALDAV_YAML, _ICS_YAML, _GOOGLE_YAML):
            rows = _integrations_for(tmp_path, yaml_text)
            assert "OpenWeather" in rows
            assert "Birthdays source" in rows
            assert "PurpleAir" in rows


# ---------------------------------------------------------------------------
# One Call health on the status page (#223)
# ---------------------------------------------------------------------------


def _set_one_call_version(app, version: str) -> None:
    """Repoint the in-memory config, as a config save would."""
    from src.config import load_config

    Path(app.config["APP_CONFIG_PATH"]).write_text(f'weather:\n  one_call_version: "{version}"\n')
    app.config["DASH_CFG"] = load_config(app.config["APP_CONFIG_PATH"])


def _record_one_call(app, outcome: str, version: str = "3.0", status: int | None = 401):
    from src.fetchers.one_call_health import STATE_FILENAME

    payload = {"outcome": outcome, "version": version, "checked_at": "2026-08-19T12:00:00+00:00"}
    if outcome == "auth_failed":
        payload["http_status"] = status
        payload["message"] = f"One Call {version} returned {status} — check one_call_version."
    path = Path(app.config["STATE_DIR"]) / STATE_FILENAME
    path.write_text(json.dumps(payload))


class TestOneCallStatus:
    def test_no_recorded_state_reports_nothing(self, client):
        data = json.loads(client.get("/api/status").data)
        assert data["one_call"] is None

    def test_healthy_state_reports_nothing(self, app, client):
        _record_one_call(app, "ok")
        data = json.loads(client.get("/api/status").data)
        assert data["one_call"] is None

    def test_transient_failure_reports_nothing(self, app, client):
        """A timeout is not actionable, so it must not colour the status page."""
        _record_one_call(app, "transient", status=None)
        data = json.loads(client.get("/api/status").data)
        assert data["one_call"] is None

    def test_auth_failure_is_surfaced(self, app, client):
        _record_one_call(app, "auth_failed", version="4.0", status=401)
        _set_one_call_version(app, "4.0")
        data = json.loads(client.get("/api/status").data)
        assert data["one_call"] is not None
        assert data["one_call"]["http_status"] == 401
        assert data["one_call"]["version"] == "4.0"

    def test_auth_failure_degrades_overall_health(self, app, client):
        _record_one_call(app, "auth_failed")
        data = json.loads(client.get("/api/status").data)
        assert data["overall"]["status"] in ("degraded", "needs_attention")
        assert any(i["kind"] == "one_call" for i in data["overall"]["issues"])

    def test_auth_failure_message_names_the_config_knob(self, app, client):
        _record_one_call(app, "auth_failed")
        data = json.loads(client.get("/api/status").data)
        assert "one_call_version" in data["one_call"]["message"]

    def test_auth_failure_says_the_rest_of_weather_is_fine(self, app, client):
        _record_one_call(app, "auth_failed")
        data = json.loads(client.get("/api/status").data)
        assert "unaffected" in data["one_call"]["detail"]

    def test_integrations_row_flags_the_failure(self, app, client):
        _record_one_call(app, "auth_failed", version="3.0")
        data = json.loads(client.get("/api/status").data)
        row = next(r for r in data["integrations"] if r["name"].startswith("OpenWeather One Call"))
        assert row["status"] == "warn"

    def test_integrations_row_is_ok_when_healthy(self, client):
        data = json.loads(client.get("/api/status").data)
        row = next(r for r in data["integrations"] if r["name"].startswith("OpenWeather One Call"))
        assert row["status"] == "ok"

    def test_turning_one_call_off_clears_the_banner(self, app, client):
        """Switching off is a documented remedy; the warning must not outlive it.

        The disabled path deliberately records nothing, so the stale
        auth_failed record would otherwise sit there forever telling the user
        to check a setting they already changed.
        """
        _record_one_call(app, "auth_failed", version="3.0")
        _set_one_call_version(app, "off")

        data = json.loads(client.get("/api/status").data)
        assert data["one_call"] is None
        assert not any(i["kind"] == "one_call" for i in data["overall"]["issues"])

    def test_switching_versions_clears_the_stale_banner(self, app, client):
        """A 3.0 failure must not keep naming 3.0 after a switch to 4.0.

        The record only refreshes on the next weather fetch, up to a
        cache.weather_fetch_interval away.
        """
        _record_one_call(app, "auth_failed", version="3.0")
        _set_one_call_version(app, "4.0")

        data = json.loads(client.get("/api/status").data)
        assert data["one_call"] is None

    def test_a_failure_on_the_configured_version_still_shows(self, app, client):
        _record_one_call(app, "auth_failed", version="4.0")
        _set_one_call_version(app, "4.0")

        data = json.loads(client.get("/api/status").data)
        assert data["one_call"] is not None
        assert data["one_call"]["version"] == "4.0"

    def test_no_row_when_one_call_is_turned_off(self, app, client):
        Path(app.config["APP_CONFIG_PATH"]).write_text('weather:\n  one_call_version: "off"\n')
        from src.config import load_config

        app.config["DASH_CFG"] = load_config(app.config["APP_CONFIG_PATH"])
        data = json.loads(client.get("/api/status").data)
        assert not any(r["name"].startswith("OpenWeather One Call") for r in data["integrations"])


# ---------------------------------------------------------------------------
# Configured timezone (#239)
# ---------------------------------------------------------------------------


class TestStatusUsesConfiguredTimezone:
    """The web layer must resolve against cfg.timezone, not the host clock.

    The documented Pi setup runs the system in UTC with a local configured
    zone (see ``_time.day_start_utc``), so reading the host clock reported
    quiet hours 7–8 hours out.
    """

    def _app_with(self, tmp_path, timezone_name):
        web_yaml = tmp_path / "web.yaml"
        web_yaml.write_text("port: 8080\n")
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text(
            f"timezone: {timezone_name}\nschedule:\n  quiet_hours_start: 23\n  quiet_hours_end: 6\n"
        )
        application = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
        application.config["TESTING"] = True
        application.config["STATE_DIR"] = str(tmp_path / "state")
        application.config["OUTPUT_DIR"] = str(tmp_path / "output")
        (tmp_path / "state").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)
        return application

    def _quiet_at(self, tmp_path, timezone_name, instant, monkeypatch):
        monkeypatch.setattr("src.web.routes.status.now_local", lambda tz: instant.astimezone(tz))
        client = self._app_with(tmp_path, timezone_name).test_client()
        return client.get("/api/status").get_json()["quiet_hours_active"]

    def test_same_instant_differs_by_configured_zone(self, tmp_path, monkeypatch):
        instant = datetime(2026, 4, 7, 5, 30, tzinfo=timezone.utc)  # 22:30 PDT
        assert self._quiet_at(tmp_path, "UTC", instant, monkeypatch) is True
        assert self._quiet_at(tmp_path, "America/Los_Angeles", instant, monkeypatch) is False

    def test_health_max_age_exemption_follows_the_configured_zone(self, tmp_path, monkeypatch):
        """An actually-dead renderer must not read healthy outside real quiet hours."""
        instant = datetime(2026, 4, 7, 5, 30, tzinfo=timezone.utc)  # 22:30 PDT
        monkeypatch.setattr("src.web.routes.status.now_local", lambda tz: instant.astimezone(tz))
        application = self._app_with(tmp_path, "America/Los_Angeles")
        marker = Path(application.config["OUTPUT_DIR"]) / "last_success.txt"
        marker.write_text((instant - timedelta(hours=6)).isoformat() + "\n")

        resp = application.test_client().get("/api/health?max_age=600")

        assert resp.status_code == 503
        assert resp.get_json()["healthy"] is False


# ---------------------------------------------------------------------------
# GET /api/status is a read (#238)
# ---------------------------------------------------------------------------


class TestStatusDoesNotPickTheTheme:
    """Reporting the current theme must not decide it.

    ``resolve_theme_name`` on a random cadence *draws* a theme and writes
    ``state/random_theme_state.json``. The page polls every 30 seconds and the
    renderer runs every 5 minutes, so the web process was winning the race to
    pick the day's theme at nearly every rollover.
    """

    def _app_with_theme(self, tmp_path, theme):
        web_yaml = tmp_path / "web.yaml"
        web_yaml.write_text("port: 8080\n")
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text(f"theme: {theme}\nstate_dir: {tmp_path / 'state'}\n")
        application = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
        application.config["TESTING"] = True
        application.config["STATE_DIR"] = str(tmp_path / "state")
        application.config["OUTPUT_DIR"] = str(tmp_path / "output")
        (tmp_path / "state").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)
        return application

    @pytest.mark.parametrize("theme", ["random", "random_daily", "random_hourly"])
    def test_status_writes_no_theme_state(self, tmp_path, theme):
        client = self._app_with_theme(tmp_path, theme).test_client()

        assert client.get("/api/status").status_code == 200

        written = [p.name for p in (tmp_path / "state").iterdir()]
        assert written == []

    @pytest.mark.parametrize("theme", ["random_daily", "random_hourly"])
    def test_status_reports_no_theme_until_the_renderer_picks_one(self, tmp_path, theme):
        client = self._app_with_theme(tmp_path, theme).test_client()

        body = client.get("/api/status").get_json()

        assert body["current_theme"] is None
        assert body["theme_info"]["mode"] == "randomized"
        assert body["theme_info"]["effective_theme"] is None
        assert "has not been drawn yet" in body["theme_info"]["detail"]

    def test_status_reports_the_pick_the_renderer_made(self, tmp_path):
        application = self._app_with_theme(tmp_path, "random_daily")
        today = date.today().isoformat()
        (tmp_path / "state" / "random_theme_state.json").write_text(
            json.dumps({"date": today, "theme": "terminal"})
        )

        body = application.test_client().get("/api/status").get_json()

        assert body["current_theme"] == "terminal"
        assert body["theme_info"]["effective_theme"] == "terminal"

    def test_a_fixed_theme_is_still_reported_verbatim(self, tmp_path):
        body = self._app_with_theme(tmp_path, "terminal").test_client()
        assert body.get("/api/status").get_json()["current_theme"] == "terminal"
