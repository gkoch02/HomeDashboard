#!/usr/bin/env python3
"""Cut a release: bump the version, date the changelog, commit, and tag.

The version lives in exactly one place — ``src/_version.py``. ``pyproject.toml``
reads it via ``[tool.setuptools.dynamic]``, so this script never has to edit two
files in lockstep.

The bump size is inferred from the ``## [Unreleased]`` block in ``CHANGELOG.md``,
following Keep a Changelog conventions:

* an ``### Added`` / ``### Changed`` / ``### Deprecated`` / ``### Removed``
  section present  -> **minor**
* only ``### Fixed`` / ``### Security``                 -> **patch**

A **major** bump is never inferred. "Is this breaking?" is a judgement call the
changelog headings cannot answer, so it must be asked for explicitly with
``--major`` or ``--version``.

Usage::

    python scripts/release.py --dry-run     # show the plan, touch nothing
    python scripts/release.py               # infer the bump and cut it
    python scripts/release.py --minor       # force a bump size
    python scripts/release.py --version 6.0.0
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "src" / "_version.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

VERSION_RE = re.compile(r'^__version__\s*=\s*"(?P<version>[^"]+)"', re.MULTILINE)
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
UNRELEASED_HEADING = "## [Unreleased]"

#: Changelog sections that imply new surface area rather than a pure fix.
MINOR_SECTIONS = {"Added", "Changed", "Deprecated", "Removed"}
PATCH_SECTIONS = {"Fixed", "Security"}


class ReleaseError(RuntimeError):
    """A precondition failed; the working tree has not been touched."""


# --------------------------------------------------------------------------
# reading state
# --------------------------------------------------------------------------


def read_version() -> tuple[int, int, int]:
    """Return the current version from ``src/_version.py`` as a triple."""
    match = VERSION_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if match is None:
        raise ReleaseError(f"no __version__ assignment found in {VERSION_FILE}")
    return parse_semver(match.group("version"))


def parse_semver(raw: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(raw.strip())
    if match is None:
        raise ReleaseError(f"{raw!r} is not a MAJOR.MINOR.PATCH version")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def fmt(version: tuple[int, int, int]) -> str:
    return "{}.{}.{}".format(*version)


def unreleased_block(text: str) -> str:
    """Return the body of the ``## [Unreleased]`` section, without its heading.

    Raises when the heading is missing entirely — that means the changelog has
    drifted from the format every other tool here assumes.
    """
    start = text.find(UNRELEASED_HEADING)
    if start == -1:
        raise ReleaseError(
            f"{CHANGELOG.name} has no '{UNRELEASED_HEADING}' heading — "
            "add one above the newest release before cutting a release"
        )
    body_start = start + len(UNRELEASED_HEADING)
    next_release = re.search(r"^## \[", text[body_start:], re.MULTILINE)
    end = body_start + next_release.start() if next_release else len(text)
    return text[body_start:end]


def sections_in(block: str) -> set[str]:
    """Return the ``### Foo`` heading names present in a changelog block."""
    return {m.group(1).strip() for m in re.finditer(r"^### (.+)$", block, re.MULTILINE)}


def infer_bump(block: str) -> str:
    """Infer ``"minor"`` or ``"patch"`` from an Unreleased block's sections."""
    sections = sections_in(block)
    if not sections:
        raise ReleaseError(
            f"the '{UNRELEASED_HEADING}' block is empty — nothing to release.\n"
            "Add the entries for this release under it, or pass an explicit "
            "--version / --major / --minor / --patch."
        )
    if sections & MINOR_SECTIONS:
        return "minor"
    if sections & PATCH_SECTIONS:
        return "patch"
    raise ReleaseError(
        "could not infer a bump from the Unreleased sections "
        f"{sorted(sections)}; pass --major / --minor / --patch explicitly"
    )


def apply_bump(current: tuple[int, int, int], bump: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def assert_clean_tree() -> None:
    if git("status", "--porcelain"):
        raise ReleaseError(
            "working tree has uncommitted changes — commit or stash them first "
            "so the release commit contains only the version and changelog"
        )


def assert_tag_free(tag: str) -> None:
    if git("tag", "--list", tag):
        raise ReleaseError(f"tag {tag} already exists")


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def rewrite_version_file(new_version: str) -> None:
    text = VERSION_FILE.read_text(encoding="utf-8")
    updated, count = VERSION_RE.subn(f'__version__ = "{new_version}"', text, count=1)
    if count != 1:
        raise ReleaseError(f"failed to rewrite {VERSION_FILE}")
    VERSION_FILE.write_text(updated, encoding="utf-8")


def roll_changelog(new_version: str, today: str) -> None:
    """Date the Unreleased block and open a fresh empty one above it."""
    text = CHANGELOG.read_text(encoding="utf-8")
    if UNRELEASED_HEADING not in text:
        raise ReleaseError(f"{CHANGELOG.name} has no '{UNRELEASED_HEADING}' heading")
    updated = text.replace(
        UNRELEASED_HEADING,
        f"{UNRELEASED_HEADING}\n\n## [{new_version}] - {today}",
        1,
    )
    CHANGELOG.write_text(updated, encoding="utf-8")


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cut a release: bump version, date the changelog, commit, tag."
    )
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--major", action="store_true", help="force a major bump")
    size.add_argument("--minor", action="store_true", help="force a minor bump")
    size.add_argument("--patch", action="store_true", help="force a patch bump")
    size.add_argument("--version", help="set an explicit MAJOR.MINOR.PATCH version")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan without editing, committing, or tagging",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="skip the clean-working-tree check (for testing this script)",
    )
    return parser


def resolve_target(args: argparse.Namespace, current: tuple[int, int, int], block: str):
    """Return ``(new_version_triple, how_it_was_chosen)``."""
    if args.version:
        return parse_semver(args.version), "explicit --version"
    for name in ("major", "minor", "patch"):
        if getattr(args, name):
            return apply_bump(current, name), f"explicit --{name}"
    bump = infer_bump(block)
    return apply_bump(current, bump), f"inferred {bump} from the Unreleased sections"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        current = read_version()
        text = CHANGELOG.read_text(encoding="utf-8")
        block = unreleased_block(text)
        new_version, reason = resolve_target(args, current, block)

        if new_version <= current:
            raise ReleaseError(
                f"refusing to go from {fmt(current)} to {fmt(new_version)} — "
                "the new version must be greater than the current one"
            )

        version_str = fmt(new_version)
        tag = f"v{version_str}"
        today = date.today().isoformat()

        assert_tag_free(tag)
        if not args.allow_dirty:
            assert_clean_tree()

        sections = sorted(sections_in(block)) or ["(none)"]
        print(f"current version : {fmt(current)}")
        print(f"new version     : {version_str}  ({reason})")
        print(f"tag             : {tag}")
        print(f"date            : {today}")
        print(f"changelog       : {', '.join(sections)}")

        if args.dry_run:
            print("\n--dry-run: nothing written.")
            return 0

        rewrite_version_file(version_str)
        roll_changelog(version_str, today)
        git("add", str(VERSION_FILE), str(CHANGELOG))
        git("commit", "-m", f"Release {version_str}")
        git("tag", "-a", tag, "-m", f"Release {version_str}")

        print(f"\nCommitted and tagged {tag}.")
        print(f"Push it with:  git push -u origin HEAD && git push origin {tag}")
        return 0

    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
