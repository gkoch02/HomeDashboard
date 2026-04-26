"""Config blueprint — view and edit the dashboard configuration.

Routes:
    GET  /config        Config editor HTML page
    GET  /api/config    Current safe config as JSON
    POST /api/config    Validate + save a config patch; returns {saved, errors, warnings}
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, render_template, request

from src.config import load_config
from src.web.config_editor import (
    apply_patch,
    config_write_lock,
    get_config_for_web,
    list_config_backups,
    restore_latest_backup,
)
from src.web.event_store import append_event

logger = logging.getLogger(__name__)

config_bp = Blueprint("config", __name__)

# Themes shown as random-mode options rather than direct selects.
_RANDOM_THEMES = frozenset({"random", "random_daily", "random_hourly"})


def _refresh_in_memory_config(config_path: str) -> bool:
    """Reload DASH_CFG and SOURCE_TTLS in lockstep.

    Stages the new values first, then assigns both keys back-to-back inside
    ``config_write_lock()`` so a concurrent reader never sees a half-applied
    state. Returns True on success; logs a warning and returns False on
    failure (the in-memory config stays at the last-loaded version until
    restart).
    """
    try:
        new_cfg = load_config(config_path)
        new_ttls = {
            "events": new_cfg.cache.events_ttl_minutes,
            "weather": new_cfg.cache.weather_ttl_minutes,
            "birthdays": new_cfg.cache.birthdays_ttl_minutes,
            "air_quality": new_cfg.cache.air_quality_ttl_minutes,
        }
    except Exception as exc:
        logger.warning("Config reload after save failed; in-memory config is stale: %s", exc)
        return False

    with config_write_lock():
        current_app.config["DASH_CFG"] = new_cfg
        current_app.config["SOURCE_TTLS"] = new_ttls
    return True


@config_bp.route("/config")
def config_page():
    config_path = current_app.config["APP_CONFIG_PATH"]
    cfg_data = get_config_for_web(config_path)

    from src.render.theme import AVAILABLE_THEMES

    # Concrete themes only (no random pseudo-themes) for the grid + schedule dropdowns.
    concrete_themes = sorted(t for t in AVAILABLE_THEMES if t not in _RANDOM_THEMES)
    all_theme_options = sorted(AVAILABLE_THEMES)

    return render_template(
        "config.html",
        cfg=cfg_data,
        concrete_themes=concrete_themes,
        all_theme_options=all_theme_options,
    )


@config_bp.route("/api/config")
def get_config():
    config_path = current_app.config["APP_CONFIG_PATH"]
    return jsonify(get_config_for_web(config_path))


@config_bp.route("/api/config/backups")
def get_config_backups():
    config_path = current_app.config["APP_CONFIG_PATH"]
    return jsonify({"backups": list_config_backups(config_path)})


@config_bp.route("/api/config/restore-latest", methods=["POST"])
def restore_config_latest():
    config_path = current_app.config["APP_CONFIG_PATH"]
    restored, message = restore_latest_backup(config_path)
    if restored:
        append_event(current_app.config["STATE_DIR"], "config_restored", message)
        _refresh_in_memory_config(config_path)
    return jsonify({"restored": restored, "message": message})


@config_bp.route("/api/config", methods=["POST"])
def save_config():
    config_path = current_app.config["APP_CONFIG_PATH"]
    patch = request.get_json(silent=True) or {}

    saved, errors, warnings = apply_patch(config_path, patch)

    # Refresh the in-memory config so the status page reflects changes immediately.
    if saved:
        append_event(
            current_app.config["STATE_DIR"],
            "config_saved",
            "Configuration saved from web UI",
            fields=sorted(patch.keys()),
        )
        _refresh_in_memory_config(config_path)

    return jsonify(
        {
            "saved": saved,
            "errors": errors,
            "warnings": warnings,
            "backups": list_config_backups(config_path),
        }
    )
