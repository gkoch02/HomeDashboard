"""Tests for src/fetchers/purpleair.py"""

from unittest.mock import MagicMock, patch

import pytest

from src.config import PurpleAirConfig
from src.data.models import AirQualityData
from src.fetchers.purpleair import fetch_air_quality, _pm25_to_aqi, _aqi_category


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cfg():
    return PurpleAirConfig(api_key="test-key", sensor_id=12345)


def _make_response(
    pm25: float = 8.5, pm10: float = 12.2, pm1: float = 5.0, status: int = 200
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {
        "sensor": {
            "sensor_index": 12345,
            "pm2.5_60minute": pm25,
            "pm1.0_atm": pm1,
            "pm10.0_atm": pm10,
        }
    }
    return resp


# ---------------------------------------------------------------------------
# AQI calculation unit tests
# ---------------------------------------------------------------------------

class TestPm25ToAqi:
    @pytest.mark.parametrize("pm25,expected_aqi,expected_cat", [
        (0.0,   0,   "Good"),
        (6.0,   25,  "Good"),
        (12.0,  50,  "Good"),
        (12.1,  51,  "Moderate"),
        (35.4,  100, "Moderate"),
        (35.5,  101, "Unhealthy for Sensitive Groups"),
        (55.4,  150, "Unhealthy for Sensitive Groups"),
        (55.5,  151, "Unhealthy"),
        (150.4, 200, "Unhealthy"),
        (150.5, 201, "Very Unhealthy"),
        (250.4, 300, "Very Unhealthy"),
        (250.5, 301, "Hazardous"),
        (350.4, 400, "Hazardous"),
        (350.5, 401, "Hazardous"),
        (500.4, 500, "Hazardous"),
    ])
    def test_breakpoints(self, pm25, expected_aqi, expected_cat):
        aqi, cat = _pm25_to_aqi(pm25)
        assert aqi == expected_aqi
        assert cat == expected_cat

    def test_above_range_clamps_to_hazardous(self):
        aqi, cat = _pm25_to_aqi(999.9)
        assert aqi == 500
        assert cat == "Hazardous"

    def test_truncates_to_one_decimal(self):
        # EPA requires truncation to 1dp before lookup
        aqi1, _ = _pm25_to_aqi(12.049)  # truncates to 12.0 → Good
        aqi2, _ = _pm25_to_aqi(12.099)  # truncates to 12.0 → Good
        aqi3, _ = _pm25_to_aqi(12.199)  # truncates to 12.1 → Moderate
        assert aqi1 == 50
        assert aqi2 == 50
        assert aqi3 == 51


class TestAqiCategory:
    @pytest.mark.parametrize("aqi,expected", [
        (0,   "Good"),
        (50,  "Good"),
        (51,  "Moderate"),
        (100, "Moderate"),
        (101, "Unhealthy for Sensitive Groups"),
        (150, "Unhealthy for Sensitive Groups"),
        (151, "Unhealthy"),
        (200, "Unhealthy"),
        (201, "Very Unhealthy"),
        (300, "Very Unhealthy"),
        (301, "Hazardous"),
        (500, "Hazardous"),
        (501, "Hazardous"),
    ])
    def test_categories(self, aqi, expected):
        assert _aqi_category(aqi) == expected


# ---------------------------------------------------------------------------
# Fetcher integration tests (mocked HTTP)
# ---------------------------------------------------------------------------

class TestFetchAirQuality:
    def test_raises_without_api_key(self):
        with pytest.raises(RuntimeError, match="api_key"):
            fetch_air_quality(PurpleAirConfig(api_key="", sensor_id=12345))

    def test_raises_without_sensor_id(self):
        with pytest.raises(RuntimeError, match="sensor_id"):
            fetch_air_quality(PurpleAirConfig(api_key="key", sensor_id=0))

    def test_fetch_success(self, cfg):
        resp = _make_response(pm25=8.5, pm10=12.2)
        with patch("src.fetchers.purpleair.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = resp

            result = fetch_air_quality(cfg)

        assert isinstance(result, AirQualityData)
        assert result.pm25 == 8.5
        assert result.pm10 == 12.2
        assert result.pm1 == 5.0
        assert result.sensor_id == cfg.sensor_id
        assert result.aqi == 35   # AQI for 8.5 µg/m³
        assert result.category == "Good"

    def test_fetch_without_pm10(self, cfg):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"sensor": {"pm2.5_60minute": 20.0}}
        with patch("src.fetchers.purpleair.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = resp

            result = fetch_air_quality(cfg)

        assert result.pm10 is None
        assert result.category == "Moderate"

    def test_fetch_supports_fields_data_shape(self, cfg):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "fields": ["sensor_index", "pm2.5_60minute", "pm1.0_atm", "pm10.0_atm"],
            "data": [[12345, 15.2, 7.1, 20.3]],
        }
        with patch("src.fetchers.purpleair.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = resp

            result = fetch_air_quality(cfg)

        assert result.pm25 == 15.2
        assert result.pm1 == 7.1
        assert result.pm10 == 20.3
        assert result.category == "Moderate"

    def test_fetch_falls_back_to_pm25_atm(self, cfg):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"sensor": {"pm2.5_atm": 22.8}}
        with patch("src.fetchers.purpleair.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = resp

            result = fetch_air_quality(cfg)

        assert result.pm25 == 22.8
        assert result.category == "Moderate"

    def test_fetch_raises_when_pm25_missing(self, cfg):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"sensor": {"temperature": 70}}
        with patch("src.fetchers.purpleair.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = resp

            with pytest.raises(RuntimeError, match="usable PM2.5 reading"):
                fetch_air_quality(cfg)

    def test_403_raises_runtime_error(self, cfg):
        resp = _make_response(status=403)
        with patch("src.fetchers.purpleair.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = resp

            with pytest.raises(RuntimeError, match="invalid or lacks read access"):
                fetch_air_quality(cfg)

    def test_404_raises_runtime_error(self, cfg):
        resp = _make_response(status=404)
        with patch("src.fetchers.purpleair.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = resp

            with pytest.raises(RuntimeError, match="not found"):
                fetch_air_quality(cfg)

    def test_correct_url_and_headers(self, cfg):
        resp = _make_response()
        with patch("src.fetchers.purpleair.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = resp

            fetch_air_quality(cfg)

        call_kwargs = mock_session.get.call_args
        assert "12345" in call_kwargs[0][0]
        assert call_kwargs[1]["headers"]["X-API-Key"] == "test-key"
        assert "pm2.5_60minute" in call_kwargs[1]["params"]["fields"]
        assert "pm1.0_atm" in call_kwargs[1]["params"]["fields"]
