"""Tests for the One Call transport (src/fetchers/weather_onecall.py).

Mocks here dispatch on the request URL rather than on call order.  The older
suite in tests/test_weather_fetcher.py uses a positional
``session.get.side_effect = [current, forecast, alerts]`` list, which pins the
number and order of HTTP calls; that is fine for the 2.5 endpoints, whose call
pattern is fixed, but the One Call path varies by version.  Dispatching on the
URL lets these tests assert things a positional list cannot express — most
usefully, that a given endpoint was *never* requested.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.config import WeatherConfig, _normalise_one_call_version
from src.config_validation import validate_config
from src.fetchers.weather import _fetch_alerts_and_uv, fetch_weather

_V3_SAMPLE = {
    "current": {"uvi": 3.2},
    "alerts": [{"event": "Heat Advisory"}],
}

# Trimmed from the response examples in the One Call API 4.0 documentation.
# Note the `data` array wrapper around what the docs call a single record, and
# that `alerts` holds bare ID strings rather than alert objects.
_V4_CURRENT_SAMPLE = {
    "lat": 51.5,
    "lon": -0.1,
    "timezone": "Europe/London",
    "timezone_offset": 3600,
    "data": [
        {
            "dt": 1777449371,
            "sunrise": 1777437375,
            "sunset": 1777490344,
            "temp": 286.42,
            "feels_like": 285.32,
            "pressure": 1024,
            "humidity": 58,
            "dew_point": 278.34,
            "uvi": 1.55,
            "clouds": 0,
            "visibility": 10000,
            "wind_speed": 8.23,
            "wind_deg": 70,
            "weather": [{"id": 800, "main": "Clear", "description": "sky is clear", "icon": "01d"}],
            "alerts": [
                "8B46C632-DCA7-44D7-8BDF-02445621BAFF",
                "29F58A35-BB91-4A73-9F46-9FC64BDF604F",
            ],
        }
    ],
}

_V4_ALERT_SAMPLE = {
    "id": "8B46C632-DCA7-44D7-8BDF-02445621BAFF",
    "sender_name": "NWS Tulsa (Eastern Oklahoma)",
    "event": "Heat Advisory",
    "start": 1597341600,
    "end": 1597366800,
    "description": "...HEAT ADVISORY REMAINS IN EFFECT...",
}


def _dispatch_session(routes: dict[str, dict], errors: dict[str, Exception] | None = None):
    """Build a mock session whose .get() is routed by URL substring.

    ``routes`` maps a URL fragment to the JSON payload to return; ``errors``
    maps a fragment to an exception raised by ``raise_for_status()``.

    An unmatched URL calls pytest.fail rather than raising AssertionError,
    because the code under test catches Exception by design — an AssertionError
    would be swallowed by the very degradation path these tests exercise, and a
    misrouted request would quietly look like a graceful failure.
    """
    errors = errors or {}

    def _get(url, **_kwargs):
        resp = MagicMock()
        for fragment, exc in errors.items():
            if fragment in url:
                resp.raise_for_status.side_effect = exc
                resp.json.return_value = {}
                return resp
        for fragment, payload in routes.items():
            if fragment in url:
                resp.raise_for_status = MagicMock()
                resp.json.return_value = payload
                return resp
        pytest.fail(f"unexpected request to {url}")

    session = MagicMock()
    session.get.side_effect = _get
    return session


def _urls(session) -> list[str]:
    return [call[0][0] for call in session.get.call_args_list]


class TestVersionRouting:
    def test_v3_hits_the_3_0_endpoint(self):
        session = _dispatch_session({"/data/3.0/onecall": _V3_SAMPLE})

        alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0")

        assert len(_urls(session)) == 1
        assert "/data/3.0/onecall" in _urls(session)[0]
        assert uv == 3.2
        assert [a.event for a in alerts] == ["Heat Advisory"]

    def test_off_makes_no_request_at_all(self):
        session = _dispatch_session({})

        alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "off")

        assert session.get.call_count == 0
        assert (alerts, uv) == ([], None)

    def test_unknown_version_falls_back_to_the_default(self):
        """A config typo must degrade to today's behaviour, not lose the data."""
        session = _dispatch_session({"/data/3.0/onecall": _V3_SAMPLE})

        alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "9.9")

        assert "/data/3.0/onecall" in _urls(session)[0]
        assert uv == 3.2

    def test_default_argument_is_v3(self):
        """tests/test_weather_fetcher.py calls this with two positional args."""
        session = _dispatch_session({"/data/3.0/onecall": _V3_SAMPLE})

        _fetch_alerts_and_uv(session, {"appid": "k"})

        assert "/data/3.0/onecall" in _urls(session)[0]


