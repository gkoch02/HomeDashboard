import logging
import shutil
from datetime import date as _date
from datetime import datetime
from pathlib import Path

from src.config import resolve_tz
from src.data_pipeline import DataPipeline
from src.dummy_data import generate_dummy_data
from src.filters import filter_events
from src.render.canvas import render_dashboard
from src.render.theme import load_theme
from src.services.output import OutputService
from src.services.run_policy import should_force_full_refresh, should_skip_refresh
from src.services.theme import resolve_theme_name

logger = logging.getLogger(__name__)

# State files that belong in state_dir (not output_dir)
_STATE_FILES = [
    "dashboard_cache.json",
    "dashboard_breaker_state.json",
    "api_quota_state.json",
    "calendar_sync_state.json",
    "random_theme_state.json",
    "random_theme_hourly_state.json",
]


def _migrate_state_files(output_dir: str, state_dir: str) -> None:
    """Move state files from output/ to state/ on first run after upgrade."""
    src_path = Path(output_dir)
    dst_path = Path(state_dir)
    for filename in _STATE_FILES:
        old = src_path / filename
        new = dst_path / filename
        if old.exists() and not new.exists():
            try:
                shutil.move(str(old), str(new))
                logger.info("Migrated state file: %s → %s", old, new)
            except Exception as exc:
                logger.warning("Failed to migrate %s: %s", old, exc)


class DashboardApp:
    def __init__(self, cfg, args):
        self.cfg = cfg
        self.args = args
        self.tz = resolve_tz(cfg.timezone)
        self.output = OutputService(cfg, self.tz)

        # Ensure state directory exists and migrate legacy state files
        Path(cfg.state_dir).mkdir(parents=True, exist_ok=True)
        _migrate_state_files(cfg.output_dir, cfg.state_dir)

    def run(self):
        logger.info("Using timezone: %s", self.tz)
        now = self._resolve_now()

        if should_skip_refresh(
            now,
            self.cfg.schedule.quiet_hours_start,
            self.cfg.schedule.quiet_hours_end,
            self.args.dry_run,
        ):
            logger.info(
                "Quiet hours (%02d:00–%02d:00) — skipping refresh",
                self.cfg.schedule.quiet_hours_start,
                self.cfg.schedule.quiet_hours_end,
            )
            return

        force_full = should_force_full_refresh(
            now,
            self.cfg.schedule.quiet_hours_end,
            self.args.force_full_refresh,
        )
        if force_full and not self.args.force_full_refresh:
            logger.info("Morning startup — forcing full refresh")

        data = self._load_data(now, force_full)
        data = self._apply_filters(data)

        configured_theme = self.args.theme if self.args.theme is not None else self.cfg.theme
        theme_name = resolve_theme_name(self.cfg, self.args.theme, now=now)
        if theme_name != configured_theme:
            logger.info("Theme resolved to: %s", theme_name)
        theme = load_theme(theme_name)
        if theme_name == "photo":
            theme.style.photo_path = self.cfg.photo.path

        logger.info("Rendering dashboard")
        image = render_dashboard(
            data,
            self.cfg.display,
            title=self.cfg.title,
            theme=theme,
            quote_refresh=self.cfg.cache.quote_refresh,
            message_text=getattr(self.args, "message", None),
        )
        self.output.publish(
            image,
            dry_run=self.args.dry_run,
            force_full=force_full,
            now=now,
            theme_name=theme_name,
        )
        self.output.write_health_marker()
        logger.info("Done")

    def _resolve_now(self) -> datetime:
        now = datetime.now(self.tz)
        if self.args.date is not None:
            override_date = _date.fromisoformat(self.args.date)
            now = datetime.combine(override_date, now.timetz())
            logger.info("Dry-run date overridden to: %s", now.date())
        return now

    def _load_data(self, now: datetime, force_full: bool):
        if self.args.dummy:
            logger.info("Using dummy data")
            return generate_dummy_data(tz=self.tz, now=now)

        pipeline = DataPipeline(
            self.cfg,
            cache_dir=self.cfg.state_dir,
            tz=self.tz,
            force_refresh=force_full,
            ignore_breakers=self.args.ignore_breakers,
        )
        return pipeline.fetch()

    def _apply_filters(self, data):
        if (
            self.cfg.filters.exclude_calendars
            or self.cfg.filters.exclude_keywords
            or self.cfg.filters.exclude_all_day
        ):
            original_count = len(data.events)
            data.events = filter_events(data.events, self.cfg.filters)
            logger.info("Filtered events: %d -> %d", original_count, len(data.events))
        return data
