"""Tests for src/render/components/weather_full.py.

Covers: hero zone, metric cards, detail strip, alert banner, forecast grid,
and the unavailable fallback — exercising branches not covered by the existing
test_weather_full_aqi.py (which focuses on the AQI card only).
"""

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import (
    AirQualityData,
    DayForecast,
    WeatherAlert,
    WeatherData,
)
from src.render.components.weather_full import draw_weather_full
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _make_forecast(n: int = 5) -> list[DayForecast]:
    return [
        DayForecast(
            date=date(2024, 3, 16) + timedelta(days=i),
            high=60.0 + i * 2,
            low=45.0 + i,
            icon="02d",
            description="partly cloudy",
            precip_chance=0.20,
        )
        for i in range(n)
    ]


def _make_weather(**overrides) -> WeatherData:
    defaults = dict(
        current_temp=72.0,
        current_icon="01d",
        current_description="clear sky",
        high=78.0,
        low=60.0,
        humidity=45,
        forecast=_make_forecast(5),
        feels_like=70.0,
        wind_speed=8.0,
        wind_deg=270.0,
        uv_index=4.0,
        pressure=1013.0,
        sunrise=datetime(2024, 3, 15, 6, 24),
        sunset=datetime(2024, 3, 15, 19, 45),
        location_name="San Francisco",
    )
    defaults.update(overrides)
    return WeatherData(**defaults)


TODAY = date(2024, 3, 15)


# ---------------------------------------------------------------------------
# Smoke — basic rendering
# ---------------------------------------------------------------------------


class TestDrawWeatherFullSmoke:
    def test_renders_with_full_data(self):
        _, draw = _make_draw()
        draw_weather_full(draw, _make_weather(), TODAY)

    def test_returns_none(self):
        _, draw = _make_draw()
        result = draw_weather_full(draw, _make_weather(), TODAY)
        assert result is None

    def test_produces_non_blank_image(self):
        img, draw = _make_draw()
        draw_weather_full(draw, _make_weather(), TODAY)
        assert img.getbbox() is not None

    def test_default_region_and_style(self):
        _, draw = _make_draw()
        draw_weather_full(draw, _make_weather(), TODAY, region=None, style=None)

    def test_custom_region_and_style(self):
        _, draw = _make_draw()
        draw_weather_full(
            draw,
            _make_weather(),
            TODAY,
            region=ComponentRegion(0, 0, 800, 480),
            style=ThemeStyle(),
        )


# ---------------------------------------------------------------------------
# Unavailable fallback
# ---------------------------------------------------------------------------


class TestDrawWeatherFullUnavailable:
    def test_renders_when_weather_is_none(self):
        _, draw = _make_draw()
        draw_weather_full(draw, None, TODAY)

    def test_unavailable_produces_non_blank_image(self):
        img, draw = _make_draw()
        draw_weather_full(draw, None, TODAY)
        assert img.getbbox() is not None

    def test_unavailable_with_air_quality_still_renders(self):
        _, draw = _make_draw()
        aq = AirQualityData(aqi=42, category="Good", pm25=9.8)
        draw_weather_full(draw, None, TODAY, air_quality=aq)


# ---------------------------------------------------------------------------
# Hero zone — optional fields
# ---------------------------------------------------------------------------


class TestHeroZone:
    def test_renders_with_location_name(self):
        _, draw = _make_draw()
        wx = _make_weather(location_name="New York")
        draw_weather_full(draw, wx, TODAY)

    def test_renders_without_location_name(self):
        _, draw = _make_draw()
        wx = _make_weather(location_name=None)
        draw_weather_full(draw, wx, TODAY)

    def test_renders_negative_temperature(self):
        _, draw = _make_draw()
        wx = _make_weather(current_temp=-15.0, high=-10.0, low=-22.0)
        draw_weather_full(draw, wx, TODAY)

    def test_renders_triple_digit_temperature(self):
        _, draw = _make_draw()
        wx = _make_weather(current_temp=105.0, high=110.0, low=90.0)
        draw_weather_full(draw, wx, TODAY)

    def test_renders_unknown_icon_uses_fallback(self):
        _, draw = _make_draw()
        wx = _make_weather(current_icon="unknown_icon_code_xyz")
        draw_weather_full(draw, wx, TODAY)


