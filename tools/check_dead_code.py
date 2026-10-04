"""Dead-code check for ``src/``, built on vulture.

Callers are counted in ``src/`` and ``scripts/`` only. A test is not a caller:
a function nothing but its own tests calls is dead weight, and counting tests
would hide exactly that.

Code reached by name rather than by call is excluded by decorator pattern
(component adapters, Flask routes and hooks) or listed in ``FRAMEWORK_HOOKS``.
``TEST_ONLY_BASELINE`` is the set of test-only names that predate this check.
It may only shrink: delete a name or give it a production caller, then remove
it here. A baseline entry that is no longer dead is reported as stale.

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
TEST_ONLY_BASELINE = [
    "AGENDA_X",
    "THEMES_NEEDING_TOMORROW",
    "_clear_people_service_cache",
    "_get_variable_font",
    "all_component_names",
    "assert_aware",
    "big_shoulders_semibold",
    "birthday_line",
    "cinzel_regular",
    "event_lanes",
    "field_spec_by_path",
    "inverted_text",
    "load_cached",
    "load_cached_source",
    "load_cached_source_with_metadata",
    "moon_photo_available",
    "quantize_to_palette",
    "save_cache",
    "unregister_component",
    "unregister_fetcher",
    "unregister_theme",
]


def find_dead_code(root: Path, baseline=TEST_ONLY_BASELINE) -> tuple[list[str], list[str]]:
    """Return (dead code outside the baseline, baseline names no longer dead)."""
    import vulture

    v = vulture.Vulture(ignore_names=FRAMEWORK_HOOKS, ignore_decorators=IGNORE_DECORATORS)
    v.scavenge([str(root / d) for d in SCAN_DIRS if (root / d).exists()])
    report_root = (root / REPORT_DIR).resolve()
    found: list[str] = []
    still_dead: set[str] = set()
    for item in v.get_unused_code(min_confidence=MIN_CONFIDENCE):
        path = Path(item.filename).resolve()
        if report_root not in path.parents:
            continue
        if item.name in baseline:
            still_dead.add(item.name)
            continue
        rel = path.relative_to(root.resolve()).as_posix()
        found.append(f"{rel}:{item.first_lineno}: {item.message}")
    stale = sorted(set(baseline) - still_dead)
    return found, stale


def main() -> int:
    if importlib.util.find_spec("vulture") is None:
        print("vulture is not installed: pip install -e '.[dev]'", file=sys.stderr)
        return 2
    found, stale = find_dead_code(Path(__file__).resolve().parent.parent)
    for line in found:
        print(line)
    for name in stale:
        print(f"TEST_ONLY_BASELINE: {name!r} is no longer dead; remove it from the list")
    if found:
        print(
            f"\nFound {len(found)} unused name(s) in src/ (tests do not count as callers).\n"
            "Delete it, or if it is reached by name, add the decorator pattern or\n"
            "framework hook to the lists in this script, with a comment.",
            file=sys.stderr,
        )
    return 1 if found or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
