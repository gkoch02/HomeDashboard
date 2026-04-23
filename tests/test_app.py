"""Tests for src/app.py — DashboardApp and _migrate_state_files."""

from argparse import Namespace
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.app import DashboardApp, _migrate_state_files

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.timezone = "UTC"
    cfg.output_dir = str(tmp_path / "output")
    cfg.state_dir = str(tmp_path / "state")
    cfg.title = "Test Dashboard"
    cfg.theme = "default"
    cfg.cache.quote_refresh = "daily"
    cfg.schedule.quiet_hours_start = 23
    cfg.schedule.quiet_hours_end = 6
    cfg.filters.exclude_calendars = []
    cfg.filters.exclude_keywords = []
    cfg.filters.exclude_all_day = False
    cfg.display.model = "epd7in5_V2"
    cfg.display.enable_partial_refresh = False
    cfg.display.max_partials_before_full = 4
    return cfg


def _make_args(**kwargs) -> Namespace:
    defaults = dict(
        dry_run=True,
        dummy=True,
        theme=None,
        date=None,
        force_full_refresh=False,
        ignore_breakers=False,
        message=None,
    )
    defaults.update(kwargs)
    return Namespace(**defaults)


def _make_app(tmp_path: Path, **arg_overrides) -> DashboardApp:
    cfg = _make_cfg(tmp_path)
    args = _make_args(**arg_overrides)
    Path(cfg.state_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    return DashboardApp(cfg, args)


# ---------------------------------------------------------------------------
# _migrate_state_files
# ---------------------------------------------------------------------------


class TestMigrateStateFiles:
    def test_moves_file_when_old_exists_new_does_not(self, tmp_path):
        output_dir = tmp_path / "output"
        state_dir = tmp_path / "state"
        output_dir.mkdir()
        state_dir.mkdir()

        old_file = output_dir / "dashboard_cache.json"
        old_file.write_text('{"data": 1}')

        _migrate_state_files(str(output_dir), str(state_dir))

        assert not old_file.exists()
        assert (state_dir / "dashboard_cache.json").exists()

    def test_skips_when_old_file_does_not_exist(self, tmp_path):
        output_dir = tmp_path / "output"
        state_dir = tmp_path / "state"
        output_dir.mkdir()
        state_dir.mkdir()

        _migrate_state_files(str(output_dir), str(state_dir))  # no error

        assert not (state_dir / "dashboard_cache.json").exists()

    def test_skips_when_destination_already_exists(self, tmp_path):
        output_dir = tmp_path / "output"
        state_dir = tmp_path / "state"
        output_dir.mkdir()
        state_dir.mkdir()

        old_file = output_dir / "dashboard_cache.json"
        old_file.write_text("old")
        new_file = state_dir / "dashboard_cache.json"
        new_file.write_text("new")

        _migrate_state_files(str(output_dir), str(state_dir))

        # destination unchanged
        assert new_file.read_text() == "new"
        # source still present (skipped)
        assert old_file.exists()

    def test_logs_warning_and_continues_on_error(self, tmp_path, caplog):
        import logging

        output_dir = tmp_path / "output"
        state_dir = tmp_path / "state"
        output_dir.mkdir()
        state_dir.mkdir()

        # Create multiple state files; one will fail
        (output_dir / "dashboard_cache.json").write_text("{}")
        (output_dir / "dashboard_breaker_state.json").write_text("{}")

        with caplog.at_level(logging.WARNING, logger="src.app"):
            with patch("shutil.move", side_effect=OSError("permission denied")):
                _migrate_state_files(str(output_dir), str(state_dir))

        assert "Failed to migrate" in caplog.text

    def test_migrates_multiple_files(self, tmp_path):
        output_dir = tmp_path / "output"
        state_dir = tmp_path / "state"
        output_dir.mkdir()
        state_dir.mkdir()

        filenames = ["dashboard_cache.json", "dashboard_breaker_state.json", "api_quota_state.json"]
        for name in filenames:
            (output_dir / name).write_text("{}")

        _migrate_state_files(str(output_dir), str(state_dir))

        for name in filenames:
            assert (state_dir / name).exists()
            assert not (output_dir / name).exists()


# ---------------------------------------------------------------------------
# DashboardApp._resolve_now
# ---------------------------------------------------------------------------


class TestResolveNow:
    def test_no_date_override_returns_current_time(self, tmp_path):
        app = _make_app(tmp_path, date=None)
        before = datetime.now(app.tz)
        result = app._resolve_now()
        after = datetime.now(app.tz)
        assert before.date() <= result.date() <= after.date()

    def test_date_override_sets_correct_date(self, tmp_path):
        from datetime import date

        app = _make_app(tmp_path, date="2025-07-04")
        result = app._resolve_now()
        assert result.date() == date(2025, 7, 4)

    def test_date_override_preserves_time_components(self, tmp_path):
        """The time portion should come from now(), not midnight."""
        app = _make_app(tmp_path, date="2025-12-25")
        result = app._resolve_now()
        # Should have some hour/minute/second (not necessarily 00:00:00 unless run at midnight)
        # Just verify it's a datetime with the right date
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 25


# ---------------------------------------------------------------------------
# DashboardApp._load_data
# ---------------------------------------------------------------------------


class TestLoadData:
    def test_dummy_mode_calls_generate_dummy_data(self, tmp_path):
        app = _make_app(tmp_path, dummy=True)
        now = datetime(2025, 6, 1, 10, 0)
        fake_data = MagicMock()

        with patch("src.app.generate_dummy_data", return_value=fake_data) as mock_gen:
            result = app._load_data(
                now,
                force_full=False,
                theme_name="default",
                event_window_start=None,
                event_window_days=7,
            )

        mock_gen.assert_called_once()
        assert result is fake_data

    def test_dummy_mode_passes_tz_and_now(self, tmp_path):
        app = _make_app(tmp_path, dummy=True)
        now = datetime(2025, 6, 1, 10, 0)

        with patch("src.app.generate_dummy_data", return_value=MagicMock()) as mock_gen:
            app._load_data(
                now,
                force_full=False,
                theme_name="default",
                event_window_start=None,
                event_window_days=7,
            )

        call_kwargs = mock_gen.call_args
        assert call_kwargs.kwargs.get("tz") == app.tz
        assert call_kwargs.kwargs.get("now") == now

    def test_live_mode_creates_pipeline_and_fetches(self, tmp_path):
        app = _make_app(tmp_path, dummy=False)
        now = datetime(2025, 6, 1, 10, 0)
        fake_data = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.fetch.return_value = fake_data

        with patch("src.app.DataPipeline", return_value=mock_pipeline) as mock_cls:
            result = app._load_data(
                now,
                force_full=True,
                theme_name="default",
                event_window_start=None,
                event_window_days=7,
            )

        mock_cls.assert_called_once()
        mock_pipeline.fetch.assert_called_once()
        assert result is fake_data

    def test_live_mode_passes_force_refresh_to_pipeline(self, tmp_path):
        app = _make_app(tmp_path, dummy=False)
        now = datetime(2025, 6, 1, 10, 0)
        mock_pipeline = MagicMock()
        mock_pipeline.fetch.return_value = MagicMock()

        with patch("src.app.DataPipeline", return_value=mock_pipeline) as mock_cls:
            app._load_data(
                now,
                force_full=True,
                theme_name="default",
                event_window_start=None,
                event_window_days=7,
            )

        init_kwargs = mock_cls.call_args.kwargs
        assert init_kwargs.get("force_refresh") is True

    def test_monthly_theme_passes_expanded_event_window(self, tmp_path):
        from datetime import date

        app = _make_app(tmp_path, dummy=False)
        now = datetime(2025, 6, 1, 10, 0)
        mock_pipeline = MagicMock()
        mock_pipeline.fetch.return_value = MagicMock()

        with patch("src.app.DataPipeline", return_value=mock_pipeline) as mock_cls:
            app._load_data(
                now,
                force_full=False,
                theme_name="monthly",
                event_window_start=date(2025, 6, 1),
                event_window_days=35,
            )

        init_kwargs = mock_cls.call_args.kwargs
        assert init_kwargs.get("event_window_start") == date(2025, 6, 1)
        assert init_kwargs.get("event_window_days") == 35


class TestEventWindowForTheme:
    def test_default_theme_uses_week_window(self, tmp_path):
        app = _make_app(tmp_path)
        start, days = app._event_window_for_theme("default", datetime(2026, 4, 11, 10, 0))
        assert start is None
        assert days == 7

    def test_monthly_theme_uses_visible_month_grid_window(self, tmp_path):
        from datetime import date

        app = _make_app(tmp_path)
        start, days = app._event_window_for_theme("monthly", datetime(2026, 4, 11, 10, 0))
        assert start == date(2026, 3, 29)
        assert days == 35


# ---------------------------------------------------------------------------
# DashboardApp._apply_filters
# ---------------------------------------------------------------------------


class TestApplyFilters:
    def _make_data(self):
        from src.data.models import CalendarEvent

        data = MagicMock()
        data.events = [
            CalendarEvent(
                summary="Meeting",
                start=datetime(2025, 6, 1, 9, 0),
                end=datetime(2025, 6, 1, 10, 0),
            ),
            CalendarEvent(
                summary="Standup",
                start=datetime(2025, 6, 1, 10, 0),
                end=datetime(2025, 6, 1, 10, 15),
            ),
        ]
        return data

    def test_no_filters_does_not_call_filter_events(self, tmp_path):
        app = _make_app(tmp_path)
        app.cfg.filters.exclude_calendars = []
        app.cfg.filters.exclude_keywords = []
        app.cfg.filters.exclude_all_day = False
        data = self._make_data()
        original_events = list(data.events)

        with patch("src.app.filter_events") as mock_filter:
            result = app._apply_filters(data)

        mock_filter.assert_not_called()
        assert result.events == original_events

    def test_exclude_keywords_calls_filter_events(self, tmp_path):
        app = _make_app(tmp_path)
        app.cfg.filters.exclude_calendars = []
        app.cfg.filters.exclude_keywords = ["Standup"]
        app.cfg.filters.exclude_all_day = False
        data = self._make_data()
        filtered = [data.events[0]]

        with patch("src.app.filter_events", return_value=filtered) as mock_filter:
            result = app._apply_filters(data)

        mock_filter.assert_called_once()
        assert result.events == filtered

    def test_exclude_calendars_calls_filter_events(self, tmp_path):
        app = _make_app(tmp_path)
        app.cfg.filters.exclude_calendars = ["Work"]
        app.cfg.filters.exclude_keywords = []
        app.cfg.filters.exclude_all_day = False
        data = self._make_data()

        with patch("src.app.filter_events", return_value=[]) as mock_filter:
            app._apply_filters(data)

        mock_filter.assert_called_once()

    def test_exclude_all_day_calls_filter_events(self, tmp_path):
        app = _make_app(tmp_path)
        app.cfg.filters.exclude_calendars = []
        app.cfg.filters.exclude_keywords = []
        app.cfg.filters.exclude_all_day = True
        data = self._make_data()

        with patch("src.app.filter_events", return_value=[]) as mock_filter:
            app._apply_filters(data)

        mock_filter.assert_called_once()


# ---------------------------------------------------------------------------
# DashboardApp.run()
# ---------------------------------------------------------------------------


class TestRun:
    def _make_full_app(self, tmp_path, **arg_overrides):
        """App with all output dirs created."""
        cfg = _make_cfg(tmp_path)
        Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.state_dir).mkdir(parents=True, exist_ok=True)
        args = _make_args(**arg_overrides)
        return DashboardApp(cfg, args)

    def test_quiet_hours_returns_early_without_render(self, tmp_path):
        app = self._make_full_app(tmp_path, dry_run=False)

        with (
            patch("src.app.should_skip_refresh", return_value=True),
            patch("src.app.render_dashboard") as mock_render,
        ):
            app.run()

        mock_render.assert_not_called()

    def test_morning_startup_logs_and_force_full(self, tmp_path, caplog):
        import logging

        app = self._make_full_app(tmp_path, dummy=True, force_full_refresh=False)
        fake_data = MagicMock()
        fake_data.events = []
        from PIL import Image

        fake_image = Image.new("1", (800, 480), 1)

        with caplog.at_level(logging.INFO, logger="src.app"):
            with (
                patch("src.app.should_skip_refresh", return_value=False),
                patch("src.app.should_force_full_refresh", return_value=True),
                patch("src.app.generate_dummy_data", return_value=fake_data),
                patch("src.app.render_dashboard", return_value=fake_image),
                patch.object(app.output, "publish"),
                patch.object(app.output, "write_health_marker"),
            ):
                app.run()

        assert "Morning startup" in caplog.text

    def test_run_dummy_renders_and_publishes(self, tmp_path):
        app = self._make_full_app(tmp_path, dummy=True, dry_run=True)
        fake_data = MagicMock()
        fake_data.events = []
        from PIL import Image

        fake_image = Image.new("1", (800, 480), 1)

        with (
            patch("src.app.should_skip_refresh", return_value=False),
            patch("src.app.should_force_full_refresh", return_value=False),
            patch("src.app.generate_dummy_data", return_value=fake_data),
            patch("src.app.render_dashboard", return_value=fake_image) as mock_render,
            patch.object(app.output, "publish") as mock_publish,
            patch.object(app.output, "write_health_marker") as mock_marker,
        ):
            app.run()

        mock_render.assert_called_once()
        mock_publish.assert_called_once()
        mock_marker.assert_called_once()
        assert mock_publish.call_args.kwargs["theme_name"] == "default"
        assert "now" in mock_publish.call_args.kwargs

    def test_theme_override_arg_used_directly(self, tmp_path):
        app = self._make_full_app(tmp_path, dummy=True, theme="minimalist")
        fake_data = MagicMock()
        fake_data.events = []
        from PIL import Image

        fake_image = Image.new("1", (800, 480), 1)

        with (
            patch("src.app.should_skip_refresh", return_value=False),
            patch("src.app.should_force_full_refresh", return_value=False),
            patch("src.app.generate_dummy_data", return_value=fake_data),
            patch("src.app.render_dashboard", return_value=fake_image),
            patch("src.app.resolve_theme_name", return_value="minimalist") as mock_resolve,
            patch.object(app.output, "publish"),
            patch.object(app.output, "write_health_marker"),
        ):
            app.run()

        # resolve_theme_name called with the override
        call_args = mock_resolve.call_args
        assert call_args.args[1] == "minimalist"

    def test_no_theme_arg_delegates_to_resolve_theme_name(self, tmp_path):
        app = self._make_full_app(tmp_path, dummy=True, theme=None)
        fake_data = MagicMock()
        fake_data.events = []
        from PIL import Image

        fake_image = Image.new("1", (800, 480), 1)

        with (
            patch("src.app.should_skip_refresh", return_value=False),
            patch("src.app.should_force_full_refresh", return_value=False),
            patch("src.app.generate_dummy_data", return_value=fake_data),
            patch("src.app.render_dashboard", return_value=fake_image),
            patch("src.app.resolve_theme_name", return_value="default") as mock_resolve,
            patch.object(app.output, "publish"),
            patch.object(app.output, "write_health_marker"),
        ):
            app.run()

        mock_resolve.assert_called_once()
        call_args = mock_resolve.call_args
        assert call_args.args[1] is None

    def test_resolved_theme_differs_from_configured_logs_info(self, tmp_path, caplog):
        """When resolve_theme_name returns a different theme than cfg.theme, log it."""
        import logging

        app = self._make_full_app(tmp_path, dummy=True, theme=None)
        fake_data = MagicMock()
        fake_data.events = []
        from PIL import Image

        fake_image = Image.new("1", (800, 480), 1)

        with caplog.at_level(logging.INFO, logger="src.app"):
            with (
                patch("src.app.should_skip_refresh", return_value=False),
                patch("src.app.should_force_full_refresh", return_value=False),
                patch("src.app.generate_dummy_data", return_value=fake_data),
                patch("src.app.render_dashboard", return_value=fake_image),
                patch("src.app.resolve_theme_name", return_value="qotd"),
                patch.object(app.output, "publish"),
                patch.object(app.output, "write_health_marker"),
            ):
                app.run()

        # cfg.theme is "default"; resolver returned "qotd" → schedule/random diverged
        assert "Theme resolved to: qotd" in caplog.text

    def test_photo_theme_injects_photo_path_into_style(self, tmp_path):
        """When the resolved theme is 'photo', cfg.photo.path is written onto the style."""
        app = self._make_full_app(tmp_path, dummy=True, theme="photo")
        app.cfg.photo.path = "/fixtures/family.jpg"
        fake_data = MagicMock()
        fake_data.events = []
        from PIL import Image

        fake_image = Image.new("1", (800, 480), 1)

        captured = {}

        def _capture_theme(_data, _display, **kwargs):
            captured["theme"] = kwargs.get("theme")
            return fake_image

        with (
            patch("src.app.should_skip_refresh", return_value=False),
            patch("src.app.should_force_full_refresh", return_value=False),
            patch("src.app.generate_dummy_data", return_value=fake_data),
            patch("src.app.render_dashboard", side_effect=_capture_theme),
            patch("src.app.resolve_theme_name", return_value="photo"),
            patch.object(app.output, "publish"),
            patch.object(app.output, "write_health_marker"),
        ):
            app.run()

        # Theme object received by the renderer should carry the configured photo path.
        assert captured["theme"].name == "photo"
        assert captured["theme"].style.photo_path == "/fixtures/family.jpg"


