"""Simple CSRF protection helpers for the Dashboard web UI.

This is intentionally lightweight: we mint a random session-bound token and
require clients to echo it in an ``X-CSRF-Token`` header for all mutating
requests. The token is also exposed to templates so the existing vanilla JS can
pick it up without any framework/session dependency.
"""

from __future__ import annotations

import hmac
import secrets

from flask import abort, jsonify, make_response, request, session

_SESSION_KEY = "csrf_token"

# With the default ephemeral secret key every session — and so every open
# tab's token — dies when the service restarts. The 403 must be JSON the
# client's resp.json() can parse, naming the fix (a reload).
EXPIRED_MESSAGE = (
    "Your session has expired — the web service probably restarted. Reload the page and try again."
)


def get_csrf_token() -> str:
    token = session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_SESSION_KEY] = token
    return token


def csrf_protect() -> None:
    expected = get_csrf_token()
    provided = request.headers.get("X-CSRF-Token", "")
    # Bytes, because compare_digest raises on a non-ASCII str and a header can carry one.
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        body = {
            "ok": False,
            "csrf_expired": True,
            "error": EXPIRED_MESSAGE,
            "message": EXPIRED_MESSAGE,
        }
        abort(make_response(jsonify(body), 403))
