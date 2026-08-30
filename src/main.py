import logging

from src.app import DashboardApp
from src.cli import parse_args
from src.config import load_config, print_validation_report, validate_config

logger = logging.getLogger(__name__)


def resolve_log_level(name: str) -> int:
    """Return the logging level for *name*, falling back to INFO.

    ``getattr(logging, name)`` is not safe here: a lowercase level resolves to
    the *function* of that name (``logging.info``), which ``setLevel`` rejects
    with ``TypeError`` — so ``level: info`` in config.yaml crashed every run
    before the renderer started. ``getLevelName`` returns the int for a known
    name and a ``"Level <x>"`` string for anything else, which is the fallback
    signal.
    """
    level = logging.getLevelName(str(name).strip().upper())
    return level if isinstance(level, int) else logging.INFO


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    logging.getLogger().setLevel(resolve_log_level(cfg.log_level))

    errors, warnings = validate_config(cfg, config_path=args.config)
    if args.check_config:
        print_validation_report(errors, warnings)
        raise SystemExit(1 if errors else 0)
    if errors:
        print_validation_report(errors, warnings)
        logger.error("Config has fatal errors — fix them or run with --check-config for details.")
        raise SystemExit(1)
    if warnings and not args.dummy:
        print_validation_report(errors, warnings)

    app = DashboardApp(cfg, args)
    app.run()


if __name__ == "__main__":
    main()
