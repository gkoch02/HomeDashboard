import logging

from src.app import DashboardApp
from src.cli import parse_args
from src.config import (
    load_config,
    print_validation_report,
    resolve_log_level,
    validate_config,
)

logger = logging.getLogger(__name__)


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # load_config() is the one step with nothing above it to catch a failure.
    # A malformed file used to surface as a raw traceback — including under
    # --check-config, the flag whose whole job is diagnosing a bad config.
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"Could not read config file {args.config}: {type(exc).__name__}: {exc}")
        print("Fix the file (or restore config/config.example.yaml) and try again.")
        raise SystemExit(1) from exc
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
