"""Guard against drift between pyproject.toml and the requirements*.txt mirrors.

``requirements.txt`` (core deps, kept for Pi deployment compat) and
``requirements-web.txt`` (the ``[web]`` extra) are hand-maintained mirrors of
``[project].dependencies`` / ``[project.optional-dependencies].web`` in
``pyproject.toml``. This test fails when they diverge so a dependency edit in
one place can't silently miss the other.

Parsing uses ``tomllib`` when available (Python 3.11+) and falls back to a
minimal array extractor on 3.10, so the CI floor job enforces the guard too.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_requirements(name: str) -> set[str]:
    lines = (ROOT / name).read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def _extract_string_array(toml_text: str, key: str) -> set[str]:
    """Fallback for Python 3.10 (no tomllib): pull one flat string array.

    Only handles the shape this project's pyproject.toml actually uses —
    ``key = [`` followed by quoted strings, one per line, closed by ``]``.
    """
    match = re.search(rf"^{re.escape(key)}\s*=\s*\[(.*?)^\]", toml_text, re.M | re.S)
    assert match, f"could not locate array {key!r} in pyproject.toml"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _pyproject_arrays() -> tuple[set[str], set[str]]:
    """Return (core dependencies, web extra) from pyproject.toml."""
    path = ROOT / "pyproject.toml"
    try:
        import tomllib
    except ImportError:
        text = path.read_text()
        return _extract_string_array(text, "dependencies"), _extract_string_array(text, "web")
    with open(path, "rb") as fh:
        project = tomllib.load(fh)["project"]
    return set(project["dependencies"]), set(project["optional-dependencies"]["web"])


def test_requirements_txt_matches_core_dependencies():
    core, _web = _pyproject_arrays()
    assert core == _read_requirements("requirements.txt")


def test_requirements_web_txt_matches_web_extra():
    _core, web = _pyproject_arrays()
    assert web == _read_requirements("requirements-web.txt")


def test_fallback_parser_agrees_with_tomllib():
    """The 3.10 regex fallback must extract exactly what tomllib reads."""
    import pytest

    tomllib = pytest.importorskip("tomllib")
    path = ROOT / "pyproject.toml"
    with open(path, "rb") as fh:
        project = tomllib.load(fh)["project"]
    text = path.read_text()
    assert _extract_string_array(text, "dependencies") == set(project["dependencies"])
    assert _extract_string_array(text, "web") == set(project["optional-dependencies"]["web"])
