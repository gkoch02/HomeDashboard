import logging

from src.app import DashboardApp
from src.cli import parse_args
from src.config import load_config, print_validation_report, validate_config

logger = logging.getLogger(__name__)


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    logging.getLogger().setLevel(getattr(logging, cfg.log_level, logging.INFO))

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
