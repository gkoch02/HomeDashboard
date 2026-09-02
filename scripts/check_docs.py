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
INKY_EMBED_RE = re.compile(r"assets/previews/theme_(\w+)_inky\.png")
# The "full batch for all concrete themes" shell loop in docs/previews.md.
PREVIEW_BATCH_RE = re.compile(r"for theme in ([^;]+); do", re.DOTALL)


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

    errors.extend(check_inky_inventory(theme_names))
    errors.extend(check_preview_batch(theme_names))
    return errors


def check_inky_inventory(theme_names: set[str]) -> list[str]:
    """Keep docs/inky-previews.md covering the same themes as docs/themes.md.

    The color catalog is a second page rather than a second image per theme, so
    nothing about rendering a new theme forces an entry onto it. Without this
    check a new theme would get a Waveshare preview in themes.md and silently
    no color one.
    """
    errors: list[str] = []
    doc = ROOT / "docs" / "inky-previews.md"
    if not doc.exists():
        return ["docs/inky-previews.md: missing"]
    text = doc.read_text()

    # Same heading level as docs/themes.md, so one convention covers both pages:
    # group headings are ###, per-theme entries are ####.
    headings = {normalize_heading(h) for h in THEME_DETAIL_RE.findall(text)}
    for name in sorted(theme_names - headings):
        errors.append(f"docs/inky-previews.md: missing heading for theme '{name}'")
    for name in sorted(headings - theme_names):
        errors.append(f"docs/inky-previews.md: unexpected theme heading '{name}'")

    embedded = set(INKY_EMBED_RE.findall(text))
    for name in sorted(theme_names - embedded):
        errors.append(f"docs/inky-previews.md: theme '{name}' has no _inky.png embed")
    for name in sorted(embedded - theme_names):
        errors.append(f"docs/inky-previews.md: unknown theme preview 'theme_{name}_inky.png'")
    return errors


def check_preview_batch(theme_names: set[str]) -> list[str]:
    """Keep the Inky preview batch loop in sync with the theme registry.

    The loop is documented as covering "all concrete themes", so a theme that
    never gets added to it silently never gets an Inky preview regenerated.
    Both ``day_arc`` and ``moonphase_photo`` drifted out of it that way before
    this check existed.
    """
    errors: list[str] = []
    previews_doc = (ROOT / "docs" / "previews.md").read_text()
    match = PREVIEW_BATCH_RE.search(previews_doc)
    if match is None:
        return ["docs/previews.md: could not find the 'for theme in ...' batch loop"]

    listed = set(match.group(1).replace("\\", " ").split())
    for name in sorted(theme_names - listed):
        errors.append(f"docs/previews.md: theme '{name}' missing from the preview batch loop")
    for name in sorted(listed - theme_names):
        errors.append(f"docs/previews.md: unknown theme '{name}' in the preview batch loop")
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
