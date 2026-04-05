"""Tests for the fuzzyclock theme and its integration with the render pipeline."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image

from src.config import DisplayConfig
from src.data.models import (
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    WeatherData,
)
from src.render.canvas import render_dashboard
from src.render.theme import (
    AVAILABLE_THEMES,
    load_theme,
)
from src.render.themes.fuzzyclock import fuzzyclock_theme

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _make_data(today: date | None = None) -> DashboardData:
    today = today or date(2026, 3, 23)
    now = datetime.combine(today, datetime.min.time().replace(hour=7, minute=30))
    return DashboardData(
        fetched_at=now,
        events=[
            CalendarEvent(
                summary="Standup",
                start=datetime.combine(today, datetime.min.time().replace(hour=9)),
                end=datetime.combine(today, datetime.min.time().replace(hour=9, minute=30)),
            ),
        ],
        weather=WeatherData(
            current_temp=68.0,
            current_icon="01d",
            current_description="clear sky",
            high=75.0,
            low=55.0,
            humidity=40,
            forecast=[
                DayForecast(
                    date=today + timedelta(days=1),
                    high=72.0,
                    low=50.0,
                    icon="02d",
                    description="partly cloudy",
                ),
            ],
        ),
        birthdays=[
            Birthday(name="Alice", date=today + timedelta(days=2)),
        ],
    )


# ---------------------------------------------------------------------------
# Theme structure
# ---------------------------------------------------------------------------


class TestFuzzyclockTheme:
    def test_name(self):
        theme = fuzzyclock_theme()
        assert theme.name == "fuzzyclock"

    def test_in_available_themes(self):
        assert "fuzzyclock" in AVAILABLE_THEMES

    def test_load_theme(self):
        theme = load_theme("fuzzyclock")
        assert theme.name == "fuzzyclock"

    def test_fuzzyclock_region_visible(self):
        theme = fuzzyclock_theme()
        assert theme.layout.fuzzyclock.visible is True

    def test_weather_region_visible(self):
        theme = fuzzyclock_theme()
        assert theme.layout.weather.visible is True

    def test_other_regions_hidden(self):
        theme = fuzzyclock_theme()
        assert theme.layout.header.visible is False
        assert theme.layout.week_view.visible is False
        assert theme.layout.birthdays.visible is False
        assert theme.layout.info.visible is False

    def test_draw_order(self):
        theme = fuzzyclock_theme()
        assert theme.layout.draw_order == ["fuzzyclock", "fuzzyclock_weather"]

    def test_canvas_size(self):
        theme = fuzzyclock_theme()
        assert theme.layout.canvas_w == 800
        assert theme.layout.canvas_h == 480

    def test_weather_region_at_bottom(self):
        theme = fuzzyclock_theme()
        w = theme.layout.weather
        assert w.y + w.h == 480  # banner fills bottom of canvas

    def test_fuzzyclock_region_above_weather(self):
        theme = fuzzyclock_theme()
        fc = theme.layout.fuzzyclock
        w = theme.layout.weather
        assert fc.y == 0
        assert fc.h == w.y  # clock ends where weather begins


# ---------------------------------------------------------------------------
# Render pipeline smoke tests
# ---------------------------------------------------------------------------


class TestFuzzyclockRender:
    def test_render_returns_image(self):
        data = _make_data()
        config = DisplayConfig()
        theme = fuzzyclock_theme()
        result = render_dashboard(data, config, theme=theme)
        assert isinstance(result, Image.Image)

    def test_render_correct_size(self):
        data = _make_data()
        config = DisplayConfig(width=800, height=480)
        theme = fuzzyclock_theme()
        result = render_dashboard(data, config, theme=theme)
        assert result.size == (800, 480)

    def test_render_no_weather(self):
        """Should not crash when weather data is absent."""
        data = _make_data()
        data.weather = None
        config = DisplayConfig()
        theme = fuzzyclock_theme()
        render_dashboard(data, config, theme=theme)

    def test_render_via_load_theme(self):
        data = _make_data()
        config = DisplayConfig()
        theme = load_theme("fuzzyclock")
        result = render_dashboard(data, config, theme=theme)
        assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# fuzzyclock_invert theme
# ---------------------------------------------------------------------------


class TestFuzzyclockInvertTheme:
    def test_name(self):
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme

        assert fuzzyclock_invert_theme().name == "fuzzyclock_invert"

    def test_in_available_themes(self):
        assert "fuzzyclock_invert" in AVAILABLE_THEMES

    def test_load_theme(self):
        assert load_theme("fuzzyclock_invert").name == "fuzzyclock_invert"

    def test_inverted_colors(self):
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme

        t = fuzzyclock_invert_theme()
        assert t.style.fg == 1  # white text on black
        assert t.style.bg == 0

    def test_fuzzyclock_region_visible(self):
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme

        assert fuzzyclock_invert_theme().layout.fuzzyclock.visible is True

    def test_weather_region_visible(self):
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme

        assert fuzzyclock_invert_theme().layout.weather.visible is True

    def test_standard_regions_hidden(self):
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme

        layout = fuzzyclock_invert_theme().layout
        assert layout.header.visible is False
        assert layout.week_view.visible is False
        assert layout.birthdays.visible is False
        assert layout.info.visible is False

    def test_draw_order(self):
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme

        assert fuzzyclock_invert_theme().layout.draw_order == ["fuzzyclock", "fuzzyclock_weather"]

    def test_weather_at_bottom(self):
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme

        layout = fuzzyclock_invert_theme().layout
        assert layout.weather.y + layout.weather.h == 480

    def test_clock_and_weather_fill_canvas(self):
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme

        layout = fuzzyclock_invert_theme().layout
        assert layout.fuzzyclock.h + layout.weather.h == 480

    def test_render_returns_image(self):
        result = render_dashboard(
            _make_data(), DisplayConfig(), theme=load_theme("fuzzyclock_invert")
        )
        assert isinstance(result, Image.Image)
        assert result.size == (800, 480)

    def test_render_no_weather(self):
        data = _make_data()
        data.weather = None
        render_dashboard(data, DisplayConfig(), theme=load_theme("fuzzyclock_invert"))
