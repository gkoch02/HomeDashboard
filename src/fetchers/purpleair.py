"""PurpleAir air quality fetcher.

Fetches current sensor readings from the PurpleAir v1 API and computes the
EPA PM2.5 AQI. Requires ``api_key`` and ``sensor_id`` from ``PurpleAirConfig``.

Configuration example (config.yaml)::

    purpleair:
      api_key: "YOUR_PURPLEAIR_API_KEY"
      sensor_id: 12345  # find at map.purpleair.com

API reference: https://community.purpleair.com/t/making-api-calls/180
"""

import logging

import requests

from src.config import PurpleAirConfig
from src.data.models import AirQualityData

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.purpleair.com/v1/sensors"
_FIELDS = "pm2.5_60minute,pm1.0_atm,pm10.0_atm"
_TIMEOUT = 10

# EPA PM2.5 AQI breakpoints: (C_lo, C_hi, I_lo, I_hi)
_PM25_BP = [
    (0.0,   12.0,   0,  50),
    (12.1,  35.4,  51, 100),
    (35.5,  55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 350.4, 301, 400),
    (350.5, 500.4, 401, 500),
]

_AQI_CATEGORIES = [
    (50,  "Good"),
    (100, "Moderate"),
    (150, "Unhealthy for Sensitive Groups"),
    (200, "Unhealthy"),
    (300, "Very Unhealthy"),
    (500, "Hazardous"),
]


def _pm25_to_aqi(pm25: float) -> tuple[int, str]:
    """Compute EPA AQI integer and category string from a PM2.5 µg/m³ reading."""
    pm25 = round(pm25, 1)  # EPA truncates to 1 decimal place before lookup
    for c_lo, c_hi, i_lo, i_hi in _PM25_BP:
        if c_lo <= pm25 <= c_hi:
            aqi = round((i_hi - i_lo) / (c_hi - c_lo) * (pm25 - c_lo) + i_lo)
            return aqi, _aqi_category(aqi)
    # Above 500.4 µg/m³ — clamp to Hazardous
    return 500, "Hazardous"


def _aqi_category(aqi: int) -> str:
    for threshold, label in _AQI_CATEGORIES:
        if aqi <= threshold:
            return label
    return "Hazardous"


def fetch_air_quality(cfg: PurpleAirConfig) -> AirQualityData:
    """Fetch current air quality from a PurpleAir sensor.

    Raises ``RuntimeError`` when credentials are missing or the API returns an
    unrecoverable error (403 invalid key, 404 sensor not found).  Transient
    network errors propagate as ``requests.RequestException`` so the caller's
    circuit-breaker logic can handle them.
    """
    if not cfg.api_key:
        raise RuntimeError("PurpleAir api_key is not configured")
    if not cfg.sensor_id:
        raise RuntimeError("PurpleAir sensor_id is not configured")

    url = f"{_BASE_URL}/{cfg.sensor_id}"
    headers = {"X-API-Key": cfg.api_key}
    params = {"fields": _FIELDS}

    with requests.Session() as session:
        resp = session.get(url, headers=headers, params=params, timeout=_TIMEOUT)

    if resp.status_code == 403:
        raise RuntimeError("PurpleAir API key is invalid or lacks read access")
    if resp.status_code == 404:
        raise RuntimeError(f"PurpleAir sensor {cfg.sensor_id} not found")
    resp.raise_for_status()

    sensor = resp.json().get("sensor", {})
    pm25_60min = float(sensor["pm2.5_60minute"])
    pm1_raw = sensor.get("pm1.0_atm")
    pm1 = float(pm1_raw) if pm1_raw is not None else None
    pm10_raw = sensor.get("pm10.0_atm")
    pm10 = float(pm10_raw) if pm10_raw is not None else None
    aqi, category = _pm25_to_aqi(pm25_60min)

    logger.info(
        "PurpleAir sensor %d: PM2.5 60m=%.1f µg/m³  AQI=%d (%s)",
        cfg.sensor_id, pm25_60min, aqi, category,
    )

    return AirQualityData(
        aqi=aqi,
        category=category,
        pm25=pm25_60min,
        pm10=pm10,
        sensor_id=cfg.sensor_id,
        pm1=pm1,
    )