class TestDegradation:
    def test_http_failure_returns_empty_and_logs_at_debug(self, caplog):
        """An error carrying no HTTP status is transient, and stays at DEBUG.

        The classification lives in src.fetchers.one_call_health, so that is
        where the line is emitted from now. A "401" in an exception's *text* is
        not evidence of a 401 response — only ``exc.response.status_code`` is.
        """
        session = _dispatch_session({}, errors={"/data/3.0/": Exception("401 Unauthorized")})

        with caplog.at_level(logging.DEBUG):
            alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0")

        assert (alerts, uv) == ([], None)
        assert any("alerts/UV fetch skipped" in r.message for r in caplog.records)
        assert not any(r.levelname == "WARNING" for r in caplog.records)

    def test_malformed_payload_returns_empty(self):
        """A list where a dict is expected must not escape the boundary."""
        session = _dispatch_session({"/data/3.0/onecall": ["not", "a", "dict"]})

        assert _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0") == ([], None)

    def test_blank_alert_events_are_dropped(self):
        payload = {"current": {}, "alerts": [{"event": "   "}, {"event": "Flood Watch"}]}
        session = _dispatch_session({"/data/3.0/onecall": payload})

        alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0")

        assert [a.event for a in alerts] == ["Flood Watch"]
        assert uv is None


class TestKnobReachesTheFetch:
    @patch("src.fetchers.weather.requests.Session")
    def test_off_skips_the_onecall_request_end_to_end(self, mock_session_cls):
        """Only the two free 2.5 endpoints are called when One Call is off."""
        session = _dispatch_session(
            {
                "/data/2.5/weather": {
                    "main": {"temp": 42.0, "temp_max": 48.0, "temp_min": 35.0, "humidity": 65},
                    "weather": [{"icon": "02d", "description": "partly cloudy"}],
                },
                "/data/2.5/forecast": {"list": []},
            }
        )
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        cfg = WeatherConfig(api_key="test-key", one_call_version="off")
        result = fetch_weather(cfg)

        assert session.get.call_count == 2
        assert not any("onecall" in u for u in _urls(session))
        assert result.uv_index is None
        assert result.alerts == []

    @patch("src.fetchers.weather.requests.Session")
    def test_v4_reaches_the_fetch_and_populates_uv_and_alerts(self, mock_session_cls):
        session = _dispatch_session(
            {
                "/data/2.5/weather": {
                    "main": {"temp": 42.0, "temp_max": 48.0, "temp_min": 35.0, "humidity": 65},
                    "weather": [{"icon": "02d", "description": "partly cloudy"}],
                },
                "/data/2.5/forecast": {"list": []},
                **_v4_routes(["ID-1"]),
            }
        )
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        cfg = WeatherConfig(api_key="test-key", one_call_version="4.0")
        result = fetch_weather(cfg)

        assert result.uv_index == 1.55
        assert [a.event for a in result.alerts] == ["Event ID-1"]
        assert not any("/data/3.0/" in u for u in _urls(session))


class TestVersionNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("3.0", "3.0"),
            (3.0, "3.0"),  # unquoted YAML float
            (3, "3.0"),  # unquoted YAML int
            (4, "4.0"),
            ("off", "off"),
            (False, "off"),  # unquoted YAML 1.1 boolean
            ("  3.0  ", "3.0"),
            ("nonsense", "nonsense"),  # preserved so validation can name it
            (None, "3.0"),  # "one_call_version:" with nothing after it
            ("", "3.0"),
            ("   ", "3.0"),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert _normalise_one_call_version(raw) == expected

    def test_parsed_from_yaml(self, tmp_path):
        from src.config import load_config

        p = tmp_path / "config.yaml"
        p.write_text("weather:\n  api_key: 'k'\n  one_call_version: 3.0\n")

        assert load_config(str(p)).weather.one_call_version == "3.0"

    def test_defaults_to_v3_when_absent(self, tmp_path):
        from src.config import load_config

        p = tmp_path / "config.yaml"
        p.write_text("weather:\n  api_key: 'k'\n")

        assert load_config(str(p)).weather.one_call_version == "3.0"

    def test_empty_key_defaults_without_warning(self, tmp_path):
        """`one_call_version:` with no value is "unset", not a typo."""
        from src.config import load_config
        from src.config_validation import validate_config

        p = tmp_path / "config.yaml"
        p.write_text("weather:\n  api_key: 'k'\n  one_call_version:\n")

        cfg = load_config(str(p))
        assert cfg.weather.one_call_version == "3.0"

        _errors, warnings = validate_config(cfg)
        assert not [w for w in warnings if w.field == "weather.one_call_version"]


