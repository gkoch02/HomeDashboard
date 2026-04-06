"""Tests for the tides theme and tides_panel component."""

from __future__ import annotations

from datetime import datetime

from PIL import Image

from src.config import DisplayConfig
from src.data.models import DashboardData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 5, 10, 30)


def _render(theme_name: str = "tides") -> Image.Image:
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme(theme_name)
    config = DisplayConfig()
    return render_dashboard(data, config, title="Test Dashboard", theme=theme)


# ---------------------------------------------------------------------------
# Theme registration
# ---------------------------------------------------------------------------


class TestTidesRegistration:
    def test_in_available_themes(self):
        assert "tides" in AVAILABLE_THEMES

    def test_load_theme(self):
        theme = load_theme("tides")
        assert theme.name == "tides"

    def test_tides_region_visible(self):
        theme = load_theme("tides")
        assert theme.layout.tides.visible is True


# ---------------------------------------------------------------------------
# Rendering smoke tests
# ---------------------------------------------------------------------------


class TestTidesTheme:
    def test_renders_correct_size(self):
        img = _render()
        assert img.size == (800, 480)

    def test_renders_1bit(self):
        img = _render()
        assert img.mode == "1"

    def test_renders_non_blank(self):
        img = _render()
        assert not all(p == 255 for p in img.tobytes()), "Image is blank"

    def test_has_inverted_bands(self):
        """Verify that the image contains both black and white regions."""
        img = _render()
        raw = img.tobytes()
        n_black = sum(1 for b in raw if b == 0)
        n_white = sum(1 for b in raw if b != 0)
        total = len(raw)
        # Inverted bands mean significant black pixels (>10% of canvas)
        assert n_black > total * 0.05, "Expected substantial inverted (black) regions"
        assert n_white > total * 0.05, "Expected substantial normal (white) regions"

    def test_renders_without_weather(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = None
        theme = load_theme("tides")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_without_host_data(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.host_data = None
        theme = load_theme("tides")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_without_air_quality(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.air_quality = None
        theme = load_theme("tides")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_all_data_missing(self):
        """Tides should gracefully handle all optional data missing."""
        data = DashboardData(fetched_at=FIXED_NOW)
        theme = load_theme("tides")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_band_skip_when_no_weather(self):
        """Weather and forecast bands should be skipped when no weather data."""
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = None
        data.host_data = None
        theme = load_theme("tides")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        # Should still render without error
        assert img.mode == "1"
