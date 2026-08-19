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


def _dispatch_session(routes: dict[str, dict], errors: dict[str, Exception] | None = None):
    """Build a mock session whose .get() is routed by URL substring.

    ``routes`` maps a URL fragment to the JSON payload to return; ``errors``
    maps a fragment to an exception raised by ``raise_for_status()``.  An
    unmatched URL fails the test loudly rather than returning a bare MagicMock.
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
        raise AssertionError(f"unexpected request to {url}")

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
        session = _dispatch_session({}, errors={"/data/3.0/": Exception("401 Unauthorized")})

        with caplog.at_level(logging.DEBUG, logger="src.fetchers.weather"):
            alerts, uv = _fetch_alerts_and_uv(session, {"appid": "k"}, "3.0")

        assert (alerts, uv) == ([], None)
        assert any("alerts/UV fetch skipped" in r.message for r in caplog.records)

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


class TestValidation:
    def _warnings_for(self, version):
        from src.config import Config

        cfg = Config()
        cfg.weather = WeatherConfig(api_key="a" * 32, latitude=1.0, one_call_version=version)
        _errors, warnings = validate_config(cfg)
        return [w for w in warnings if w.field == "weather.one_call_version"]

    @pytest.mark.parametrize("version", ["3.0", "off"])
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
        assert field["choices"] == ["3.0", "off"]
        assert not field.get("secret")