class TestValidation:
    def _warnings_for(self, version):
        from src.config import Config

        cfg = Config()
        cfg.weather = WeatherConfig(api_key="a" * 32, latitude=1.0, one_call_version=version)
        _errors, warnings = validate_config(cfg)
        return [w for w in warnings if w.field == "weather.one_call_version"]

    @pytest.mark.parametrize("version", ["3.0", "4.0", "off"])
    def test_supported_versions_are_silent(self, version):
        assert self._warnings_for(version) == []

    def test_unknown_version_warns_without_erroring(self):
        warnings = self._warnings_for("2.5")

        assert len(warnings) == 1
        assert "2.5" in warnings[0].message


class TestSchema:
    def test_field_is_editable_and_not_secret(self):
        from src.config_schema import editable_field_paths, to_json

        assert "weather.one_call_version" in editable_field_paths()

        field = next(
            f
            for section in to_json()["sections"]
            for f in section["fields"]
            if f["path"] == "weather.one_call_version"
        )
        assert field["type"] == "enum"
        assert field["choices"] == ["3.0", "4.0", "off"]
        assert not field.get("secret")


class TestV4Parsers:
    """The pure dict-in/value-out half of the 4.0 support, tested without HTTP."""

    def test_parses_uv_from_the_data_wrapper(self):
        from src.fetchers.weather_onecall import _v4_parse_uv

        assert _v4_parse_uv(_V4_CURRENT_SAMPLE) == 1.55

    @pytest.mark.parametrize("payload", [{}, {"data": []}, {"data": [{}]}])
    def test_missing_uv_is_none_not_an_error(self, payload):
        from src.fetchers.weather_onecall import _v4_parse_uv

        assert _v4_parse_uv(payload) is None

    def test_parses_alert_ids(self):
        from src.fetchers.weather_onecall import _v4_parse_alert_ids

        assert _v4_parse_alert_ids(_V4_CURRENT_SAMPLE) == [
            "8B46C632-DCA7-44D7-8BDF-02445621BAFF",
            "29F58A35-BB91-4A73-9F46-9FC64BDF604F",
        ]

    @pytest.mark.parametrize(
        "payload", [{}, {"data": []}, {"data": [{}]}, {"data": [{"alerts": []}]}]
    )
    def test_no_alerts_is_an_empty_list(self, payload):
        from src.fetchers.weather_onecall import _v4_parse_alert_ids

        assert _v4_parse_alert_ids(payload) == []

    def test_blank_alert_ids_are_dropped(self):
        from src.fetchers.weather_onecall import _v4_parse_alert_ids

        payload = {"data": [{"alerts": ["  ", "", "REAL-ID"]}]}
        assert _v4_parse_alert_ids(payload) == ["REAL-ID"]

    def test_parses_alert_detail_into_a_weather_alert(self):
        from src.fetchers.weather_onecall import _v4_parse_alert_detail

        alert = _v4_parse_alert_detail(_V4_ALERT_SAMPLE)
        assert alert is not None
        assert alert.event == "Heat Advisory"

    @pytest.mark.parametrize("payload", [{}, {"event": ""}, {"event": "   "}, {"event": None}])
    def test_nameless_alert_detail_is_dropped(self, payload):
        """Matches the 3.0 path, which skips alerts with no usable event name."""
        from src.fetchers.weather_onecall import _v4_parse_alert_detail

        assert _v4_parse_alert_detail(payload) is None


