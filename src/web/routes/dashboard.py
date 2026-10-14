"""Dashboard data blueprint — the cached snapshot as JSON, for clients that draw it themselves.

Routes:
    GET /api/dashboard    Every enabled source from the cache, plus today's quote

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
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify

from src._time import now_local, to_aware
from src.data.models import StalenessLevel
from src.fetchers.cache import check_staleness, load_cache_blob, load_cached_source_from_blob
from src.fetchers.registry import get_fetcher
from src.filters import filter_events
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
            "units": cfg.weather.units,
            "quote": {"text": quote["text"], "author": quote["author"]},
            "sources": sources,
        }
    )
