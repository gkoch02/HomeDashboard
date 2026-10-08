"""Snapshot render tests — verify stable themes produce consistent output.

These tests render a dashboard with fixed dummy data and a pinned date,
then verify basic image properties (size, mode, non-blank). They catch
accidental rendering regressions without relying on pixel-exact comparison,
which would be fragile across font rendering differences.
"""

from datetime import datetime

import pytest
from PIL import Image

from src.config import DisplayConfig
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import load_theme

# Use a fixed date so dummy data is deterministic
FIXED_NOW = datetime(2026, 4, 6, 10, 30)  # A Monday morning


def _render_theme(theme_name: str) -> Image.Image:
    """Render a dashboard with dummy data for the given theme."""
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme(theme_name)
    config = DisplayConfig()
    return render_dashboard(data, config, title="Test Dashboard", theme=theme)


class TestDefaultThemeSnapshot:
    def test_renders_correct_size(self):
        img = _render_theme("default")
        assert img.size == (800, 480)

    def test_renders_non_blank(self):
        img = _render_theme("default")
        # A blank white image has all pixels at 255; a rendered one has black pixels
        pixels = list(img.tobytes())
        assert not all(p == 255 for p in pixels), "Image is blank (all white)"

    def test_renders_as_1bit(self):
        img = _render_theme("default")
        assert img.mode == "1"


class TestTerminalThemeSnapshot:
    def test_renders_correct_size(self):
        img = _render_theme("terminal")
        assert img.size == (800, 480)

    def test_renders_non_blank(self):
        img = _render_theme("terminal")
        pixels = list(img.tobytes())
        # Terminal theme has dark bg, so check it's not all black either
        has_white = any(p != 0 for p in pixels)
        has_black = any(p == 0 for p in pixels)
        assert has_white and has_black, "Image has no variation"


class TestAllThemesRender:
    """Smoke test: every theme should render without crashing."""

    THEMES = [
        "default",
        "terminal",
        "old_fashioned",
        "fantasy",
        "qotd",
        "qotd_invert",
        "weather",
        "fuzzyclock",
        "fuzzyclock_invert",
        "diags",
        "air_quality",
        "moonphase",
        "moonphase_invert",
    ]

    def test_all_themes_render_800x480(self):
        for theme_name in self.THEMES:
            img = _render_theme(theme_name)
            assert img.size == (800, 480), f"{theme_name} rendered wrong size: {img.size}"
            assert isinstance(img, Image.Image), f"{theme_name} didn't return an Image"


@pytest.mark.parametrize("fill", [0, 1])
def test_terminal_non_blank_check_rejects_uniform_images(monkeypatch, fill):
    monkeypatch.setattr(__name__ + "._render_theme", lambda _name: Image.new("1", (800, 480), fill))
    with pytest.raises(AssertionError, match="Image has no variation"):
        TestTerminalThemeSnapshot().test_renders_non_blank()