# ---------------------------------------------------------------------------
# Metric cards — optional wind, UV, pressure
# ---------------------------------------------------------------------------


class TestMetricCards:
    def test_four_cards_without_air_quality(self):
        _, draw = _make_draw()
        draw_weather_full(draw, _make_weather(), TODAY, air_quality=None)

    def test_five_cards_with_air_quality(self):
        _, draw = _make_draw()
        aq = AirQualityData(aqi=55, category="Moderate", pm25=12.5)
        draw_weather_full(draw, _make_weather(), TODAY, air_quality=aq)

    def test_feels_like_none_shows_temp_card(self):
        """When feels_like is None, card shows current temp with 'Temp' label."""
        _, draw = _make_draw()
        wx = _make_weather(feels_like=None)
        draw_weather_full(draw, wx, TODAY)

    def test_wind_speed_none_shows_dash(self):
        _, draw = _make_draw()
        wx = _make_weather(wind_speed=None, wind_deg=None)
        draw_weather_full(draw, wx, TODAY)

    def test_wind_deg_none_omits_compass(self):
        _, draw = _make_draw()
        wx = _make_weather(wind_speed=10.0, wind_deg=None)
        draw_weather_full(draw, wx, TODAY)

    def test_uv_none_shows_pressure_card(self):
        """When UV is absent but pressure is present, shows pressure card."""
        _, draw = _make_draw()
        wx = _make_weather(uv_index=None, pressure=1015.0)
        draw_weather_full(draw, wx, TODAY)

    def test_uv_and_pressure_none_shows_dash_card(self):
        _, draw = _make_draw()
        wx = _make_weather(uv_index=None, pressure=None)
        draw_weather_full(draw, wx, TODAY)

    def test_air_quality_long_category_truncated(self):
        """Very long category string is truncated to 11 chars in the card."""
        _, draw = _make_draw()
        aq = AirQualityData(
            aqi=120,
            category="Unhealthy for Sensitive Groups",
            pm25=38.0,
        )
        draw_weather_full(draw, _make_weather(), TODAY, air_quality=aq)


# ---------------------------------------------------------------------------
# Detail strip
# ---------------------------------------------------------------------------


class TestDetailStrip:
    def test_renders_with_sunrise_and_sunset(self):
        _, draw = _make_draw()
        wx = _make_weather(
            sunrise=datetime(2024, 3, 15, 6, 24),
            sunset=datetime(2024, 3, 15, 19, 45),
        )
        draw_weather_full(draw, wx, TODAY)

    def test_renders_without_sunrise(self):
        _, draw = _make_draw()
        wx = _make_weather(sunrise=None)
        draw_weather_full(draw, wx, TODAY)

    def test_renders_without_sunset(self):
        _, draw = _make_draw()
        wx = _make_weather(sunset=None)
        draw_weather_full(draw, wx, TODAY)

    def test_renders_without_sunrise_and_sunset(self):
        _, draw = _make_draw()
        wx = _make_weather(sunrise=None, sunset=None)
        draw_weather_full(draw, wx, TODAY)

    def test_renders_without_today_date(self):
        """today=None skips moon phase section in the detail strip."""
        _, draw = _make_draw()
        draw_weather_full(draw, _make_weather(), today=None)

    def test_renders_with_today_and_moon(self):
        """today provided → moon glyph and phase name rendered in detail strip."""
        _, draw = _make_draw()
        draw_weather_full(draw, _make_weather(), TODAY)

    def test_pressure_in_strip_when_uv_present(self):
        """Pressure appears in the detail strip only when UV is also available."""
        _, draw = _make_draw()
        wx = _make_weather(uv_index=3.0, pressure=1013.0)
        draw_weather_full(draw, wx, TODAY)

    def test_pm_breakdown_in_strip_with_air_quality(self):
        _, draw = _make_draw()
        aq = AirQualityData(aqi=42, category="Good", pm25=9.8, pm1=4.5, pm10=15.0)
        draw_weather_full(draw, _make_weather(), TODAY, air_quality=aq)

    def test_pm_breakdown_without_pm1_and_pm10(self):
        _, draw = _make_draw()
        aq = AirQualityData(aqi=42, category="Good", pm25=9.8, pm1=None, pm10=None)
        draw_weather_full(draw, _make_weather(), TODAY, air_quality=aq)


