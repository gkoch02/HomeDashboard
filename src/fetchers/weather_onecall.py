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

4.0 is modular.  ``/onecall/current`` wraps its single record in a ``data``
array, so ``uvi`` sits at ``data[0].uvi`` — and ``data[0].alerts`` is a list of
alert *ID strings*, not alert objects.  Resolving one ID to the event name that
``WeatherAlert`` carries costs an extra request to ``/onecall/alert/{id}``.

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


# ---------------------------------------------------------------------------
# One Call 4.0 — modular endpoints
#
# These parsers are pure (dict in, value out) and hold all of this module's
# knowledge of the 4.0 envelope.  If OpenWeather reshapes a response, they are
# the only things that need to change.  They tolerate absent optional data but
# deliberately do not guess at unrecognised shapes: a genuinely wrong payload
# raises, and the caller's degradation boundary turns that into ([], None) —
# the same result a key without the subscription already gets.
# ---------------------------------------------------------------------------


def _v4_first_record(payload: dict) -> dict | None:
    """Return the single record from a 4.0 response, or None if absent.

    Even endpoints documented as returning exactly one record wrap it in the
    same ``data`` array the paginated timeline endpoints use.
    """
    records = payload.get("data") or []
    return records[0] if records else None


def _v4_parse_uv(payload: dict) -> float | None:
    """Extract the UV index from a ``/onecall/current`` response."""
    record = _v4_first_record(payload)
    if record is None:
        return None
    uvi = record.get("uvi")
    return None if uvi is None else float(uvi)


def _v4_parse_alert_ids(payload: dict) -> list[str]:
    """Extract active alert IDs from a ``/onecall/current`` response.

    4.0 reports alerts as bare ID strings; each one needs its own request to
    ``/onecall/alert/{id}`` before it has a name worth displaying.
    """
    record = _v4_first_record(payload)
    if record is None:
        return []
    return [str(a).strip() for a in record.get("alerts") or [] if str(a).strip()]


def _v4_parse_alert_detail(payload: dict) -> WeatherAlert | None:
    """Build a WeatherAlert from an ``/onecall/alert/{id}`` response.

    Returns None for an alert with no usable event name, matching how the 3.0
    path drops nameless alerts rather than rendering a blank banner row.
    """
    event = str(payload.get("event") or "").strip()
    return WeatherAlert(event=event) if event else None
