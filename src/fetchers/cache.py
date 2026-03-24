"""File-based cache for DashboardData.

v2 format (schema_version=2): per-source buckets with independent fetched_at
timestamps, enabling callers to detect how stale each data source is individually.

v1 format (legacy, no schema_version key): flat structure — read-only backward
compat so existing cache files are not broken after upgrading.
"""

import json
import logging
import os
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path

from src.data.models import (
    AirQualityData, Birthday, CalendarEvent, DashboardData, DayForecast, StalenessLevel,
    WeatherAlert, WeatherData,
)

logger = logging.getLogger(__name__)


def check_staleness(
    fetched_at: datetime, ttl_minutes: int, now: datetime | None = None,
) -> StalenessLevel:
    """Determine staleness level based on cache age relative to TTL.

    - FRESH:   age <= ttl
    - AGING:   ttl < age <= 2*ttl
    - STALE:   2*ttl < age <= 4*ttl
    - EXPIRED: age > 4*ttl
    """
    if now is None:
        now = datetime.now()
    age_minutes = (now - fetched_at).total_seconds() / 60
    if age_minutes <= ttl_minutes:
        return StalenessLevel.FRESH
    if age_minutes <= ttl_minutes * 2:
        return StalenessLevel.AGING
    if age_minutes <= ttl_minutes * 4:
        return StalenessLevel.STALE
    return StalenessLevel.EXPIRED


_CACHE_FILENAME = "dashboard_cache.json"

_SCHEMA_VERSION = 2
_cache_lock = threading.Lock()


def load_cached(cache_dir: str) -> DashboardData | None:
    """Return the last cached DashboardData, or None if absent / corrupt."""
    path = Path(cache_dir) / _CACHE_FILENAME
    if not path.exists():
        return None
    try:
        with open(path) as f:
            raw = json.load(f)
        data = _deserialise(raw)
        logger.info("Loaded cached data from %s (fetched at %s)", path, data.fetched_at)
        return data
    except Exception as exc:
        logger.warning("Cache read failed (%s), ignoring: %s", path, exc)
        return None


def load_cached_source(
    source: str, cache_dir: str
) -> tuple[list | WeatherData | AirQualityData | None, datetime] | None:
    """Load data for a single source from the cache.

    Returns ``(data, fetched_at)`` if the source exists in the cache, else
    ``None``.  *source* must be one of ``"events"``, ``"weather"``, or
    ``"birthdays"``.

    Falls back to reading the whole v1 cache when the file is in legacy format,
    so existing cache files work without requiring a full re-fetch.
    """
    path = Path(cache_dir) / _CACHE_FILENAME
    if not path.exists():
        return None
    try:
        with _cache_lock:
            with open(path) as f:
                raw = json.load(f)
    except Exception as exc:
        logger.warning("Cache read failed (%s): %s", path, exc)
        return None

    if raw.get("schema_version") == _SCHEMA_VERSION:
        block = raw.get(source)
        if not block:
            return None
        try:
            fetched_at = datetime.fromisoformat(block["fetched_at"])
            if source == "events":
                data: list | WeatherData | AirQualityData | None = (
                    [_deser_event(e) for e in block.get("data", [])]
                )
            elif source == "weather":
                data = _deser_weather(block["data"]) if block.get("data") else None
            elif source == "birthdays":
                data = [_deser_birthday(b) for b in block.get("data", [])]
            elif source == "air_quality":
                data = _deser_air_quality(block["data"]) if block.get("data") else None
            else:
                return None
            return data, fetched_at
        except Exception as exc:
            logger.warning("Cache source %r decode failed: %s", source, exc)
            return None
    else:
        # v1 fallback: deserialise the whole legacy object and return the source
        try:
            legacy = _deserialise_v1(raw)
        except Exception:
            return None
        if source == "events":
            return legacy.events, legacy.fetched_at
        elif source == "weather":
            return legacy.weather, legacy.fetched_at
        elif source == "birthdays":
            return legacy.birthdays, legacy.fetched_at
        return None


