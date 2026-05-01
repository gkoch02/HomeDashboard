#!/usr/bin/env python3
"""Validate markdown links and canonical theme inventories."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = [ROOT / "README.md", ROOT / "CONTRIBUTING.md"] + sorted((ROOT / "docs").glob("*.md"))
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
THEME_DETAIL_RE = re.compile(r"^####\s+(.+)$", re.MULTILINE)


def normalize_heading(heading: str) -> str:
    return heading.strip("` ").lower().replace(" ", "_")


def load_theme_names() -> set[str]:
    """Authoritative theme inventory from the v5 registry.

    Falls back to scanning ``src/render/themes/*.py`` for registration
    calls when the package can't be imported (e.g. running the docs check
    inside a sandbox without the project deps installed).
    """
    sys.path.insert(0, str(ROOT))
    try:
        from src.render.themes.registry import all_theme_names

        return set(all_theme_names()) | {"default"}
    except Exception:
        # Fallback: scan each theme module for its register_theme(...) call.
        names: set[str] = {"default"}
        for theme_file in sorted((ROOT / "src" / "render" / "themes").glob("*.py")):
            if theme_file.name in {"__init__.py", "registry.py"}:
                continue
            text = theme_file.read_text()
            match = re.search(r'register_theme\(\s*["\']([a-z_]+)["\']', text)
            if match:
                names.add(match.group(1))
        return names


def check_links() -> list[str]:
    errors: list[str] = []
    for doc in DOC_FILES:
        text = doc.read_text()
        for raw_target in LINK_RE.findall(text):
            target = raw_target.strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            resolved = (doc.parent / path).resolve()
            if not resolved.exists():
                errors.append(f"{doc.relative_to(ROOT)}: missing link target {target}")
    return errors


def check_theme_inventory(theme_names: set[str]) -> list[str]:
    errors: list[str] = []

    themes_doc = (ROOT / "docs" / "themes.md").read_text()
    detail_headings = {normalize_heading(h) for h in THEME_DETAIL_RE.findall(themes_doc)}
    missing_in_themes = sorted(theme_names - detail_headings)
    extra_in_themes = sorted(detail_headings - theme_names)
    for name in missing_in_themes:
        errors.append(f"docs/themes.md: missing heading for theme '{name}'")
    for name in extra_in_themes:
        errors.append(f"docs/themes.md: unexpected theme heading '{name}'")

    return errors


def main() -> int:
    theme_names = load_theme_names()
    errors = check_links()
    errors.extend(check_theme_inventory(theme_names))
    if errors:
        for err in errors:
            print(err)
        return 1
    print("docs-check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
