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
from tests.inkutils import text_line_heights

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
        """Without weather the plate still renders, and differs from one with weather."""
        with_weather = render_dashboard(_make_data(), DisplayConfig(), theme=fuzzyclock_theme())
        data = _make_data()
        data.weather = None
        result = render_dashboard(data, DisplayConfig(), theme=fuzzyclock_theme())
        assert isinstance(result, Image.Image)
        assert result.tobytes() != with_weather.tobytes(), "the weather band ignores the data"

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
        """Without weather the plate still renders, and differs from one with weather."""
        theme = load_theme("fuzzyclock_invert")
        with_weather = render_dashboard(_make_data(), DisplayConfig(), theme=theme)
        data = _make_data()
        data.weather = None
        result = render_dashboard(data, DisplayConfig(), theme=theme)
        assert isinstance(result, Image.Image)
        assert result.tobytes() != with_weather.tobytes(), "the weather band ignores the data"


class TestFuzzyclockInk:
    def _draw(self) -> tuple[Image.Image, tuple[int, int, int, int]]:
        from PIL import ImageDraw

        from src.render.components.fuzzyclock_panel import draw_fuzzyclock

        theme = fuzzyclock_theme()
        region = theme.layout.fuzzyclock
        img = Image.new("1", (theme.layout.canvas_w, theme.layout.canvas_h), 1)
        draw_fuzzyclock(
            ImageDraw.Draw(img), datetime(2026, 3, 23, 7, 30), region=region, style=theme.style
        )
        return img, (region.x, region.y, region.x + region.w, region.y + region.h)

    def test_phrase_and_date_line_both_ink(self):
        img, box = self._draw()
        lines = text_line_heights(img, box)
        assert len(lines) == 2, lines
        phrase_h, date_h = lines
        assert date_h < phrase_h
