#!/usr/bin/env python3
"""Refresh the tested dependency snapshot in ``constraints/``.

``requirements*.txt`` stay minimum-version ranges; this script records one
resolution of them per supported Raspberry Pi OS release so a known install can
be reproduced. ``make pi-install`` installs through the snapshot that matches
the venv's Python (see docs/setup.md, "Reproducible installs").

Each snapshot is resolved with ``uv pip compile`` *for the Pi*, not for the host
running this script: 64-bit Raspberry Pi OS (aarch64, glibc 2.36 as the floor),
at the Python version that release ships. A pin whose line set is unchanged keeps
its ``# Verified:`` line; a changed snapshot resets it to pending until someone
runs the checklist in docs/setup.md on hardware and records the result.

Usage::

    python scripts/lock_deps.py                    # re-resolve every snapshot
    python scripts/lock_deps.py --waveshare master # pin the vendor driver tip
    python scripts/lock_deps.py --waveshare <sha>  # pin a specific commit

Needs ``uv`` on PATH (``pip install uv``) for the Python snapshots and ``git``
for ``--waveshare``. Both change only files under ``constraints/``.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSTRAINTS_DIR = REPO_ROOT / "constraints"
REQUIREMENTS = ("requirements.txt", "requirements-web.txt", "requirements-pi.txt")

#: Python version -> the Raspberry Pi OS release that ships it.
TARGETS = {
    "3.11": "Raspberry Pi OS Bookworm",
    "3.13": "Raspberry Pi OS Trixie",
}
#: uv's name for 64-bit Raspberry Pi OS: aarch64 at Bookworm's glibc.
PLATFORM = "aarch64-manylinux_2_36"

WAVESHARE_REPO = "https://github.com/waveshare/e-Paper"
WAVESHARE_REF_FILE = CONSTRAINTS_DIR / "waveshare-epd.ref"

PENDING = "# Verified: pending -- run the hardware checklist in docs/setup.md"
VERIFIED_RE = re.compile(r"^# Verified:.*$", re.MULTILINE)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def snapshot_path(python: str) -> Path:
    return CONSTRAINTS_DIR / f"py{python}.txt"


def pins(text: str) -> list[str]:
    """The non-comment lines of a snapshot, i.e. what pip actually reads."""
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def resolve(python: str) -> list[str]:
    """Return ``name==version`` lines for every requirement at ``python`` on the Pi."""
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("uv not found on PATH; install it with `pip install uv`")
    out = subprocess.run(
        [
            uv,
            "pip",
            "compile",
            "--quiet",
            "--no-header",
            "--no-annotate",
            "--python-version",
            python,
            "--python-platform",
            PLATFORM,
            *REQUIREMENTS,
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return pins(out)


def render(python: str, lines: list[str], verified: str) -> str:
    header = [
        f"# Tested dependency snapshot: {TARGETS[python]}, Python {python}, 64-bit (aarch64).",
        "# Resolved by scripts/lock_deps.py from " + ", ".join(REQUIREMENTS) + ".",
        "# Installed by `make pi-install`; refresh procedure in docs/setup.md.",
        verified,
    ]
    return "\n".join(header + lines) + "\n"


def write_snapshot(python: str) -> bool:
    """Re-resolve one snapshot; return True when its pins changed."""
    path = snapshot_path(python)
    old = path.read_text() if path.exists() else ""
    lines = resolve(python)
    changed = pins(old) != lines
    match = VERIFIED_RE.search(old)
    verified = PENDING if changed or match is None else match.group(0)
    path.write_text(render(python, lines, verified))
    return changed


def resolve_waveshare(ref: str) -> str:
    """Turn a branch or tag name into the commit it names; pass a SHA through."""
    if SHA_RE.match(ref):
        return ref
    out = subprocess.run(
        ["git", "ls-remote", WAVESHARE_REPO, ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if not out or not SHA_RE.match(out[0]):
        sys.exit(f"{ref!r} names no ref in {WAVESHARE_REPO}")
    return out[0]


def write_waveshare(ref: str) -> str:
    """Record the commit *ref* names; an unchanged commit keeps its Verified line."""
    sha = resolve_waveshare(ref)
    old = WAVESHARE_REF_FILE.read_text() if WAVESHARE_REF_FILE.exists() else ""
    match = VERIFIED_RE.search(old)
    unchanged = sha in old.splitlines() and match is not None
    verified = match.group(0) if unchanged else PENDING
    WAVESHARE_REF_FILE.write_text(
        "# Tested waveshare/e-Paper commit, installed by `make install-display-drivers`.\n"
        "# Refresh with `scripts/lock_deps.py --waveshare <ref>` (docs/setup.md).\n"
        f"{verified}\n"
        f"{sha}\n"
    )
    return sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--waveshare",
        metavar="REF",
        help="pin the Waveshare driver to REF (branch, tag or commit) instead of "
        "re-resolving the Python snapshots",
    )
    args = parser.parse_args(argv)

    CONSTRAINTS_DIR.mkdir(exist_ok=True)
    if args.waveshare:
        sha = write_waveshare(args.waveshare)
        print(f"{WAVESHARE_REF_FILE.relative_to(REPO_ROOT)}: {sha} (verification pending)")
        return 0
    for python in TARGETS:
        changed = write_snapshot(python)
        state = "changed, verification pending" if changed else "unchanged"
        print(f"{snapshot_path(python).relative_to(REPO_ROOT)}: {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
