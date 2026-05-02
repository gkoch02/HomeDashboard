"""AST-based check for naive datetime usage outside ``src/_time.py``.

Flags ``datetime.now()`` (no arguments) and ``datetime.utcnow()`` calls in
files under ``src/``. Use ``src._time.now_utc`` / ``now_local`` instead, or
mark the line with ``# allow-naive-datetime`` when naive local wall-clock
time is intentional (file-name timestamps, quiet-hours comparisons against
config strings, test-friendly fallbacks).

The marker is intentionally NOT ``# noqa: NAIVE_DATETIME`` — ruff's ``noqa``
parser would warn about the unknown code.

Usage::

    python tools/check_naive_datetime.py

Exit code 0 = clean, 1 = violations found, 2 = invocation error.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_ALLOWED_FILES = {
    "src/_time.py",
}

_NOQA_MARKER = "allow-naive-datetime"


def _is_naive_datetime_call(node: ast.Call) -> str | None:
    """Return a label if *node* is a naive ``datetime.now()`` / ``utcnow()``."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr == "utcnow":
        return "datetime.utcnow()"
    if func.attr == "now" and not node.args and not node.keywords:
        return "datetime.now()"
    return None


def _has_marker_near(lines: list[str], start_line: int, end_line: int) -> bool:
    """Search a small window around the call for the allow-naive-datetime marker.

    ``ruff format`` may wrap a call across multiple physical lines, putting
    the trailing comment on a different line than ``ast.Call.lineno``. The
    window covers the call's full extent plus a few lines of slack so a
    chained call like ``datetime.now().strftime(...)`` whose marker lands on
    the closing-paren line is still recognised.
    """
    lo = max(0, start_line - 2)
    hi = min(len(lines), end_line + 5)
    return any(_NOQA_MARKER in lines[i] for i in range(lo, hi))


def check_file(path: Path, repo_root: Path) -> list[tuple[int, str]]:
    rel = path.relative_to(repo_root).as_posix()
    if rel in _ALLOWED_FILES:
        return []
    try:
        source = path.read_text()
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    lines = source.splitlines()

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        label = _is_naive_datetime_call(node)
        if label is None:
            continue
        start_line = (node.lineno - 1) if node.lineno else 0
        end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
        if _has_marker_near(lines, start_line, end_line):
            continue
        violations.append((node.lineno, label))
    return violations


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    src_root = repo_root / "src"
    if not src_root.exists():
        print("src/ not found", file=sys.stderr)
        return 2

    failures = 0
    for path in sorted(src_root.rglob("*.py")):
        for line, label in check_file(path, repo_root):
            rel = path.relative_to(repo_root).as_posix()
            print(f"{rel}:{line}: NAIVE_DATETIME {label} — use src/_time.py helpers")
            failures += 1
    if failures:
        print(
            f"\nFound {failures} naive datetime usage(s).\n"
            "Use src._time.now_utc()/now_local()/to_aware() or mark intentional\n"
            "naive uses with `# allow-naive-datetime`.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