def _v4_routes(alert_ids=None, uvi=1.55):
    """A /onecall/current payload with the given alert IDs, plus alert details."""
    record = dict(_V4_CURRENT_SAMPLE["data"][0])
    record["uvi"] = uvi
    record["alerts"] = ["ID-1", "ID-2"] if alert_ids is None else alert_ids
    routes = {"/onecall/current": {**_V4_CURRENT_SAMPLE, "data": [record]}}
    for alert_id in record["alerts"]:
        routes[f"/onecall/alert/{alert_id}"] = {**_V4_ALERT_SAMPLE, "event": f"Event {alert_id}"}
    return routes


class TestV4Transport:
    def test_routes_only_to_4_0_endpoints(self):
        session = _dispatch_session(_v4_routes())

        _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0")

        assert _urls(session)
        for url in _urls(session):
            assert "/data/4.0/onecall" in url
            assert "/data/3.0/" not in url
            assert "/data/2.5/" not in url

    def test_resolves_alert_ids_to_event_names(self):
        session = _dispatch_session(_v4_routes(["ID-1"]))

        alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0")

        assert uv == 1.55
        assert [a.event for a in alerts] == ["Event ID-1"]

    def test_quiet_day_costs_a_single_request(self):
        """With no active alerts 4.0 is no more expensive than 3.0."""
        session = _dispatch_session(_v4_routes([]))

        alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0")

        assert session.get.call_count == 1
        assert alerts == []
        assert uv == 1.55

    def test_alert_detail_requests_are_capped(self):
        from src.fetchers.weather_onecall import _V4_MAX_ALERT_DETAILS

        session = _dispatch_session(_v4_routes([f"ID-{i}" for i in range(10)]))

        alerts, _uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0")

        detail_calls = [u for u in _urls(session) if "/onecall/alert/" in u]
        assert len(detail_calls) == _V4_MAX_ALERT_DETAILS
        assert len(alerts) == _V4_MAX_ALERT_DETAILS

    def test_alert_detail_request_omits_lat_lon_and_units(self):
        """That endpoint takes the ID in the path and nothing but appid."""
        session = _dispatch_session(_v4_routes(["ID-1"]))

        _fetch_alerts_and_uv(
            session, {"appid": "k", "lat": 1.0, "lon": 2.0, "units": "imperial"}, "4.0"
        )

        detail_call = next(c for c in session.get.call_args_list if "/onecall/alert/" in c[0][0])
        assert detail_call.kwargs["params"] == {"appid": "k"}

    def test_one_failing_alert_does_not_lose_the_others(self):
        routes = _v4_routes(["ID-1", "ID-2"])
        session = _dispatch_session(routes, errors={"/onecall/alert/ID-1": Exception("500")})

        alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0")

        assert [a.event for a in alerts] == ["Event ID-2"]
        assert uv == 1.55, "a failed alert lookup must not cost the UV index"

    def test_unauthorised_key_degrades_gracefully(self):
        """A 4.0 key calling 4.0 without the subscription 401s like any other."""
        session = _dispatch_session({}, errors={"/onecall/current": Exception("401 Unauthorized")})

        assert _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0") == ([], None)

    def test_rate_limited_request_degrades_gracefully(self):
        session = _dispatch_session({}, errors={"/onecall/current": Exception("429 Too Many")})

        assert _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0") == ([], None)

    def test_malformed_payload_degrades_gracefully(self):
        session = _dispatch_session({"/onecall/current": ["not", "a", "dict"]})

        assert _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0") == ([], None)

    def test_alert_ids_are_url_escaped_into_the_path(self):
        routes = _v4_routes([])
        routes["/onecall/alert/a%2Fb%3Fc"] = _V4_ALERT_SAMPLE
        routes["/onecall/current"]["data"][0]["alerts"] = ["a/b?c"]
        session = _dispatch_session(routes)

        _fetch_alerts_and_uv(session, {"appid": "k"}, "4.0")

        detail_call = next(c for c in session.get.call_args_list if "/onecall/alert/" in c[0][0])
        assert detail_call[0][0].endswith("/onecall/alert/a%2Fb%3Fc")


