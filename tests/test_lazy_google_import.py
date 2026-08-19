"""Guard: importing the fetcher package must not pull the Google API stack.

Regression test for #211 — googleapiclient + friends cost 1-2 s to import
on a Pi, and every run (ICS-only, CalDAV-only, --dummy, the web server via
state_reader) imports src.fetchers through the registry side-effect
imports. The heavy imports are deferred into _build_service /
_fetch_incremental so only Google-API runs pay for them.

Runs in a subprocess so prior in-process imports can't pre-populate
sys.modules and mask a leak (same pattern as the naive-datetime guard).
"""

import subprocess
import sys

_HEAVY = ("googleapiclient", "google.oauth2", "google_auth_httplib2", "httplib2")


def _import_leaks(module: str) -> list[str]:
    code = (
        "import sys\n"
        f"import {module}\n"
        f"leaked = [m for m in {_HEAVY!r} if m in sys.modules]\n"
        "print(','.join(leaked))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    out = result.stdout.strip()
    return out.split(",") if out else []


class TestLazyGoogleImport:
    def test_importing_fetchers_package_is_google_free(self):
        assert _import_leaks("src.fetchers") == []

    def test_importing_cache_is_google_free(self):
        # The web server reaches the fetcher layer through state_reader →
        # src.fetchers.cache; that path must stay light too.
        assert _import_leaks("src.fetchers.cache") == []

    def test_importing_calendar_google_is_google_free(self):
        assert _import_leaks("src.fetchers.calendar_google") == []
