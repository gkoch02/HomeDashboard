"""Live theme preview endpoint.

``POST /api/preview`` renders any registered theme against dummy data and
returns the PNG bytes inline. The web editor uses this to show "what does
the dashboard look like with this theme / these settings?" without
touching the live dashboard timer or hardware.

Requesting a candidate config patch is intentionally out of scope for
v5.0: previewing arbitrary patches without first persisting them would
require synthesising a temporary ``Config`` and the matching
``DataPipeline`` / ``OutputService``, which doubles the surface area.
The web UI gets the bigger win — visual feedback on theme choice — for
a fraction of the complexity. Patch-preview can be a follow-up.
"""

from __future__ import annotations

import io
import logging

from flask import Blueprint, current_app, jsonify, request, send_file

from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import AVAILABLE_THEMES, load_theme

logger = logging.getLogger(__name__)

preview_bp = Blueprint("preview", __name__)

# Pseudo-themes resolve at runtime; force them to a concrete pick for previews.
_PSEUDO_THEMES = {"random", "random_daily", "random_hourly"}


@preview_bp.route("/api/preview", methods=["POST"])
def render_preview():
    """Render *theme* against dummy data and return the PNG.

    Request JSON: ``{"theme": "<theme name>"}``.
    Response: ``image/png`` on success, ``application/json`` with an
    ``error`` key on bad input.
    """
    payload = request.get_json(silent=True) or {}
    theme_name = payload.get("theme")
    if not isinstance(theme_name, str) or not theme_name:
        return jsonify({"error": "Request body must include a 'theme' string."}), 400

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
