"""Actions blueprint — trigger refresh, reset breakers, clear cache.

Routes:
    POST /api/trigger-refresh           Touch state/web_trigger (path unit picks it up)
    POST /api/reset-breaker             {source} → set breaker state to closed
    POST /api/clear-cache               {source} or {source: "all"} → remove cache entry
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

actions_bp = Blueprint("actions", __name__)

logger = logging.getLogger(__name__)

_VALID_SOURCES = frozenset({"events", "weather", "birthdays", "air_quality"})


@actions_bp.route("/api/trigger-refresh", methods=["POST"])
def trigger_refresh():
    """Create state/web_trigger so the systemd path unit starts dashboard.service."""
    trigger_path = Path(current_app.config["STATE_DIR"]) / "web_trigger"
    try:
        trigger_path.parent.mkdir(parents=True, exist_ok=True)
        trigger_path.touch()
        logger.info("Web trigger created: %s", trigger_path)
        return jsonify({"ok": True, "message": "Refresh triggered"})
    except Exception as exc:
        logger.error("Could not create trigger file: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@actions_bp.route("/api/reset-breaker", methods=["POST"])
def reset_breaker():
    """Reset a named circuit breaker to closed state."""
    body = request.get_json(silent=True) or {}
    source = body.get("source", "")
    if source not in _VALID_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source: {source!r}"}), 400

    state_path = Path(current_app.config["STATE_DIR"]) / "dashboard_breaker_state.json"
    try:
        raw: dict = {}
        if state_path.exists():
            with open(state_path) as f:
                raw = json.load(f)

        raw[source] = {
            "consecutive_failures": 0,
            "last_failure_at": None,
            "state": "closed",
        }
        _atomic_write_json(state_path, raw)
        logger.info("Breaker reset via web UI: source=%s", source)
        return jsonify({"ok": True, "source": source})
    except Exception as exc:
        logger.error("Could not reset breaker for %s: %s", source, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@actions_bp.route("/api/clear-cache", methods=["POST"])
def clear_cache():
    """Remove one or all sources from the dashboard cache."""
    body = request.get_json(silent=True) or {}
    source = body.get("source", "")

    if source != "all" and source not in _VALID_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source: {source!r}"}), 400

    cache_path = Path(current_app.config["STATE_DIR"]) / "dashboard_cache.json"
    try:
        raw: dict = {"schema_version": 2}
        if cache_path.exists():
            with open(cache_path) as f:
                raw = json.load(f)

        if source == "all":
            raw = {"schema_version": 2}
        else:
            raw.pop(source, None)

        _atomic_write_json(cache_path, raw)
        logger.info("Cache cleared via web UI: source=%s", source)
        return jsonify({"ok": True, "source": source})
    except Exception as exc:
        logger.error("Could not clear cache for %s: %s", source, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
