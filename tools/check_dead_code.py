"""Dead-code check for ``src/``, built on vulture.

Callers are counted in ``src/`` and ``scripts/`` only. A test is not a caller:
a function nothing but its own tests calls is dead weight, and counting tests
would hide exactly that.

Code reached by name rather than by call is excluded by decorator pattern
(component adapters, Flask routes and hooks) or listed in ``FRAMEWORK_HOOKS``.

Usage::

    python tools/check_dead_code.py

Exit code 0 = clean, 1 = dead code found, 2 = vulture not installed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# 60 is the confidence vulture gives an unused function, class or variable;
# a higher floor reports only unused imports and unreachable code.
MIN_CONFIDENCE = 60
SCAN_DIRS = ("src", "scripts")
REPORT_DIR = "src"
IGNORE_DECORATORS = ["@register_component", "@*.route", "@*.before_request"]
FRAMEWORK_HOOKS = [
    "_from_iterable",  # collections.abc.Set hook, called by the ABC's operators
    "web_authenticated",  # set on flask.g, read by name
]


def find_dead_code(root: Path) -> list[str]:
    """Return one ``path:line: message`` entry per unused name under ``src/``."""
    import vulture

    v = vulture.Vulture(ignore_names=FRAMEWORK_HOOKS, ignore_decorators=IGNORE_DECORATORS)
    v.scavenge([str(root / d) for d in SCAN_DIRS if (root / d).exists()])
    report_root = (root / REPORT_DIR).resolve()
    found: list[str] = []
    for item in v.get_unused_code(min_confidence=MIN_CONFIDENCE):
        path = Path(item.filename).resolve()
        if report_root not in path.parents:
            continue
        rel = path.relative_to(root.resolve()).as_posix()
        found.append(f"{rel}:{item.first_lineno}: {item.message}")
    return found


def main() -> int:
    if importlib.util.find_spec("vulture") is None:
        print("vulture is not installed: pip install -e '.[dev]'", file=sys.stderr)
        return 2
    found = find_dead_code(Path(__file__).resolve().parent.parent)
    for line in found:
        print(line)
    if found:
        print(
            f"\nFound {len(found)} unused name(s) in src/ (tests do not count as callers).\n"
            "Delete it, or if it is reached by name, add the decorator pattern or\n"
            "framework hook to the lists in this script, with a comment.",
            file=sys.stderr,
        )
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
