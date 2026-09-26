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
# Deliberately requires Markdown *image* syntax, not just the path: a page that
# merely links to theme_<name>_inky.png shows no image, and a check that accepted
# a bare path would pass on a catalog page displaying nothing.
INKY_EMBED_RE = re.compile(r"!\[[^\]]*\]\([^)]*?assets/previews/theme_(\w+)_inky\.png\)")
INKY_ACCENT_RE = re.compile(r"^#### (\w+)\n\n(Accents: [^\n]*)$", re.MULTILINE)

THEMES_DIR = ROOT / "src" / "render" / "themes"
REGISTER_PALETTE_RE = re.compile(
    r"""register_theme\(\s*["'](\w+)["']\s*,[^)]*?"""
    r"inky_palette=\(\s*_?INKY_(\w+)\s*,\s*_?INKY_(\w+)\s*\)",
    re.DOTALL,
)
ACCENT_ASSIGN_RE = re.compile(r"\baccent_(info|warn|alert|good|primary|secondary)=([^,\n]+)")
INKY_TOKEN_RE = re.compile(r"^_?inky_([a-z]+)$", re.IGNORECASE)
# canvas._resolve_style fills each unset semantic role with these.
SEMANTIC_DEFAULTS = {"info": "blue", "warn": "yellow", "alert": "red", "good": "green"}
# canvas._resolve_inky_palette falls back to this for a theme with no registration
# — which is `default`, a pseudo-name with no module.
FALLBACK_PALETTE = ("blue", "red")
# The "full batch for all concrete themes" shell loop in docs/previews.md.
PREVIEW_BATCH_RE = re.compile(r"for theme in ([^;]+); do", re.DOTALL)

EXAMPLE_CONFIG = ROOT / "config" / "config.example.yaml"
# The delimited theme-name block in config.example.yaml. Group labels inside it
# are UPPERCASE precisely so the lowercase token scan below picks up theme names
# and nothing else.
EXAMPLE_THEME_BLOCK_RE = re.compile(
    r"^# --- theme names.*?$(.*?)^# --- end theme names", re.MULTILINE | re.DOTALL
)
EXAMPLE_THEME_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*")
# Pseudo-names that are valid in `theme:` but are not registered themes.
THEME_PSEUDO_NAMES = {"random", "random_daily", "random_hourly"}

# Config fields that are deliberately absent from the example file.
#   sensor_id_invalid — not a YAML key at all; load_config() sets it to carry a
#                       malformed sensor_id through to validate_config().
EXAMPLE_CONFIG_EXEMPT = {"purpleair.sensor_id_invalid"}
# Top-level Config scalars that live under a section in YAML, as (section, key).
EXAMPLE_CONFIG_RENAMED = {
    "output_dir": ("output", "dry_run_dir"),
    "log_level": ("logging", "level"),
}
# Container fields whose list items are documented by example rather than by key.
EXAMPLE_CONFIG_CONTAINERS = {
    "countdown.events",
    "theme_schedule.entries",
    "theme_rules.rules",
}


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
    errors.extend(check_inky_accents(theme_names))
    errors.extend(check_preview_batch(theme_names))
    return errors


def effective_accents() -> tuple[dict[str, dict], list[str]]:
    """Resolve each theme's Inky accents the way ``canvas._resolve_style`` does.

    An explicit ``ThemeStyle.accent_*`` wins over both the registered
    ``inky_palette`` pair and the semantic default — ``qotd`` sets
    ``accent_primary`` to blue while registering ``(red, blue)``, so reading the
    registration alone would document a red primary the panel never shows.

    Returns ``(accents, errors)``; an accent value this cannot read is an error
    rather than a silent omission, since a shape we can't parse is exactly the
    case where the page would drift unnoticed.
    """
    accents: dict[str, dict] = {"default": {"pair": FALLBACK_PALETTE, "overrides": {}}}
    errors: list[str] = []
    for theme_file in sorted(THEMES_DIR.glob("*.py")):
        if theme_file.name in {"__init__.py", "registry.py"}:
            continue
        text = theme_file.read_text()
        registered = REGISTER_PALETTE_RE.search(text)
        if registered is None:
            continue
        name = registered.group(1)
        explicit: dict[str, str] = {}
        for role, raw in ACCENT_ASSIGN_RE.findall(text):
            token = INKY_TOKEN_RE.match(raw.strip())
            if token is None:
                errors.append(
                    f"{theme_file.relative_to(ROOT)}: cannot read accent_{role}={raw.strip()!r} "
                    f"— extend check_docs.effective_accents() so the docs stay checkable"
                )
                continue
            explicit[role] = token.group(1).lower()
        accents[name] = {
            "pair": (
                explicit.get("primary", registered.group(2).lower()),
                explicit.get("secondary", registered.group(3).lower()),
            ),
            "overrides": {
                role: value
                for role, value in explicit.items()
                if role in SEMANTIC_DEFAULTS and value != SEMANTIC_DEFAULTS[role]
            },
        }
    return accents, errors


