"""Weather alerts: One Call fetch and parsing, and the weather panel's alert row."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.data.models import (
    WeatherAlert,
)
from src.render import layout as L
from src.render.components.weather_panel import draw_weather
from tests.conftest import make_draw, make_weather
from tests.inkutils import ink, ink_x_extent

WEATHER_BOX = (L.WEATHER_X, L.WEATHER_Y, L.WEATHER_X + L.WEATHER_W, L.WEATHER_Y + L.WEATHER_H)


class TestWeatherAlerts:
    def test_alert_renders_without_crash(self):
        """An alert takes a forecast column as a filled (inverted) bar."""
        img, draw = make_draw()
        draw_weather(draw, make_weather(alerts=[WeatherAlert(event="Flood Watch")]))
        plain, plain_draw = make_draw()
        draw_weather(plain_draw, make_weather(alerts=[]))
        assert ink(img, WEATHER_BOX) > ink(plain, WEATHER_BOX) * 2, (
            "the alert column is not inverted"
        )

    def test_no_alerts_renders_normally(self):
        """No alerts draws the panel with no inverted column."""
        img, draw = make_draw()
        draw_weather(draw, make_weather(alerts=[]))
        area = L.WEATHER_W * L.WEATHER_H
        assert 0 < ink(img, WEATHER_BOX) < area * 0.5

    def test_long_alert_name_truncated(self):
        """A 200-char alert stays inside the panel rather than overflowing."""
        img, draw = make_draw()
        draw_weather(draw, make_weather(alerts=[WeatherAlert(event="A" * 200)]))
        extent = ink_x_extent(img, WEATHER_BOX)
        assert extent is not None, "nothing drawn"
        assert extent[1] <= L.WEATHER_X + L.WEATHER_W, "the alert text left the panel"
        # Nothing but chrome to the right: the panel's border hlines are drawn
        # to x0+w inclusive, so they put a few pixels on the column past the
        # region — the same convention weather_panel and birthday_bar share.
        assert ink(img, (L.WEATHER_X + L.WEATHER_W + 1, 0, 800, 480)) == 0

    def test_weather_alert_model(self):
        a = WeatherAlert(event="Tornado Warning")
        assert a.event == "Tornado Warning"

    def test_weather_data_has_alerts_field(self):
        w = make_weather()
        assert w.alerts == []

    def test_fetch_alerts_returns_empty_on_failure(self):
        """_fetch_alerts_and_uv must silently return ([], None) on any HTTP error."""
        from src.fetchers.weather import _fetch_alerts_and_uv

        params = {"lat": 0, "lon": 0, "appid": "key", "units": "imperial"}
        session = MagicMock()
        session.get.side_effect = Exception("network")
        alerts, uv = _fetch_alerts_and_uv(session, params)
        assert alerts == []
        assert uv is None

    def test_fetch_alerts_parses_response(self):
        """_fetch_alerts_and_uv should parse event names from a valid response."""
        from src.fetchers.weather import _fetch_alerts_and_uv

        params = {"lat": 0, "lon": 0, "appid": "key", "units": "imperial"}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "alerts": [
                {"event": "Dense Fog Advisory", "description": "..."},
                {"event": "Winter Storm Warning", "description": "..."},
            ],
            "current": {"uvi": 6.5},
        }
        session = MagicMock()
        session.get.return_value = mock_resp
        alerts, uv = _fetch_alerts_and_uv(session, params)
        assert len(alerts) == 2
        assert alerts[0].event == "Dense Fog Advisory"
        assert alerts[1].event == "Winter Storm Warning"
        assert uv == 6.5

    def test_fetch_alerts_skips_empty_event_names(self):
        from src.fetchers.weather import _fetch_alerts_and_uv

        params = {"lat": 0, "lon": 0, "appid": "key", "units": "imperial"}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"alerts": [{"event": "  "}, {"event": "Real Alert"}]}
        session = MagicMock()
        session.get.return_value = mock_resp
        alerts, uv = _fetch_alerts_and_uv(session, params)
        assert len(alerts) == 1
        assert alerts[0].event == "Real Alert"

    def test_fetch_weather_includes_alerts(self):
        """Full fetch_weather call includes alerts in the returned WeatherData."""
        from src.config import WeatherConfig
        from src.fetchers.weather import fetch_weather

        cfg = WeatherConfig(api_key="key", latitude=0.0, longitude=0.0)
        current_resp = MagicMock()
        current_resp.raise_for_status = MagicMock()
        current_resp.json.return_value = {
            "main": {"temp": 50.0, "temp_max": 55.0, "temp_min": 45.0, "humidity": 60},
            "weather": [{"icon": "01d", "description": "clear sky"}],
        }
        forecast_resp = MagicMock()
        forecast_resp.raise_for_status = MagicMock()
        forecast_resp.json.return_value = {"list": []}

        alert_resp = MagicMock()
        alert_resp.raise_for_status = MagicMock()
        alert_resp.json.return_value = {"alerts": [{"event": "Flood Watch"}]}

        session = MagicMock()
        session.get.side_effect = [current_resp, forecast_resp, alert_resp]
        with patch("src.fetchers.weather.requests.Session") as mock_session_cls:
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = fetch_weather(cfg)

        assert len(result.alerts) == 1
        assert result.alerts[0].event == "Flood Watch"