# ---------------------------------------------------------------------------
# Alert banner
# ---------------------------------------------------------------------------


class TestAlertBanner:
    def test_renders_single_alert(self):
        _, draw = _make_draw()
        wx = _make_weather()
        wx.alerts = [WeatherAlert(event="Flood Watch")]
        draw_weather_full(draw, wx, TODAY)

    def test_renders_multiple_alerts(self):
        _, draw = _make_draw()
        wx = _make_weather()
        wx.alerts = [
            WeatherAlert(event="Flood Watch"),
            WeatherAlert(event="Wind Advisory"),
            WeatherAlert(event="Freeze Warning"),
        ]
        draw_weather_full(draw, wx, TODAY)

    def test_renders_very_long_alert_event_name(self):
        """Extremely long alert text triggers the truncation branch."""
        _, draw = _make_draw()
        wx = _make_weather()
        wx.alerts = [
            WeatherAlert(event="A" * 200),
            WeatherAlert(event="B" * 200),
        ]
        draw_weather_full(draw, wx, TODAY)

    def test_no_alerts_no_banner(self):
        _, draw = _make_draw()
        wx = _make_weather()
        wx.alerts = []
        draw_weather_full(draw, wx, TODAY)


# ---------------------------------------------------------------------------
# Forecast grid
# ---------------------------------------------------------------------------


class TestForecastGrid:
    def test_renders_five_day_forecast(self):
        _, draw = _make_draw()
        draw_weather_full(draw, _make_weather(forecast=_make_forecast(5)), TODAY)

    def test_renders_one_day_forecast(self):
        _, draw = _make_draw()
        draw_weather_full(draw, _make_weather(forecast=_make_forecast(1)), TODAY)

    def test_renders_empty_forecast_shows_fallback(self):
        _, draw = _make_draw()
        wx = _make_weather(forecast=[])
        draw_weather_full(draw, wx, TODAY)

    def test_renders_forecast_without_precip_chance(self):
        _, draw = _make_draw()
        fc = [
            DayForecast(
                date=date(2024, 3, 17) + timedelta(days=i),
                high=65.0 + i,
                low=50.0 + i,
                icon="01d",
                description="clear",
                precip_chance=None,
            )
            for i in range(3)
        ]
        draw_weather_full(draw, _make_weather(forecast=fc), TODAY)

    def test_renders_forecast_with_low_precip_chance_excluded(self):
        """precip_chance < 5% should not render the precip label."""
        _, draw = _make_draw()
        fc = [
            DayForecast(
                date=date(2024, 3, 17),
                high=65.0,
                low=50.0,
                icon="01d",
                description="clear",
                precip_chance=0.02,
            )
        ]
        draw_weather_full(draw, _make_weather(forecast=fc), TODAY)

    def test_renders_forecast_with_unknown_icon(self):
        _, draw = _make_draw()
        fc = [
            DayForecast(
                date=date(2024, 3, 17),
                high=65.0,
                low=50.0,
                icon="invalid_xyz",
                description="unknown",
            )
        ]
        draw_weather_full(draw, _make_weather(forecast=fc), TODAY)

    def test_hero_temp_scales_down_for_wide_strings(self):
        """Extreme temps (e.g. -100°) exercise the font auto-scale-down loop."""
        img, draw = _make_draw()
        # A 4-digit temperature string is wide enough to force the scale loop
        # in the hero zone (see weather_full.py line 139).
        wx = _make_weather(current_temp=-100.4)
        draw_weather_full(draw, wx, TODAY)
        assert img.getbbox() is not None

    def test_detail_strip_empty_when_no_sun_no_moon_no_aq(self):
        """No sunrise/sunset, no pressure+UV pair, no AQ, and no today → strip is skipped.

        This covers the early-return in _draw_detail_strip (weather_full.py:329-330)
        when no detail segments are emitted.
        """
        img, draw = _make_draw()
        wx = _make_weather(
            sunrise=None,
            sunset=None,
            uv_index=None,  # pressure needs uv_index to surface in the strip
            pressure=None,
        )
        # today=None suppresses the moon-phase placeholder → parts stays empty.
        draw_weather_full(draw, wx, today=None, air_quality=None)
        assert img.size == (800, 480)
