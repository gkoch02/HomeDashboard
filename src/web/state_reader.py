"""Read-only accessors for all Dashboard-v4 runtime state files.

All functions are pure reads — no side effects, no writes. Each function
degrades gracefully (returns empty/None) when state files are absent or corrupt,
so the web UI never crashes due to a missing state file.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from src.fetchers.cache import check_staleness
from src.fetchers.host import fetch_host_data
from src.services.run_policy import in_quiet_hours

logger = logging.getLogger(__name__)

_SOURCES = ("events", "weather", "birthdays", "air_quality")


def read_last_success(output_dir: str) -> dict:
    """Return last-run info from output/last_success.txt.

    Returns::

        {
            "timestamp": "2026-04-06T14:35:00",   # ISO string or None
            "seconds_since": 142,                  # int or None
        }
    """
    path = Path(output_dir) / "last_success.txt"
    if not path.exists():
        return {"timestamp": None, "seconds_since": None}
    try:
        raw = path.read_text().strip()
        ts = datetime.fromisoformat(raw)
        now = datetime.now(timezone.utc)
        # Normalise: if ts is naive treat it as local time.
        if ts.tzinfo is None:
            ts = ts.astimezone(timezone.utc)
        seconds_since = int((now - ts).total_seconds())
        return {"timestamp": ts.isoformat(), "seconds_since": max(0, seconds_since)}
    except Exception as exc:
        logger.debug("Could not read last_success.txt: %s", exc)
        return {"timestamp": None, "seconds_since": None}


def read_breakers(state_dir: str) -> dict[str, dict]:
    """Return per-source circuit breaker states.

    Returns a dict keyed by source name::

        {
            "weather": {"state": "closed", "consecutive_failures": 0, "last_failure_at": None},
            ...
        }

    Missing sources default to state="closed", 0 failures.
    """
    path = Path(state_dir) / "dashboard_breaker_state.json"
    raw: dict = {}
    if path.exists():
        try:
            with open(path) as f:
                raw = json.load(f)
        except Exception as exc:
            logger.debug("Could not read breaker state: %s", exc)

    result = {}
    for source in _SOURCES:
        entry = raw.get(source, {})
        result[source] = {
            "state": entry.get("state", "closed"),
            "consecutive_failures": entry.get("consecutive_failures", 0),
            "last_failure_at": entry.get("last_failure_at"),
        }
    return result


def read_cache_ages(state_dir: str, ttls: dict[str, int]) -> dict[str, dict]:
    """Return per-source cache age and staleness level.

    *ttls* maps source name → TTL in minutes (used to compute staleness).

    Returns a dict keyed by source name::

        {
            "weather": {
                "cache_age_minutes": 18.3,   # or None if never cached
                "staleness": "fresh",         # fresh / aging / stale / expired / unknown
                "fetched_at": "2026-04-06T14:17:00",
            },
            ...
        }
    """
    path = Path(state_dir) / "dashboard_cache.json"
    raw: dict = {}
    if path.exists():
        try:
            with open(path) as f:
                raw = json.load(f)
        except Exception as exc:
            logger.debug("Could not read cache: %s", exc)

    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc)
    result: dict[str, dict] = {}
    for source in _SOURCES:
        block = raw.get(source)
        if not block or not block.get("fetched_at"):
            result[source] = {"cache_age_minutes": None, "staleness": "unknown", "fetched_at": None}
            continue
        try:
            fetched_at = datetime.fromisoformat(block["fetched_at"])
            if fetched_at.tzinfo is None:
                age_minutes = (now_local - fetched_at).total_seconds() / 60
                staleness = check_staleness(fetched_at, ttls.get(source, 60), now=now_local)
            else:
                fetched_at_utc = fetched_at.astimezone(timezone.utc)
                age_minutes = (now_utc - fetched_at_utc).total_seconds() / 60
                staleness = check_staleness(fetched_at_utc, ttls.get(source, 60), now=now_utc)
            result[source] = {
                "cache_age_minutes": round(age_minutes, 1),
                "staleness": staleness.value,
                "fetched_at": block["fetched_at"],
            }
        except Exception as exc:
            logger.debug("Could not parse cache entry for %s: %s", source, exc)
            result[source] = {"cache_age_minutes": None, "staleness": "unknown", "fetched_at": None}
    return result


def read_quota(state_dir: str) -> dict[str, int]:
    """Return today's API call counts per source.

    Returns a dict like ``{"google": 5, "weather": 2, ...}``.
    If the quota file is from a previous day the counts are still returned
    (for display purposes the date is shown alongside them).
    """
    path = Path(state_dir) / "api_quota_state.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            raw = json.load(f)
        return dict(raw.get("counts", {}))
    except Exception as exc:
        logger.debug("Could not read quota state: %s", exc)
        return {}


def read_host_metrics() -> dict | None:
    """Return host system metrics as a plain dict (or None on total failure)."""
    host = fetch_host_data()
    if host is None:
        return None
    return {
        "hostname": host.hostname,
        "uptime_seconds": host.uptime_seconds,
        "load_1m": host.load_1m,
        "load_5m": host.load_5m,
        "load_15m": host.load_15m,
        "ram_used_mb": host.ram_used_mb,
        "ram_total_mb": host.ram_total_mb,
        "disk_used_gb": host.disk_used_gb,
        "disk_total_gb": host.disk_total_gb,
        "cpu_temp_c": host.cpu_temp_c,
        "ip_address": host.ip_address,
    }


def is_quiet_hours_now(quiet_hours_start: int, quiet_hours_end: int) -> bool:
    """Return True if the current local time falls in the quiet window."""
    return in_quiet_hours(datetime.now(), quiet_hours_start, quiet_hours_end)


def read_log_tail(output_dir: str, n: int = 100) -> list[str]:
    """Return the last *n* lines from output/dashboard.log.

    Uses a fixed-size deque so large log files are never fully loaded into memory.
    Returns an empty list if the log file does not exist.
    """
    path = Path(output_dir) / "dashboard.log"
    if not path.exists():
        return []
    try:
        lines: deque[str] = deque(maxlen=n)
        with open(path, errors="replace") as f:
            for line in f:
                lines.append(line.rstrip("\n"))
        return list(lines)
    except Exception as exc:
        logger.debug("Could not read log: %s", exc)
        return []
