"""Image blueprint — serves rendered dashboard PNGs.

Routes:
    GET /image/latest          Most recent dashboard render (output/latest.png)
    GET /image/theme/<name>    Committed theme preview (assets/previews/theme_<name>.png)
"""

from __future__ import annotations

import re
from pathlib import Path

from flask import Blueprint, current_app, send_file
from werkzeug.exceptions import NotFound

image_bp = Blueprint("image", __name__)

# Allowlist: only filenames matching [a-z0-9_] to prevent path traversal.
_SAFE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _resolve_dir(config_key: str, default_relative: tuple[str, ...]) -> Path:
    """Resolve a Flask app-config dir, with a project-relative default.

    Reads ``current_app.config[config_key]`` if set; otherwise falls back to
    ``<repo_root>/<default_relative...>``.  Relative configured paths are
    likewise resolved against ``<repo_root>``.
    """
    configured = current_app.config.get(config_key)
    if configured is not None:
        candidate = Path(configured)
        if candidate.is_absolute():
            return candidate
        return Path(current_app.root_path).parent.parent / candidate
    return Path(current_app.root_path).parent.parent.joinpath(*default_relative)


def _output_dir() -> Path:
    """Runtime artefacts directory (latest.png lives here)."""
    return _resolve_dir("OUTPUT_DIR", ("output",))


def _preview_dir() -> Path:
    """Committed theme-preview asset directory (assets/previews)."""
    return _resolve_dir("PREVIEW_DIR", ("assets", "previews"))


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
    path = _preview_dir() / f"theme_{name}.png"
    if not path.exists():
        raise NotFound(f"No preview for theme '{name}'. Run 'make previews' to generate them.")
    return send_file(path.resolve(), mimetype="image/png", max_age=3600)
