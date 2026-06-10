"""Live theme preview endpoint.

``POST /api/preview`` renders any registered theme against dummy data and
returns the PNG bytes inline. The web editor uses this to show "what does
the dashboard look like with this theme / these settings?" without
touching the live dashboard timer or hardware.

The optional ``"patch"`` field (same flat ``{"field.path": value}`` shape
as ``POST /api/config``) renders against a *candidate* config built from
the current YAML plus the patch — nothing is persisted, and the same
allowlist/validation pipeline as a real save applies. The editor's
"Live preview" button uses this so unsaved edits (title, display toggles,
coordinates, …) are visible before committing them.
"""

from __future__ import annotations

import io
import logging

from flask import Blueprint, current_app, jsonify, request, send_file

from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import AVAILABLE_THEMES, load_theme
from src.web.config_editor import build_patched_config

logger = logging.getLogger(__name__)

preview_bp = Blueprint("preview", __name__)

# Pseudo-themes resolve at runtime; force them to a concrete pick for previews.
_PSEUDO_THEMES = {"random", "random_daily", "random_hourly"}


@preview_bp.route("/api/preview", methods=["POST"])
def render_preview():
    """Render *theme* against dummy data and return the PNG.

    Request JSON: ``{"theme": "<theme name>"}`` plus an optional
    ``"patch"`` dict of unsaved config edits to preview against.
    Response: ``image/png`` on success, ``application/json`` with an
    ``error`` key on bad input.
    """
    payload = request.get_json(silent=True) or {}
    theme_name = payload.get("theme")
    if not isinstance(theme_name, str) or not theme_name:
        return jsonify({"error": "Request body must include a 'theme' string."}), 400

    patch = payload.get("patch")
    if patch is not None and not isinstance(patch, dict):
        return jsonify({"error": "'patch' must be an object of field-path/value pairs."}), 400

    if theme_name in _PSEUDO_THEMES:
        return (
            jsonify(
                {
                    "error": (
                        "Pseudo-themes are resolved at run-time; pick a concrete theme "
                        "name for the preview."
                    )
                }
            ),
            400,
        )

    if theme_name not in AVAILABLE_THEMES:
        return jsonify({"error": f"Unknown theme: {theme_name!r}"}), 400

    if patch:
        candidate, errors, _warnings = build_patched_config(
            current_app.config["APP_CONFIG_PATH"], patch
        )
        if candidate is None:
            return (
                jsonify(
                    {
                        "error": "Config patch failed validation.",
                        "validation_errors": errors,
                    }
                ),
                400,
            )
        cfg = candidate
    else:
        cfg = current_app.config["DASH_CFG"]

    try:
        theme = load_theme(theme_name)
    except Exception as exc:
        logger.warning("Preview load_theme(%s) failed: %s", theme_name, exc)
        return jsonify({"error": f"Could not load theme: {exc}"}), 500

    try:
        data = generate_dummy_data(tz=None)
        image = render_dashboard(
            data,
            cfg.display,
            title=cfg.title,
            theme=theme,
            quote_refresh=cfg.cache.quote_refresh,
            latitude=cfg.weather.latitude,
            longitude=cfg.weather.longitude,
        )
    except Exception as exc:
        logger.warning("Preview render(%s) failed: %s", theme_name, exc)
        return jsonify({"error": f"Render failed: {exc}"}), 500

    buf = io.BytesIO()
    # Always emit RGB so the browser can display Inky-coloured previews
    # without any backend-specific decoding on the client.
    image.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return send_file(
        buf,
        mimetype="image/png",
        as_attachment=False,
        download_name=f"preview_{theme_name}.png",
    )
