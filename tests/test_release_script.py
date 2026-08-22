"""Tests for ``scripts/release.py``.

The script mutates the repository — it rewrites two files, commits, and tags —
so the behaviour that matters most is what happens when one of those steps
fails partway. Each test drives the real script against a throwaway git repo.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release.py"

CHANGELOG_SEED = """# Changelog

## [Unreleased]

### Fixed

- Something small.

## [1.2.3] - 2026-01-01

### Added

- The first thing.
"""


def _load_release_module():
    """Import ``scripts/release.py`` by path — ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location("_release_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves its module via sys.modules[cls.__module__]; without
    # this the decorator raises AttributeError on a module loaded by path.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def release(tmp_path, monkeypatch):
    """A release module pointed at a throwaway repo, plus that repo's path."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "_version.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_SEED, encoding="utf-8")

    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "seed")

    module = _load_release_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "VERSION_FILE", tmp_path / "src" / "_version.py")
    monkeypatch.setattr(module, "CHANGELOG", tmp_path / "CHANGELOG.md")
    return module, tmp_path


# --------------------------------------------------------------------------
# bump inference
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ("Added", "minor"),
        ("Changed", "minor"),
        ("Deprecated", "minor"),
        ("Removed", "minor"),
        ("Fixed", "patch"),
        ("Security", "patch"),
    ],
)
def test_infer_bump_from_section(release, section, expected):
    module, _ = release
    assert module.infer_bump(f"\n\n### {section}\n\n- An entry.\n") == expected


def test_added_beats_fixed(release):
    """A block with both is a feature release, not a patch."""
    module, _ = release
    block = "\n\n### Fixed\n\n- A fix.\n\n### Added\n\n- A feature.\n"
    assert module.infer_bump(block) == "minor"


def test_major_is_never_inferred(release):
    """No combination of headings may produce a major bump."""
    module, _ = release
    every = "".join(
        f"\n\n### {name}\n\n- x.\n" for name in module.MINOR_SECTIONS | module.PATCH_SECTIONS
    )
    assert module.infer_bump(every) != "major"


def test_empty_unreleased_block_is_an_error(release):
    module, _ = release
    with pytest.raises(module.ReleaseError, match="empty"):
        module.infer_bump("\n\n")


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


def test_release_bumps_commits_and_tags(release):
    module, repo = release
    assert module.main([]) == 0

    assert '__version__ = "1.2.4"' in (repo / "src" / "_version.py").read_text()
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "## [1.2.4] - " in changelog
    # A fresh empty Unreleased block is opened above the dated one.
    assert changelog.index("## [Unreleased]") < changelog.index("## [1.2.4]")
    assert _git(repo, "tag", "--list") == "v1.2.4"
    assert not _git(repo, "status", "--porcelain")


# --------------------------------------------------------------------------
# rollback — the reason this module exists
# --------------------------------------------------------------------------


def _snapshot(repo: Path) -> tuple[str, str, str]:
    return (
        (repo / "src" / "_version.py").read_text(),
        (repo / "CHANGELOG.md").read_text(),
        _git(repo, "rev-parse", "HEAD"),
    )


def test_rollback_when_the_commit_fails(release):
    """A rejecting pre-commit hook must leave the tree exactly as it was.

    Without the rollback the files stay rewritten and the Unreleased block
    stays rolled, so the retry reports "the Unreleased block is empty" — true,
    and nothing to do with the real failure.
    """
    module, repo = release
    before = _snapshot(repo)

    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    assert module.main([]) == 1
    assert _snapshot(repo) == before
    assert not _git(repo, "status", "--porcelain")
    assert _git(repo, "tag", "--list") == ""


def test_retry_succeeds_after_a_rolled_back_failure(release):
    """The whole point: fix the cause, run again, get the same release."""
    module, repo = release
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    assert module.main([]) == 1

    hook.unlink()
    assert module.main([]) == 0
    assert '__version__ = "1.2.4"' in (repo / "src" / "_version.py").read_text()
    assert _git(repo, "tag", "--list") == "v1.2.4"


def test_rollback_when_the_tag_fails_after_a_successful_commit(release):
    """The harder path: the release commit has to be peeled back off HEAD."""
    module, repo = release
    before = _snapshot(repo)

    real_git = module.git

    def failing_tag(*args, **kwargs):
        if args[:2] == ("tag", "-a"):
            raise module.ReleaseError("simulated tag failure")
        return real_git(*args, **kwargs)

    module.git = failing_tag
    try:
        assert module.main([]) == 1
    finally:
        module.git = real_git

    assert _snapshot(repo) == before, "HEAD or the files were left moved"
    assert not _git(repo, "status", "--porcelain")
    assert _git(repo, "tag", "--list") == ""


def test_rollback_leaves_unrelated_work_alone(release):
    """``--allow-dirty`` means the tree may hold other edits; never blow them away."""
    module, repo = release
    # Tracked and modified, not merely untracked: `git reset --hard` leaves
    # untracked files alone, so an untracked file could not detect the mistake
    # this test exists to prevent.
    unrelated = repo / "notes.txt"
    unrelated.write_text("committed\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-qm", "add notes")
    unrelated.write_text("work in progress\n", encoding="utf-8")

    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    assert module.main(["--allow-dirty"]) == 1
    assert unrelated.read_text() == "work in progress\n"
