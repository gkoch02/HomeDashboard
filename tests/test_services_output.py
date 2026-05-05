"""Tests for src/services/output.py (OutputService)."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    return datetime(2026, 4, 8, 12, 0)


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
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                _save_last_refresh(str(tmp_path), datetime(2026, 4, 8, 12, 0))

        assert "refresh throttle" in caplog.text


class TestLegacyInkyMigration:
    def test_legacy_file_loaded_when_new_file_missing(self, tmp_path):
        legacy = tmp_path / "inky_refresh_state.json"
        legacy.write_text('{"last_refresh_at": "2026-04-08T11:30:00"}')
        ts = _load_last_refresh(str(tmp_path))
        assert ts == datetime(2026, 4, 8, 11, 30)
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
        assert ts == datetime(2026, 4, 8, 11, 30)


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
