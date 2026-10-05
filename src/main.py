import logging
import os
import signal
import sys
import threading
import traceback

from src.app import DashboardApp, RunTerminated
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

    # load_config() is the one step with nothing above it to catch a failure;
    # a malformed file must not surface as a raw traceback, least of all under
    # --check-config.
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


def _raise_terminated(signum, _frame):
    raise RunTerminated(f"stopped by signal {signum}")


def _leave(code: int) -> None:
    """Exit now, without joining threads: a fetch worker stuck past the
    pipeline deadline is a non-daemon thread the interpreter would join forever.
    """
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def _leave_if_threads_stuck(code: int, *, show_traceback: bool = False) -> None:
    stuck = [
        t.name
        for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon and t.is_alive()
    ]
    if not stuck:
        return
    if show_traceback:
        # The re-raise this replaces would have printed it.
        traceback.print_exc()
    logger.warning("Exiting without waiting for stuck threads: %s", ", ".join(stuck))
    _leave(code)


if __name__ == "__main__":
    # systemd ends a run past its TimeoutStartSec= with SIGTERM. The default
    # action kills the process outright, skipping the finally that puts a
    # Waveshare panel to sleep and the last_error.txt marker; raising runs both.
    signal.signal(signal.SIGTERM, _raise_terminated)
    try:
        main()
    except RunTerminated:
        logger.error("Run stopped by SIGTERM.")
        _leave(128 + signal.SIGTERM)
    except SystemExit as exc:
        # The process's own exits all carry an int code (or none).
        _leave_if_threads_stuck(exc.code if isinstance(exc.code, int) else int(bool(exc.code)))
        raise
    except BaseException:
        _leave_if_threads_stuck(1, show_traceback=True)
        raise
    _leave_if_threads_stuck(0)