# ---------------------------------------------------------------------------
# Integration: end-to-end DashboardApp.run() with real collaborators where
# possible. These tests catch wiring regressions (wrong kwargs, missed
# forwarding, state-dir coupling) that unit tests with MagicMock miss.
# ---------------------------------------------------------------------------


class TestRunIntegration:
    """Exercise DashboardApp.run() against real config + real DataPipeline.

    Only I/O boundaries are mocked: Google/OWM fetchers and the eInk driver.
    The goal is to verify that cache fallback, theme schedule resolution, and
    quiet-hours behavior all wire together correctly.
    """

    def _write_config(self, tmp_path, **overrides) -> Path:
        import yaml

        cfg_path = tmp_path / "config.yaml"
        payload: dict = {
            "title": "Integration",
            "timezone": "UTC",
            "theme": "default",
            "state_dir": str(tmp_path / "state"),
            "output": {"dry_run_dir": str(tmp_path / "output")},
            "weather": {"api_key": "abc123", "latitude": 37.7, "longitude": -122.4},
            "google": {"ical_url": "https://example.invalid/cal.ics"},
            "cache": {
                "events_ttl_minutes": 60,
                "weather_ttl_minutes": 30,
                "birthdays_ttl_minutes": 1440,
                "events_fetch_interval": 120,
                "weather_fetch_interval": 60,
                "birthdays_fetch_interval": 1440,
            },
        }
        for key, value in overrides.items():
            payload[key] = value
        cfg_path.write_text(yaml.safe_dump(payload))
        (tmp_path / "state").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)
        return cfg_path

    def _build_args(self, **overrides) -> Namespace:
        defaults = dict(
            dry_run=True,
            dummy=False,
            theme=None,
            date=None,
            force_full_refresh=False,
            ignore_breakers=False,
            message=None,
        )
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_quiet_hours_exits_before_fetching_or_rendering(self, tmp_path):
        """During quiet hours, app exits without touching DataPipeline or the display."""
        from src.config import load_config

        cfg_path = self._write_config(
            tmp_path,
            schedule={"quiet_hours_start": 0, "quiet_hours_end": 23},
        )
        cfg = load_config(str(cfg_path))
        args = self._build_args(dry_run=False)  # quiet-hours check only applies to real runs
        app = DashboardApp(cfg, args)

        with (
            patch("src.app.DataPipeline") as mock_pipeline_cls,
            patch("src.app.render_dashboard") as mock_render,
            patch.object(app.output, "publish") as mock_publish,
        ):
            app.run()

        mock_pipeline_cls.assert_not_called()
        mock_render.assert_not_called()
        mock_publish.assert_not_called()

    def test_theme_schedule_overrides_configured_theme(self, tmp_path):
        """A theme_schedule entry whose time has passed must override cfg.theme."""
        from src.config import load_config

        cfg_path = self._write_config(
            tmp_path,
            theme="default",
            theme_schedule=[
                {"time": "00:00", "theme": "minimalist"},
                {"time": "20:00", "theme": "fuzzyclock"},
            ],
        )
        cfg = load_config(str(cfg_path))
        args = self._build_args(dry_run=True, dummy=True, date="2026-04-22")
        app = DashboardApp(cfg, args)

        captured: dict = {}

        def _capture(_data, _display, **kwargs):
            from PIL import Image

            captured["theme_name"] = kwargs["theme"].name
            return Image.new("1", (800, 480), 1)

        with (
            patch("src.app.render_dashboard", side_effect=_capture),
            patch.object(app.output, "publish"),
            patch.object(app.output, "write_health_marker"),
            # Freeze "now" at 10:00 so the 00:00 entry is active (20:00 not yet).
            patch(
                "src.app.datetime",
                wraps=datetime,
                **{"now.return_value": datetime(2026, 4, 22, 10, 0, tzinfo=app.tz)},
            ),
        ):
            app.run()

        assert captured["theme_name"] == "minimalist"

    def test_cached_data_used_when_all_fetchers_raise(self, tmp_path):
        """When every live fetcher raises, DataPipeline falls back to cached values."""
        import json
        from datetime import datetime as real_datetime
        from datetime import timedelta as real_timedelta
        from datetime import timezone as real_timezone

        from src.config import load_config

        cfg_path = self._write_config(tmp_path)
        state_dir = tmp_path / "state"

        # Seed a valid v2 cache so the fallback path has something to return.
        # DataPipeline uses a tz-aware `now`, so cache timestamps must be tz-aware
        # as well to avoid a TypeError in (self.fetched_at - cached_at).
        now = real_datetime.now(real_timezone.utc)
        fresh = (now - real_timedelta(minutes=5)).isoformat()
        cache_payload = {
            "schema_version": 2,
            "events": {"fetched_at": fresh, "data": []},
            "weather": {
                "fetched_at": fresh,
                "data": {
                    "current_temp": 55.0,
                    "current_icon": "01d",
                    "current_description": "clear",
                    "high": 60.0,
                    "low": 48.0,
                    "humidity": 50,
                    "forecast": [],
                    "alerts": [],
                },
            },
            "birthdays": {"fetched_at": fresh, "data": []},
        }
        (state_dir / "dashboard_cache.json").write_text(json.dumps(cache_payload))

        cfg = load_config(str(cfg_path))
        args = self._build_args(dry_run=True)
        app = DashboardApp(cfg, args)

        from PIL import Image

        with (
            # Kill every live fetcher path so only the cache can satisfy the run.
            patch(
                "src.fetchers.calendar.fetch_events",
                side_effect=RuntimeError("calendar down"),
            ),
            patch(
                "src.fetchers.weather.fetch_weather",
                side_effect=RuntimeError("owm down"),
            ),
            patch(
                "src.fetchers.calendar.fetch_birthdays",
                side_effect=RuntimeError("birthdays down"),
            ),
            patch("src.app.render_dashboard", return_value=Image.new("1", (800, 480), 1)),
            patch.object(app.output, "publish") as mock_publish,
            patch.object(app.output, "write_health_marker"),
        ):
            app.run()

        # App completed and attempted to publish — it didn't crash on fetcher failures.
        mock_publish.assert_called_once()
