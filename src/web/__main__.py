"""Entry point: python -m src.web

Usage:
    python -m src.web
    python -m src.web --config config/web.yaml --app-config config/config.yaml
    python -m src.web --port 8080
"""

from __future__ import annotations

import argparse
import logging

from src.web.app import _load_web_config, create_app


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dashboard web UI server")
    p.add_argument(
        "--config",
        default="config/web.yaml",
        metavar="PATH",
        help="Web UI config file (auth credentials, port). Default: config/web.yaml",
    )
    p.add_argument(
        "--app-config",
        default="config/config.yaml",
        metavar="PATH",
        help="Dashboard app config file. Default: config/config.yaml",
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="Override port from config (default: 8080)",
    )
    p.add_argument(
        "--host",
        default=None,
        metavar="HOST",
        help="Bind address (default: 127.0.0.1)",
    )
    return p


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    args = build_parser().parse_args()

    # Use the factory's reader so broken auth configuration cannot become defaults.
    try:
        web_cfg = _load_web_config(args.config)
    except ValueError as exc:
        logging.error("%s", exc)
        raise SystemExit(1) from exc

    port = args.port or web_cfg.get("port", 8080)
    host = args.host or web_cfg.get("host", "127.0.0.1")

    app = create_app(
        web_config_path=args.config,
        app_config_path=args.app_config,
    )

    try:
        from waitress import serve

        logging.getLogger(__name__).info("Serving on http://%s:%d (waitress)", host, port)
        serve(app, host=host, port=port, threads=2)
    except ImportError:
        logging.getLogger(__name__).warning(
            "waitress not installed — falling back to Flask dev server (not for production)"
        )
        app.run(host=host, port=port)


if __name__ == "__main__":
    main()
