"""Tests for GET /api/dashboard — the cached snapshot served to native clients."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.data.models import Birthday, CalendarEvent, WeatherData
from src.fetchers.cache import save_source
from src.web.app import create_app
from src.web.routes.dashboard import SCHEMA_VERSION

ZONE = "America/New_York"


@pytest.fixture()
def app(tmp_path):
    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text("port: 8080\n")
    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text(
        f'timezone: "{ZONE}"\n'
        "filters:\n"
        '  exclude_keywords: ["secret"]\n'
        "birthdays:\n"
        '  source: "file"\n'
    )
    application = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
    application.config["TESTING"] = True
    application.config["STATE_DIR"] = str(tmp_path / "state")
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def _now():
    return datetime.now(timezone.utc)


def _weather():
    return WeatherData(
        current_temp=61.0,
        current_icon="02d",
        current_description="few clouds",
        high=66.0,
        low=50.0,
        humidity=48,
    )


def test_empty_cache_reports_every_enabled_source_as_unknown(client):
    body = client.get("/api/dashboard").get_json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["timezone"] == ZONE
    assert body["sources"]["events"] == {"fetched_at": None, "staleness": "unknown", "data": None}
    assert body["sources"]["weather"]["data"] is None


def test_disabled_source_is_omitted(client):
    # PurpleAir is on only with an api_key and sensor_id; the fixture sets neither.
    assert "air_quality" not in client.get("/api/dashboard").get_json()["sources"]


def test_fresh_sources_carry_their_data(app, client):
    state = app.config["STATE_DIR"]
    save_source("weather", _weather(), _now(), state)
    save_source("birthdays", [Birthday("Ada", date(1990, 12, 10), 36)], _now(), state)

    sources = client.get("/api/dashboard").get_json()["sources"]
    assert sources["weather"]["staleness"] == "fresh"
    assert sources["weather"]["data"]["current_temp"] == 61.0
    assert sources["birthdays"]["data"] == [{"name": "Ada", "date": "1990-12-10", "age": 36}]


def test_event_times_carry_the_configured_offset(app, client):
    start = datetime(2026, 10, 14, 9, 30)  # naive local, as fetchers store it
    event = CalendarEvent("Dentist", start, start + timedelta(hours=1))
    save_source("events", [event], _now(), app.config["STATE_DIR"])

    (sent,) = client.get("/api/dashboard").get_json()["sources"]["events"]["data"]
    sent_start = datetime.fromisoformat(sent["start"])
    assert sent_start.utcoffset() is not None
    assert sent_start == start.replace(tzinfo=ZoneInfo(ZONE))


def test_events_pass_through_the_configured_filters(app, client):
    start = datetime(2026, 10, 14, 9, 30)
    events = [
        CalendarEvent("Dentist", start, start + timedelta(hours=1)),
        CalendarEvent("Secret party", start, start + timedelta(hours=2)),
    ]
    save_source("events", events, _now(), app.config["STATE_DIR"])

    sent = client.get("/api/dashboard").get_json()["sources"]["events"]["data"]
    assert [e["summary"] for e in sent] == ["Dentist"]


def test_expired_source_sends_no_data(app, client):
    long_ago = _now() - timedelta(days=30)
    save_source("weather", _weather(), long_ago, app.config["STATE_DIR"])

    weather = client.get("/api/dashboard").get_json()["sources"]["weather"]
    assert weather["staleness"] == "expired"
    assert weather["data"] is None
    assert weather["fetched_at"] is not None


def test_quote_is_included(client):
    quote = client.get("/api/dashboard").get_json()["quote"]
    assert quote["text"] and quote["author"]


def test_route_requires_auth_when_configured(tmp_path):
    from src.web.auth import hash_password

    web_yaml = tmp_path / "web.yaml"
    web_yaml.write_text(f'auth:\n  username: "admin"\n  password_hash: "{hash_password("pw")}"\n')
    app = create_app(web_config_path=str(web_yaml), app_config_path=None)
    assert app.test_client().get("/api/dashboard").status_code == 401


def test_local_zone_events_take_the_offset_of_their_own_date(tmp_path, monkeypatch):
    # A fixed-offset "local" zone taken in October would stamp -04:00 on a November event.
    import time

    monkeypatch.setenv("TZ", ZONE)
    time.tzset()
    try:
        web_yaml = tmp_path / "web.yaml"
        web_yaml.write_text("port: 8080\n")
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text('timezone: "local"\n')
        app = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
        app.config["STATE_DIR"] = str(tmp_path / "state")
        october = datetime(2026, 10, 14, 9, 0)
        november = datetime(2026, 11, 2, 9, 0)
        events = [
            CalendarEvent("Before", october, october + timedelta(hours=1)),
            CalendarEvent("After", november, november + timedelta(hours=1)),
        ]
        save_source("events", events, _now(), app.config["STATE_DIR"])

        sent = app.test_client().get("/api/dashboard").get_json()["sources"]["events"]["data"]
        offsets = {e["summary"]: datetime.fromisoformat(e["start"]).utcoffset() for e in sent}
        assert offsets == {"Before": timedelta(hours=-4), "After": timedelta(hours=-5)}
    finally:
        monkeypatch.undo()
        time.tzset()


def test_units_follow_the_cached_weather_not_the_config(app, client):
    weather = _weather()
    weather.units = "metric"  # fetched before config switched to imperial
    save_source("weather", weather, _now(), app.config["STATE_DIR"])
    assert client.get("/api/dashboard").get_json()["units"] == "metric"


def test_units_fall_back_to_config_without_weather(client):
    assert client.get("/api/dashboard").get_json()["units"] == "imperial"


def test_moon_block_matches_the_panel_math(client):
    from src.render.moon import moon_illumination, moon_phase_fraction, moon_phase_name

    body = client.get("/api/dashboard").get_json()
    moon = body["moon"]
    today = datetime.fromisoformat(body["generated_at"]).date()  # the request's own day
    assert moon["phase_name"] == moon_phase_name(today)
    assert [d["date"] for d in moon["days"]] == [
        (today + timedelta(days=n)).isoformat() for n in range(-3, 4)
    ]
    centre = moon["days"][3]
    assert centre["fraction"] == round(moon_phase_fraction(today), 4)
    assert centre["illumination"] == round(moon_illumination(today), 1)
    assert moon["next"]["kind"] in {"full", "new"}
    assert moon["quote"]["text"]


def test_moon_rise_and_set_need_coordinates(tmp_path, client):
    assert client.get("/api/dashboard").get_json()["moon"]["rise"] is None  # (0, 0): unset

    web_yaml = tmp_path / "web2.yaml"
    web_yaml.write_text("port: 8080\n")
    cfg_yaml = tmp_path / "config2.yaml"
    cfg_yaml.write_text(f'timezone: "{ZONE}"\nweather:\n  latitude: 40.71\n  longitude: -74.0\n')
    located = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
    located.config["STATE_DIR"] = str(tmp_path / "state")
    moon = located.test_client().get("/api/dashboard").get_json()["moon"]
    times = [datetime.fromisoformat(t) for t in (moon["rise"], moon["set"]) if t]
    assert times, "a located dashboard has a moonrise or a moonset on most days"
    assert all(t.utcoffset() is not None for t in times)


def test_local_zone_moon_times_take_the_offset_of_their_own_date(tmp_path, monkeypatch):
    # On the spring-forward day a fixed offset taken at 01:00 EST would stamp every later
    # moonrise or moonset -05:00; New York's rules give -04:00 from 03:00.
    import time
    from zoneinfo import ZoneInfo as Zone

    from src.astronomy import moon_times

    monkeypatch.setenv("TZ", ZONE)
    time.tzset()
    try:
        web_yaml = tmp_path / "web.yaml"
        web_yaml.write_text("port: 8080\n")
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text('timezone: "local"\nweather:\n  latitude: 40.71\n  longitude: -74.0\n')
        app = create_app(web_config_path=str(web_yaml), app_config_path=str(cfg_yaml))
        app.config["STATE_DIR"] = str(tmp_path / "state")
        spring = datetime(2026, 3, 8, 1, 0, tzinfo=Zone(ZONE))
        monkeypatch.setattr(
            "src.web.routes.dashboard.now_local", lambda tz=None: spring.astimezone(tz)
        )

        body = app.test_client().get("/api/dashboard").get_json()
        assert body["timezone"] == ZONE

        expected = moon_times(spring.date(), 40.71, -74.0, tz=Zone(ZONE))
        for key, value in (("rise", expected.rise), ("set", expected.set)):
            sent = body["moon"][key]
            if value is None:
                assert sent is None
            else:
                assert datetime.fromisoformat(sent) == value
                assert (
                    datetime.fromisoformat(sent).utcoffset()
                    == value.astimezone(Zone(ZONE)).utcoffset()
                )
    finally:
        monkeypatch.undo()
        time.tzset()
