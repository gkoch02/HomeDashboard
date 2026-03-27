import argparse

from src._version import __version__
from src.render.theme import AVAILABLE_THEMES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Home Dashboard for eInk display")
    parser.add_argument(
        "--dry-run", action="store_true", help="Render to PNG instead of display",
    )
    parser.add_argument(
        "--config", default="config/config.yaml", help="Path to config file",
    )
    parser.add_argument(
        "--force-full-refresh", action="store_true", help="Force a full display refresh",
    )
    parser.add_argument(
        "--ignore-breakers",
        action="store_true",
        help="Ignore circuit breaker OPEN state for this run and attempt fetches anyway",
    )
    parser.add_argument(
        "--dummy", action="store_true",
        help="Use dummy data instead of fetching from APIs",
    )
    parser.add_argument(
        "--check-config", action="store_true",
        help="Validate config and exit without rendering",
    )
    parser.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Override 'today' for the dry-run preview (e.g. 2025-12-25). "
            "Only meaningful with --dry-run."
        ),
    )
    parser.add_argument(
        "--theme",
        choices=sorted(AVAILABLE_THEMES),
        default=None,
        metavar="THEME",
        help=(
            "Override the theme from config. "
            f"Choices: {', '.join(sorted(AVAILABLE_THEMES))}"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    return parser


def parse_args(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.date is not None and not args.dry_run:
        parser.error("--date requires --dry-run")
    return args