def save_source(
    source: str,
    data: list | WeatherData | AirQualityData | None,
    fetched_at: datetime,
    cache_dir: str,
) -> None:
    """Update a single source's data in the cache file (v2 format).

    Reads the existing cache first so other sources are preserved, then
    overwrites with the updated content.
    """
    path = Path(cache_dir) / _CACHE_FILENAME
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    if source == "events":
        serialized: list | dict | None = [_ser_event(e) for e in (data or [])]
    elif source == "weather":
        serialized = _ser_weather(data) if data else None  # type: ignore[arg-type]
    elif source == "birthdays":
        serialized = [_ser_birthday(b) for b in (data or [])]  # type: ignore[union-attr]
    elif source == "air_quality":
        serialized = _ser_air_quality(data) if data else None  # type: ignore[arg-type]
    else:
        logger.warning("Unknown cache source: %r", source)
        return

    with _cache_lock:
        # Preserve existing sources when possible
        raw: dict = {"schema_version": _SCHEMA_VERSION}
        if path.exists():
            try:
                with open(path) as f:
                    existing = json.load(f)
                if existing.get("schema_version") == _SCHEMA_VERSION:
                    raw = existing
            except Exception:
                pass  # start fresh

        raw["schema_version"] = _SCHEMA_VERSION
        raw[source] = {"fetched_at": fetched_at.isoformat(), "data": serialized}

        try:
            _atomic_write_json(path, raw)
            logger.debug("Cache source %r written to %s", source, path)
        except Exception as exc:
            logger.warning("Cache write failed for source %r: %s", source, exc)


def save_cache(data: DashboardData, cache_dir: str) -> None:
    """Persist full DashboardData to the cache file (v2 format)."""
    path = Path(cache_dir) / _CACHE_FILENAME
    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, _serialise(data))
        logger.debug("Cache written to %s", path)
    except Exception as exc:
        logger.warning("Cache write failed: %s", exc)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON to *path* atomically via a temp file + rename."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialise(data: DashboardData) -> dict:
    """Serialise to v2 format with per-source timestamps."""
    ts = data.fetched_at.isoformat()
    return {
        "schema_version": _SCHEMA_VERSION,
        "events": {
            "fetched_at": ts,
            "data": [_ser_event(e) for e in data.events],
        },
        "weather": {
            "fetched_at": ts,
            "data": _ser_weather(data.weather) if data.weather else None,
        },
        "birthdays": {
            "fetched_at": ts,
            "data": [_ser_birthday(b) for b in data.birthdays],
        },
    }


def _ser_event(e: CalendarEvent) -> dict:
    return {
        "summary": e.summary,
        "start": e.start.isoformat(),
        "end": e.end.isoformat(),
        "is_all_day": e.is_all_day,
        "location": e.location,
        "calendar_name": e.calendar_name,
        "event_id": e.event_id,
    }


def _ser_weather(w: WeatherData) -> dict:
    return {
        "current_temp": w.current_temp,
        "current_icon": w.current_icon,
        "current_description": w.current_description,
        "high": w.high,
        "low": w.low,
        "humidity": w.humidity,
        "feels_like": w.feels_like,
        "wind_speed": w.wind_speed,
        "wind_deg": w.wind_deg,
        "pressure": w.pressure,
        "uv_index": w.uv_index,
        "sunrise": w.sunrise.isoformat() if w.sunrise else None,
        "sunset": w.sunset.isoformat() if w.sunset else None,
        "forecast": [
            {
                "date": f.date.isoformat(),
                "high": f.high,
                "low": f.low,
                "icon": f.icon,
                "description": f.description,
                "precip_chance": f.precip_chance,
            }
            for f in w.forecast
        ],
        "alerts": [{"event": a.event} for a in w.alerts],
    }


def _ser_birthday(b: Birthday) -> dict:
    return {"name": b.name, "date": b.date.isoformat(), "age": b.age}


