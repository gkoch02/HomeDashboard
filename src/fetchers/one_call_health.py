"""Persisted health state for the OpenWeatherMap One Call fetch.

One Call supplies exactly two values — weather alerts and the UV index — and
its failure is deliberately silent: ``weather._fetch_alerts_and_uv`` turns any
error into ``([], None)`` so a render can never be broken by them. That
contract is worth keeping, but it used to make a *permanent* misconfiguration
indistinguishable from a ten-second read timeout: both produced one DEBUG line
and no other trace.

The two failures want different handling. A timeout is transient and genuinely
fine at DEBUG. An HTTP 401 or 403 is not: an account holds a subscription to
either 3.0 or 4.0 and never both, so calling the wrong one 401s exactly like
holding no subscription at all. That happens after a working install too — a
lapsed subscription, a product migration, a key rotated to one without the
entitlement — and the symptom is alerts and UV quietly vanishing while the run
still succeeds and the status page stays green.

So this module records the outcome across runs. The renderer is a short-lived
timer job, so in-process deduplication would warn on every tick; persisting the
state means the WARNING fires once on the healthy→failing transition, and the
web UI can read the same file to show why alerts stopped arriving.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src._io import atomic_write_json
from src._time import now_utc

logger = logging.getLogger(__name__)

STATE_FILENAME = "one_call_health.json"

# Outcomes recorded in the state file.
OK = "ok"
AUTH_FAILED = "auth_failed"
TRANSIENT = "transient"


def _state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / STATE_FILENAME


def _http_status(exc: BaseException) -> int | None:
    """Return the HTTP status carried by *exc*, if it carries one.

    Read defensively rather than by isinstance: this runs inside a degradation
    boundary, and an attribute lookup that raised here would defeat the whole
    point of that boundary.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def classify(exc: BaseException) -> tuple[str, int | None]:
    """Classify a One Call failure as permanent or transient.

    Returns ``(outcome, http_status)`` where *outcome* is :data:`AUTH_FAILED`
    for the two statuses that mean "this key cannot call this product" and
    :data:`TRANSIENT` for everything else — timeouts, connection errors, 5xx,
    and unexpected payloads, none of which an operator can act on.
    """
    status = _http_status(exc)
    if status in (401, 403):
        return AUTH_FAILED, status
    return TRANSIENT, status


def describe(outcome: str, version: str, status: int | None) -> str:
    """One actionable sentence about *outcome*, for logs and the web UI."""
    if outcome != AUTH_FAILED:
        return f"One Call {version} request failed."
    return (
        f"One Call {version} returned {status} — the API key is not subscribed to "
        f"this version. Check weather.one_call_version against your OpenWeather "
        f"subscription (an account can hold only one)."
    )


def read_health(state_dir: str | Path) -> dict[str, Any]:
    """Return the recorded One Call health, degrading to ``{}`` when absent.

    ``{}`` means "nothing recorded" — a fresh install, One Call turned off, or
    a state directory that was cleared. Callers should treat it as unknown
    rather than healthy.
    """
    path = _state_path(state_dir)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            raw = json.load(f)
    except Exception as exc:
        logger.debug("Could not read One Call health state: %s", exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def _write(state_dir: str | Path, payload: dict[str, Any]) -> None:
    try:
        atomic_write_json(_state_path(state_dir), payload, indent=2)
    except Exception as exc:
        # Health bookkeeping must never be the thing that breaks a fetch.
        logger.debug("Could not persist One Call health state: %s", exc)


def record_success(state_dir: str | Path | None, version: str) -> None:
    """Record a successful One Call fetch, clearing any recorded failure."""
    if state_dir is None:
        return
    previous = read_health(state_dir).get("outcome")
    if previous == AUTH_FAILED:
        logger.info("One Call %s is answering again; alerts and UV have resumed.", version)
    _write(
        state_dir,
        {"outcome": OK, "version": version, "checked_at": now_utc().isoformat()},
    )


def record_failure(state_dir: str | Path | None, version: str, exc: BaseException) -> str:
    """Record a failed One Call fetch and log it at the level it deserves.

    A permanent failure is logged at WARNING the first time it appears, and at
    DEBUG while it persists, so a misconfiguration is visible without emitting
    a line every ``weather_fetch_interval``. A transient failure stays at DEBUG
    throughout. Returns the classified outcome.
    """
    outcome, status = classify(exc)
    message = describe(outcome, version, status)

    if outcome != AUTH_FAILED:
        logger.debug("Weather alerts/UV fetch skipped: %s", exc)
    else:
        previously = read_health(state_dir).get("outcome") if state_dir is not None else None
        if previously == AUTH_FAILED:
            logger.debug("%s (unchanged since the last run)", message)
        else:
            logger.warning("%s", message)

    if state_dir is not None:
        _write(
            state_dir,
            {
                "outcome": outcome,
                "version": version,
                "http_status": status,
                "message": message,
                "detail": str(exc),
                "checked_at": now_utc().isoformat(),
            },
        )
    return outcome
