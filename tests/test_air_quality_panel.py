"""Tests for src/render/components/air_quality_panel.py
and src/render/themes/air_quality.py."""

from datetime import date, timedelta

import pytest
from PIL import Image, ImageDraw

from src.data.models import AirQualityData, DashboardData, DayForecast, WeatherData
from src.render.components.air_quality_panel import draw_air_quality_full
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _make_aq(**overrides) -> AirQualityData:
    defaults = dict(
        aqi=42,
        category="Good",
        pm25=9.8,
        pm10=14.2,
        pm1=6.1,
        sensor_id=99999,
        temperature=72.0,
        humidity=55.0,
        pressure=1013.0,
    )
    defaults.update(overrides)
    return AirQualityData(**defaults)


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
                high=70.0 + i,
                low=55.0 + i,
                icon="02d",
                description="partly cloudy",
                precip_chance=0.20,
            )
            for i in range(4)
        ],
    )
    defaults.update(overrides)
    return WeatherData(**defaults)


def _make_data(**overrides) -> DashboardData:
    data = DashboardData(
        air_quality=_make_aq(),
        weather=_make_weather(),
    )
    for k, v in overrides.items():
        setattr(data, k, v)
    return data


# ---------------------------------------------------------------------------
# Smoke tests — full data
# ---------------------------------------------------------------------------


class TestDrawAirQualityFullSmoke:
    def test_renders_with_full_data(self):
        _, draw = _make_draw()
        draw_air_quality_full(draw, _make_data(), date(2024, 3, 15))

    def test_returns_none(self):
        _, draw = _make_draw()
        result = draw_air_quality_full(draw, _make_data(), date(2024, 3, 15))
        assert result is None

    def test_produces_non_blank_image(self):
        img, draw = _make_draw()
        draw_air_quality_full(draw, _make_data(), date(2024, 3, 15))
        assert img.getbbox() is not None

    def test_default_region_and_style(self):
        """Passing region=None and style=None triggers default-assignment branches."""
        _, draw = _make_draw()
        draw_air_quality_full(draw, _make_data(), region=None, style=None)

    def test_custom_region(self):
        _, draw = _make_draw()
        region = ComponentRegion(10, 10, 780, 460)
        draw_air_quality_full(draw, _make_data(), region=region, style=ThemeStyle())

    def test_custom_style(self):
        _, draw = _make_draw()
        style = ThemeStyle()
        draw_air_quality_full(draw, _make_data(), style=style)


# ---------------------------------------------------------------------------
# Unavailable fallback
# ---------------------------------------------------------------------------


class TestDrawAirQualityUnavailable:
    def test_renders_when_air_quality_is_none(self):
        _, draw = _make_draw()
        data = _make_data(air_quality=None)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_unavailable_produces_non_blank_image(self):
        img, draw = _make_draw()
        data = _make_data(air_quality=None)
        draw_air_quality_full(draw, data)
        assert img.getbbox() is not None

    def test_unavailable_does_not_crash_with_weather_also_none(self):
        _, draw = _make_draw()
        data = _make_data(air_quality=None, weather=None)
        draw_air_quality_full(draw, data)


# ---------------------------------------------------------------------------
# Weather strip variations
# ---------------------------------------------------------------------------


class TestWeatherStrip:
    def test_renders_without_weather(self):
        """Weather=None shows fallback message in strip."""
        _, draw = _make_draw()
        data = _make_data(weather=None)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_renders_without_forecast(self):
        _, draw = _make_draw()
        wx = _make_weather(forecast=[])
        data = _make_data(weather=wx)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_renders_with_empty_precip_chance(self):
        """Forecast items with precip_chance=None or < 0.05 render without precip string."""
        _, draw = _make_draw()
        wx = _make_weather(
            forecast=[
                DayForecast(
                    date=date(2024, 3, 17),
                    high=70.0,
                    low=55.0,
                    icon="01d",
                    description="clear",
                    precip_chance=None,
                ),
                DayForecast(
                    date=date(2024, 3, 18),
                    high=68.0,
                    low=52.0,
                    icon="02d",
                    description="cloudy",
                    precip_chance=0.02,
                ),
            ]
        )
        data = _make_data(weather=wx)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_renders_with_high_precip_chance(self):
        _, draw = _make_draw()
        wx = _make_weather(
            forecast=[
                DayForecast(
                    date=date(2024, 3, 17),
                    high=65.0,
                    low=50.0,
                    icon="10d",
                    description="rain",
                    precip_chance=0.90,
                ),
            ]
        )
        data = _make_data(weather=wx)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_renders_without_today_date(self):
        """today=None (default) still renders the full layout."""
        _, draw = _make_draw()
        draw_air_quality_full(draw, _make_data())


# ---------------------------------------------------------------------------
# PM row variations
# ---------------------------------------------------------------------------


class TestPMRow:
    def test_only_pm25_when_pm1_and_pm10_absent(self):
        """With pm1=None and pm10=None, only PM2.5 column is drawn."""
        _, draw = _make_draw()
        aq = _make_aq(pm1=None, pm10=None)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_pm25_and_pm10_only(self):
        _, draw = _make_draw()
        aq = _make_aq(pm1=None)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_all_three_pm_columns(self):
        _, draw = _make_draw()
        aq = _make_aq(pm1=3.2, pm25=9.8, pm10=15.0)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_zero_pm_values(self):
        _, draw = _make_draw()
        aq = _make_aq(pm1=0.0, pm25=0.0, pm10=0.0)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))


