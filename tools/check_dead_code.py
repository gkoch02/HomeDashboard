"""Dead-code check for ``src/``, built on vulture.

``src/``, ``scripts/`` and ``tests/`` are all scanned, so a name a script or a
test calls counts as used, but only findings under ``src/`` are reported:
vulture misreads mock setup in tests (``m.__exit__ = ...``) as dead code, and
test helpers are the assertion guard's business, not this one's.

Code reached by name rather than by call is excluded by pattern below, never
one finding at a time: component adapters registered by decorator, Flask
routes and hooks, and the few framework hooks listed in ``IGNORE_NAMES``.

Usage::

    python tools/check_dead_code.py

Exit code 0 = clean, 1 = dead code found, 2 = vulture not installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 60 is the confidence vulture gives an unused function, class or variable;
# a higher floor reports only unused imports and unreachable code.
MIN_CONFIDENCE = 60
SCAN_DIRS = ("src", "scripts", "tests")
REPORT_DIR = "src"
IGNORE_DECORATORS = [
    "@register_component",
    "@*.route",
    "@*.before_request",
    "@pytest.fixture",
]
IGNORE_NAMES = [
    "_component_builtins",  # side-effect import that populates the component registry
    "_from_iterable",  # collections.abc.Set hook, called by the ABC's operators
    "web_authenticated",  # set on flask.g, read by name
]


def find_dead_code(root: Path, scan_dirs=SCAN_DIRS, report_dir=REPORT_DIR) -> list[str]:
    import vulture

    v = vulture.Vulture(ignore_names=IGNORE_NAMES, ignore_decorators=IGNORE_DECORATORS)
    v.scavenge([str(root / d) for d in scan_dirs if (root / d).exists()])
    report_root = (root / report_dir).resolve()
    found = []
    for item in v.get_unused_code(min_confidence=MIN_CONFIDENCE):
        path = Path(item.filename).resolve()
        if report_root in path.parents:
            rel = path.relative_to(root.resolve()).as_posix()
            found.append(f"{rel}:{item.first_lineno}: {item.message}")
    return found


def main(argv: list[str] | None = None) -> int:
    try:
        import vulture  # noqa: F401
    except ImportError:
        print("vulture is not installed: pip install -e '.[dev]'", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    found = find_dead_code(root)
    for line in found:
        print(line)
    if found:
        print(
            f"\nFound {len(found)} unused name(s) in src/.\n"
            "Delete it, or if it is reached by name (a decorator, a framework hook),\n"
            "add the pattern to IGNORE_DECORATORS / IGNORE_NAMES with a comment.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
