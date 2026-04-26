import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.display.driver import DryRunDisplay, build_display_driver, image_changed

logger = logging.getLogger(__name__)

_INKY_REFRESH_STATE = "inky_refresh_state.json"
_INKY_REFRESH_INTERVAL_SECONDS = 3600
_FUZZYCLOCK_THEMES = {"fuzzyclock", "fuzzyclock_invert"}


def _is_inky_rate_limited_theme(theme_name: str) -> bool:
    return theme_name not in _FUZZYCLOCK_THEMES


def _last_inky_refresh_path(state_dir: str) -> Path:
    return Path(state_dir) / _INKY_REFRESH_STATE


def _load_last_inky_refresh(state_dir: str) -> Optional[datetime]:
    path = _last_inky_refresh_path(state_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            return None
        value = raw.get("last_refresh_at")
        if not isinstance(value, str):
            return None
        return datetime.fromisoformat(value)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _save_last_inky_refresh(state_dir: str, now: datetime) -> None:
    path = _last_inky_refresh_path(state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_refresh_at": now.isoformat()}) + "\n")
    except OSError as exc:
        logger.warning("Could not write Inky refresh state: %s", exc)


def should_throttle_inky_refresh(
    *,
    provider: str,
    theme_name: str,
    now: datetime,
    state_dir: str,
    force_full: bool,
) -> bool:
    if provider != "inky" or force_full or not _is_inky_rate_limited_theme(theme_name):
        return False
    last_refresh = _load_last_inky_refresh(state_dir)
    if last_refresh is None:
        return False
    elapsed_seconds = (now - last_refresh).total_seconds()
    return elapsed_seconds < _INKY_REFRESH_INTERVAL_SECONDS


class OutputService:
    def __init__(self, cfg, tz):
        self.cfg = cfg
        self.tz = tz

    def publish(
        self,
        image,
        *,
        dry_run: bool,
        force_full: bool,
        now: datetime,
        theme_name: str,
    ) -> None:
        if dry_run:
            DryRunDisplay(output_dir=self.cfg.output_dir).show(image)
            return

        if should_throttle_inky_refresh(
            provider=self.cfg.display.provider,
            theme_name=theme_name,
            now=now,
            state_dir=self.cfg.state_dir,
            force_full=force_full,
        ):
            logger.info(
                "Inky refresh throttled — skipping hardware update for theme '%s'", theme_name
            )
            return

        if not image_changed(image, self.cfg.output_dir) and not force_full:
            logger.info("Image unchanged — skipping display refresh")
            return

        build_display_driver(
            provider=self.cfg.display.provider,
            model=self.cfg.display.model,
            enable_partial=self.cfg.display.enable_partial_refresh,
            max_partials=self.cfg.display.max_partials_before_full,
            state_dir=self.cfg.state_dir,
        ).show(image, force_full=force_full)

        if self.cfg.display.provider == "inky":
            _save_last_inky_refresh(self.cfg.state_dir, now)

        # Save latest.png so the web UI always reflects the current display.
        try:
            latest = Path(self.cfg.output_dir) / "latest.png"
            latest.parent.mkdir(parents=True, exist_ok=True)
            image.save(latest)
        except Exception as exc:
            logger.warning("Could not save latest.png: %s", exc)

    def write_health_marker(self) -> None:
        try:
            marker = Path(self.cfg.output_dir) / "last_success.txt"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(datetime.now(self.tz).isoformat() + "\n")
        except Exception as exc:
            logger.warning("Could not write last_success.txt: %s", exc)

    def write_error_marker(self, exc: BaseException) -> None:
        """Persist a structured marker describing the most recent run failure.

        The marker is overwritten on each failure and intentionally not deleted
        on success — readers compare its timestamp to ``last_success.txt`` to
        decide whether the error is current or stale.
        """
        try:
            marker = Path(self.cfg.output_dir) / "last_error.txt"
            marker.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "timestamp": datetime.now(self.tz).isoformat(),
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
            marker.write_text(json.dumps(payload, sort_keys=True) + "\n")
        except Exception as write_exc:
            logger.warning("Could not write last_error.txt: %s", write_exc)
