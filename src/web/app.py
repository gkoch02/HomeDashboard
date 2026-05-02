"""Flask application factory for the Dashboard web UI.

Usage::

    from src.web.app import create_app
    app = create_app("config/web.yaml", "config/config.yaml")

The factory is intentionally thin — it loads config, wires auth, and registers
blueprints. Routes live in src/web/routes/.

P1 blueprints (read-only status):
    status_bp   — GET /  and  GET /api/status
    image_bp    — GET /image/latest  and  GET /image/theme/<name>
    logs_bp     — GET /api/logs

P2 blueprints (config controls):
    config_bp   — GET /config  GET/POST /api/config
    actions_bp  — POST /api/trigger-refresh  /api/reset-breaker  /api/clear-cache
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from flask import Flask

from src.config import load_config
from src.web.auth import make_auth_middleware

logger = logging.getLogger(__name__)


def _load_web_config(path: str | None) -> dict:
    """Load web.yaml; return an empty dict if absent or unreadable."""
    if not path or not Path(path).exists():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Could not load web config %s: %s", path, exc)
        return {}


def create_app(
    web_config_path: str | None = None,
    app_config_path: str | None = None,
) -> Flask:
    """Create and configure the Flask application.

    Args:
        web_config_path:  Path to config/web.yaml (auth credentials, port).
        app_config_path:  Path to config/config.yaml (dashboard config for TTLs etc.).
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # --- Load configs ---
    web_cfg = _load_web_config(web_config_path)
    app.secret_key = web_cfg.get("secret_key") or "dashboard-web-dev-secret"
    dash_cfg = None
    if app_config_path and Path(app_config_path).exists():
        try:
            dash_cfg = load_config(app_config_path)
        except Exception as exc:
            logger.warning("Could not load dashboard config %s: %s", app_config_path, exc)

    if dash_cfg is None:
        from src.config import Config

        dash_cfg = Config()

    # --- Store runtime paths and config in app.config ---
    app.config["DASH_CFG"] = dash_cfg
    app.config["STATE_DIR"] = dash_cfg.state_dir
    app.config["OUTPUT_DIR"] = dash_cfg.output_dir
    app.config["APP_CONFIG_PATH"] = app_config_path or "config/config.yaml"
    app.config["WEB_AUTH_ENABLED"] = bool(
        web_cfg.get("auth", {}).get("username") and web_cfg.get("auth", {}).get("password_hash")
    )

    # Derived TTL map for staleness calculations.
    app.config["SOURCE_TTLS"] = {
        "events": dash_cfg.cache.events_ttl_minutes,
        "weather": dash_cfg.cache.weather_ttl_minutes,
        "birthdays": dash_cfg.cache.birthdays_ttl_minutes,
        "air_quality": dash_cfg.cache.air_quality_ttl_minutes,
    }

    # --- CSRF + template globals ---
    from src.web.csrf import csrf_protect, get_csrf_token

    @app.before_request
    def _csrf_for_mutations():
        from flask import request

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf_protect()

    app.jinja_env.globals["csrf_token"] = get_csrf_token

    # --- Auth ---
    auth_section = web_cfg.get("auth", {})
    auth_fn = make_auth_middleware(
        username=auth_section.get("username"),
        password_hash=auth_section.get("password_hash"),
    )
    app.before_request(auth_fn)

    # --- Register P1 blueprints ---
    from src.web.routes.image import image_bp
    from src.web.routes.logs import logs_bp
    from src.web.routes.status import status_bp

    app.register_blueprint(status_bp)
    app.register_blueprint(image_bp)
    app.register_blueprint(logs_bp)

    # P2 blueprints
    from src.web.routes.actions import actions_bp
    from src.web.routes.config import config_bp
    from src.web.routes.preview import preview_bp

    app.register_blueprint(config_bp)
    app.register_blueprint(actions_bp)
    app.register_blueprint(preview_bp)

    logger.info(
        "Web UI started — state_dir=%s output_dir=%s",
        app.config["STATE_DIR"],
        app.config["OUTPUT_DIR"],
    )
    return app
