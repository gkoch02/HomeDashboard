"""Image blueprint — serves rendered dashboard PNGs.

Routes:
    GET /image/latest          Most recent dashboard render (output/latest.png)
    GET /image/theme/<name>    Pre-generated theme preview (output/theme_<name>.png)
"""

from __future__ import annotations

import re
from pathlib import Path

from flask import Blueprint, current_app, send_file
from werkzeug.exceptions import NotFound

image_bp = Blueprint("image", __name__)

# Allowlist: only filenames matching [a-z0-9_] to prevent path traversal.
_SAFE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _output_dir() -> Path:
    configured = Path(current_app.config["OUTPUT_DIR"])
    if configured.is_absolute():
        return configured
    return Path(current_app.root_path).parent.parent / configured


@image_bp.route("/image/latest")
def latest():
    path = _output_dir() / "latest.png"
    if not path.exists():
        raise NotFound("No dashboard image has been rendered yet.")
    response = send_file(path.resolve(), mimetype="image/png", max_age=0)
    # Prevent all caching so the browser always fetches a fresh copy.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@image_bp.route("/image/theme/<name>")
def theme_preview(name: str):
    if not _SAFE_NAME_RE.match(name):
        raise NotFound("Invalid theme name.")
    path = _output_dir() / f"theme_{name}.png"
    if not path.exists():
        raise NotFound(f"No preview for theme '{name}'. Run 'make previews' to generate them.")
    return send_file(path.resolve(), mimetype="image/png", max_age=3600)