def expected_accent_line(name: str, entry: dict) -> str:
    primary, secondary = entry["pair"]
    parts = [f"Accents: **{primary}** primary, **{secondary}** secondary"]
    overrides = entry["overrides"]
    for role in ("info", "warn", "alert", "good"):
        if role in overrides:
            parts.append(f"overrides `accent_{role}` \u2192 {overrides[role]}")
    parts.append(f"[description in Themes \u2197](themes.md#{name})")
    return " \u00b7 ".join(parts)


def check_inky_accents(theme_names: set[str]) -> list[str]:
    """Hold each color entry's stated accents to what the theme actually resolves.

    The accent pair is the substance of the color page — a wrong one is worse
    than none, and nothing about editing a theme's style would otherwise
    prompt anyone to revisit the page.
    """
    doc = ROOT / "docs" / "inky-previews.md"
    if not doc.exists():
        return []
    accents, errors = effective_accents()
    found = dict(INKY_ACCENT_RE.findall(doc.read_text()))
    for name in sorted(theme_names):
        entry = accents.get(name)
        if entry is None:
            errors.append(f"docs/inky-previews.md: no resolvable accents for theme '{name}'")
            continue
        expected = expected_accent_line(name, entry)
        actual = found.get(name)
        if actual is None:
            errors.append(f"docs/inky-previews.md: theme '{name}' has no 'Accents:' line")
        elif actual != expected:
            errors.append(
                f"docs/inky-previews.md: theme '{name}' accents are stale\n"
                f"    expected: {expected}\n"
                f"    found:    {actual}"
            )
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


def example_config_sections() -> tuple[dict[str, type], list[str]]:
    """Return ``({section_name: dataclass}, scalar_field_names)`` for ``Config``.

    Imported rather than scanned: the point of the check is that it tracks
    ``src/config.py`` exactly, and a regex over dataclass bodies would be one
    more thing to keep in sync.

    A section is identified by its ``default_factory`` being a dataclass, not by
    ``field.type``: ``src/config.py`` uses ``from __future__ import annotations``,
    so every ``field.type`` is the *string* of the annotation and no type-based
    test can ever fire.
    """
    import dataclasses

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src import config as config_module

    sections: dict[str, type] = {}
    scalars: list[str] = []
    for f in dataclasses.fields(config_module.Config):
        if dataclasses.is_dataclass(f.default_factory):
            sections[f.name] = f.default_factory
        else:
            scalars.append(f.name)
    # ThemeRuleCondition is not a Config field — it is the shape of a
    # `theme_rules[].when` block, and its keys drifted out of the example once.
    sections["theme_rules.when"] = config_module.ThemeRuleCondition
    return sections, scalars


def uncomment(line: str) -> str:
    """Strip one leading comment marker, keeping the line's YAML indentation.

    The example documents most options commented out, in two spellings — the
    marker before the indent (``#   sensor_id: 12345``) and after it
    (``  # quantization_mode: "threshold"``). Both have to normalise to the
    indentation the key would have if it were live, because indentation is
    what tells a section's key apart from a top-level one.
    """
    return re.sub(r"^(\s*)#+ ?", r"\1", line.rstrip("\n"))


def example_config_regions(text: str) -> dict[str, str]:
    """Split the example into one region of text per top-level key.

    A region runs from the start of the comment block introducing a top-level
    key to the start of the next one, so the prose above ``theme_rules:``
    documenting its ``when:`` conditions counts as part of that section.

    Scoping matters: searching the whole file for a bare key name lets one
    section satisfy another's requirement, which is the failure Codex caught on
    this PR — ``weather.api_key`` covered for a deleted ``purpleair.api_key``,
    ``photo.path`` and ``quotes.path`` covered for each other, and a rule's
    ``theme:`` covered for the top-level one. Those are exactly the omissions
    this check exists to catch.
    """
    lines = text.splitlines()
    top_level = re.compile(r"^([a-z_][a-z0-9_]*)\s*:")
    # Index each top-level key to the first line of the comment block above it.
    starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        match = top_level.match(uncomment(line))
        if match is None:
            continue
        start = i
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        starts.append((start, match.group(1)))

    regions: dict[str, str] = {}
    for idx, (start, name) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        # A key repeated at top level (none today) keeps the union of its blocks.
        regions[name] = regions.get(name, "") + "\n".join(lines[start:end]) + "\n"
    return regions


