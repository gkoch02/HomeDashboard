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
            display = DryRunDisplay(output_dir=self.cfg.output_dir)
            display.show(image)
            return

        if not image_changed(image, self.cfg.output_dir) and not force_full:
            logger.info("Image unchanged — skipping display refresh")
            return

        from src.display.driver import WaveshareDisplay
        display = WaveshareDisplay(
            model=self.cfg.display.model,
            enable_partial=self.cfg.display.enable_partial_refresh,
            max_partials=self.cfg.display.max_partials_before_full,
        )
        display.show(image, force_full=force_full)

    def write_health_marker(self) -> None:
        try:
            marker = Path(self.cfg.output_dir) / "last_success.txt"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(datetime.now(self.tz).isoformat() + "\n")
        except Exception as exc:
            logger.warning("Could not write last_success.txt: %s", exc)
