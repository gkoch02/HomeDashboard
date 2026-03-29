import logging
from datetime import date as _date, datetime

from src.data_pipeline import DataPipeline
from src.dummy_data import generate_dummy_data
from src.filters import filter_events
from src.render.canvas import render_dashboard
from src.services_output_service import OutputService
from src.config import resolve_tz
from src.render.theme import load_theme
from src.services_run_policy import should_force_full_refresh, should_skip_refresh
from src.services_theme_service import resolve_theme_name

logger = logging.getLogger(__name__)


class DashboardApp:
    def __init__(self, cfg, args):
        self.cfg = cfg
        self.args = args
        self.tz = resolve_tz(cfg.timezone)
        self.output = OutputService(cfg, self.tz)

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
            now, self.cfg.schedule.quiet_hours_end, self.args.force_full_refresh,
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

        logger.info("Rendering dashboard")
        image = render_dashboard(data, self.cfg.display, title=self.cfg.title, theme=theme)
        self.output.publish(image, dry_run=self.args.dry_run, force_full=force_full)
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
            cache_dir=self.cfg.output_dir,
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
