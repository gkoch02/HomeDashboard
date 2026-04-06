"""Config blueprint — view and edit the dashboard configuration.

Routes:
    GET  /config        Config editor HTML page
    GET  /api/config    Current safe config as JSON
    POST /api/config    Validate + save a config patch; returns {saved, errors, warnings}
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request

from src.web.config_editor import apply_patch, get_config_for_web

config_bp = Blueprint("config", __name__)

# Themes shown as random-mode options rather than direct selects.
_RANDOM_THEMES = frozenset({"random", "random_daily", "random_hourly"})


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


@config_bp.route("/api/config", methods=["POST"])
def save_config():
    config_path = current_app.config["APP_CONFIG_PATH"]
    patch = request.get_json(silent=True) or {}

    saved, errors, warnings = apply_patch(config_path, patch)

    # Refresh the in-memory config so the status page reflects changes immediately.
    if saved:
        try:
            from src.config import load_config

            current_app.config["DASH_CFG"] = load_config(config_path)
            new_cfg = current_app.config["DASH_CFG"]
            current_app.config["SOURCE_TTLS"] = {
                "events": new_cfg.cache.events_ttl_minutes,
                "weather": new_cfg.cache.weather_ttl_minutes,
                "birthdays": new_cfg.cache.birthdays_ttl_minutes,
                "air_quality": new_cfg.cache.air_quality_ttl_minutes,
            }
        except Exception:
            pass  # Stale in-memory config is harmless until restart.

    return jsonify({"saved": saved, "errors": errors, "warnings": warnings})
