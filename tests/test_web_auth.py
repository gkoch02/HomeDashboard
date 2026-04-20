"""Tests for src.web.auth — password hashing, check_password, Basic Auth middleware, CLI."""

from __future__ import annotations

import logging
import runpy
import sys
from unittest.mock import patch

import pytest
from flask import Flask

from src.web.auth import check_password, hash_password, make_auth_middleware


def test_hash_password_includes_scrypt_prefix():
    h = hash_password("hunter2")
    assert h.startswith("scrypt:")
    # Format: scrypt:<base64 salt>:<base64 digest>
    assert h.count(":") == 2


def test_hash_password_roundtrip():
    h = hash_password("hunter2")
    assert check_password("hunter2", h) is True


def test_hash_password_different_each_call():
    """Salt should differ → two hashes of the same password are distinct."""
    assert hash_password("same") != hash_password("same")


def test_check_password_rejects_wrong_password():
    h = hash_password("correct")
    assert check_password("wrong", h) is False


def test_check_password_rejects_non_scrypt_prefix():
    assert check_password("x", "md5:garbage") is False
    assert check_password("x", "") is False
    assert check_password("x", "scrypthash-no-colon") is False


def test_check_password_handles_malformed_scrypt_payload():
    # Valid prefix but invalid base64 / wrong number of parts → exception swallowed.
    assert check_password("x", "scrypt:not-base64!:also-not-base64!") is False
    assert check_password("x", "scrypt:onlyonepart") is False


def test_check_password_empty_password_against_valid_hash():
    h = hash_password("real")
    assert check_password("", h) is False


# ---------------------------------------------------------------------------
# make_auth_middleware
# ---------------------------------------------------------------------------


def test_make_auth_middleware_open_access_when_unconfigured(caplog):
    with caplog.at_level(logging.WARNING, logger="src.web.auth"):
        mw = make_auth_middleware(None, None)
    assert mw() is None
    assert any("NOT configured" in rec.message for rec in caplog.records)


def test_make_auth_middleware_open_access_when_username_missing(caplog):
    with caplog.at_level(logging.WARNING, logger="src.web.auth"):
        mw = make_auth_middleware("", "scrypt:xxx:yyy")
    assert mw() is None


def test_make_auth_middleware_open_access_when_password_missing(caplog):
    with caplog.at_level(logging.WARNING, logger="src.web.auth"):
        mw = make_auth_middleware("admin", "")
    assert mw() is None


def _app_with_auth(username, password_hash):
    """Build a minimal Flask app that runs the auth middleware on each request."""
    app = Flask(__name__)
    app.before_request(make_auth_middleware(username, password_hash))

    @app.route("/ping")
    def ping():
        return "pong"

    return app


def test_middleware_returns_401_without_credentials():
    h = hash_password("secret")
    app = _app_with_auth("admin", h)
    client = app.test_client()
    resp = client.get("/ping")
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers
    assert resp.headers["WWW-Authenticate"].startswith("Basic")


def test_middleware_returns_401_with_bad_credentials():
    h = hash_password("secret")
    app = _app_with_auth("admin", h)
    client = app.test_client()
    resp = client.get("/ping", headers={"Authorization": "Basic YWRtaW46d3Jvbmc="})
    assert resp.status_code == 401


def test_middleware_returns_401_with_wrong_username():
    h = hash_password("secret")
    app = _app_with_auth("admin", h)
    client = app.test_client()
    # other:secret
    resp = client.get("/ping", headers={"Authorization": "Basic b3RoZXI6c2VjcmV0"})
    assert resp.status_code == 401


def test_middleware_passes_with_correct_credentials():
    h = hash_password("secret")
    app = _app_with_auth("admin", h)
    client = app.test_client()
    # admin:secret
    resp = client.get("/ping", headers={"Authorization": "Basic YWRtaW46c2VjcmV0"})
    assert resp.status_code == 200
    assert resp.data == b"pong"


# ---------------------------------------------------------------------------
# CLI entrypoint: python -m src.web.auth --set-password
# ---------------------------------------------------------------------------


def test_cli_set_password_prints_hash(capsys):
    argv = ["src.web.auth", "--set-password"]
    with patch.object(sys, "argv", argv), patch("getpass.getpass", side_effect=["hello", "hello"]):
        runpy.run_module("src.web.auth", run_name="__main__")
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert out.startswith("scrypt:")
    # The printed hash must validate against the original password.
    assert check_password("hello", out) is True
    assert check_password("wrong", out) is False


def test_cli_set_password_mismatch_exits_1(capsys):
    argv = ["src.web.auth", "--set-password"]
    with (
        patch.object(sys, "argv", argv),
        patch("getpass.getpass", side_effect=["hello", "goodbye"]),
    ):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("src.web.auth", run_name="__main__")
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "do not match" in err


def test_cli_no_args_prints_usage_and_exits_1(capsys):
    argv = ["src.web.auth"]
    with patch.object(sys, "argv", argv):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("src.web.auth", run_name="__main__")
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Usage:" in out
