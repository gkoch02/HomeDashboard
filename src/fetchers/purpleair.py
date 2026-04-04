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
import math
from typing import Any

import requests

from src.config import PurpleAirConfig
from src.data.models import AirQualityData

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.purpleair.com/v1/sensors"
_FIELD_NAMES = [
    "pm2.5_60minute",
    "pm2.5_60minute_a",
    "pm2.5_60minute_b",
    "pm2.5_atm",
    "pm2.5_atm_a",
    "pm2.5_atm_b",
    "pm1.0_atm",
    "pm10.0_atm",
    "temperature",
    "humidity",
    "pressure",
]
_FIELDS = ",".join(_FIELD_NAMES)
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
    pm25 = math.floor(pm25 * 10) / 10  # EPA truncates to 1 decimal place before lookup
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


def _sensor_payload_to_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize PurpleAir response into a single key/value mapping.

    PurpleAir can return either:
    1) {"sensor": {...}} for single-sensor lookups
    2) {"fields": [...], "data": [[...]]} for row/column payloads
    """
    sensor = payload.get("sensor")
    if isinstance(sensor, dict):
        return sensor

    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list):
        logger.debug("PurpleAir payload missing 'fields' list: keys=%s", sorted(payload.keys()))
        return {}
    if not isinstance(data, list) or not data:
        logger.debug("PurpleAir payload missing 'data' list: keys=%s", sorted(payload.keys()))
        return {}

    # data can be a single row list or a list of rows; use the first row.
    row = data[0] if isinstance(data[0], list) else data
    if not isinstance(row, list):
        logger.debug("PurpleAir data row is not a list: type=%s", type(row).__name__)
        return {}
    return dict(zip(fields, row))


def _first_float(sensor: dict[str, Any], keys: list[str]) -> float | None:
    """Return the first parseable float found for any key in `keys`."""
    for key in keys:
        value = sensor.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


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

    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"PurpleAir returned non-JSON response (status {resp.status_code}): {exc}"
        ) from exc
    sensor = _sensor_payload_to_dict(payload)

    pm25_60min = _first_float(
        sensor,
        [
            "pm2.5_60minute",
            "pm2.5_60minute_a",
            "pm2.5_60minute_b",
            "pm2.5_atm",
            "pm2.5_atm_a",
            "pm2.5_atm_b",
        ],
    )
    if pm25_60min is None:
        available = sorted(sensor.keys())
        raise RuntimeError(
            "PurpleAir response did not include a usable PM2.5 reading. "
            f"Available keys: {available}"
        )

    pm1 = _first_float(sensor, ["pm1.0_atm", "pm1.0_atm_a", "pm1.0_atm_b"])
    pm10 = _first_float(sensor, ["pm10.0_atm", "pm10.0_atm_a", "pm10.0_atm_b"])
    temperature = _first_float(sensor, ["temperature"])
    humidity = _first_float(sensor, ["humidity"])
    pressure = _first_float(sensor, ["pressure"])
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
        temperature=temperature,
        humidity=humidity,
        pressure=pressure,
    )
