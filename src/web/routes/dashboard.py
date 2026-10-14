"""Dashboard data blueprint — the cached snapshot as JSON, for clients that draw it themselves.

Routes:
    GET /api/dashboard    Every enabled source from the cache, today's quote and the moon

The payload is read from ``dashboard_cache.json`` and never triggers a fetch:
the systemd timer stays the only caller of the upstream APIs, so a client
polling this route costs no quota. Each source carries its own ``fetched_at``
and staleness, and an expired source is sent with ``data: null``, which is how
the renderer treats it. Events pass through the configured filters, so a
client shows what the panel shows.

Event times are stored as naive local wall-clock; they are sent with the
configured zone's offset attached, so a client in another zone still places
them correctly. ``schema_version`` changes whenever a field is removed or
changes meaning; new optional fields do not bump it.

``moon`` is computed per request, like the moonphase panel's data block: it is pure
math (``src/render/moon.py``, ``src/astronomy.py``), so a client draws the phase without
porting the astronomy, and both agree on it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify

from src._time import now_local, to_aware
from src.astronomy import moon_times
from src.data.models import StalenessLevel
from src.fetchers.cache import check_staleness, load_cache_blob, load_cached_source_from_blob
from src.fetchers.registry import get_fetcher
from src.filters import filter_events
from src.render.components.moonphase_panel import is_supermoon
from src.render.moon import (
    moon_illumination,
    moon_phase_age,
    moon_phase_fraction,
    moon_phase_name,
    next_full_moon,
    next_new_moon,
)
from src.render.primitives import usable_coords
from src.render.quotes import quote_for
from src.web.sources import source_names
from src.web.state_reader import config_tz

dashboard_bp = Blueprint("dashboard", __name__)

SCHEMA_VERSION = 1


def _zone_name(tz) -> str | None:
    """The IANA name of *tz* when it has one; a fixed-offset ``local`` zone has none."""
    return getattr(tz, "key", None)


def _attach_zone(naive: datetime, cfg, tz) -> datetime:
    """*naive* local wall-clock with the offset it has on its own date.

    ``local`` resolves to a fixed offset taken from the current moment, which would put
    an event on the far side of a DST change an hour out; the host's local rules apply
    the offset in force on the event's date instead.
    """
    if naive.tzinfo is not None:
        return naive
    if getattr(cfg, "timezone", "local") == "local":
        return naive.astimezone()
    return to_aware(naive, tz)


def _source_block(name: str, blob: dict | None, cfg, tz, now: datetime) -> dict | None:
    """One source's entry, or None when the source is disabled in config."""
    fetcher = get_fetcher(name)
    if fetcher is None or not fetcher.enabled(cfg):
        return None
    decoded = load_cached_source_from_blob(name, blob)
    if decoded is None:
        return {"fetched_at": None, "staleness": "unknown", "data": None}
    data, fetched_at = decoded
    staleness = check_staleness(
        fetched_at.astimezone(timezone.utc),
        fetcher.ttl_minutes(cfg),
        now=now.astimezone(timezone.utc),
    )
    if staleness is StalenessLevel.EXPIRED:
        payload = None
    elif name == "events" and isinstance(data, list):
        payload = fetcher.serialize(filter_events(data, cfg.filters))
        for event in payload:
            for key in ("start", "end"):
                event[key] = _attach_zone(datetime.fromisoformat(event[key]), cfg, tz).isoformat()
    else:
        payload = fetcher.serialize(data)
    return {
        "fetched_at": fetched_at.isoformat(),
        "staleness": staleness.value,
        "data": payload,
    }


def _moon(cfg, tz, now: datetime) -> dict:
    """Today's moon and the six days around it, as the moonphase panel computes them.

    ``fraction`` is the point in the lunation at noon UTC on the day (0 new, 0.5 full;
    waxing below 0.5), which is what a client needs to draw the terminator. ``rise`` and
    ``set`` are present only when the dashboard has coordinates, as on the panel.
    """
    today = now.date()
    full_date, full_days = next_full_moon(today, tz)
    new_date, new_days = next_new_moon(today, tz)
    if full_days <= new_days:
        upcoming = {"kind": "full", "date": full_date.isoformat(), "days": full_days}
    else:
        upcoming = {"kind": "new", "date": new_date.isoformat(), "days": new_days}

    rise = moonset = None
    coords = usable_coords(cfg.weather.latitude, cfg.weather.longitude)
    if coords is not None:
        times = moon_times(today, *coords, tz=tz)
        rise = times.rise.astimezone(tz).isoformat() if times.rise else None
        moonset = times.set.astimezone(tz).isoformat() if times.set else None

    def day(d) -> dict:
        return {
            "date": d.isoformat(),
            "age_days": round(moon_phase_age(d), 2),
            "fraction": round(moon_phase_fraction(d), 4),
            "illumination": round(moon_illumination(d), 1),
        }

    quote = quote_for(
        today,
        refresh=cfg.cache.quote_refresh,
        prefix="moonphase-",
        path=Path(cfg.quotes.path) if cfg.quotes.path else None,
    )
    return {
        "phase_name": moon_phase_name(today),
        "supermoon": is_supermoon(today),
        "rise": rise,
        "set": moonset,
        "next": upcoming,
        "days": [day(today + timedelta(days=delta)) for delta in range(-3, 4)],
        "quote": {"text": quote["text"], "author": quote["author"]},
    }


def _units(sources: dict[str, dict], cfg) -> str:
    """The units the weather on screen is in: the cached entry's own, falling back to config.

    After ``weather.units`` changes, a still-fresh cache holds values in the old units until
    the next fetch, so reading the config would label 68 °F as 68 °C.
    """
    weather = (sources.get("weather") or {}).get("data") or {}
    return weather.get("units") or cfg.weather.units


@dashboard_bp.route("/api/dashboard")
def api_dashboard():
    cfg = current_app.config["DASH_CFG"]
    tz = config_tz(cfg)
    now = now_local(tz)
    blob = load_cache_blob(current_app.config["STATE_DIR"])

    sources: dict[str, dict] = {}
    for name in source_names():
        block = _source_block(name, blob, cfg, tz, now)
        if block is not None:
            sources[name] = block

    # Called as qotd_panel and info_panel call it, so a sub-daily cadence buckets on the
    # same clock and the TV shows the panel's quote.
    quote = quote_for(
        now.date(),
        refresh=cfg.cache.quote_refresh,
        path=Path(cfg.quotes.path) if cfg.quotes.path else None,
    )
    return jsonify(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now.isoformat(),
            "timezone": _zone_name(tz),
            "utc_offset_seconds": int((now.utcoffset() or timedelta(0)).total_seconds()),
            "units": _units(sources, cfg),
            "quote": {"text": quote["text"], "author": quote["author"]},
            "moon": _moon(cfg, tz, now),
            "sources": sources,
        }
    )
