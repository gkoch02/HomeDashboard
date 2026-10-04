"""AST-based check for test functions that cannot fail.

Flags every ``test_*`` function under ``tests/`` whose body contains no
``assert`` statement, no ``pytest.raises`` / ``pytest.warns`` block, no
``pytest.fail`` call, and no ``.assert_*`` call on a mock. Such a test passes
for any implementation, including a deleted one.

A test that really is a "does not raise" smoke test says so with
``# allow-no-assert`` on its ``def`` line, so the choice is visible in review.

A test that delegates its checks to a helper is recognised when the helper's
name starts with ``assert_`` or ``_assert`` (e.g. ``_assert_filmstrip``); a
method call counts when its name starts with ``assert`` (mock and unittest).
Checks inside a nested function or lambda do not count: they run only if
something calls them.

Usage::

    python tools/check_test_assertions.py

Exit code 0 = clean, 1 = violations found, 2 = invocation error.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_MARKER = "allow-no-assert"
_PYTEST_CHECKS = {"raises", "warns", "deprecated_call", "fail"}


def _own_nodes(fn: ast.AST):
    """Walk *fn*'s body without entering nested functions, lambdas or classes.

    An ``assert`` inside a nested callback only runs if something calls the
    callback, so it is not evidence that the test checks anything.
    """
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _is_check_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        receiver = func.value
        if isinstance(receiver, ast.Name) and receiver.id == "pytest":
            return func.attr in _PYTEST_CHECKS
        # mock.assert_called_once_with(...), self.assertEqual(...)
        return func.attr.startswith("assert")
    if isinstance(func, ast.Name):
        return func.id.startswith(("assert_", "_assert"))
    return False


def _checks_something(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in _own_nodes(fn):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call) and _is_check_call(node):
            return True
    return False


def check_file(path: Path) -> list[tuple[int, str]]:
    try:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return []
    lines = source.splitlines()
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        if _checks_something(node):
            continue
        def_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        if _MARKER in def_line:
            continue
        violations.append((node.lineno, node.name))
    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    tests_root = repo_root / "tests"
    if not tests_root.exists():
        print("tests/ not found", file=sys.stderr)
        return 2
    failures = 0
    for path in sorted(tests_root.rglob("test_*.py")):
        for line, name in check_file(path):
            rel = path.relative_to(repo_root).as_posix()
            print(f"{rel}:{line}: NO_ASSERT {name} checks nothing")
            failures += 1
    if failures:
        print(
            f"\nFound {failures} test(s) that cannot fail.\n"
            "Assert on the behaviour the test is named for, or mark a deliberate\n"
            "smoke test with `# allow-no-assert` on its def line.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
