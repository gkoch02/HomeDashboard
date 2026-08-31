"""Tests for src/services/output.py (OutputService)."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.services.output import (
    OutputService,
    _load_last_refresh,
    _resolve_min_refresh_seconds,
    _save_last_refresh,
    should_throttle_display_refresh,
)


def _make_image(w: int = 800, h: int = 480) -> Image.Image:
    return Image.new("1", (w, h), 1)


def _make_cfg(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.output_dir = str(tmp_path)
    cfg.state_dir = str(tmp_path / "state")
    cfg.display.provider = "waveshare"
    cfg.display.model = "epd7in5_V2"
    cfg.display.enable_partial_refresh = False
    cfg.display.max_partials_before_full = 4
    cfg.display.min_refresh_interval_seconds = None
    return cfg


def _make_tz():
    import zoneinfo

    return zoneinfo.ZoneInfo("UTC")


def _now() -> datetime:
    # Aware, matching production: publish() receives now_local(tz). Repo
    # convention: tests comparing against persisted timestamps must construct
    # aware values (naive-legacy parsing is pinned separately below).
    return datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# publish() — dry-run path
# ---------------------------------------------------------------------------


class TestPublishDryRun:
    def test_calls_dry_run_display_show(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with patch("src.services.output.DryRunDisplay", return_value=mock_display) as mock_cls:
            svc.publish(image, dry_run=True, force_full=False, now=_now(), theme_name="default")

        mock_cls.assert_called_once_with(output_dir=str(tmp_path))
        mock_display.show.assert_called_once_with(image)

    def test_dry_run_returns_immediately_no_waveshare(self, tmp_path):
        """dry_run=True must never touch the hardware driver factory."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.DryRunDisplay", return_value=MagicMock()),
            patch("src.services.output.image_changed") as mock_changed,
            patch("src.services.output.build_display_driver") as mock_build,
        ):
            svc.publish(image, dry_run=True, force_full=False, now=_now(), theme_name="default")

        mock_changed.assert_not_called()
        mock_build.assert_not_called()

    def test_dry_run_force_full_still_uses_dry_run_display(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with patch("src.services.output.DryRunDisplay", return_value=mock_display):
            svc.publish(image, dry_run=True, force_full=True, now=_now(), theme_name="default")

        mock_display.show.assert_called_once_with(image)


# ---------------------------------------------------------------------------
# publish() — hardware path
# ---------------------------------------------------------------------------


class TestPublishHardware:
    def test_image_unchanged_skips_display(self, tmp_path):
        """When image_changed returns False and force_full is False, no display write."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=False),
            patch("src.services.output.build_display_driver") as mock_build,
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        mock_build.assert_not_called()

    def test_image_changed_calls_waveshare(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.services.output.build_display_driver", return_value=mock_display),
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        mock_display.show.assert_called_once_with(image, force_full=False)

    def test_force_full_bypasses_change_check(self, tmp_path):
        """force_full=True should call WaveshareDisplay even when image is unchanged."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with (
            patch("src.services.output.image_changed", return_value=False),
            patch("src.services.output.build_display_driver", return_value=mock_display),
        ):
            svc.publish(image, dry_run=False, force_full=True, now=_now(), theme_name="default")

        mock_display.show.assert_called_once_with(image, force_full=True)

    def test_waveshare_constructed_with_config_values(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "waveshare"
        cfg.display.model = "epd7in5_HD"
        cfg.display.enable_partial_refresh = True
        cfg.display.max_partials_before_full = 7

        svc = OutputService(cfg, _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch(
                "src.services.output.build_display_driver", return_value=mock_display
            ) as mock_cls,
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        mock_cls.assert_called_once_with(
            provider="waveshare",
            model="epd7in5_HD",
            enable_partial=True,
            max_partials=7,
            state_dir=str(tmp_path / "state"),
        )

    def test_image_changed_called_with_correct_args(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=False) as mock_changed,
            patch("src.services.output.build_display_driver"),
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        mock_changed.assert_called_once_with(image, str(tmp_path))

    def test_hardware_publish_saves_latest_png(self, tmp_path):
        """After a hardware display write, latest.png must be updated."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.services.output.build_display_driver", return_value=MagicMock()),
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        assert (tmp_path / "latest.png").exists()

    def test_hardware_publish_skipped_does_not_save_latest_png(self, tmp_path):
        """When the image is unchanged and not forced, latest.png must not be written."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=False),
            patch("src.services.output.build_display_driver", return_value=MagicMock()),
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        assert not (tmp_path / "latest.png").exists()

    def test_hardware_publish_latest_png_save_failure_does_not_raise(self, tmp_path, caplog):
        """A failure saving latest.png must log a warning but not crash."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.services.output.build_display_driver", return_value=MagicMock()),
            patch.object(image, "save", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="src.services.output"),
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        assert "latest.png" in caplog.text

    def test_inky_driver_built_with_provider(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        cfg.display.enable_partial_refresh = True
        # Disable the cooldown so the test isolates the driver-build path.
        cfg.display.min_refresh_interval_seconds = 0
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        mock_display = MagicMock()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch(
                "src.services.output.build_display_driver", return_value=mock_display
            ) as mock_cls,
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        mock_cls.assert_called_once_with(
            provider="inky",
            model="impression_7_3_2025",
            enable_partial=True,
            max_partials=4,
            state_dir=str(tmp_path / "state"),
        )

    def test_inky_default_60s_cooldown_throttles_within_minute(self, tmp_path):
        """Inky default cooldown is 60s; a 30-second-old refresh blocks the next one."""
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        cfg.display.min_refresh_interval_seconds = None  # default → 60 for Inky
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        state_dir = Path(cfg.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        # 30 seconds ago — within the default 60s cooldown.
        last = (_now() - timedelta(seconds=30)).isoformat()
        (state_dir / "refresh_throttle_state.json").write_text(
            json.dumps({"last_refresh_at": last})
        )

        with (
            patch("src.services.output.image_changed", return_value=True) as mock_changed,
            patch("src.services.output.build_display_driver") as mock_build,
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        mock_changed.assert_not_called()
        mock_build.assert_not_called()

    def test_inky_default_cooldown_passes_after_60s(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        cfg.display.min_refresh_interval_seconds = None  # default → 60
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        state_dir = Path(cfg.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        last = (_now() - timedelta(seconds=120)).isoformat()
        (state_dir / "refresh_throttle_state.json").write_text(
            json.dumps({"last_refresh_at": last})
        )

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch(
                "src.services.output.build_display_driver", return_value=MagicMock()
            ) as mock_build,
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        mock_build.assert_called_once()

    def test_inky_3600s_cooldown_restores_v4_hourly_throttle(self, tmp_path):
        """Setting 3600 explicitly preserves the v4 'once an hour' Inky behaviour."""
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        cfg.display.min_refresh_interval_seconds = 3600
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        state_dir = Path(cfg.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        last = (_now() - timedelta(minutes=30)).isoformat()
        (state_dir / "refresh_throttle_state.json").write_text(
            json.dumps({"last_refresh_at": last})
        )

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.services.output.build_display_driver") as mock_build,
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        mock_build.assert_not_called()

    def test_force_full_bypasses_cooldown(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        state_dir = Path(cfg.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "refresh_throttle_state.json").write_text(
            '{"last_refresh_at":"2026-04-08T11:59:55"}'
        )

        with (
            patch("src.services.output.image_changed", return_value=False),
            patch(
                "src.services.output.build_display_driver", return_value=MagicMock()
            ) as mock_build,
        ):
            svc.publish(image, dry_run=False, force_full=True, now=_now(), theme_name="default")

        mock_build.assert_called_once()

    def test_legacy_inky_state_file_migrated_on_first_read(self, tmp_path):
        """A legacy `inky_refresh_state.json` triggers migration to the new file."""
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        # Restore v4 hourly cooldown so the legacy "30 minutes ago" timestamp throttles.
        cfg.display.min_refresh_interval_seconds = 3600
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        state_dir = Path(cfg.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        legacy = state_dir / "inky_refresh_state.json"
        last_iso = (_now() - timedelta(minutes=30)).isoformat()
        legacy.write_text(json.dumps({"last_refresh_at": last_iso}))

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.services.output.build_display_driver") as mock_build,
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        # Legacy was honoured (build skipped because 30m < 3600s) and migrated:
        mock_build.assert_not_called()
        assert not legacy.exists()
        assert (state_dir / "refresh_throttle_state.json").exists()


class TestThemePartialRefreshOptOut:
    """A theme that declines the fast waveform overrides the config opt-in (#222)."""

    def _publish(self, cfg, tmp_path, **kwargs):
        svc = OutputService(cfg, _make_tz())
        mock_display = MagicMock()
        with (
            patch("src.services.output.image_changed", return_value=True),
            patch(
                "src.services.output.build_display_driver", return_value=mock_display
            ) as mock_build,
        ):
            svc.publish(
                _make_image(),
                dry_run=False,
                force_full=False,
                now=_now(),
                **kwargs,
            )
        return mock_build

    def test_theme_opt_out_forces_full_waveform(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.enable_partial_refresh = True

        mock_build = self._publish(
            cfg,
            tmp_path,
            theme_name="halftone_agenda",
            theme_supports_partial=False,
        )

        assert mock_build.call_args.kwargs["enable_partial"] is False

    def test_theme_that_supports_partials_keeps_the_config_value(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.enable_partial_refresh = True

        mock_build = self._publish(
            cfg,
            tmp_path,
            theme_name="default",
            theme_supports_partial=True,
        )

        assert mock_build.call_args.kwargs["enable_partial"] is True

    def test_opt_out_does_not_switch_partials_on(self, tmp_path):
        """The theme flag can only remove partial refresh, never add it."""
        cfg = _make_cfg(tmp_path)
        cfg.display.enable_partial_refresh = False

        mock_build = self._publish(
            cfg,
            tmp_path,
            theme_name="default",
            theme_supports_partial=True,
        )

        assert mock_build.call_args.kwargs["enable_partial"] is False

    def test_default_is_partial_capable(self, tmp_path):
        """Callers that don't pass the flag are unaffected."""
        cfg = _make_cfg(tmp_path)
        cfg.display.enable_partial_refresh = True

        mock_build = self._publish(cfg, tmp_path, theme_name="default")

        assert mock_build.call_args.kwargs["enable_partial"] is True

    def test_override_is_logged(self, tmp_path, caplog):
        cfg = _make_cfg(tmp_path)
        cfg.display.enable_partial_refresh = True

        with caplog.at_level(logging.INFO, logger="src.services.output"):
            self._publish(
                cfg,
                tmp_path,
                theme_name="halftone_agenda",
                theme_supports_partial=False,
            )

        assert "halftone_agenda" in caplog.text
        assert "partial refresh" in caplog.text

    def test_no_log_when_partials_were_off_anyway(self, tmp_path, caplog):
        cfg = _make_cfg(tmp_path)
        cfg.display.enable_partial_refresh = False

        with caplog.at_level(logging.INFO, logger="src.services.output"):
            self._publish(
                cfg,
                tmp_path,
                theme_name="halftone_agenda",
                theme_supports_partial=False,
            )

        assert "does not support partial refresh" not in caplog.text


class TestThrottleHelper:
    def test_zero_min_interval_never_throttles(self, tmp_path):
        (tmp_path / "refresh_throttle_state.json").write_text(
            '{"last_refresh_at":"2026-04-08T11:59:59"}'
        )
        assert (
            should_throttle_display_refresh(
                provider="waveshare",
                now=_now(),
                state_dir=str(tmp_path),
                force_full=False,
                min_interval_seconds=0,
            )
            is False
        )

    def test_force_full_never_throttles(self, tmp_path):
        (tmp_path / "refresh_throttle_state.json").write_text(
            '{"last_refresh_at":"2026-04-08T11:59:59"}'
        )
        assert (
            should_throttle_display_refresh(
                provider="inky",
                now=_now(),
                state_dir=str(tmp_path),
                force_full=True,
                min_interval_seconds=60,
            )
            is False
        )

    def test_throttles_when_under_cooldown(self, tmp_path):
        (tmp_path / "refresh_throttle_state.json").write_text(
            '{"last_refresh_at":"2026-04-08T11:59:30"}'
        )
        assert (
            should_throttle_display_refresh(
                provider="inky",
                now=_now(),
                state_dir=str(tmp_path),
                force_full=False,
                min_interval_seconds=60,
            )
            is True
        )

    def test_passes_after_cooldown(self, tmp_path):
        last = (_now() - timedelta(seconds=120)).isoformat()
        (tmp_path / "refresh_throttle_state.json").write_text(json.dumps({"last_refresh_at": last}))
        assert (
            should_throttle_display_refresh(
                provider="inky",
                now=_now(),
                state_dir=str(tmp_path),
                force_full=False,
                min_interval_seconds=60,
            )
            is False
        )


class TestResolveMinRefreshSeconds:
    def test_explicit_value_passes_through(self):
        assert _resolve_min_refresh_seconds("inky", 3600) == 3600
        assert _resolve_min_refresh_seconds("waveshare", 30) == 30

    def test_negative_clamped_to_zero(self):
        assert _resolve_min_refresh_seconds("inky", -10) == 0

    def test_inky_default_60(self):
        assert _resolve_min_refresh_seconds("inky", None) == 60

    def test_waveshare_default_0(self):
        assert _resolve_min_refresh_seconds("waveshare", None) == 0

    def test_unknown_provider_default_0(self):
        assert _resolve_min_refresh_seconds("unknown", None) == 0


# ---------------------------------------------------------------------------
# write_health_marker()
# ---------------------------------------------------------------------------


class TestWriteHealthMarker:
    def test_creates_last_success_file(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        svc.write_health_marker()

        marker = tmp_path / "last_success.txt"
        assert marker.exists()

    def test_file_contains_iso_timestamp(self, tmp_path):
        import re

        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        svc.write_health_marker()

        content = (tmp_path / "last_success.txt").read_text().strip()
        # ISO format: YYYY-MM-DDTHH:MM:SS...
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", content)

    def test_creates_parent_directories(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.output_dir = str(tmp_path / "nested" / "output")

        svc = OutputService(cfg, _make_tz())
        svc.write_health_marker()

        assert (tmp_path / "nested" / "output" / "last_success.txt").exists()

    def test_write_failure_logs_warning_and_does_not_raise(self, tmp_path, caplog):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())

        with caplog.at_level(logging.WARNING, logger="src.services.output"):
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                svc.write_health_marker()  # must not raise

        assert "last_success.txt" in caplog.text


# ---------------------------------------------------------------------------
# Refresh state I/O — defensive branches
# ---------------------------------------------------------------------------


class TestLoadLastRefreshDefensive:
    def test_returns_none_when_state_file_missing(self, tmp_path):
        assert _load_last_refresh(str(tmp_path)) is None

    def test_returns_none_when_value_is_not_a_string(self, tmp_path):
        (tmp_path / "refresh_throttle_state.json").write_text(
            json.dumps({"last_refresh_at": 12345})
        )
        assert _load_last_refresh(str(tmp_path)) is None

    def test_returns_none_when_value_key_missing(self, tmp_path):
        (tmp_path / "refresh_throttle_state.json").write_text(json.dumps({}))
        assert _load_last_refresh(str(tmp_path)) is None

    def test_returns_none_on_unparseable_json(self, tmp_path):
        (tmp_path / "refresh_throttle_state.json").write_text("not-json{{{")
        assert _load_last_refresh(str(tmp_path)) is None

    def test_returns_none_on_invalid_iso_timestamp(self, tmp_path):
        (tmp_path / "refresh_throttle_state.json").write_text(
            json.dumps({"last_refresh_at": "totally-not-a-date"})
        )
        assert _load_last_refresh(str(tmp_path)) is None

    def test_returns_none_when_json_root_is_not_an_object(self, tmp_path):
        (tmp_path / "refresh_throttle_state.json").write_text(json.dumps([]))
        assert _load_last_refresh(str(tmp_path)) is None
        (tmp_path / "refresh_throttle_state.json").write_text(json.dumps("x"))
        assert _load_last_refresh(str(tmp_path)) is None


class TestSaveLastRefreshDefensive:
    def test_save_failure_logs_warning_and_does_not_raise(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="src.services.output"):
            with patch("src.services.output.atomic_write_json", side_effect=OSError("disk full")):
                _save_last_refresh(str(tmp_path), datetime(2026, 4, 8, 12, 0))

        assert "refresh throttle" in caplog.text


class TestLegacyInkyMigration:
    def test_legacy_file_loaded_when_new_file_missing(self, tmp_path):
        legacy = tmp_path / "inky_refresh_state.json"
        legacy.write_text('{"last_refresh_at": "2026-04-08T11:30:00"}')
        ts = _load_last_refresh(str(tmp_path))
        # Regression (#208): legacy v4 files hold naive UTC timestamps; the
        # reader must attach UTC so the aware-now subtraction in
        # should_throttle_display_refresh can't raise TypeError.
        assert ts == datetime(2026, 4, 8, 11, 30, tzinfo=timezone.utc)
        # Migration deleted the legacy file and wrote the new one.
        assert not legacy.exists()
        assert (tmp_path / "refresh_throttle_state.json").exists()

    def test_legacy_file_with_garbage_json_returns_none(self, tmp_path):
        (tmp_path / "inky_refresh_state.json").write_text("not-json")
        assert _load_last_refresh(str(tmp_path)) is None

    def test_legacy_file_with_missing_key_returns_none(self, tmp_path):
        (tmp_path / "inky_refresh_state.json").write_text("{}")
        assert _load_last_refresh(str(tmp_path)) is None

    def test_legacy_file_with_invalid_iso_returns_none(self, tmp_path):
        (tmp_path / "inky_refresh_state.json").write_text(
            json.dumps({"last_refresh_at": "totally-not-a-date"})
        )
        assert _load_last_refresh(str(tmp_path)) is None

    def test_legacy_rename_oserror_still_returns_timestamp(self, tmp_path):
        """When the atomic rename of the legacy file fails with OSError, the
        parsed timestamp is still returned — the migration is best-effort."""
        legacy = tmp_path / "inky_refresh_state.json"
        legacy.write_text('{"last_refresh_at": "2026-04-08T11:30:00"}')

        with patch("pathlib.Path.replace", side_effect=OSError("read-only fs")):
            ts = _load_last_refresh(str(tmp_path))

        # Timestamp was still parsed and returned even though rename failed.
        assert ts == datetime(2026, 4, 8, 11, 30, tzinfo=timezone.utc)


class TestThrottleNoStateFile:
    def test_no_state_file_does_not_throttle(self, tmp_path):
        """When min_interval > 0 but no prior refresh state exists, don't throttle."""
        from datetime import timezone

        result = should_throttle_display_refresh(
            provider="inky",
            now=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
            state_dir=str(tmp_path),
            force_full=False,
            min_interval_seconds=3600,
        )
        assert result is False


class TestWriteErrorMarker:
    def test_creates_error_marker_file(self, tmp_path):
        from src.config import Config

        cfg = Config()
        cfg.output_dir = str(tmp_path)
        svc = OutputService(cfg, tz=None)
        exc = RuntimeError("something broke")
        svc.write_error_marker(exc)

        marker = tmp_path / "last_error.txt"
        assert marker.exists()
        payload = json.loads(marker.read_text())
        assert payload["exception_type"] == "RuntimeError"
        assert payload["message"] == "something broke"
        assert "timestamp" in payload

    def test_write_failure_logs_warning_and_does_not_raise(self, tmp_path, caplog):
        from src.config import Config

        cfg = Config()
        cfg.output_dir = str(tmp_path)
        svc = OutputService(cfg, tz=None)

        with caplog.at_level(logging.WARNING, logger="src.services.output"):
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                svc.write_error_marker(RuntimeError("oops"))

        assert "last_error.txt" in caplog.text


# ---------------------------------------------------------------------------
# Regression: issue #207 — hash persisted only after a successful show()
# ---------------------------------------------------------------------------


class TestFailedShowDoesNotPinHash:
    def test_failed_show_leaves_hash_absent_so_next_run_retries(self, tmp_path):
        """A transient hardware failure must not record the frame as displayed —
        the next run with identical content has to retry the write instead of
        skipping it as 'unchanged' and pinning the panel on stale content."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        failing = MagicMock()
        failing.show.side_effect = RuntimeError("SPI glitch")

        with (
            patch("src.services.output.build_display_driver", return_value=failing),
            pytest.raises(RuntimeError),
        ):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        assert not (tmp_path / "last_image_hash.txt").exists()

        # Same content, working hardware: the write happens this time.
        working = MagicMock()
        with patch("src.services.output.build_display_driver", return_value=working):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")
        working.show.assert_called_once()
        assert (tmp_path / "last_image_hash.txt").exists()

    def test_successful_show_persists_hash_and_dedupes_next_run(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        driver = MagicMock()

        with patch("src.services.output.build_display_driver", return_value=driver):
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")
            svc.publish(image, dry_run=False, force_full=False, now=_now(), theme_name="default")

        # Second publish with identical content skipped the hardware write.
        assert driver.show.call_count == 1


# ---------------------------------------------------------------------------
# Regression: issue #208 — naive legacy timestamp must not wedge publishing
# ---------------------------------------------------------------------------


class TestNaiveThrottleTimestamp:
    def test_naive_state_timestamp_does_not_raise_in_throttle(self, tmp_path):
        """A migrated v4 state file holds a naive ISO timestamp; the cooldown
        subtraction against an aware now must work (naive = UTC convention),
        not raise TypeError on every publish until the file is deleted."""
        (tmp_path / "refresh_throttle_state.json").write_text(
            '{"last_refresh_at": "2026-04-08T11:59:30"}'
        )
        assert (
            should_throttle_display_refresh(
                provider="inky",
                now=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
                state_dir=str(tmp_path),
                force_full=False,
                min_interval_seconds=60,
            )
            is True
        )

    def test_naive_legacy_file_round_trips_through_publish_cooldown(self, tmp_path):
        legacy = tmp_path / "inky_refresh_state.json"
        legacy.write_text('{"last_refresh_at": "2026-04-08T11:30:00"}')
        ts = _load_last_refresh(str(tmp_path))
        assert ts is not None and ts.tzinfo is not None


class TestLatestPngDuringCooldown:
    """latest.png must show the current render, not the last painted frame (#245).

    The unchanged-hash path is fine — the file already matches by definition.
    The cooldown path is not: the content *did* change, the panel just is not
    allowed to redraw yet, so the web UI's "current display" image was wrong
    for up to min_refresh_interval_seconds — an hour for anyone who sets 3600
    on Inky to restore the v4 hourly throttle.
    """

    def _svc(self, tmp_path, interval=3600):
        cfg = _make_cfg(tmp_path)
        cfg.display.min_refresh_interval_seconds = interval
        return OutputService(cfg, _make_tz()), cfg

    def _publish(self, svc, image, now):
        with patch("src.services.output.build_display_driver") as driver:
            svc.publish(image, dry_run=False, force_full=False, now=now, theme_name="agenda")
        return driver

    def test_a_deferred_refresh_still_updates_latest_png(self, tmp_path):
        svc, cfg = self._svc(tmp_path)
        now = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)

        # First run paints, and records the refresh so the cooldown applies.
        self._publish(svc, _make_image(), now)
        first = (tmp_path / "latest.png").read_bytes()

        # Two minutes later the content has changed, but the cooldown blocks it.
        changed = _make_image()
        changed.putpixel((0, 0), 0)
        driver = self._publish(svc, changed, now + timedelta(minutes=2))

        driver.assert_not_called()  # the panel was correctly not written
        assert (tmp_path / "latest.png").read_bytes() != first

    def test_the_deferred_frame_is_the_one_rendered(self, tmp_path):
        svc, _cfg = self._svc(tmp_path)
        now = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        self._publish(svc, _make_image(), now)

        changed = _make_image()
        for x in range(20):
            changed.putpixel((x, 0), 0)
        self._publish(svc, changed, now + timedelta(minutes=2))

        saved = Image.open(tmp_path / "latest.png").convert("1")
        assert [saved.getpixel((x, 0)) for x in range(20)] == [0] * 20

    def test_a_deferred_run_does_not_pin_the_image_hash(self, tmp_path):
        """The change is still pending, so the next eligible run must paint it."""
        svc, _cfg = self._svc(tmp_path)
        now = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        self._publish(svc, _make_image(), now)

        changed = _make_image()
        changed.putpixel((0, 0), 0)
        self._publish(svc, changed, now + timedelta(minutes=2))

        # Cooldown elapsed: the same content must now reach the panel.
        driver = self._publish(svc, changed, now + timedelta(hours=2))
        driver.return_value.show.assert_called_once()

    def test_an_unchanged_image_leaves_latest_png_alone(self, tmp_path):
        """No cooldown, identical content — the file already matches."""
        cfg = _make_cfg(tmp_path)
        cfg.display.min_refresh_interval_seconds = 0
        svc = OutputService(cfg, _make_tz())
        now = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        image = _make_image()

        self._publish(svc, image, now)
        latest = tmp_path / "latest.png"
        stamp = latest.stat().st_mtime_ns

        driver = self._publish(svc, image, now + timedelta(minutes=30))

        driver.assert_not_called()
        assert latest.stat().st_mtime_ns == stamp

    def test_a_dry_run_is_unaffected(self, tmp_path):
        svc, _cfg = self._svc(tmp_path)
        svc.publish(
            _make_image(),
            dry_run=True,
            force_full=False,
            now=datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc),
            theme_name="agenda",
        )
        assert (tmp_path / "latest.png").exists()