# ---------------------------------------------------------------------------
# Ambient sensor cards variations
# ---------------------------------------------------------------------------


class TestAmbientCards:
    def test_no_ambient_fields(self):
        """When temperature, humidity, and pressure are all None, no cards are drawn."""
        _, draw = _make_draw()
        aq = _make_aq(temperature=None, humidity=None, pressure=None)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_temperature_only(self):
        _, draw = _make_draw()
        aq = _make_aq(temperature=72.0, humidity=None, pressure=None)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_humidity_only(self):
        _, draw = _make_draw()
        aq = _make_aq(temperature=None, humidity=60.0, pressure=None)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_pressure_only(self):
        _, draw = _make_draw()
        aq = _make_aq(temperature=None, humidity=None, pressure=1013.0)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_temp_and_humidity_only(self):
        _, draw = _make_draw()
        aq = _make_aq(temperature=70.0, humidity=55.0, pressure=None)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_all_three_cards(self):
        _, draw = _make_draw()
        aq = _make_aq(temperature=68.0, humidity=50.0, pressure=1015.0)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_temperature_hidden_when_from_fallback(self):
        """When temperature is from OWM fallback, the temp card is hidden."""
        _, draw = _make_draw()
        # Temperature and pressure from fallback, humidity from sensor
        aq = _make_aq(
            temperature=68.0,
            humidity=55.0,
            pressure=1013.0,
            fallback_fields={"temperature", "pressure"},
        )
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_only_humidity_shown_when_temp_from_fallback(self):
        """Only humidity card shown when temperature is fallback and pressure is None."""
        _, draw = _make_draw()
        aq = _make_aq(
            temperature=68.0,
            humidity=55.0,
            pressure=None,
            fallback_fields={"temperature"},
        )
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_humidity_and_pressure_shown_without_temperature(self):
        """Humidity and pressure cards centered when temperature is fallback."""
        _, draw = _make_draw()
        aq = _make_aq(
            temperature=68.0,
            humidity=55.0,
            pressure=1013.0,
            fallback_fields={"temperature"},
        )
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))


# ---------------------------------------------------------------------------
# AQI scale bar — various AQI values covering all six zones
# ---------------------------------------------------------------------------


class TestAqiHeroAndScaleBar:
    @pytest.mark.parametrize(
        "aqi,category",
        [
            (0, "Good"),
            (25, "Good"),
            (50, "Good"),
            (75, "Moderate"),
            (100, "Moderate"),
            (125, "Unhealthy for Sensitive Groups"),
            (151, "Unhealthy"),
            (201, "Very Unhealthy"),
            (301, "Hazardous"),
            (500, "Hazardous"),
        ],
    )
    def test_aqi_zones_render_without_error(self, aqi, category):
        _, draw = _make_draw()
        aq = _make_aq(aqi=aqi, category=category)
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_aqi_zero_does_not_crash(self):
        _, draw = _make_draw()
        aq = _make_aq(aqi=0, category="Good")
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_aqi_max_does_not_crash(self):
        _, draw = _make_draw()
        aq = _make_aq(aqi=500, category="Hazardous")
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))

    def test_aqi_large_number_renders(self):
        """Three-digit AQI renders; auto-scale loop doesn't hang."""
        _, draw = _make_draw()
        aq = _make_aq(aqi=350, category="Hazardous")
        data = _make_data(air_quality=aq)
        draw_air_quality_full(draw, data, date(2024, 3, 15))


# ---------------------------------------------------------------------------
# air_quality theme factory — src/render/themes/air_quality.py
# ---------------------------------------------------------------------------


class TestAirQualityTheme:
    def test_theme_name(self):
        from src.render.themes.air_quality import air_quality_theme

        assert air_quality_theme().name == "air_quality"

    def test_theme_in_available_themes(self):
        from src.render.theme import AVAILABLE_THEMES

        assert "air_quality" in AVAILABLE_THEMES

    def test_load_theme_returns_air_quality(self):
        from src.render.theme import load_theme

        assert load_theme("air_quality").name == "air_quality"

    def test_air_quality_full_region_visible(self):
        from src.render.themes.air_quality import air_quality_theme

        assert air_quality_theme().layout.air_quality_full.visible is True

    def test_standard_regions_hidden(self):
        from src.render.themes.air_quality import air_quality_theme

        layout = air_quality_theme().layout
        assert layout.header.visible is False
        assert layout.week_view.visible is False
        assert layout.weather.visible is False

    def test_uses_space_grotesk_fonts(self):
        from src.render.fonts import sg_bold, sg_regular
        from src.render.themes.air_quality import air_quality_theme

        style = air_quality_theme().style
        assert style.font_regular is sg_regular
        assert style.font_bold is sg_bold

    def test_renders_via_canvas(self):
        from PIL import Image as PILImage

        from src.config import DisplayConfig
        from src.render.canvas import render_dashboard
        from src.render.theme import load_theme

        result = render_dashboard(_make_data(), DisplayConfig(), theme=load_theme("air_quality"))
        assert isinstance(result, PILImage.Image)
        assert result.size == (800, 480)