def documents_key(text: str, key: str, *, top_level: bool = False) -> bool:
    """True when *text* documents ``key:`` as a YAML key, commented or not.

    Accepts the flow-mapping form too (``{ temp_at_most: 32 }``), which is how
    the ``theme_rules`` conditions are written. With *top_level*, the key must
    sit at indentation zero — without it a rule's nested ``theme:`` would stand
    in for the top-level ``theme:``.
    """
    indent = r"" if top_level else r"[ \t]*"
    for line in text.splitlines():
        bare = uncomment(line)
        if re.match(rf"^{indent}(?:- )?{re.escape(key)}\s*:", bare):
            return True
        if not top_level and re.search(rf"[{{,]\s*{re.escape(key)}\s*:", bare):
            return True
    return False


def check_example_config_fields() -> list[str]:
    """Fail when a config field exists in code but not in config.example.yaml.

    The example file is what `make setup` copies, so an option missing from it
    is effectively undiscoverable even when docs/configuration.md covers it.
    Five fields had drifted out of it this way, three of them editable from the
    web UI — a user could find them in the editor but not in the file the
    editor writes.
    """
    import dataclasses

    errors: list[str] = []
    text = EXAMPLE_CONFIG.read_text()
    regions = example_config_regions(text)
    sections, scalars = example_config_sections()

    for section, cls in sections.items():
        # "theme_rules.when" is documented inside the theme_rules region.
        region = regions.get(section.split(".", 1)[0], "")
        for f in dataclasses.fields(cls):
            path = f"{section}.{f.name}"
            if path in EXAMPLE_CONFIG_EXEMPT or path in EXAMPLE_CONFIG_CONTAINERS:
                continue
            if not documents_key(region, f.name):
                errors.append(
                    f"config/config.example.yaml: no entry for '{path}' "
                    f"— add it (commented out at its default if optional)"
                )
    for name in scalars:
        section, key = EXAMPLE_CONFIG_RENAMED.get(name, ("", name))
        scope = regions.get(section, "") if section else text
        if not documents_key(scope, key, top_level=not section):
            where = f"{section}.{key}" if section else f"top-level '{key}'"
            errors.append(f"config/config.example.yaml: no entry for {where}")
    return errors


def check_example_config_themes(theme_names: set[str]) -> list[str]:
    """Keep the theme list in config.example.yaml matching the registry.

    docs/themes.md and docs/inky-previews.md are already held to the registry,
    but the example config was not — and had fallen 12 themes behind, so a
    third of the catalog was invisible to anyone reading only the template.
    """
    text = EXAMPLE_CONFIG.read_text()
    match = EXAMPLE_THEME_BLOCK_RE.search(text)
    if match is None:
        return ["config/config.example.yaml: could not find the theme-names block"]

    listed = set(EXAMPLE_THEME_TOKEN_RE.findall(match.group(1)))
    errors: list[str] = []
    for name in sorted(theme_names - listed):
        errors.append(f"config/config.example.yaml: theme '{name}' missing from the theme list")
    for name in sorted(listed - theme_names - THEME_PSEUDO_NAMES):
        errors.append(f"config/config.example.yaml: unknown theme '{name}' in the theme list")
    return errors


README_THEME_COUNT_RE = re.compile(r"\b(\d+) built-in themes\b")


def check_readme_theme_count(theme_names: set[str]) -> list[str]:
    """The README's headline theme count must match the registry.

    ``default`` is a pseudo-name, not a theme a user would count; the README
    said 34 for six themes after the registry reached 40.
    """
    concrete = len(theme_names - {"default"})
    text = (ROOT / "README.md").read_text()
    counts = README_THEME_COUNT_RE.findall(text)
    if not counts:
        return ["README.md: no 'N built-in themes' line to check against the registry"]
    return [
        f"README.md: says {n} built-in themes, the registry has {concrete}"
        for n in counts
        if int(n) != concrete
    ]


def main() -> int:
    theme_names = load_theme_names()
    errors = check_links()
    errors.extend(check_readme_theme_count(theme_names))
    errors.extend(check_theme_inventory(theme_names))
    errors.extend(check_example_config_themes(theme_names))
    errors.extend(check_example_config_fields())
    if errors:
        for err in errors:
            print(err)
        return 1
    print("docs-check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
