"""OpenWeatherMap One Call transport for weather alerts and the UV index.

The dashboard's current conditions and forecast come from the free
``/data/2.5/weather`` and ``/data/2.5/forecast`` endpoints.  Only two values —
active weather alerts and the UV index — come from the One Call product family,
which is a separate paid-tier opt-in (free for the first 1,000 calls a day).

OpenWeather ships One Call as two mutually exclusive products, and an account
can hold a subscription to only one of them.  Calling the version you are *not*
subscribed to returns HTTP 401, indistinguishable from having no subscription
at all, so the version is a config choice (``weather.one_call_version``) rather
than something this module can detect.

Shape contract
--------------
Every field name and path below was taken from the One Call API documentation.
If OpenWeather changes an envelope, only the URL constants and the parsing
helpers in this module need to change.

3.0 is a single all-in-one request; ``uvi`` sits at ``current.uvi`` and alerts
arrive inline as full objects under ``alerts``.

Functions here are free to raise; ``weather._fetch_alerts_and_uv`` owns the
single degradation boundary that turns any failure into ``([], None)``.
"""

from __future__ import annotations

import logging

import requests  # type: ignore[import-untyped]

from src.data.models import WeatherAlert

logger = logging.getLogger(__name__)

_V3_URL = "https://api.openweathermap.org/data/3.0/onecall"

_TIMEOUT = 10  # seconds

DEFAULT_VERSION = "3.0"
SUPPORTED_VERSIONS = ("3.0", "off")


def fetch_alerts_and_uv(
    session: requests.Session,
    params: dict,
    *,
    version: str = DEFAULT_VERSION,
) -> tuple[list[WeatherAlert], float | None]:
    """Fetch active weather alerts and the UV index via the selected One Call version.

    ``version`` is ``"3.0"`` or ``"off"`` (skip the request entirely).  Any
    unrecognised value falls back to the default, so a config typo degrades to
    today's behaviour rather than losing the data outright.

    May raise; the caller is responsible for degrading to ``([], None)``.
    """
    if version == "off":
        return [], None
    return _fetch_v3(session, params)


# ---------------------------------------------------------------------------
# One Call 3.0 — single all-in-one request
# ---------------------------------------------------------------------------


def _fetch_v3(
    session: requests.Session,
    params: dict,
) -> tuple[list[WeatherAlert], float | None]:
    onecall_params = {
        **params,
        "exclude": "minutely,hourly,daily",
    }
    resp = session.get(_V3_URL, params=onecall_params, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    alerts: list[WeatherAlert] = []
    for a in data.get("alerts", []):
        event = a.get("event", "").strip()
        if event:
            alerts.append(WeatherAlert(event=event))

    uv_index: float | None = None
    current = data.get("current", {})
    if "uvi" in current:
        uv_index = float(current["uvi"])

    return alerts, uv_index
