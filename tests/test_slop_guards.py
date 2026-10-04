"""The repo-hygiene guards: tests that cannot fail, dead code, and the CLAUDE.md budget.

Each guard is run against the real tree, then shown to reject the shape it
exists to catch, so a guard that silently stops matching fails here.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assertions = _load("_check_test_assertions", REPO_ROOT / "tools" / "check_test_assertions.py")
check_docs = _load("_check_docs_under_test", REPO_ROOT / "scripts" / "check_docs.py")


class TestAssertionGuard:
    def test_suite_has_no_test_that_cannot_fail(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "check_test_assertions.py")],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def _names(self, tmp_path: Path, body: str) -> list[str]:
        path = tmp_path / "test_sample.py"
        path.write_text(body)
        return [name for _, name in assertions.check_file(path)]

    def test_flags_a_test_with_no_check(self, tmp_path):
        assert self._names(tmp_path, "def test_x():\n    run()\n") == ["test_x"]

    def test_accepts_every_form_of_check(self, tmp_path):
        body = (
            "def test_assert():\n    assert run()\n"
            "def test_raises():\n    with pytest.raises(ValueError):\n        run()\n"
            "def test_mock():\n    m.assert_called_once_with(1)\n"
            "def test_helper():\n    _assert_layout(run())\n"
            "def test_fail():\n    pytest.fail('x')\n"
            "def test_marked():  # allow-no-assert\n    run()\n"
        )
        assert self._names(tmp_path, body) == []

    def test_ignores_helpers_that_are_not_tests(self, tmp_path):
        assert self._names(tmp_path, "def make_fixture():\n    return 1\n") == []


def _claude_md(gotchas: str, padding: int = 0) -> str:
    return "# Title\n\n" + "word " * padding + "\n\n## Gotchas\n\n" + gotchas + "\n## Next\n"


class TestClaudeMdBudget:
    def test_repo_claude_md_is_within_budget(self):
        assert check_docs.check_claude_md_budget() == []

    def test_flags_a_long_gotcha_bullet(self):
        long = "- " + "word " * (check_docs.GOTCHA_BULLET_MAX_WORDS + 1)
        errors = check_docs.check_claude_md_budget(_claude_md(long))
        assert any("bullet" in e for e in errors), errors

    def test_counts_continuation_lines_and_nested_bullets(self):
        half = check_docs.GOTCHA_BULLET_MAX_WORDS // 2 + 1
        wrapped = "- " + "word " * half + "\n  " + "word " * half
        assert check_docs.check_claude_md_budget(_claude_md(wrapped))
        nested = "- short\n  - " + "word " * (check_docs.GOTCHA_BULLET_MAX_WORDS + 1)
        assert check_docs.check_claude_md_budget(_claude_md(nested))

    def test_flags_the_gotchas_total(self):
        bullet = "- " + "word " * 90 + "\n"
        count = check_docs.GOTCHAS_MAX_WORDS // 90 + 1
        errors = check_docs.check_claude_md_budget(_claude_md(bullet * count))
        assert any("Gotchas:" in e for e in errors), errors

    def test_flags_the_file_total(self):
        text = _claude_md("- short\n", padding=check_docs.CLAUDE_MD_MAX_WORDS + 1)
        errors = check_docs.check_claude_md_budget(text)
        assert any(e.startswith("CLAUDE.md:") for e in errors), errors

    def test_headings_inside_gotchas_are_not_bullets(self):
        text = _claude_md("### Group\n\n- one rule\n")
        assert check_docs.gotcha_bullets(text) == ["- one rule"]


dead_code = _load("_check_dead_code", REPO_ROOT / "tools" / "check_dead_code.py")


class TestDeadCodeGuard:
    """Skipped where vulture is absent (the core-install job installs no dev extras)."""

    def setup_method(self):
        pytest.importorskip("vulture")

    def test_src_has_no_dead_code(self):
        assert dead_code.find_dead_code(REPO_ROOT) == []

    def _tree(self, tmp_path: Path, src: str, tests: str = "") -> list[str]:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "mod.py").write_text(src)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_mod.py").write_text(tests)
        return dead_code.find_dead_code(tmp_path)

    def test_flags_an_unused_function(self, tmp_path):
        found = self._tree(tmp_path, "def used():\n    pass\n\ndef dead():\n    pass\n\nused()\n")
        assert len(found) == 1 and "'dead'" in found[0], found

    def test_a_call_from_tests_counts_as_use(self, tmp_path):
        tests = "from src.mod import helper\n\ndef test_it():\n    assert helper()\n"
        assert self._tree(tmp_path, "def helper():\n    return 1\n", tests) == []

    def test_reports_nothing_under_tests(self, tmp_path):
        tests = "def _unused_test_helper():\n    pass\n"
        assert self._tree(tmp_path, "x = 1\nprint(x)\n", tests) == []

    def test_decorator_registered_code_is_not_dead(self, tmp_path):
        src = "@register_component('x')\ndef _adapter(ctx):\n    print(ctx)\n"
        assert self._tree(tmp_path, src) == []
