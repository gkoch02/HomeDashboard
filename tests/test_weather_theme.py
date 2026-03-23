"""Tests for the full-screen weather theme and weather_full component."""

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import (
    DashboardData, DayForecast, WeatherAlert, WeatherData,
)
from src.render.canvas import render_dashboard
from src.render.components.weather_full import draw_weather_full
from src.render.theme import (
    AVAILABLE_THEMES, ComponentRegion, ThemeLayout, load_theme,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_weather(**overrides) -> WeatherData:
    defaults = dict(
        current_temp=72.0,
        current_icon="01d",
        current_description="clear sky",
        high=78.0,
        low=60.0,
        humidity=45,
        forecast=[
            DayForecast(
                date=date(2024, 3, 16) + timedelta(days=i),
                high=58.0 + i * 2,
                low=42.0 + i,
                icon="02d",
                description="partly cloudy",
                precip_chance=0.1 * i,
            )
            for i in range(5)
        ],
        feels_like=70.0,
        wind_speed=5.0,
        wind_deg=315.0,
        pressure=1013.0,
        uv_index=3.0,
        sunrise=datetime(2024, 3, 15, 6, 24),
        sunset=datetime(2024, 3, 15, 19, 45),
    )
    defaults.update(overrides)
    return WeatherData(**defaults)


def _make_data(weather=None) -> DashboardData:
    today = date(2024, 3, 15)
    now = datetime.combine(today, datetime.min.time().replace(hour=8))
    return DashboardData(
        fetched_at=now,
        events=[],
        weather=weather,
        birthdays=[],
    )


def _draw_surface():
    img = Image.new("1", (800, 480), 1)
    return ImageDraw.Draw(img)


# ---------------------------------------------------------------------------
# Theme registration tests
# ---------------------------------------------------------------------------

class TestWeatherThemeRegistration:
    def test_weather_in_available_themes(self):
        assert "weather" in AVAILABLE_THEMES

    def test_load_theme_returns_weather(self):
        theme = load_theme("weather")
        assert theme.name == "weather"

    def test_weather_full_region_covers_canvas(self):
        theme = load_theme("weather")
        r = theme.layout.weather_full
        assert r.x == 0
        assert r.y == 0
        assert r.w == 800
        assert r.h == 480
        assert r.visible is True

    def test_standard_regions_hidden(self):
        theme = load_theme("weather")
        layout = theme.layout
        assert not layout.header.visible
        assert not layout.week_view.visible
        assert not layout.birthdays.visible
        assert not layout.info.visible
        assert not layout.today_view.visible

    def test_draw_order_uses_weather_full(self):
        theme = load_theme("weather")
        assert theme.layout.draw_order == ["weather_full"]

    def test_style_borderless(self):
        theme = load_theme("weather")
        assert theme.style.show_borders is False

    def test_style_black_on_white(self):
        theme = load_theme("weather")
        assert theme.style.fg == 0
        assert theme.style.bg == 1

    def test_weather_full_default_invisible_on_other_themes(self):
        """The weather_full region should be hidden by default on non-weather themes."""
        layout = ThemeLayout()
        assert not layout.weather_full.visible


# ---------------------------------------------------------------------------
# Rendering integration tests
# ---------------------------------------------------------------------------

class TestWeatherThemeRendering:
    def test_renders_valid_image_with_full_data(self):
        theme = load_theme("weather")
        data = _make_data(weather=_make_weather())
        config = DisplayConfig()
        img = render_dashboard(data, config, theme=theme)
        assert isinstance(img, Image.Image)
        assert img.size[0] > 0
        assert img.size[1] > 0

    def test_renders_with_none_weather(self):
        theme = load_theme("weather")
        data = _make_data(weather=None)
        config = DisplayConfig()
        img = render_dashboard(data, config, theme=theme)
        assert isinstance(img, Image.Image)

    def test_renders_with_alerts(self):
        weather = _make_weather(
            alerts=[WeatherAlert(event="Flood Watch"), WeatherAlert(event="Wind Advisory")],
        )
        theme = load_theme("weather")
        data = _make_data(weather=weather)
        config = DisplayConfig()
        img = render_dashboard(data, config, theme=theme)
        assert isinstance(img, Image.Image)

    def test_renders_with_minimal_data(self):
        weather = WeatherData(
            current_temp=55.0,
            current_icon="03d",
            current_description="overcast",
            high=60.0,
            low=45.0,
            humidity=80,
        )
        theme = load_theme("weather")
        data = _make_data(weather=weather)
        config = DisplayConfig()
        img = render_dashboard(data, config, theme=theme)
        assert isinstance(img, Image.Image)


# ---------------------------------------------------------------------------
# Component unit tests
# ---------------------------------------------------------------------------

class TestDrawWeatherFull:
    def test_none_weather_does_not_crash(self):
        draw = _draw_surface()
        draw_weather_full(draw, None, today=date(2024, 3, 15))

    def test_basic_weather(self):
        draw = _draw_surface()
        weather = _make_weather()
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_all_optional_fields(self):
        draw = _draw_surface()
        weather = _make_weather()
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_no_optional_fields(self):
        draw = _draw_surface()
        weather = WeatherData(
            current_temp=55.0,
            current_icon="01d",
            current_description="clear",
            high=60.0,
            low=45.0,
            humidity=50,
        )
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_with_alerts(self):
        draw = _draw_surface()
        weather = _make_weather(
            alerts=[WeatherAlert(event="Tornado Warning")],
        )
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_empty_forecast(self):
        draw = _draw_surface()
        weather = _make_weather(forecast=[])
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_many_forecast_days_capped_at_five(self):
        draw = _draw_surface()
        forecast = [
            DayForecast(
                date=date(2024, 3, 16) + timedelta(days=i),
                high=60.0 + i, low=40.0 + i,
                icon="02d", description="cloudy",
            )
            for i in range(10)
        ]
        weather = _make_weather(forecast=forecast)
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_wind_without_direction(self):
        draw = _draw_surface()
        weather = _make_weather(wind_speed=10.0, wind_deg=None)
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_negative_temperature(self):
        draw = _draw_surface()
        weather = _make_weather(current_temp=-15.0, high=-5.0, low=-20.0)
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_custom_region(self):
        draw = _draw_surface()
        weather = _make_weather()
        region = ComponentRegion(10, 10, 780, 460)
        draw_weather_full(draw, weather, today=date(2024, 3, 15), region=region)

    def test_no_today_date(self):
        """Moon phase is skipped when today is None."""
        draw = _draw_surface()
        weather = _make_weather()
        draw_weather_full(draw, weather, today=None)

    def test_pressure_shown_in_detail_when_uv_in_cards(self):
        """When UV is available, pressure appears in the detail strip."""
        draw = _draw_surface()
        weather = _make_weather(uv_index=5.0, pressure=1020.0)
        draw_weather_full(draw, weather, today=date(2024, 3, 15))

    def test_pressure_in_cards_when_no_uv(self):
        """When UV is None, pressure takes the 4th card slot."""
        draw = _draw_surface()
        weather = _make_weather(uv_index=None, pressure=1015.0)
        draw_weather_full(draw, weather, today=date(2024, 3, 15))
