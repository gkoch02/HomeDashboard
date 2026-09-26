"""HTTP Basic Auth for the Dashboard web UI.

Passwords are stored as scrypt hashes in config/web.yaml — no extra dependencies,
pure stdlib. Run ``python -m src.web.auth --set-password`` to generate a hash.

Auth is optional: if no password_hash is configured the server still starts but
logs a warning and serves all routes unauthenticated. This is intentional for
local/development use; set a password before exposing the UI on a network.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import logging
import os
import sys

from flask import Response, g, request

logger = logging.getLogger(__name__)

# Scrypt parameters — conservative enough for a Pi, strong enough for a local service.
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32


def hash_password(password: str) -> str:
    """Return a storable scrypt hash string for *password*."""
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt:{base64.b64encode(salt).decode()}:{base64.b64encode(dk).decode()}"


def check_password(password: str, stored_hash: str) -> bool:
    """Return True if *password* matches *stored_hash*."""
    if not stored_hash.startswith("scrypt:"):
        return False
    try:
        _, salt_b64, dk_b64 = stored_hash.split(":", 2)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# Paths an uptime monitor must reach without credentials: a probe that cannot
# send Basic Auth got a 401 indistinguishable from "down" (#309). An
# unauthenticated caller gets the status code and a bare healthy flag — the
# route reads ``g.web_authenticated`` — never timestamps or exception types.
PUBLIC_PATHS = frozenset({"/api/health"})


def make_auth_middleware(username: str | None, password_hash: str | None):
    """Return a before_request function that enforces Basic Auth.

    If *username* or *password_hash* is falsy, auth is skipped (open access)
    and a one-time warning is logged at startup.
    """
    if not username or not password_hash:
        logger.warning(
            "Web UI auth is NOT configured — all routes are publicly accessible. "
            "Set auth.username and auth.password_hash in config/web.yaml."
        )

        def _no_auth():
            pass  # open access: routes treat an unset g.web_authenticated as True

        return _no_auth

    def _check_auth():
        auth = request.authorization
        if auth and auth.username == username and check_password(auth.password, password_hash):
            g.web_authenticated = True
            return None
        if request.path in PUBLIC_PATHS:
            g.web_authenticated = False
            return None
        return Response(
            "Dashboard authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="Dashboard"'},
        )

    return _check_auth


# ---------------------------------------------------------------------------
# CLI helper: python -m src.web.auth --set-password
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--set-password" in sys.argv:
        pw = getpass.getpass("New password: ")
        pw2 = getpass.getpass("Confirm password: ")
        if pw != pw2:
            print("Passwords do not match.", file=sys.stderr)
            sys.exit(1)
        print(hash_password(pw))
    else:
        print("Usage: python -m src.web.auth --set-password")
        sys.exit(1)
