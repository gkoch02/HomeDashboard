"""Tests for src/services/output.py (OutputService)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from src.services.output import OutputService


def _make_image(w: int = 800, h: int = 480) -> Image.Image:
    return Image.new("1", (w, h), 1)


def _make_cfg(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.output_dir = str(tmp_path)
    cfg.display.model = "epd7in5_V2"
    cfg.display.enable_partial_refresh = False
    cfg.display.max_partials_before_full = 4
    return cfg


def _make_tz():
    import zoneinfo

    return zoneinfo.ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# publish() — dry-run path
# ---------------------------------------------------------------------------


class TestPublishDryRun:
    def test_calls_dry_run_display_show(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with patch("src.services.output.DryRunDisplay", return_value=mock_display) as mock_cls:
            svc.publish(image, dry_run=True, force_full=False)

        mock_cls.assert_called_once_with(output_dir=str(tmp_path))
        mock_display.show.assert_called_once_with(image)

    def test_dry_run_returns_immediately_no_waveshare(self, tmp_path):
        """dry_run=True must never touch WaveshareDisplay."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.DryRunDisplay", return_value=MagicMock()),
            patch("src.services.output.image_changed") as mock_changed,
        ):
            svc.publish(image, dry_run=True, force_full=False)

        mock_changed.assert_not_called()

    def test_dry_run_force_full_still_uses_dry_run_display(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with patch("src.services.output.DryRunDisplay", return_value=mock_display):
            svc.publish(image, dry_run=True, force_full=True)

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
            patch("src.display.driver.WaveshareDisplay") as mock_ws,
        ):
            svc.publish(image, dry_run=False, force_full=False)

        mock_ws.assert_not_called()

    def test_image_changed_calls_waveshare(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.display.driver.WaveshareDisplay", return_value=mock_display),
        ):
            svc.publish(image, dry_run=False, force_full=False)

        mock_display.show.assert_called_once_with(image, force_full=False)

    def test_force_full_bypasses_change_check(self, tmp_path):
        """force_full=True should call WaveshareDisplay even when image is unchanged."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with (
            patch("src.services.output.image_changed", return_value=False),
            patch("src.display.driver.WaveshareDisplay", return_value=mock_display),
        ):
            svc.publish(image, dry_run=False, force_full=True)

        mock_display.show.assert_called_once_with(image, force_full=True)

    def test_waveshare_constructed_with_config_values(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.display.model = "epd7in5_HD"
        cfg.display.enable_partial_refresh = True
        cfg.display.max_partials_before_full = 7

        svc = OutputService(cfg, _make_tz())
        image = _make_image()
        mock_display = MagicMock()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.display.driver.WaveshareDisplay", return_value=mock_display) as mock_cls,
        ):
            svc.publish(image, dry_run=False, force_full=False)

        mock_cls.assert_called_once_with(
            model="epd7in5_HD",
            enable_partial=True,
            max_partials=7,
        )

    def test_image_changed_called_with_correct_args(self, tmp_path):
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=False) as mock_changed,
            patch("src.display.driver.WaveshareDisplay"),
        ):
            svc.publish(image, dry_run=False, force_full=False)

        mock_changed.assert_called_once_with(image, str(tmp_path))

    def test_hardware_publish_saves_latest_png(self, tmp_path):
        """After a hardware display write, latest.png must be updated."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.display.driver.WaveshareDisplay", return_value=MagicMock()),
        ):
            svc.publish(image, dry_run=False, force_full=False)

        assert (tmp_path / "latest.png").exists()

    def test_hardware_publish_skipped_does_not_save_latest_png(self, tmp_path):
        """When the image is unchanged and not forced, latest.png must not be written."""
        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=False),
            patch("src.display.driver.WaveshareDisplay", return_value=MagicMock()),
        ):
            svc.publish(image, dry_run=False, force_full=False)

        assert not (tmp_path / "latest.png").exists()

    def test_hardware_publish_latest_png_save_failure_does_not_raise(self, tmp_path, caplog):
        """A failure saving latest.png must log a warning but not crash."""
        import logging

        svc = OutputService(_make_cfg(tmp_path), _make_tz())
        image = _make_image()

        with (
            patch("src.services.output.image_changed", return_value=True),
            patch("src.display.driver.WaveshareDisplay", return_value=MagicMock()),
            patch.object(image, "save", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="src.services.output"),
        ):
            svc.publish(image, dry_run=False, force_full=False)  # must not raise

        assert "latest.png" in caplog.text


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
        import logging

        svc = OutputService(_make_cfg(tmp_path), _make_tz())

        with caplog.at_level(logging.WARNING, logger="src.services.output"):
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                svc.write_health_marker()  # must not raise

        assert "last_success.txt" in caplog.text
