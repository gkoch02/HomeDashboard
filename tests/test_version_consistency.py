"""Guard the release invariants that used to drift by hand.

The version has exactly one home (``src/_version.py``) and exactly one mirror
that has to agree with it (the newest dated ``CHANGELOG.md`` entry). Both used
to be edited by hand in separate commits, which is how ``pyproject.toml`` and
``src/_version.py`` came to disagree — see the ``4.6.0`` / ``5.2.0`` pair in the
history. These tests fail the build rather than letting the drift ship.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
#: ``## [5.2.0] - 2026-08-21``. Older entries omit the date and some use two
#: components (``## [4.2]``), so the date and the patch component are optional.
RELEASE_HEADING_RE = re.compile(
    r"^## \[(?P<version>\d+(?:\.\d+)*)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?\s*$",
    re.MULTILINE,
)


@pytest.fixture(scope="module")
def version() -> str:
    from src._version import __version__

    return __version__


@pytest.fixture(scope="module")
def changelog_text() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def test_version_is_semver(version: str) -> None:
    assert SEMVER_RE.match(version), (
        f"__version__ is {version!r}; it must be MAJOR.MINOR.PATCH so the "
        "release script and the vX.Y.Z tag format stay derivable from it"
    )


def test_pyproject_does_not_pin_a_second_version() -> None:
    """``pyproject.toml`` must read the version, never restate it."""
    text = PYPROJECT.read_text(encoding="utf-8")
    hardcoded = re.search(r'^version\s*=\s*"', text, re.MULTILINE)
    assert hardcoded is None, (
        "pyproject.toml declares a literal version again. It must stay "
        'dynamic = ["version"] reading src/_version.py, or the two files can '
        "drift apart the way they did before 5.2.0."
    )
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "src._version.__version__"}' in text


def test_changelog_has_an_unreleased_heading(changelog_text: str) -> None:
    """The release script rolls this heading forward; it has to be there."""
    assert "## [Unreleased]" in changelog_text


def test_changelog_newest_entry_matches_version(version: str, changelog_text: str) -> None:
    """A bump without a changelog entry (or the reverse) fails here."""
    headings = RELEASE_HEADING_RE.findall(changelog_text)
    assert headings, "no '## [X.Y.Z]' release headings found in CHANGELOG.md"
    newest = headings[0][0]
    assert newest == version, (
        f"__version__ is {version} but the newest CHANGELOG entry is {newest}. "
        "Cut releases with `make release` so both move together."
    )


def test_newest_changelog_entry_is_dated(changelog_text: str) -> None:
    match = RELEASE_HEADING_RE.search(changelog_text)
    assert match is not None
    assert match.group("date"), (
        f"the newest release heading '## [{match.group('version')}]' has no date. "
        "Released entries are dated; undated work belongs under [Unreleased]."
    )


def test_release_versions_descend(changelog_text: str) -> None:
    """Newest first, no duplicates — so 'the newest entry' is unambiguous."""
    versions = [
        tuple(int(p) for p in v.split(".")) for v, _ in RELEASE_HEADING_RE.findall(changelog_text)
    ]
    assert len(versions) == len(set(versions)), "duplicate release headings in CHANGELOG.md"
    assert versions == sorted(versions, reverse=True), (
        "CHANGELOG.md release headings are not in descending version order"
    )
