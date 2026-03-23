"""OpenWeatherMap fetcher — current conditions + extended forecast + active alerts."""

import logging
from datetime import date, datetime, timezone, tzinfo

import requests

from src.config import WeatherConfig
from src.data.models import DayForecast, WeatherAlert, WeatherData

logger = logging.getLogger(__name__)

_OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
_OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
_OWM_ONECALL_URL = "https://api.openweathermap.org/data/2.5/onecall"
_TIMEOUT = 10  # seconds


def _today(tz: tzinfo | None) -> date:
    if tz is None:
        return date.today()
    return datetime.now(tz).date()


def fetch_weather(cfg: WeatherConfig, tz: tzinfo | None = None) -> WeatherData:
    """Fetch current weather, extended forecast, and active alerts from OpenWeatherMap.

    Returns up to 6 days of forecast data (all future days available from the
    OWM 5-day/3-hour endpoint, excluding today).

    Raises:
        RuntimeError: if the API key is missing or the current/forecast request fails.
    """
    if not cfg.api_key:
        raise RuntimeError("Weather API key is not configured")

    params = {
        "lat": cfg.latitude,
        "lon": cfg.longitude,
        "appid": cfg.api_key,
        "units": cfg.units,
    }

    with requests.Session() as session:
        current = _fetch_current(session, params)
        today_high, today_low, forecast = _fetch_forecast(session, params, tz=tz)
        alerts, uv_index = _fetch_alerts_and_uv(session, params)

    # Extract sunrise/sunset as timezone-aware datetimes when available
    slot_tz = tz if tz is not None else timezone.utc
    sunrise: datetime | None = None
    sunset: datetime | None = None
    if "sys" in current:
        if "sunrise" in current["sys"]:
            sunrise = datetime.fromtimestamp(current["sys"]["sunrise"], tz=slot_tz)
        if "sunset" in current["sys"]:
            sunset = datetime.fromtimestamp(current["sys"]["sunset"], tz=slot_tz)

    if not current.get("weather"):
        raise RuntimeError("OWM response missing 'weather' array")
    if "main" not in current:
        raise RuntimeError("OWM response missing 'main' object")

    return WeatherData(
        current_temp=current["main"]["temp"],
        current_icon=current["weather"][0]["icon"],
        current_description=current["weather"][0]["description"],
        # Use today's slots from the forecast grid for a proper daily high/low.
        # The /weather endpoint only gives the current-period range, not the
        # full-day range (fix: weather high/low from current slot, not daily).
        # Fall back to the current endpoint values when no today slots exist.
        high=today_high if today_high is not None else current["main"]["temp_max"],
        low=today_low if today_low is not None else current["main"]["temp_min"],
        humidity=current["main"]["humidity"],
        forecast=forecast,
        alerts=alerts,
        feels_like=current["main"].get("feels_like"),
        wind_speed=current.get("wind", {}).get("speed"),
        wind_deg=current.get("wind", {}).get("deg"),
        pressure=current["main"].get("pressure"),
        uv_index=uv_index,
        sunrise=sunrise,
        sunset=sunset,
    )


def _fetch_current(session: requests.Session, params: dict) -> dict:
    resp = session.get(_OWM_CURRENT_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _fetch_forecast(
    session: requests.Session, params: dict, tz: tzinfo | None = None
) -> tuple[float | None, float | None, list[DayForecast]]:
    """Fetch 5-day / 3-hour forecast and collapse to daily highs/lows.

    Returns:
        (today_high, today_low, future_forecasts) — today values are None when
        the forecast grid contains no slots for today (rare near midnight).
    """
    resp = session.get(_OWM_FORECAST_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    slot_tz = tz if tz is not None else timezone.utc
    today = _today(tz)
    by_day: dict[date, list[dict]] = {}
    for slot in data["list"]:
        dt = datetime.fromtimestamp(slot["dt"], tz=slot_tz).date()
        by_day.setdefault(dt, []).append(slot)

    # Derive today's full-day high/low from the forecast grid rather than the
    # point-in-time /weather endpoint values.
    today_high: float | None = None
    today_low: float | None = None
    if today in by_day:
        today_slots = [s for s in by_day[today] if "main" in s]
        if today_slots:
            today_high = max(s["main"]["temp_max"] for s in today_slots)
            today_low = min(s["main"]["temp_min"] for s in today_slots)

    forecasts: list[DayForecast] = []
    for day_date in sorted(d for d in by_day if d != today)[:6]:
        slots = [s for s in by_day[day_date] if "main" in s]
        if not slots:
            continue
        highs = [s["main"]["temp_max"] for s in slots]
        lows = [s["main"]["temp_min"] for s in slots]
        midday = _pick_midday(slots, tz=tz) or slots[0]
        # Maximum precipitation probability across all slots for the day (0.0–1.0)
        pop_values = [s.get("pop", 0.0) for s in slots]
        precip_chance = max(pop_values) if pop_values else None
        midday_weather = midday.get("weather") or []
        if not midday_weather:
            continue
        forecasts.append(DayForecast(
            date=day_date,
            high=max(highs),
            low=min(lows),
            icon=midday_weather[0]["icon"],
            description=midday_weather[0]["description"],
            precip_chance=precip_chance,
        ))

    return today_high, today_low, forecasts


def _fetch_alerts_and_uv(
    session: requests.Session, params: dict,
) -> tuple[list[WeatherAlert], float | None]:
    """Fetch active weather alerts and UV index from OWM OneCall 2.5.

    Returns ``(alerts, uv_index)`` — both are best-effort.  On any failure
    (network error, unsupported API tier) returns ``([], None)``.
    """
    onecall_params = {
        **params,
        "exclude": "minutely,hourly,daily",
    }
    try:
        resp = session.get(_OWM_ONECALL_URL, params=onecall_params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug("Weather alerts/UV fetch skipped: %s", exc)
        return [], None

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


def _pick_midday(slots: list[dict], tz: tzinfo | None = None) -> dict | None:
    """Return the slot closest to noon local time, or None if list is empty."""
    slot_tz = tz if tz is not None else timezone.utc
    for slot in slots:
        dt = datetime.fromtimestamp(slot["dt"], tz=slot_tz)
        if dt.hour in (11, 12, 13, 14):
            return slot
    return None