class TestEnumStaysConsistent:
    """The accepted set is declared once; nothing may drift from it."""

    def test_schema_choices_are_the_canonical_tuple(self):
        from src.config_schema import ONE_CALL_VERSIONS, schema

        field = next(
            f
            for section in schema()
            for f in section.fields
            if f.path == "weather.one_call_version"
        )
        assert field.choices == ONE_CALL_VERSIONS

    def test_every_accepted_value_validates_and_dispatches(self):
        """Nothing in the enum may be rejected by validation or unroutable."""
        from src.config import Config
        from src.config_schema import ONE_CALL_VERSIONS

        for version in ONE_CALL_VERSIONS:
            cfg = Config()
            cfg.weather = WeatherConfig(api_key="a" * 32, latitude=1.0, one_call_version=version)
            _errors, warnings = validate_config(cfg)
            assert not [w for w in warnings if w.field == "weather.one_call_version"], version

    def test_template_offers_exactly_the_canonical_values(self):
        """The hand-written config page must not drift from the schema."""
        import re
        from pathlib import Path

        from src.config_schema import ONE_CALL_VERSIONS

        html = Path("src/web/templates/config.html").read_text()
        block = re.search(r'data-field="weather\.one_call_version".*?\{% endfor %\}', html, re.S)
        assert block, "no one_call_version select in config.html"
        offered = re.search(r"\{% for v in (\[[^\]]*\]) %\}", block.group(0))
        assert offered
        assert [x.strip().strip("\"'") for x in offered.group(1)[1:-1].split(",")] == list(
            ONE_CALL_VERSIONS
        )


class TestWebAssetsOfferTheField:
    """Static checks on the hand-written config page.

    These read the files as text rather than importing anything, so they stay
    in the core suite; the tests that exercise the web editor itself live in
    tests/test_web_config.py, which the no-extras CI job skips.
    """

    def test_template_offers_a_select_for_the_field(self):
        from pathlib import Path

        html = Path("src/web/templates/config.html").read_text()
        assert 'data-field="weather.one_call_version"' in html

    def test_the_save_patch_includes_the_field(self):
        """dashboard.js must send it, or the dropdown silently does nothing."""
        from pathlib import Path

        js = Path("src/web/static/dashboard.js").read_text()
        assert 'patch["weather.one_call_version"]' in js
        assert 'v("cfg-onecall")' in js


class TestFailureClassificationReachesTheBoundary:
    """The degradation contract holds, but a permanent failure is visible (#223)."""

    def _auth_error(self):
        from unittest.mock import MagicMock

        import requests

        return requests.HTTPError("401", response=MagicMock(status_code=401))

    def test_a_401_still_degrades_to_empty(self, tmp_path):
        session = _dispatch_session({}, errors={"/data/3.0/": self._auth_error()})

        result = _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0", state_dir=str(tmp_path))

        assert result == ([], None)

    def test_a_401_warns_and_is_recorded(self, tmp_path, caplog):
        session = _dispatch_session({}, errors={"/data/3.0/": self._auth_error()})

        with caplog.at_level(logging.DEBUG):
            _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0", state_dir=str(tmp_path))

        from src.fetchers import one_call_health

        assert [r for r in caplog.records if r.levelname == "WARNING"]
        assert one_call_health.read_health(str(tmp_path))["outcome"] == "auth_failed"

    def test_a_timeout_is_not_recorded_as_an_auth_failure(self, tmp_path):
        import requests

        session = _dispatch_session({}, errors={"/data/3.0/": requests.Timeout("slow")})

        _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0", state_dir=str(tmp_path))

        from src.fetchers import one_call_health

        assert one_call_health.read_health(str(tmp_path))["outcome"] == "transient"

    def test_a_success_records_health(self, tmp_path):
        session = _dispatch_session({"/data/3.0/onecall": _V3_SAMPLE})

        _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0", state_dir=str(tmp_path))

        from src.fetchers import one_call_health

        assert one_call_health.read_health(str(tmp_path))["outcome"] == "ok"

    def test_off_records_nothing(self, tmp_path):
        """A deliberately disabled One Call is not a healthy fetch."""
        session = _dispatch_session({})

        _fetch_alerts_and_uv(session, {"appid": "k"}, "off", state_dir=str(tmp_path))

        from src.fetchers import one_call_health

        assert one_call_health.read_health(str(tmp_path)) == {}

    def test_no_state_dir_still_degrades_cleanly(self):
        session = _dispatch_session({}, errors={"/data/3.0/": self._auth_error()})

        assert _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0") == ([], None)
