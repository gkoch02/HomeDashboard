"""Tests for src/web/__main__.py — the `python -m src.web` entry point."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.web.__main__ import build_parser, main

# ---------------------------------------------------------------------------
# build_parser — argument shape
# ---------------------------------------------------------------------------


def test_build_parser_defaults():
    args = build_parser().parse_args([])
    assert args.config == "config/web.yaml"
    assert args.app_config == "config/config.yaml"
    assert args.port is None
    assert args.host is None


def test_build_parser_overrides():
    args = build_parser().parse_args(
        [
            "--config",
            "/tmp/web.yaml",
            "--app-config",
            "/tmp/app.yaml",
            "--port",
            "9000",
            "--host",
            "127.0.0.1",
        ]
    )
    assert args.config == "/tmp/web.yaml"
    assert args.app_config == "/tmp/app.yaml"
    assert args.port == 9000
    assert args.host == "127.0.0.1"


def test_build_parser_port_must_be_int():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--port", "not-a-number"])


# ---------------------------------------------------------------------------
# main() — exercises the runtime path with waitress mocked out
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_app():
    return MagicMock(name="flask_app")


def _patch_create_app(fake_app):
    return patch("src.web.__main__.create_app", return_value=fake_app)


def test_main_uses_defaults_when_config_missing(tmp_path, fake_app):
    """Missing web.yaml is handled gracefully — defaults to port 8080, host 0.0.0.0."""
    fake_serve = MagicMock()
    with (
        _patch_create_app(fake_app),
        patch("sys.argv", ["src.web", "--config", str(tmp_path / "missing.yaml")]),
        patch.dict("sys.modules", {"waitress": MagicMock(serve=fake_serve)}),
    ):
        main()

    fake_serve.assert_called_once()
    kwargs = fake_serve.call_args.kwargs
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8080


def test_main_reads_port_from_config(tmp_path, fake_app):
    cfg = tmp_path / "web.yaml"
    cfg.write_text("port: 9090\nhost: 127.0.0.1\n")
    fake_serve = MagicMock()
    with (
        _patch_create_app(fake_app),
        patch("sys.argv", ["src.web", "--config", str(cfg)]),
        patch.dict("sys.modules", {"waitress": MagicMock(serve=fake_serve)}),
    ):
        main()

    kwargs = fake_serve.call_args.kwargs
    assert kwargs["port"] == 9090
    assert kwargs["host"] == "127.0.0.1"


def test_main_cli_port_overrides_config(tmp_path, fake_app):
    cfg = tmp_path / "web.yaml"
    cfg.write_text("port: 9090\n")
    fake_serve = MagicMock()
    with (
        _patch_create_app(fake_app),
        patch("sys.argv", ["src.web", "--config", str(cfg), "--port", "5555"]),
        patch.dict("sys.modules", {"waitress": MagicMock(serve=fake_serve)}),
    ):
        main()
    assert fake_serve.call_args.kwargs["port"] == 5555


def test_main_cli_host_overrides_config(tmp_path, fake_app):
    cfg = tmp_path / "web.yaml"
    cfg.write_text("host: 127.0.0.1\n")
    fake_serve = MagicMock()
    with (
        _patch_create_app(fake_app),
        patch("sys.argv", ["src.web", "--config", str(cfg), "--host", "192.168.1.5"]),
        patch.dict("sys.modules", {"waitress": MagicMock(serve=fake_serve)}),
    ):
        main()
    assert fake_serve.call_args.kwargs["host"] == "192.168.1.5"


def test_main_warns_on_unreadable_config(tmp_path, fake_app, caplog):
    cfg = tmp_path / "web.yaml"
    cfg.write_text("not: valid: yaml: : :")
    fake_serve = MagicMock()
    with (
        _patch_create_app(fake_app),
        patch("sys.argv", ["src.web", "--config", str(cfg)]),
        patch.dict("sys.modules", {"waitress": MagicMock(serve=fake_serve)}),
        caplog.at_level(logging.WARNING),
    ):
        main()
    assert any("Could not read" in rec.message for rec in caplog.records)
    # Falls back to defaults.
    assert fake_serve.call_args.kwargs["port"] == 8080


def test_main_falls_back_to_flask_when_waitress_missing(tmp_path, fake_app, caplog):
    """When `import waitress` fails, fall back to app.run() with a warning."""
    # Setting sys.modules["waitress"] = None forces Python's import machinery
    # to raise ImportError for `from waitress import serve` without intercepting
    # any other imports inside main().
    with (
        _patch_create_app(fake_app),
        patch("sys.argv", ["src.web"]),
        patch.dict("sys.modules", {"waitress": None}),
        caplog.at_level(logging.WARNING),
    ):
        main()

    assert any("waitress not installed" in rec.message for rec in caplog.records)
    fake_app.run.assert_called_once()


def test_main_passes_config_paths_to_create_app(tmp_path, fake_app):
    cfg = tmp_path / "web.yaml"
    cfg.write_text("")
    app_cfg = tmp_path / "app.yaml"
    app_cfg.write_text("")
    fake_serve = MagicMock()
    with (
        patch("src.web.__main__.create_app", return_value=fake_app) as mock_create,
        patch("sys.argv", ["src.web", "--config", str(cfg), "--app-config", str(app_cfg)]),
        patch.dict("sys.modules", {"waitress": MagicMock(serve=fake_serve)}),
    ):
        main()
    mock_create.assert_called_once_with(web_config_path=str(cfg), app_config_path=str(app_cfg))
