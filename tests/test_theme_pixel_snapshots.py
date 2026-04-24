"""Pixel-hash snapshot tests for every registered theme.

Renders each theme with pinned dummy data and a fixed date, then hashes the
final image bytes and compares against a baseline in
``tests/snapshots/theme_pixel_hashes.json``.

This catches classes of rendering regressions that the coarse smoke tests in
``test_render_snapshots.py`` miss — component drift, font-size bumps, theme
style edits, quantize / palette tweaks.

Pillow font rasterisation can shift across any release (major, minor, or
patch), so the baselines are pinned against the exact Pillow version recorded
in the JSON under ``reference_env.pillow_version``. When the runtime Pillow
doesn't match that version, the hash comparison is skipped (the render itself
still runs, proving the theme doesn't crash) — so routine upstream Pillow
releases in the normal test matrix don't fail CI spuriously.

The strict hash assertion fires in the dedicated ``snapshot-tests`` CI job,
which reads ``reference_env.pillow_version`` and installs exactly that
Pillow version before running this file.

When a diff is expected (intentional theme change, deliberate Pillow upgrade),
regenerate baselines::

    UPDATE_SNAPSHOTS=1 python -m pytest tests/test_theme_pixel_snapshots.py

``UPDATE_SNAPSHOTS=1`` also stamps the current Pillow version as the new
reference, so commit the updated JSON alongside the source change.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import PIL
import pytest

from src.config import DisplayConfig
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import _THEME_REGISTRY, load_theme

# A Monday morning — matches the pin in test_render_snapshots.py so both suites
# exercise the same dummy-data shape.
FIXED_NOW = datetime(2026, 4, 6, 10, 30)

BASELINE_PATH = Path(__file__).parent / "snapshots" / "theme_pixel_hashes.json"

# Themes that need extra inputs to render non-empty content.
_MESSAGE_TEXT = "Snapshot test message."

# Themes whose output depends on external files that aren't part of the repo.
# They still render (background_fn no-ops when the file is missing) but we
# document them here so future maintainers see them explicitly.
_EXTERNAL_ASSET_THEMES: frozenset[str] = frozenset({"photo"})

THEME_NAMES = sorted(set(_THEME_REGISTRY.keys()) | {"default"})

_CURRENT_PILLOW_VERSION = PIL.__version__


def _render(theme_name: str):
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme(theme_name)
    config = DisplayConfig()
    kwargs: dict[str, str] = {}
    if theme_name == "message":
        kwargs["message_text"] = _MESSAGE_TEXT
    return render_dashboard(data, config, title="Test Dashboard", theme=theme, **kwargs)


def _hash_image(theme_name: str) -> str:
    img = _render(theme_name)
    return hashlib.sha256(img.tobytes()).hexdigest()


def _load_baseline_doc() -> dict:
    if not BASELINE_PATH.exists():
        return {"reference_env": {}, "themes": {}}
    doc = json.loads(BASELINE_PATH.read_text())
    # Normalise legacy flat format just in case a stale file is picked up.
    if "themes" not in doc:
        return {"reference_env": {}, "themes": doc}
    return doc


def _load_baselines() -> dict[str, str]:
    return _load_baseline_doc().get("themes", {})


def _reference_pillow_version() -> str | None:
    env = _load_baseline_doc().get("reference_env", {})
    value = env.get("pillow_version")
    return str(value) if value else None


def _write_baseline_doc(themes: dict[str, str]) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "reference_env": {
            "pillow_version": _CURRENT_PILLOW_VERSION,
        },
        "themes": dict(sorted(themes.items())),
    }
    BASELINE_PATH.write_text(json.dumps(doc, indent=2) + "\n")


@pytest.mark.parametrize("theme_name", THEME_NAMES)
def test_theme_pixel_hash(theme_name: str) -> None:
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        actual = _hash_image(theme_name)
        themes = _load_baselines()
        themes[theme_name] = actual
        _write_baseline_doc(themes)
        return

    # Always render — this proves the theme doesn't crash even when we can't
    # assert the hash (different Pillow version than the baseline).
    actual = _hash_image(theme_name)

    ref_version = _reference_pillow_version()
    if ref_version is not None and ref_version != _CURRENT_PILLOW_VERSION:
        pytest.skip(
            f"Snapshot baselines pinned to Pillow {ref_version}; "
            f"running Pillow {_CURRENT_PILLOW_VERSION}. "
            f"Hash assertion skipped (runs in the snapshot-tests CI job)."
        )
    expected = _load_baselines().get(theme_name)
    if expected is None:
        pytest.fail(
            f"No baseline hash for theme {theme_name!r}. "
            f"Run UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py "
            f"to regenerate baselines, then commit the updated JSON."
        )
    assert actual == expected, (
        f"Theme {theme_name!r} pixel hash changed.\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}\n"
        f"If this change is intentional, regenerate baselines with "
        f"UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py "
        f"and commit the updated JSON."
    )


def test_all_registered_themes_are_covered() -> None:
    """Guard: every theme in _THEME_REGISTRY must have a baseline entry.

    This catches the "added a theme but forgot to regenerate baselines" case.
    """
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        pytest.skip("Regenerating baselines; skip coverage guard for this run.")
    baselines = _load_baselines()
    missing = sorted(set(THEME_NAMES) - set(baselines.keys()))
    assert not missing, (
        f"Themes are missing from snapshot baselines: {missing}. "
        f"Run UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py."
    )


def test_external_asset_themes_are_documented() -> None:
    """Guard: themes that depend on external files must still be in the registry."""
    unknown = _EXTERNAL_ASSET_THEMES - set(_THEME_REGISTRY.keys())
    assert not unknown, f"Unknown themes in _EXTERNAL_ASSET_THEMES: {unknown}"
