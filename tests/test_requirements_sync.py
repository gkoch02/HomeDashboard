"""Guard against drift between pyproject.toml and the requirements*.txt mirrors.

``requirements.txt`` (core deps, kept for Pi deployment compat) and
``requirements-web.txt`` (the ``[web]`` extra) are hand-maintained mirrors of
``[project].dependencies`` / ``[project.optional-dependencies].web`` in
``pyproject.toml``. This test fails when they diverge so a dependency edit in
one place can't silently miss the other.
"""

from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib", reason="tomllib requires Python 3.11+")

ROOT = Path(__file__).resolve().parents[1]


def _read_requirements(name: str) -> set[str]:
    lines = (ROOT / name).read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def _pyproject() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def test_requirements_txt_matches_core_dependencies():
    project = _pyproject()["project"]
    assert set(project["dependencies"]) == _read_requirements("requirements.txt")


def test_requirements_web_txt_matches_web_extra():
    project = _pyproject()["project"]
    assert set(project["optional-dependencies"]["web"]) == _read_requirements(
        "requirements-web.txt"
    )
