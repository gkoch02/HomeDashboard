"""Actions blueprint — trigger refresh, reset breakers, clear cache.

Routes:
    POST /api/trigger-refresh           Touch state/web_trigger (path unit picks it up)
    POST /api/reset-breaker             {source} → set breaker state to closed
    POST /api/clear-cache               {source} or {source: "all"} → remove cache entry
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from src._io import locked_update_json
from src.web.event_store import append_event
from src.web.sources import is_known_source

actions_bp = Blueprint("actions", __name__)

logger = logging.getLogger(__name__)


@actions_bp.route("/api/trigger-refresh", methods=["POST"])
def trigger_refresh():
    """Create state/web_trigger so the systemd path unit starts dashboard.service."""
    trigger_path = Path(current_app.config["STATE_DIR"]) / "web_trigger"
    try:
        trigger_path.parent.mkdir(parents=True, exist_ok=True)
        trigger_path.touch()
        logger.info("Web trigger created: %s", trigger_path)
        append_event(
            current_app.config["STATE_DIR"], "refresh_requested", "Manual refresh requested"
        )
        return jsonify({"ok": True, "message": "Refresh triggered"})
    except Exception as exc:
        logger.error("Could not create trigger file: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@actions_bp.route("/api/reset-breaker", methods=["POST"])
def reset_breaker():
    """Reset a named circuit breaker to closed state."""
    body = request.get_json(silent=True) or {}
    source = body.get("source", "")
    if not is_known_source(source):
        return jsonify({"ok": False, "error": f"Unknown source: {source!r}"}), 400

    state_path = Path(current_app.config["STATE_DIR"]) / "dashboard_breaker_state.json"

    def _reset(raw: dict) -> dict:
        raw[source] = {
            "consecutive_failures": 0,
            "last_failure_at": None,
            "state": "closed",
        }
        return raw

    try:
        # Read-modify-write under one lock. The renderer rewrites this file
        # wholesale from a separate process on every fetch, and a reset is most
        # likely to be pressed *while* a run is in flight — unlocked, whichever
        # process wrote last erased the other's change, so a reset could report
        # success while the breaker stayed open (#242).
        locked_update_json(state_path, _reset, default={}, indent=2)
        logger.info("Breaker reset via web UI: source=%s", source)
        append_event(
            current_app.config["STATE_DIR"],
            "breaker_reset",
            f"Breaker reset for {source}",
            source=source,
        )
        return jsonify({"ok": True, "source": source})
    except Exception as exc:
        logger.error("Could not reset breaker for %s: %s", source, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@actions_bp.route("/api/clear-cache", methods=["POST"])
def clear_cache():
    """Remove one or all sources from the dashboard cache."""
    body = request.get_json(silent=True) or {}
    source = body.get("source", "")

    if source != "all" and not is_known_source(source):
        return jsonify({"ok": False, "error": f"Unknown source: {source!r}"}), 400

    cache_path = Path(current_app.config["STATE_DIR"]) / "dashboard_cache.json"

    def _clear(raw: dict) -> dict:
        if source == "all":
            return {"schema_version": 2}
        raw.pop(source, None)
        return raw

    try:
        # Same lock as the breaker reset: unlocked, a source the renderer had
        # just refreshed could be resurrected from this process's stale read,
        # or a just-saved source silently dropped (#242).
        locked_update_json(cache_path, _clear, default={"schema_version": 2}, indent=2)
        logger.info("Cache cleared via web UI: source=%s", source)
        append_event(
            current_app.config["STATE_DIR"],
            "cache_cleared",
            f"Cache cleared for {source}",
            source=source,
        )
        return jsonify({"ok": True, "source": source})
    except Exception as exc:
        logger.error("Could not clear cache for %s: %s", source, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
