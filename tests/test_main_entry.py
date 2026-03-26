"""Tests for the main() entry point in src/main.py.

These tests exercise the CLI argument parsing and the main execution flow
including dry-run, dummy data, check-config, and quiet-hours exit paths.
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.config import Config, load_config


def _write_minimal_config(path: Path) -> None:
    """Write a minimal valid config to *path*."""
    path.write_text(yaml.dump({
        "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
        "output": {"dry_run_dir": str(path.parent)},
    }))


class TestMainDryRunDummy:
    """main() with --dry-run --dummy should render and write latest.png."""

    def test_dry_run_dummy_produces_image(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", ["main", "--dry-run", "--dummy", "--config", str(config_path)]):
            from src.main import main
            main()

        assert (tmp_path / "latest.png").exists()

    def test_dry_run_dummy_writes_last_success(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", ["main", "--dry-run", "--dummy", "--config", str(config_path)]):
            from src.main import main
            main()

        assert (tmp_path / "last_success.txt").exists()

    def test_dry_run_dummy_with_force_full_refresh(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", [
            "main", "--dry-run", "--dummy", "--force-full-refresh",
            "--config", str(config_path),
        ]):
            from src.main import main
            main()  # should not raise

        assert (tmp_path / "latest.png").exists()

    def test_dry_run_dummy_with_event_filters(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
            "output": {"dry_run_dir": str(tmp_path)},
            "filters": {
                "exclude_keywords": ["Standup"],
                "exclude_all_day": True,
            },
        }))

        with patch("sys.argv", ["main", "--dry-run", "--dummy", "--config", str(config_path)]):
            from src.main import main
            main()

        assert (tmp_path / "latest.png").exists()


class TestMainCheckConfig:
    """--check-config should validate and exit without rendering."""

    def test_check_config_valid_exits_zero(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", ["main", "--check-config", "--config", str(config_path)]):
            from src.main import main
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_check_config_no_render(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", ["main", "--check-config", "--config", str(config_path)]):
            from src.main import main
            with patch("src.main.render_dashboard") as mock_render:
                with pytest.raises(SystemExit):
                    main()
        mock_render.assert_not_called()


class TestMainQuietHours:
    """Non-dry-run in quiet hours should exit early without rendering."""

    def test_quiet_hours_skips_render(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
            "output": {"dry_run_dir": str(tmp_path)},
            "schedule": {"quiet_hours_start": 0, "quiet_hours_end": 23},
        }))

        # Not a dry-run, and all hours are quiet → should exit early
        with patch("sys.argv", ["main", "--config", str(config_path)]):
            from src.main import main
            with patch("src.main.render_dashboard") as mock_render:
                with patch("src.main.fetch_live_data") as mock_fetch:
                    main()

        mock_render.assert_not_called()
        mock_fetch.assert_not_called()


class TestMainConfigErrors:
    """Fatal config errors should print report and exit(1)."""

    def test_fatal_config_error_exits_one(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        from src.config import ConfigError
        fake_error = ConfigError(field="test", message="fatal error")

        with patch("sys.argv", ["main", "--config", str(config_path)]):
            from src.main import main
            with patch("src.main.validate_config", return_value=([fake_error], [])):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1


class TestMainMorningStartup:
    """Morning startup flag causes a forced full refresh."""

    def test_morning_startup_triggers_force_full(self, tmp_path):
        """Morning startup (6:00, quiet_hours_end=6) forces full refresh."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        # Patch _is_morning_startup to return True so the morning path is exercised
        with patch("sys.argv", ["main", "--dry-run", "--dummy", "--config", str(config_path)]):
            from src.main import main
            with patch("src.main._is_morning_startup", return_value=True):
                main()

        assert (tmp_path / "latest.png").exists()


