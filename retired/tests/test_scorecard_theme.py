"""Tests for the scorecard theme and scorecard_panel component."""

from __future__ import annotations

from datetime import datetime

from PIL import Image

from src.config import DisplayConfig
from src.data.models import DashboardData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 5, 10, 30)


def _render(theme_name: str = "scorecard") -> Image.Image:
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme(theme_name)
    config = DisplayConfig()
    return render_dashboard(data, config, title="Test Dashboard", theme=theme)


# ---------------------------------------------------------------------------
# Theme registration
# ---------------------------------------------------------------------------


class TestScorecardRegistration:
    def test_in_available_themes(self):
        assert "scorecard" in AVAILABLE_THEMES

    def test_load_theme(self):
        theme = load_theme("scorecard")
        assert theme.name == "scorecard"

    def test_scorecard_region_visible(self):
        theme = load_theme("scorecard")
        assert theme.layout.scorecard.visible is True


# ---------------------------------------------------------------------------
# Rendering smoke tests
# ---------------------------------------------------------------------------


class TestScorecardTheme:
    def test_renders_correct_size(self):
        img = _render()
        assert img.size == (800, 480)

    def test_renders_1bit(self):
        img = _render()
        assert img.mode == "1"

    def test_renders_non_blank(self):
        img = _render()
        assert not all(p == 255 for p in img.tobytes()), "Image is blank"

    def test_renders_without_weather(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = None
        theme = load_theme("scorecard")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_without_air_quality(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.air_quality = None
        theme = load_theme("scorecard")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_without_host_data(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.host_data = None
        theme = load_theme("scorecard")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_without_birthdays(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.birthdays = []
        theme = load_theme("scorecard")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_all_data_missing(self):
        """Scorecard should gracefully handle all optional data missing."""
        data = DashboardData(fetched_at=FIXED_NOW)
        theme = load_theme("scorecard")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_before_sunrise(self):
        early = datetime(2026, 4, 5, 4, 0)
        data = generate_dummy_data(now=early)
        theme = load_theme("scorecard")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)