def _deserialise(raw: dict) -> DashboardData:
    if raw.get("schema_version") == _SCHEMA_VERSION:
        return _deserialise_v2(raw)
    return _deserialise_v1(raw)


def _deserialise_v2(raw: dict) -> DashboardData:
    events_block = raw.get("events", {})
    weather_block = raw.get("weather", {})
    birthdays_block = raw.get("birthdays", {})

    # Use the most recent per-source fetched_at as the overall timestamp
    timestamps = []
    for block in (events_block, weather_block, birthdays_block):
        if block and block.get("fetched_at"):
            try:
                timestamps.append(datetime.fromisoformat(block["fetched_at"]))
            except ValueError:
                pass
    fetched_at = max(timestamps) if timestamps else datetime.now()

    events = [_deser_event(e) for e in events_block.get("data", [])]
    weather = _deser_weather(weather_block["data"]) if weather_block.get("data") else None
    birthdays = [_deser_birthday(b) for b in birthdays_block.get("data", [])]

    return DashboardData(
        fetched_at=fetched_at,
        events=events,
        weather=weather,
        birthdays=birthdays,
    )


def _deserialise_v1(raw: dict) -> DashboardData:
    """Deserialise legacy v1 flat format."""
    return DashboardData(
        fetched_at=datetime.fromisoformat(raw["fetched_at"]),
        events=[_deser_event(e) for e in raw.get("events", [])],
        weather=_deser_weather(raw["weather"]) if raw.get("weather") else None,
        birthdays=[_deser_birthday(b) for b in raw.get("birthdays", [])],
    )


def _deser_event(e: dict) -> CalendarEvent:
    return CalendarEvent(
        summary=e["summary"],
        start=datetime.fromisoformat(e["start"]),
        end=datetime.fromisoformat(e["end"]),
        is_all_day=e.get("is_all_day", False),
        location=e.get("location"),
        calendar_name=e.get("calendar_name"),
        event_id=e.get("event_id"),
    )


def _deser_weather(w: dict) -> WeatherData:
    sunrise = datetime.fromisoformat(w["sunrise"]) if w.get("sunrise") else None
    sunset = datetime.fromisoformat(w["sunset"]) if w.get("sunset") else None
    return WeatherData(
        current_temp=w["current_temp"],
        current_icon=w["current_icon"],
        current_description=w["current_description"],
        high=w["high"],
        low=w["low"],
        humidity=w["humidity"],
        feels_like=w.get("feels_like"),
        wind_speed=w.get("wind_speed"),
        wind_deg=w.get("wind_deg"),
        pressure=w.get("pressure"),
        uv_index=w.get("uv_index"),
        sunrise=sunrise,
        sunset=sunset,
        forecast=[
            DayForecast(
                date=date.fromisoformat(f["date"]),
                high=f["high"],
                low=f["low"],
                icon=f["icon"],
                description=f["description"],
                precip_chance=f.get("precip_chance"),
            )
            for f in w.get("forecast", [])
        ],
        alerts=[WeatherAlert(event=a["event"]) for a in w.get("alerts", [])],
    )


def _deser_birthday(b: dict) -> Birthday:
    return Birthday(
        name=b["name"],
        date=date.fromisoformat(b["date"]),
        age=b.get("age"),
    )


def _ser_air_quality(aq: AirQualityData) -> dict:
    return {
        "aqi": aq.aqi,
        "category": aq.category,
        "pm25": aq.pm25,
        "pm10": aq.pm10,
        "sensor_id": aq.sensor_id,
        "pm1": aq.pm1,
    }


def _deser_air_quality(d: dict) -> AirQualityData:
    return AirQualityData(
        aqi=d["aqi"],
        category=d["category"],
        pm25=d["pm25"],
        pm10=d.get("pm10"),
        sensor_id=d.get("sensor_id"),
        pm1=d.get("pm1"),
    )
