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
GALLERY_ENTRY_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def normalize_heading(heading: str) -> str:
    return heading.strip("` ").lower().replace(" ", "_")


def load_theme_names() -> set[str]:
    text = (ROOT / "src" / "render" / "theme.py").read_text()
    names = set(re.findall(r'"([a-z_]+)":\s+\("src\.render\.themes\.', text))
    names.add("default")
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


def check_theme_gallery(theme_names: set[str]) -> list[str]:
    errors: list[str] = []

    themes_doc = (ROOT / "docs" / "themes.md").read_text()
    detail_headings = {normalize_heading(h) for h in THEME_DETAIL_RE.findall(themes_doc)}
    missing_in_themes = sorted(theme_names - detail_headings)
    extra_in_themes = sorted(detail_headings - theme_names)
    for name in missing_in_themes:
        errors.append(f"docs/themes.md: missing heading for theme '{name}'")
    for name in extra_in_themes:
        errors.append(f"docs/themes.md: unexpected theme heading '{name}'")

    gallery_doc = (ROOT / "docs" / "color-themes.md").read_text()
    gallery_headings = {
        normalize_heading(h)
        for h in GALLERY_ENTRY_RE.findall(gallery_doc)
        if h.strip() not in {"Color Themes"}
    }
    missing_in_gallery = sorted(theme_names - gallery_headings)
    extra_in_gallery = sorted(gallery_headings - theme_names)
    for name in missing_in_gallery:
        errors.append(f"docs/color-themes.md: missing gallery entry for theme '{name}'")
    for name in extra_in_gallery:
        errors.append(f"docs/color-themes.md: unexpected gallery entry '{name}'")

    return errors


def main() -> int:
    theme_names = load_theme_names()
    errors = check_links()
    errors.extend(check_theme_gallery(theme_names))
    if errors:
        for err in errors:
            print(err)
        return 1
    print("docs-check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
