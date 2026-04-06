import logging
from datetime import datetime
from pathlib import Path

from src.display.driver import DryRunDisplay, image_changed

logger = logging.getLogger(__name__)


class OutputService:
    def __init__(self, cfg, tz):
        self.cfg = cfg
        self.tz = tz

    def publish(self, image, *, dry_run: bool, force_full: bool) -> None:
        if dry_run:
            DryRunDisplay(output_dir=self.cfg.output_dir).show(image)
            return

        if not image_changed(image, self.cfg.output_dir) and not force_full:
            logger.info("Image unchanged — skipping display refresh")
            return

        from src.display.driver import WaveshareDisplay

        WaveshareDisplay(
            model=self.cfg.display.model,
            enable_partial=self.cfg.display.enable_partial_refresh,
            max_partials=self.cfg.display.max_partials_before_full,
        ).show(image, force_full=force_full)

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
