"""The repo-hygiene guards: tests that cannot fail, dead code, and the CLAUDE.md budget.

Each guard is shown to reject the shape it exists to catch, so a guard that
silently stops matching fails here. The full-tree dead-code scan runs in the
lint job, not here, so the four-version test matrix does not repeat it.
"""

from __future__ import annotations

import importlib.util
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
dead_code = _load("_check_dead_code", REPO_ROOT / "tools" / "check_dead_code.py")


class TestAssertionGuard:
    def test_suite_has_no_test_that_cannot_fail(self):
        found = [
            f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
            for path in sorted((REPO_ROOT / "tests").rglob("test_*.py"))
            for line, name in assertions.check_file(path)
        ]
        assert found == [], "\n".join(found)

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
            "def test_unittest():\n    self.assertEqual(run(), 1)\n"
            "def test_helper():\n    _assert_layout(run())\n"
            "def test_fail():\n    pytest.fail('x')\n"
            "def test_marked():  # allow-no-assert\n    run()\n"
        )
        assert self._names(tmp_path, body) == []

    def test_an_assert_in_a_nested_callback_does_not_count(self, tmp_path):
        body = "def test_x():\n    def cb(v):\n        assert v\n    run(lambda v: v)\n"
        assert self._names(tmp_path, body) == ["test_x"]

    def test_lookalike_calls_do_not_count(self, tmp_path):
        body = (
            "def test_future():\n    future.fail()\n"
            "def test_obj():\n    obj.raises()\n"
            "def test_fixture():\n    assertions_for(run())\n"
            "def test_skip_only():\n    pytest.importorskip('x')\n"
        )
        assert self._names(tmp_path, body) == [
            "test_future",
            "test_obj",
            "test_fixture",
            "test_skip_only",
        ]

    def test_ignores_helpers_that_are_not_tests(self, tmp_path):
        assert self._names(tmp_path, "def make_fixture():\n    return 1\n") == []


def _claude_md(gotchas: str, padding: int = 0) -> str:
    return "# Title\n\n" + "word " * padding + "\n\n## Gotchas\n\n" + gotchas + "\n## Next\n"


class TestClaudeMdBudget:
    def test_repo_claude_md_is_within_budget(self):
        assert check_docs.check_claude_md_budget() == []

    def test_repo_claude_md_has_gotchas_to_measure(self):
        text = (REPO_ROOT / "CLAUDE.md").read_text()
        assert len(check_docs.gotcha_bullets(text)) > 20

    def test_a_missing_gotchas_section_is_an_error(self):
        errors = check_docs.check_claude_md_budget("# Title\n\n## Pitfalls\n\n- rule\n")
        assert any("no `## Gotchas`" in e for e in errors), errors

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

    def test_a_paragraph_after_a_bullet_is_not_part_of_it(self):
        text = _claude_md("- one rule\n\n### Group\n\nIntro sentence for the group.\n")
        assert check_docs.gotcha_bullets(text) == ["- one rule"]

    def test_flags_the_gotchas_total(self):
        bullet = "- " + "word " * 90 + "\n"
        count = check_docs.GOTCHAS_MAX_WORDS // 90 + 1
        errors = check_docs.check_claude_md_budget(_claude_md(bullet * count))
        assert any("Gotchas:" in e for e in errors), errors

    def test_prose_outside_bullets_counts_toward_the_section(self):
        prose = "word " * (check_docs.GOTCHAS_MAX_WORDS + 1)
        errors = check_docs.check_claude_md_budget(_claude_md(prose + "\n\n- short\n"))
        assert any("Gotchas:" in e for e in errors), errors

    def test_flags_the_file_total(self):
        text = _claude_md("- short\n", padding=check_docs.CLAUDE_MD_MAX_WORDS + 1)
        errors = check_docs.check_claude_md_budget(text)
        assert any(e.startswith("CLAUDE.md:") for e in errors), errors


class TestDeadCodeGuard:
    """Skipped where vulture is absent (the core-install job installs no dev extras)."""

    def setup_method(self):
        pytest.importorskip("vulture")

    def _tree(self, tmp_path: Path, src: str, tests: str = "", baseline=()):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "mod.py").write_text(src)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_mod.py").write_text(tests)
        return dead_code.find_dead_code(tmp_path, baseline=list(baseline))

    def test_flags_an_unused_function(self, tmp_path):
        found, _ = self._tree(
            tmp_path, "def used():\n    pass\n\ndef dead():\n    pass\n\nused()\n"
        )
        assert len(found) == 1 and "'dead'" in found[0], found

    def test_a_call_from_tests_does_not_count(self, tmp_path):
        tests = "from src.mod import helper\n\ndef test_it():\n    assert helper()\n"
        found, _ = self._tree(tmp_path, "def helper():\n    return 1\n", tests)
        assert len(found) == 1 and "'helper'" in found[0], found

    def test_the_baseline_admits_known_names_only(self, tmp_path):
        src = "def legacy():\n    pass\n\ndef fresh():\n    pass\n"
        found, stale = self._tree(tmp_path, src, baseline=["legacy"])
        assert len(found) == 1 and "'fresh'" in found[0], found
        assert stale == []

    def test_a_baseline_entry_that_is_used_again_is_stale(self, tmp_path):
        found, stale = self._tree(tmp_path, "def back():\n    pass\n\nback()\n", baseline=["back"])
        assert (found, stale) == ([], ["back"])

    def test_decorator_registered_code_is_not_dead(self, tmp_path):
        src = "@register_component('x')\ndef _adapter(ctx):\n    print(ctx)\n"
        found, _ = self._tree(tmp_path, src)
        assert found == []
