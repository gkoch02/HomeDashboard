"""Tests for src/fetchers/weather.py"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.config import WeatherConfig
from src.fetchers.weather import fetch_weather, _pick_midday
from src.render.primitives import deg_to_compass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cfg():
    return WeatherConfig(
        api_key="test-key",
        latitude=40.7128,
        longitude=-74.006,
        units="imperial",
    )


def _make_slot(hour: int, day_offset: int = 1, temp: float = 50.0, icon: str = "01d") -> dict:
    """Helper to build a minimal OWM forecast slot."""
    base = datetime(2024, 3, 15, hour, 0, tzinfo=timezone.utc)
    from datetime import timedelta
    dt = base + timedelta(days=day_offset)
    return {
        "dt": int(dt.timestamp()),
        "main": {"temp": temp, "temp_max": temp + 5, "temp_min": temp - 5},
        "weather": [{"icon": icon, "description": "clear sky"}],
    }


def _mock_current_response() -> dict:
    return {
        "main": {"temp": 42.0, "temp_max": 48.0, "temp_min": 35.0, "humidity": 65},
        "weather": [{"icon": "02d", "description": "partly cloudy"}],
    }


def _mock_forecast_response(today: date) -> dict:
    slots = []
    for day_offset in range(1, 4):
        for hour in [6, 12, 18]:
            slots.append(_make_slot(hour, day_offset=day_offset))
    return {"list": slots}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFetchWeather:
    def test_raises_without_api_key(self):
        cfg_no_key = WeatherConfig(api_key="", latitude=0.0, longitude=0.0)
        with pytest.raises(RuntimeError, match="API key"):
            fetch_weather(cfg_no_key)

    @patch("src.fetchers.weather.requests.Session")
    def test_returns_weather_data(self, mock_session_cls, cfg):
        today = date.today()
        current_resp = MagicMock()
        current_resp.json.return_value = _mock_current_response()
        current_resp.raise_for_status = MagicMock()

        forecast_resp = MagicMock()
        forecast_resp.json.return_value = _mock_forecast_response(today)
        forecast_resp.raise_for_status = MagicMock()

        alerts_resp = MagicMock()
        alerts_resp.json.return_value = {}
        alerts_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.side_effect = [current_resp, forecast_resp, alerts_resp]
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_weather(cfg)

        assert result.current_temp == 42.0
        assert result.current_icon == "02d"
        assert result.humidity == 65
        assert len(result.forecast) == 3

    @patch("src.fetchers.weather.requests.Session")
    def test_forecast_excludes_today(self, mock_session_cls, cfg):
        from datetime import timezone
        today = date.today()
        today_dt = datetime.combine(
            today, datetime.min.time().replace(hour=12)
        ).replace(tzinfo=timezone.utc)

        current_resp = MagicMock()
        current_resp.json.return_value = _mock_current_response()
        current_resp.raise_for_status = MagicMock()

        # Include a today slot that should be excluded
        today_slot = {
            "dt": int(today_dt.timestamp()),
            "main": {"temp": 99.0, "temp_max": 100.0, "temp_min": 90.0},
            "weather": [{"icon": "99d", "description": "today"}],
        }
        forecast_resp = MagicMock()
        forecast_resp.json.return_value = {
            "list": [today_slot] + _mock_forecast_response(today)["list"],
        }
        forecast_resp.raise_for_status = MagicMock()

        alerts_resp = MagicMock()
        alerts_resp.json.return_value = {}
        alerts_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.side_effect = [current_resp, forecast_resp, alerts_resp]
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_weather(cfg)
        for day_forecast in result.forecast:
            assert day_forecast.date != today

    @patch("src.fetchers.weather.requests.Session")
    def test_forecast_max_six_days(self, mock_session_cls, cfg):
        today = date.today()
        current_resp = MagicMock()
        current_resp.json.return_value = _mock_current_response()
        current_resp.raise_for_status = MagicMock()

        # 8 future days of slots — only 6 should be returned
        from datetime import timedelta, timezone
        slots = []
        for day_offset in range(1, 9):
            dt = datetime.combine(
                today, datetime.min.time().replace(hour=12)
            ).replace(tzinfo=timezone.utc)
            dt = dt + timedelta(days=day_offset)
            slots.append({
                "dt": int(dt.timestamp()),
                "main": {"temp": 50.0, "temp_max": 55.0, "temp_min": 45.0},
                "weather": [{"icon": "01d", "description": "clear"}],
            })

        forecast_resp = MagicMock()
        forecast_resp.json.return_value = {"list": slots}
        forecast_resp.raise_for_status = MagicMock()

        alerts_resp = MagicMock()
        alerts_resp.json.return_value = {}
        alerts_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.side_effect = [current_resp, forecast_resp, alerts_resp]
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_weather(cfg)
        assert len(result.forecast) == 6


class TestPickMidday:
    def test_returns_midday_slot(self):
        slots = [_make_slot(6), _make_slot(12), _make_slot(18)]
        result = _pick_midday(slots)
        from datetime import timezone
        dt = datetime.fromtimestamp(result["dt"], tz=timezone.utc)
        assert dt.hour in (11, 12, 13, 14)

    def test_returns_none_for_empty(self):
        assert _pick_midday([]) is None

    def test_returns_none_when_no_midday_slot(self):
        slots = [_make_slot(3), _make_slot(6)]
        assert _pick_midday(slots) is None

    def test_uses_local_tz_for_noon(self):
        import zoneinfo
        # UTC+0: slot at hour 12 UTC is noon UTC
        # UTC-5 (EST): same slot is hour 7 local — not midday
        # UTC+12: same slot is hour 0 next day — not midday
        # Slot at UTC 17:00 = noon EST (UTC-5)
        slots = [_make_slot(17)]
        est = zoneinfo.ZoneInfo("America/New_York")
        result = _pick_midday(slots, tz=est)
        assert result is not None  # 17 UTC = 12 EST
        result_utc = _pick_midday(slots)
        assert result_utc is None  # 17 UTC is not in (11,12,13,14) UTC


# ---------------------------------------------------------------------------
# deg_to_compass
# ---------------------------------------------------------------------------

class TestDegToCompass:
    def test_north(self):
        assert deg_to_compass(0) == "N"

    def test_north_from_360(self):
        assert deg_to_compass(360) == "N"

    def test_northeast(self):
        assert deg_to_compass(45) == "NE"

    def test_east(self):
        assert deg_to_compass(90) == "E"

    def test_southeast(self):
        assert deg_to_compass(135) == "SE"

    def test_south(self):
        assert deg_to_compass(180) == "S"

    def test_southwest(self):
        assert deg_to_compass(225) == "SW"

    def test_west(self):
        assert deg_to_compass(270) == "W"

    def test_northwest(self):
        assert deg_to_compass(315) == "NW"

    def test_boundary_north_northeast(self):
        # 22.5° is the midpoint between N and NE — rounds to NE (round half up)
        result = deg_to_compass(22.5)
        assert result in ("N", "NE")

    def test_slightly_east_of_north(self):
        assert deg_to_compass(23) == "NE"

    def test_slightly_west_of_north(self):
        assert deg_to_compass(337) == "NW"

    def test_exactly_338_degrees(self):
        # 338 / 45 = 7.5 → round to 8 → % 8 = 0 → N
        assert deg_to_compass(338) == "N"

    def test_wraps_correctly_over_360(self):
        # 405 degrees == 45 degrees == NE
        assert deg_to_compass(405) == "NE"

    def test_all_cardinal_directions_covered(self):
        cardinals = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
        results = {deg_to_compass(i * 45) for i in range(8)}
        assert results == cardinals


# ---------------------------------------------------------------------------
# _today() with timezone (line 22)
# ---------------------------------------------------------------------------

class TestToday:
    def test_today_with_none_tz_returns_local_date(self):
        from src.fetchers.weather import _today
        result = _today(None)
        assert result == date.today()

    def test_today_with_tz_returns_tz_aware_date(self):
        import zoneinfo
        from src.fetchers.weather import _today
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        result = _today(tz)
        expected = datetime.now(tz).date()
        assert result == expected


# ---------------------------------------------------------------------------
# Sunrise / sunset parsing (lines 54-57)
# ---------------------------------------------------------------------------

class TestSunriseSunset:
    @patch("src.fetchers.weather.requests.Session")
    def test_sunrise_sunset_parsed(self, mock_session_cls, cfg):
        """Verify sunrise and sunset are populated when sys key is present."""
        from datetime import timezone as _tz
        today = date.today()

        sunrise_ts = int(datetime(today.year, today.month, today.day, 6, 24, tzinfo=_tz.utc).timestamp())
        sunset_ts = int(datetime(today.year, today.month, today.day, 19, 51, tzinfo=_tz.utc).timestamp())

        current_resp = MagicMock()
        current_resp.json.return_value = {
            "main": {
                "temp": 42.0, "temp_max": 48.0, "temp_min": 35.0, "humidity": 65,
                "feels_like": 38.0,
            },
            "weather": [{"icon": "02d", "description": "partly cloudy"}],
            "sys": {"sunrise": sunrise_ts, "sunset": sunset_ts},
            "wind": {"speed": 10.0, "deg": 270.0},
        }
        current_resp.raise_for_status = MagicMock()

        forecast_resp = MagicMock()
        forecast_resp.json.return_value = _mock_forecast_response(today)
        forecast_resp.raise_for_status = MagicMock()

        alerts_resp = MagicMock()
        alerts_resp.json.return_value = {}
        alerts_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.side_effect = [current_resp, forecast_resp, alerts_resp]
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_weather(cfg)

        assert result.sunrise is not None
        assert result.sunset is not None
        assert result.sunrise.hour == 6
        assert result.sunset.hour == 19

    @patch("src.fetchers.weather.requests.Session")
    def test_sunrise_sunset_absent_when_no_sys_key(self, mock_session_cls, cfg):
        """sunrise/sunset are None when the API response has no sys key."""
        today = date.today()

        current_resp = MagicMock()
        current_resp.json.return_value = {
            "main": {"temp": 42.0, "temp_max": 48.0, "temp_min": 35.0, "humidity": 65},
            "weather": [{"icon": "02d", "description": "cloudy"}],
            # No "sys" key
        }
        current_resp.raise_for_status = MagicMock()

        forecast_resp = MagicMock()
        forecast_resp.json.return_value = _mock_forecast_response(today)
        forecast_resp.raise_for_status = MagicMock()

        alerts_resp = MagicMock()
        alerts_resp.json.return_value = {}
        alerts_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.side_effect = [current_resp, forecast_resp, alerts_resp]
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_weather(cfg)
        assert result.sunrise is None
        assert result.sunset is None
