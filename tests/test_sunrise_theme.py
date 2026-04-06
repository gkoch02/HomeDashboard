"""Tests for the sunrise theme and sunrise_panel component."""

from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import WeatherData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.sunrise_panel import (
    _sun_position_fraction,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 5, 10, 30)


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _make_weather(**overrides) -> WeatherData:
    defaults = dict(
        current_temp=72.0,
        current_icon="02d",
        current_description="partly cloudy",
        high=78.0,
        low=60.0,
        humidity=52,
        sunrise=datetime(2026, 4, 5, 6, 12),
        sunset=datetime(2026, 4, 5, 19, 48),
    )
    defaults.update(overrides)
    return WeatherData(**defaults)


def _render(theme_name: str = "sunrise") -> Image.Image:
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme(theme_name)
    config = DisplayConfig()
    return render_dashboard(data, config, title="Test Dashboard", theme=theme)


# ---------------------------------------------------------------------------
# Theme registration
# ---------------------------------------------------------------------------


class TestSunriseRegistration:
    def test_in_available_themes(self):
        assert "sunrise" in AVAILABLE_THEMES

    def test_load_theme(self):
        theme = load_theme("sunrise")
        assert theme.name == "sunrise"

    def test_sunrise_region_visible(self):
        theme = load_theme("sunrise")
        assert theme.layout.sunrise.visible is True


# ---------------------------------------------------------------------------
# Sun position logic
# ---------------------------------------------------------------------------


class TestSunPositionFraction:
    def test_sunrise_returns_zero(self):
        sr = datetime(2026, 4, 5, 6, 0)
        ss = datetime(2026, 4, 5, 18, 0)
        assert _sun_position_fraction(sr, sr, ss) == 0.0

    def test_sunset_returns_one(self):
        sr = datetime(2026, 4, 5, 6, 0)
        ss = datetime(2026, 4, 5, 18, 0)
        assert _sun_position_fraction(ss, sr, ss) == 1.0

    def test_midday_returns_half(self):
        sr = datetime(2026, 4, 5, 6, 0)
        ss = datetime(2026, 4, 5, 18, 0)
        noon = datetime(2026, 4, 5, 12, 0)
        assert _sun_position_fraction(noon, sr, ss) == 0.5

    def test_before_sunrise_negative(self):
        sr = datetime(2026, 4, 5, 6, 0)
        ss = datetime(2026, 4, 5, 18, 0)
        early = datetime(2026, 4, 5, 4, 0)
        assert _sun_position_fraction(early, sr, ss) < 0

    def test_after_sunset_gt_one(self):
        sr = datetime(2026, 4, 5, 6, 0)
        ss = datetime(2026, 4, 5, 18, 0)
        late = datetime(2026, 4, 5, 20, 0)
        assert _sun_position_fraction(late, sr, ss) > 1.0


# ---------------------------------------------------------------------------
# Rendering smoke tests
# ---------------------------------------------------------------------------


class TestSunriseTheme:
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
        """Should not crash when weather is None."""
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = None
        theme = load_theme("sunrise")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_without_events(self):
        """Should not crash when no events."""
        data = generate_dummy_data(now=FIXED_NOW)
        data.events = []
        theme = load_theme("sunrise")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)

    def test_renders_after_sunset(self):
        """Should show moon glyph instead of sun after sunset."""
        late = datetime(2026, 4, 5, 21, 0)
        data = generate_dummy_data(now=late)
        theme = load_theme("sunrise")
        config = DisplayConfig()
        img = render_dashboard(data, config, title="Test", theme=theme)
        assert img.size == (800, 480)
