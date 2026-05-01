"""Enforce ``tools/check_naive_datetime.py`` returns clean in CI.

Each new naive ``datetime.now()`` / ``datetime.utcnow()`` call under ``src/``
must either use :mod:`src._time` helpers or carry a ``# noqa: NAIVE_DATETIME``
comment on the same line. Without this test, drift from the convention only
surfaces when a downstream timestamp bug appears.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "tools" / "check_naive_datetime.py"


def test_no_naive_datetime_in_src():
    result = subprocess.run(
        [sys.executable, str(GUARD)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"naive datetime guard reported violations:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
