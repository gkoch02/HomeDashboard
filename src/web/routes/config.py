"""Config blueprint — view and edit the dashboard configuration.

Routes:
    GET  /config        Config editor HTML page
    GET  /api/config    Current safe config as JSON
    POST /api/config    Validate + save a config patch; returns {saved, errors, warnings}
"""

from __future__ import annotations

import logging

import yaml  # type: ignore[import-untyped]
from flask import Blueprint, current_app, jsonify, render_template, request

from src.config import load_config
from src.config_schema import to_json as schema_to_json
from src.web.config_editor import (
    apply_patch,
    config_write_lock,
    get_config_for_web,
    list_config_backups,
    restore_latest_backup,
)
from src.web.event_store import append_event
from src.web.sources import source_ttls

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
        new_ttls = source_ttls(new_cfg)
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

    from src.config_schema import LOG_LEVELS, QUANTIZATION_MODES

    return render_template(
        "config.html",
        cfg=cfg_data,
        concrete_themes=concrete_themes,
        all_theme_options=all_theme_options,
        log_levels=LOG_LEVELS,
        quantization_modes=QUANTIZATION_MODES,
    )


@config_bp.route("/api/config")
def get_config():
    config_path = current_app.config["APP_CONFIG_PATH"]
    return jsonify(get_config_for_web(config_path))


@config_bp.route("/api/config/backups")
def get_config_backups():
    config_path = current_app.config["APP_CONFIG_PATH"]
    return jsonify({"backups": list_config_backups(config_path)})


@config_bp.route("/api/config/schema")
def get_config_schema():
    """Return the v5 config schema with current values inlined.

    Every field, its label, type, choices, and whether it is secret or
    editable; secret fields carry a ``has_value`` boolean instead of a
    value. This is a machine-readable view for API clients and tooling —
    the config page's form is still hand-written in ``config.html``, and
    ``tests/test_web_config_schema_coverage.py`` holds the two together.
    """
    config_path = current_app.config["APP_CONFIG_PATH"]
    cfg_data = get_config_for_web(config_path)
    values = _flatten_for_schema(cfg_data)
    return jsonify(schema_to_json(values=values))


def _flatten_for_schema(cfg_for_web: dict) -> dict:
    """Flatten the nested ``get_config_for_web`` output to dotted-path keys.

    A secret surfaces as ``_<name>_set``; that flag becomes the secret's
    ``has_value`` only when ``<section>.<name>`` really is a secret schema
    path. The suffix alone is not enough: ``purpleair._sensor_id_set`` is a
    display flag for a plain int field, and reading it as the value reported
    the sensor ID as ``True`` (#308). Other ``_``-prefixed keys are read-only
    values (``display._model``, ``google._calendar_id``) and keep their
    public path.
    """
    from src.config_schema import secret_field_paths

    secrets = secret_field_paths()
    out: dict[str, object] = {}
    for top_key, value in cfg_for_web.items():
        if top_key == "theme_rules_yaml":
            try:
                out["theme_rules"] = yaml.safe_load(value or "") or []
            except yaml.YAMLError:
                out["theme_rules"] = []
            continue
        if not isinstance(value, dict):
            out[top_key] = value
            continue
        for inner_key, inner_value in value.items():
            if not inner_key.startswith("_"):
                out[f"{top_key}.{inner_key}"] = inner_value
                continue
            name = inner_key[1:]
            if name.endswith("_set"):
                path = f"{top_key}.{name[:-4]}"
                if path in secrets:
                    out[path] = inner_value
                continue
            out[f"{top_key}.{name}"] = inner_value
    return out


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
