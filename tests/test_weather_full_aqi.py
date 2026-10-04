"""Tests for AQI card rendering in the weather_full component."""

from datetime import date, datetime, timedelta

import pytest
from PIL import Image, ImageDraw

from src.data.models import AirQualityData, DayForecast, WeatherData
from src.render.components.weather_full import draw_weather_full
from src.render.theme import ComponentRegion, ThemeStyle
from tests.inkutils import ink

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _make_weather() -> WeatherData:
    return WeatherData(
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
            )
            for i in range(5)
        ],
        feels_like=70.0,
        wind_speed=5.0,
        wind_deg=315.0,
        uv_index=3.0,
        sunrise=datetime(2024, 3, 15, 6, 24),
        sunset=datetime(2024, 3, 15, 19, 45),
    )


def _make_aqi(**overrides) -> AirQualityData:
    defaults = dict(aqi=42, category="Good", pm25=9.8, pm10=14.2, sensor_id=99999)
    defaults.update(overrides)
    return AirQualityData(**defaults)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


TODAY = date(2024, 3, 15)

# The metric-card band, mirrored from draw_weather_full's own proportions.
_CARDS_Y0 = int(480 * 0.44)
CARDS = (0, _CARDS_Y0, 800, _CARDS_Y0 + int(480 * 0.155))


def _render(weather, air_quality, **kwargs) -> Image.Image:
    img, draw = _make_draw()
    draw_weather_full(draw, weather, TODAY, air_quality=air_quality, **kwargs)
    return img


class TestDrawWeatherFullAqi:
    """Every AQI input shape renders a non-blank plate; nothing finer is asserted here.

    The card's content is measured in test_weather_full_component.py.
    """

    @pytest.mark.parametrize(
        "weather_present, aqi_kwargs, draw_kwargs",
        [
            (True, None, {}),
            (True, dict(aqi=42, category="Good"), {}),
            (True, dict(aqi=120, category="Unhealthy for Sensitive Groups", pm25=40.0), {}),
            (True, dict(aqi=300, category="Very Unhealthy", pm25=200.0), {}),
            (False, {}, {}),
            (True, {}, dict(region=ComponentRegion(0, 0, 800, 480), style=ThemeStyle())),
            (True, dict(pm10=None), {}),
        ],
        ids=[
            "no_aqi",
            "good",
            "long_category_label",
            "hazardous",
            "weather_unavailable",
            "explicit_region_and_style",
            "pm10_missing",
        ],
    )
    def test_renders_a_non_blank_plate(self, weather_present, aqi_kwargs, draw_kwargs):
        weather = _make_weather() if weather_present else None
        aq = None if aqi_kwargs is None else _make_aqi(**aqi_kwargs)
        assert ink(_render(weather, aq, **draw_kwargs)) > 0

    def test_aqi_card_changes_the_cards_band(self):
        """The fifth card is drawn from the reading: the band differs with and without it."""
        with_aqi = _render(_make_weather(), _make_aqi())
        without = _render(_make_weather(), None)
        assert ink(with_aqi, CARDS) != ink(without, CARDS), "the AQI card is not drawn"
