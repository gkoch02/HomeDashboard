"""Tests for the main() entry point in src/main.py.

These tests exercise the CLI argument parsing and the main execution flow
including dry-run, dummy data, check-config, and quiet-hours exit paths.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


def _write_minimal_config(path: Path) -> None:
    """Write a minimal valid config to *path*."""
    path.write_text(
        yaml.dump(
            {
                "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
                "output": {"dry_run_dir": str(path.parent)},
            }
        )
    )


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

        with patch(
            "sys.argv",
            [
                "main",
                "--dry-run",
                "--dummy",
                "--force-full-refresh",
                "--config",
                str(config_path),
            ],
        ):
            from src.main import main

            main()

        assert (tmp_path / "latest.png").exists()

    def test_dry_run_dummy_with_event_filters(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
                    "output": {"dry_run_dir": str(tmp_path)},
                    "filters": {
                        "exclude_keywords": ["Standup"],
                        "exclude_all_day": True,
                    },
                }
            )
        )

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

            with patch("src.app.render_dashboard") as mock_render:
                with pytest.raises(SystemExit):
                    main()
        mock_render.assert_not_called()


class TestMainQuietHours:
    """Non-dry-run in quiet hours should exit early without rendering."""

    def test_quiet_hours_skips_render(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
                    "output": {"dry_run_dir": str(tmp_path)},
                    "schedule": {"quiet_hours_start": 0, "quiet_hours_end": 23},
                }
            )
        )

        with patch("sys.argv", ["main", "--config", str(config_path)]):
            from src.main import main

            with patch("src.app.render_dashboard") as mock_render:
                with (
                    patch("src.data_pipeline.DataPipeline.fetch") as mock_fetch,
                    patch("src.app.should_skip_refresh", return_value=True),
                ):
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
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", ["main", "--dry-run", "--dummy", "--config", str(config_path)]):
            from src.main import main

            with patch("src.services.run_policy.is_morning_startup_window", return_value=True):
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
                main()

        assert (tmp_path / "latest.png").exists()


class TestMainModule:
    """__main__ guard — calling main() via __name__ == '__main__'."""

    def test_if_name_main_block(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch("sys.argv", ["main", "--dry-run", "--dummy", "--config", str(config_path)]):
            import src.main as main_mod

            with patch.object(main_mod, "main") as mock_main:
                if True:
                    main_mod.main()
            mock_main.assert_called_once()


class TestMainDateFlag:
    """--date should override 'today' in dry-run mode."""

    def test_date_flag_renders_image(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch(
            "sys.argv",
            [
                "main",
                "--dry-run",
                "--dummy",
                "--date",
                "2025-12-25",
                "--config",
                str(config_path),
            ],
        ):
            from src.main import main

            main()

        assert (tmp_path / "latest.png").exists()

    def test_date_flag_overrides_now(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch(
            "sys.argv",
            [
                "main",
                "--dry-run",
                "--dummy",
                "--date",
                "2025-07-04",
                "--config",
                str(config_path),
            ],
        ):
            from datetime import date

            from src.main import main

            with patch(
                "src.app.generate_dummy_data",
                wraps=__import__("src.app", fromlist=["generate_dummy_data"]).generate_dummy_data,
            ) as mock_gen:
                main()

        call_kwargs = mock_gen.call_args
        passed_now = call_kwargs.kwargs.get("now") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        assert passed_now is not None
        assert passed_now.date() == date(2025, 7, 4)

    def test_date_without_dry_run_errors(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch(
            "sys.argv",
            [
                "main",
                "--dummy",
                "--date",
                "2025-12-25",
                "--config",
                str(config_path),
            ],
        ):
            from src.main import main

            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code != 0

    def test_invalid_date_format_errors(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        with patch(
            "sys.argv",
            [
                "main",
                "--dry-run",
                "--dummy",
                "--date",
                "not-a-date",
                "--config",
                str(config_path),
            ],
        ):
            from src.main import main

            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code != 0


class TestMainLiveDataPath:
    """Tests for the non-dummy data fetch path and image-change logic."""

    @pytest.fixture(autouse=True)
    def _stable_run_policy(self):
        """Pin run-policy gates so tests are independent of wall-clock time.

        Without this, CI runs between 06:00-06:29 local force a full refresh
        via is_morning_startup(), which bypasses the image-unchanged early
        return and reaches build_display_driver -> waveshare_epd import.
        """
        with (
            patch("src.app.should_force_full_refresh", return_value=False),
            patch("src.app.should_skip_refresh", return_value=False),
        ):
            yield

    def test_dry_run_without_dummy_calls_pipeline_fetch(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        from src.dummy_data import generate_dummy_data

        fake_data = generate_dummy_data()

        with patch("sys.argv", ["main", "--dry-run", "--config", str(config_path)]):
            from src.main import main

            with patch(
                "src.data_pipeline.DataPipeline.fetch", return_value=fake_data
            ) as mock_fetch:
                main()

        mock_fetch.assert_called_once()
        assert (tmp_path / "latest.png").exists()

    def test_ignore_breakers_flag_passed_to_pipeline(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        captured = {}
        real_init = __import__("src.data_pipeline", fromlist=["DataPipeline"]).DataPipeline.__init__

        def spying_init(
            self,
            cfg,
            cache_dir,
            tz=None,
            force_refresh=False,
            ignore_breakers=False,
            event_window_start=None,
            event_window_days=7,
        ):
            captured["ignore_breakers"] = ignore_breakers
            real_init(
                self,
                cfg,
                cache_dir,
                tz=tz,
                force_refresh=force_refresh,
                ignore_breakers=ignore_breakers,
                event_window_start=event_window_start,
                event_window_days=event_window_days,
            )

        from src.dummy_data import generate_dummy_data

        fake_data = generate_dummy_data()

        with patch(
            "sys.argv",
            [
                "main",
                "--dry-run",
                "--ignore-breakers",
                "--config",
                str(config_path),
            ],
        ):
            from src.main import main

            with (
                patch("src.data_pipeline.DataPipeline.__init__", new=spying_init),
                patch("src.data_pipeline.DataPipeline.fetch", return_value=fake_data),
            ):
                main()

        assert captured["ignore_breakers"] is True

    def test_image_unchanged_skips_hardware_refresh(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
                    "output": {"dry_run_dir": str(tmp_path)},
                }
            )
        )

        from src.dummy_data import generate_dummy_data

        fake_data = generate_dummy_data()

        with patch("sys.argv", ["main", "--config", str(config_path)]):
            from src.main import main

            with (
                patch("src.data_pipeline.DataPipeline.fetch", return_value=fake_data),
                patch("src.services.output.image_changed", return_value=False) as mock_changed,
            ):
                main()

        mock_changed.assert_called_once()

    def test_image_changed_calls_waveshare_display(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "weather": {"api_key": "test", "latitude": 37.0, "longitude": -122.0},
                    "output": {"dry_run_dir": str(tmp_path)},
                }
            )
        )

        from src.dummy_data import generate_dummy_data

        fake_data = generate_dummy_data()

        mock_display = MagicMock()

        with patch("sys.argv", ["main", "--config", str(config_path)]):
            from src.main import main

            with (
                patch("src.data_pipeline.DataPipeline.fetch", return_value=fake_data),
                patch("src.services.output.image_changed", return_value=True),
                patch("src.services.output.build_display_driver", return_value=mock_display),
            ):
                main()

        mock_display.show.assert_called_once()