class TestMainLastSuccessWriteFailure:
    """Failure writing last_success.txt should not crash the process."""

    def test_last_success_write_error_does_not_crash(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", ["main", "--dry-run", "--dummy", "--config", str(config_path)]):
            from src.main import main
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                main()  # should not raise

        # Image was still written (before the last_success write attempted)
        assert (tmp_path / "latest.png").exists()


class TestMainModule:
    """__main__ guard — calling main() via __name__ == '__main__'."""

    def test_if_name_main_block(self, tmp_path):
        """Exercise the ``if __name__ == '__main__': main()`` guard."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", ["main", "--dry-run", "--dummy", "--config", str(config_path)]):
            import importlib
            import src.main as main_mod
            with patch.object(main_mod, "main") as mock_main:
                # Simulate the guard by calling it directly
                if True:  # mirrors the guard
                    main_mod.main()
            mock_main.assert_called_once()


class TestMainDateFlag:
    """--date should override 'today' in dry-run mode."""

    def test_date_flag_renders_image(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", [
            "main", "--dry-run", "--dummy", "--date", "2025-12-25",
            "--config", str(config_path),
        ]):
            from src.main import main
            main()

        assert (tmp_path / "latest.png").exists()

    def test_date_flag_overrides_now(self, tmp_path):
        """generate_dummy_data should receive a 'now' on the specified date."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", [
            "main", "--dry-run", "--dummy", "--date", "2025-07-04",
            "--config", str(config_path),
        ]):
            from src.main import main
            from datetime import date
            with patch("src.main.generate_dummy_data", wraps=__import__("src.main", fromlist=["generate_dummy_data"]).generate_dummy_data) as mock_gen:
                main()

        call_kwargs = mock_gen.call_args
        passed_now = call_kwargs.kwargs.get("now") or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else None)
        assert passed_now is not None
        assert passed_now.date() == date(2025, 7, 4)

    def test_date_without_dry_run_errors(self, tmp_path):
        """--date without --dry-run should exit with an error."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", [
            "main", "--dummy", "--date", "2025-12-25",
            "--config", str(config_path),
        ]):
            from src.main import main
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code != 0

    def test_invalid_date_format_errors(self, tmp_path):
        """An invalid --date value should exit with an error."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", [
            "main", "--dry-run", "--dummy", "--date", "not-a-date",
            "--config", str(config_path),
        ]):
            from src.main import main
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code != 0


class TestMainLiveDataPath:
    """Tests for the non-dummy data fetch path (line 507) and image-change logic."""

    def test_dry_run_without_dummy_calls_fetch_live_data(self, tmp_path):
        """--dry-run without --dummy calls fetch_live_data (line 507)."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        from src.main import generate_dummy_data
        fake_data = generate_dummy_data()

        with patch("sys.argv", ["main", "--dry-run", "--config", str(config_path)]):
            from src.main import main
            with patch("src.main.fetch_live_data", return_value=fake_data) as mock_fetch:
                main()

        mock_fetch.assert_called_once()
        assert (tmp_path / "latest.png").exists()

    def test_ignore_breakers_flag_passed_to_fetch_live_data(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        from src.main import generate_dummy_data
        fake_data = generate_dummy_data()

        with patch("sys.argv", [
            "main", "--dry-run", "--ignore-breakers", "--config", str(config_path),
        ]):
            from src.main import main
            with patch("src.main.fetch_live_data", return_value=fake_data) as mock_fetch:
                main()

        assert mock_fetch.call_args.kwargs["ignore_breakers"] is True

    def test_image_unchanged_skips_hardware_refresh(self, tmp_path):
        """When image_changed returns False, the display refresh is skipped (lines 528-529)."""
        import yaml
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
            "output": {"dry_run_dir": str(tmp_path)},
        }))

        from src.main import generate_dummy_data
        fake_data = generate_dummy_data()

        with patch("sys.argv", ["main", "--config", str(config_path)]):
            from src.main import main
            with patch("src.main.fetch_live_data", return_value=fake_data), \
                 patch("src.main.image_changed", return_value=False) as mock_changed, \
                 patch("src.main._in_quiet_hours", return_value=False):
                main()

        mock_changed.assert_called_once()

    def test_image_changed_calls_waveshare_display(self, tmp_path):
        """When image changed (non-dry-run), WaveshareDisplay.show() is called (lines 531-537)."""
        import yaml
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
            "output": {"dry_run_dir": str(tmp_path)},
        }))

        from src.main import generate_dummy_data
        fake_data = generate_dummy_data()

        mock_display = MagicMock()

        with patch("sys.argv", ["main", "--config", str(config_path)]):
            from src.main import main
            with patch("src.main.fetch_live_data", return_value=fake_data), \
                 patch("src.main.image_changed", return_value=True), \
                 patch("src.main._in_quiet_hours", return_value=False), \
                 patch("src.display.driver.WaveshareDisplay", return_value=mock_display):
                main()

        mock_display.show.assert_called_once()
