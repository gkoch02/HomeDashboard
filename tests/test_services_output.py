"""Tests for src/services/output.py (OutputService)."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from src.services.output import (
    OutputService,
    _load_last_inky_refresh,
    _save_last_inky_refresh,
    should_throttle_inky_refresh,
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
        import logging

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

    def test_inky_non_fuzzyclock_throttles_within_one_hour(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        state_dir = Path(cfg.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "inky_refresh_state.json").write_text(
            '{"last_refresh_at":"2026-04-08T11:30:00"}\n'
        )

        with (
            patch("src.services.output.image_changed", return_value=True) as mock_changed,
            patch("src.services.output.build_display_driver") as mock_build,
        ):
            svc.publish(
                image,
                dry_run=False,
                force_full=False,
                now=datetime(2026, 4, 8, 12, 0),
                theme_name="default",
            )

        mock_changed.assert_not_called()
        mock_build.assert_not_called()

    def test_inky_fuzzyclock_bypasses_hourly_throttle(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        state_dir = Path(cfg.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "inky_refresh_state.json").write_text(
            '{"last_refresh_at":"2026-04-08T11:30:00"}\n'
        )

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch(
                "src.services.output.build_display_driver", return_value=MagicMock()
            ) as mock_build,
        ):
            svc.publish(
                image,
                dry_run=False,
                force_full=False,
                now=datetime(2026, 4, 8, 12, 0),
                theme_name="fuzzyclock",
            )

        mock_build.assert_called_once()

    def test_inky_force_full_bypasses_hourly_throttle(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.provider = "inky"
        cfg.display.model = "impression_7_3_2025"
        svc = OutputService(cfg, _make_tz())
        image = Image.new("RGB", (800, 480), "white")
        state_dir = Path(cfg.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "inky_refresh_state.json").write_text(
            '{"last_refresh_at":"2026-04-08T11:30:00"}\n'
        )

        with (
            patch("src.services.output.image_changed", return_value=False),
            patch(
                "src.services.output.build_display_driver", return_value=MagicMock()
            ) as mock_build,
        ):
            svc.publish(
                image,
                dry_run=False,
                force_full=True,
                now=datetime(2026, 4, 8, 12, 0),
                theme_name="default",
            )

        mock_build.assert_called_once()


class TestInkyThrottleHelper:
    def test_non_inky_never_throttled(self, tmp_path):
        assert (
            should_throttle_inky_refresh(
                provider="waveshare",
                theme_name="default",
                now=_now(),
                state_dir=str(tmp_path),
                force_full=False,
            )
            is False
        )

    def test_fuzzyclock_theme_never_throttled(self, tmp_path):
        state = tmp_path / "inky_refresh_state.json"
        state.write_text('{"last_refresh_at":"2026-04-08T11:30:00"}\n')
        assert (
            should_throttle_inky_refresh(
                provider="inky",
                theme_name="fuzzyclock_invert",
                now=_now(),
                state_dir=str(tmp_path),
                force_full=False,
            )
            is False
        )

    def test_throttles_when_last_refresh_under_one_hour(self, tmp_path):
        state = tmp_path / "inky_refresh_state.json"
        state.write_text('{"last_refresh_at":"2026-04-08T11:30:00"}\n')
        assert (
            should_throttle_inky_refresh(
                provider="inky",
                theme_name="default",
                now=_now(),
                state_dir=str(tmp_path),
                force_full=False,
            )
            is True
        )

    def test_does_not_throttle_after_one_hour(self, tmp_path):
        state = tmp_path / "inky_refresh_state.json"
        refreshed_at = (_now() - timedelta(hours=1, minutes=1)).isoformat()
        state.write_text(f'{{"last_refresh_at":"{refreshed_at}"}}\n')
        assert (
            should_throttle_inky_refresh(
                provider="inky",
                theme_name="default",
                now=_now(),
                state_dir=str(tmp_path),
                force_full=False,
            )
            is False
        )


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
# Inky refresh state I/O — defensive branches
# ---------------------------------------------------------------------------


class TestLoadLastInkyRefreshDefensive:
    def test_returns_none_when_state_file_missing(self, tmp_path):
        # No file at all → returns None directly (no exception path).
        assert _load_last_inky_refresh(str(tmp_path)) is None

    def test_returns_none_when_value_is_not_a_string(self, tmp_path):
        """Triggers the `if not isinstance(value, str): return None` branch."""
        (tmp_path / "inky_refresh_state.json").write_text(json.dumps({"last_refresh_at": 12345}))
        assert _load_last_inky_refresh(str(tmp_path)) is None

    def test_returns_none_when_value_key_missing(self, tmp_path):
        """value is None → not a string → return None."""
        (tmp_path / "inky_refresh_state.json").write_text(json.dumps({}))
        assert _load_last_inky_refresh(str(tmp_path)) is None

    def test_returns_none_on_unparseable_json(self, tmp_path):
        """Triggers the trailing `except Exception: return None`."""
        (tmp_path / "inky_refresh_state.json").write_text("not-json{{{")
        assert _load_last_inky_refresh(str(tmp_path)) is None

    def test_returns_none_on_invalid_iso_timestamp(self, tmp_path):
        """fromisoformat raises ValueError → except branch returns None."""
        (tmp_path / "inky_refresh_state.json").write_text(
            json.dumps({"last_refresh_at": "totally-not-a-date"})
        )
        assert _load_last_inky_refresh(str(tmp_path)) is None

    def test_returns_none_when_json_root_is_not_an_object(self, tmp_path):
        """Valid JSON that isn't a dict (e.g. a list or string) must not raise."""
        (tmp_path / "inky_refresh_state.json").write_text(json.dumps([]))
        assert _load_last_inky_refresh(str(tmp_path)) is None
        (tmp_path / "inky_refresh_state.json").write_text(json.dumps("x"))
        assert _load_last_inky_refresh(str(tmp_path)) is None


class TestSaveLastInkyRefreshDefensive:
    def test_save_failure_logs_warning_and_does_not_raise(self, tmp_path, caplog):
        """A write failure must be caught and surfaced as a warning."""
        with caplog.at_level(logging.WARNING, logger="src.services.output"):
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                _save_last_inky_refresh(str(tmp_path), datetime(2026, 4, 8, 12, 0))

        assert "Inky refresh state" in caplog.text
