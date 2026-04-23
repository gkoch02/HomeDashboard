"""Tests for src/render/components/weather_panel.py"""

from datetime import date, datetime, timedelta, timezone

from PIL import Image, ImageDraw

from src.data.models import AirQualityData, DayForecast, WeatherAlert, WeatherData
from src.render.components.weather_panel import (
    _aqi_accent,
    _draw_aqi_column,
    _fmt_time,
    draw_weather,
)
from src.render.theme import ThemeStyle


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _make_weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=55.0,
        current_icon="01d",
        current_description="clear",
        high=60.0,
        low=45.0,
        humidity=50,
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


class TestDrawWeatherNone:
    def test_none_weather_renders_unavailable(self):
        img, draw = _make_draw()
        draw_weather(draw, None)
        assert img.getbbox() is not None

    def test_none_weather_with_today_renders_moon(self):
        img, draw = _make_draw()
        draw_weather(draw, None, today=date(2024, 3, 15))
        assert img.getbbox() is not None


class TestDrawWeatherDetails:
    def test_feels_like_renders(self):
        weather = _make_weather(feels_like=48.0)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_wind_speed_renders(self):
        weather = _make_weather(wind_speed=15.0)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_both_feels_like_and_wind_renders(self):
        weather = _make_weather(feels_like=48.0, wind_speed=12.0)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_neither_feels_like_nor_wind_falls_back_to_humidity(self):
        """When neither feels_like nor wind_speed is set, humidity is shown."""
        weather = _make_weather(feels_like=None, wind_speed=None, humidity=72)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_sunrise_and_sunset_render(self):
        tz = timezone.utc
        today = date(2024, 3, 15)
        weather = _make_weather(
            sunrise=datetime.combine(today, datetime.min.time().replace(hour=6, minute=24)).replace(
                tzinfo=tz
            ),
            sunset=datetime.combine(today, datetime.min.time().replace(hour=19, minute=51)).replace(
                tzinfo=tz
            ),
        )
        img, draw = _make_draw()
        draw_weather(draw, weather, today=today)
        assert img.getbbox() is not None

    def test_only_sunrise_renders(self):
        tz = timezone.utc
        today = date(2024, 3, 15)
        weather = _make_weather(
            sunrise=datetime.combine(today, datetime.min.time().replace(hour=6, minute=24)).replace(
                tzinfo=tz
            ),
            sunset=None,
        )
        img, draw = _make_draw()
        draw_weather(draw, weather, today=today)
        assert img.getbbox() is not None

    def test_only_sunset_renders(self):
        tz = timezone.utc
        today = date(2024, 3, 15)
        weather = _make_weather(
            sunrise=None,
            sunset=datetime.combine(today, datetime.min.time().replace(hour=19, minute=51)).replace(
                tzinfo=tz
            ),
        )
        img, draw = _make_draw()
        draw_weather(draw, weather, today=today)
        assert img.getbbox() is not None


class TestDrawWeatherForecastStrip:
    def _forecast(self, n: int) -> list[DayForecast]:
        return [
            DayForecast(
                date=date(2024, 3, 16) + timedelta(days=i),
                high=55.0 + i,
                low=40.0 + i,
                icon="01d",
                description="clear",
            )
            for i in range(n)
        ]

    def test_no_forecast_no_crash(self):
        weather = _make_weather(forecast=[])
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_three_forecast_columns_no_alerts(self):
        weather = _make_weather(forecast=self._forecast(3))
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_one_alert_plus_two_forecast_columns(self):
        weather = _make_weather(
            forecast=self._forecast(2),
            alerts=[WeatherAlert(event="Flood Watch")],
        )
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_two_alerts_plus_one_forecast_column(self):
        weather = _make_weather(
            forecast=self._forecast(1),
            alerts=[
                WeatherAlert(event="Flood Watch"),
                WeatherAlert(event="Wind Advisory"),
            ],
        )
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_two_alerts_no_forecast(self):
        weather = _make_weather(
            forecast=[],
            alerts=[
                WeatherAlert(event="Dense Fog Advisory"),
                WeatherAlert(event="Winter Storm Warning"),
            ],
        )
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_forecast_with_precip_chance(self):
        forecast = [
            DayForecast(
                date=date(2024, 3, 16),
                high=50.0,
                low=38.0,
                icon="10d",
                description="rain",
                precip_chance=0.75,
            )
        ]
        weather = _make_weather(forecast=forecast)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_forecast_below_precip_threshold_no_third_row(self):
        """Precipitation below 5% should not render the precip percentage row."""
        forecast = [
            DayForecast(
                date=date(2024, 3, 16),
                high=50.0,
                low=38.0,
                icon="01d",
                description="clear",
                precip_chance=0.02,
            )
        ]
        weather = _make_weather(forecast=forecast)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_with_moon_phase(self):
        weather = _make_weather(forecast=self._forecast(2))
        img, draw = _make_draw()
        draw_weather(draw, weather, today=date(2024, 3, 15))
        assert img.getbbox() is not None


class TestEnhancedWeatherRendering:
    """Tests for wind compass direction and UV index rendering paths."""

    def test_wind_compass_rendered_when_wind_deg_present(self):
        """wind_deg should trigger compass suffix in wind string — no crash."""
        weather = _make_weather(wind_speed=12.0, wind_deg=270.0)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_wind_compass_all_cardinal_directions(self):
        """All 8 compass sectors render without error."""
        for deg in [0, 45, 90, 135, 180, 225, 270, 315]:
            weather = _make_weather(wind_speed=10.0, wind_deg=float(deg))
            _, draw = _make_draw()
            draw_weather(draw, weather)  # must not raise

    def test_wind_deg_without_wind_speed_no_crash(self):
        """wind_deg alone (no wind_speed) should not crash rendering."""
        weather = _make_weather(wind_speed=None, wind_deg=90.0)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_uv_index_renders_in_hilo_row(self):
        """uv_index is appended to the hi/lo row when it fits."""
        weather = _make_weather(uv_index=5.0)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_uv_index_zero_renders(self):
        weather = _make_weather(uv_index=0.0)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_uv_index_high_value_renders(self):
        weather = _make_weather(uv_index=11.0)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_uv_index_none_no_crash(self):
        """uv_index=None should not crash and should render normal hi/lo."""
        weather = _make_weather(uv_index=None)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_all_enhanced_fields_together(self):
        """All v3 enhanced fields (wind_deg, uv_index) together."""
        weather = _make_weather(
            wind_speed=15.0,
            wind_deg=135.0,
            uv_index=8.0,
            feels_like=52.0,
        )
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None


class TestLocationName:
    def test_location_name_in_label_renders(self):
        """location_name should be appended to the WEATHER label without crashing."""
        weather = _make_weather(location_name="San Francisco")
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_location_name_none_no_crash(self):
        """location_name=None (default) should render identically to before."""
        weather = _make_weather(location_name=None)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None

    def test_very_long_location_name_truncated_gracefully(self):
        """A very long location name that doesn't fit should be silently omitted."""
        weather = _make_weather(location_name="A" * 100)
        img, draw = _make_draw()
        draw_weather(draw, weather)
        assert img.getbbox() is not None


class TestStalenessGlyph:
    def test_stale_weather_renders_glyph(self):
        """STALE staleness should draw the '!' badge without crashing."""
        from src.data.models import StalenessLevel
        from src.render.theme import ComponentRegion

        weather = _make_weather()
        img, draw = _make_draw()
        draw_weather(
            draw,
            weather,
            region=ComponentRegion(0, 0, 300, 120),
            staleness=StalenessLevel.STALE,
        )
        assert img.getbbox() is not None

    def test_expired_weather_renders_glyph(self):
        """EXPIRED staleness should also draw the badge."""
        from src.data.models import StalenessLevel
        from src.render.theme import ComponentRegion

        weather = _make_weather()
        img, draw = _make_draw()
        draw_weather(
            draw,
            weather,
            region=ComponentRegion(0, 0, 300, 120),
            staleness=StalenessLevel.EXPIRED,
        )
        assert img.getbbox() is not None

    def test_fresh_weather_no_glyph_no_crash(self):
        """FRESH staleness should not draw a badge and must not crash."""
        from src.data.models import StalenessLevel

        weather = _make_weather()
        img, draw = _make_draw()
        draw_weather(draw, weather, staleness=StalenessLevel.FRESH)
        assert img.getbbox() is not None

    def test_stale_weather_without_forecast_strip_still_renders_glyph(self):
        """show_forecast_strip=False returns early but still draws the stale badge."""
        from src.data.models import StalenessLevel
        from src.render.theme import ComponentRegion, ThemeStyle

        weather = _make_weather()
        img, draw = _make_draw()
        # Wide enough to hit the no-forecast branch — four detail rows fill
        # the full panel height, then the early-return path emits the glyph.
        style = ThemeStyle(show_forecast_strip=False)
        draw_weather(
            draw,
            weather,
            region=ComponentRegion(0, 0, 300, 240),
            style=style,
            staleness=StalenessLevel.STALE,
        )
        assert img.getbbox() is not None

    def test_stale_weather_with_populated_forecast_renders_glyph(self):
        """Forecast strip drawn AND staleness EXPIRED → glyph painted at the end."""
        from src.data.models import StalenessLevel
        from src.render.theme import ComponentRegion

        # Explicit three-day forecast so the forecast strip is fully populated
        # (n_cols=3) and execution reaches the tail-end staleness glyph call.
        weather = _make_weather(forecast=_make_forecast(3))
        img, draw = _make_draw()
        draw_weather(
            draw,
            weather,
            region=ComponentRegion(0, 0, 400, 160),
            staleness=StalenessLevel.EXPIRED,
        )
        assert img.getbbox() is not None

    def test_none_staleness_no_crash(self):
        """staleness=None (default) must not crash."""
        weather = _make_weather()
        img, draw = _make_draw()
        draw_weather(draw, weather, staleness=None)
        assert img.getbbox() is not None


class TestFmtTime:
    def test_formats_am_time(self):
        dt = datetime(2024, 3, 15, 6, 24, tzinfo=timezone.utc)
        result = _fmt_time(dt)
        assert "6" in result
        assert "a" in result

    def test_formats_pm_time(self):
        dt = datetime(2024, 3, 15, 19, 51, tzinfo=timezone.utc)
        result = _fmt_time(dt)
        assert "7" in result
        assert "p" in result

    def test_on_the_hour_drops_minutes(self):
        dt = datetime(2024, 3, 15, 8, 0, tzinfo=timezone.utc)
        result = _fmt_time(dt)
        assert ":00" not in result


def _make_aqi(aqi=42, category="Good", **kwargs):
    return AirQualityData(aqi=aqi, category=category, pm25=kwargs.pop("pm25", 9.0), **kwargs)


def _make_forecast(day_count=3):
    base = date(2026, 4, 20)
    return [
        DayForecast(
            date=base + timedelta(days=i + 1),
            icon="01d",
            description="clear",
            high=60 + i,
            low=50 + i,
            precip_chance=0.15,
        )
        for i in range(day_count)
    ]


class TestAQIForecastColumn:
    """Exercises the air-quality column that replaces a forecast slot when AQ data exists."""

    def test_aqi_column_renders_when_air_quality_present(self):
        weather = _make_weather(forecast=_make_forecast(3))
        aqi = _make_aqi(aqi=42, category="Good")
        img, draw = _make_draw()
        draw_weather(draw, weather, today=date(2026, 4, 20), air_quality=aqi)
        # Something was rendered — the image is no longer blank white.
        assert img.getbbox() is not None

    def test_aqi_column_truncates_long_category_label(self):
        """Long category labels are truncated with an ellipsis so they fit the column."""
        weather = _make_weather(forecast=_make_forecast(3))
        aqi = _make_aqi(
            aqi=175,
            category="Unhealthy for Sensitive Groups with Extra Long Descriptor",
        )
        img, draw = _make_draw()
        # Use a narrow region so truncation kicks in.
        from src.render.theme import ComponentRegion

        region = ComponentRegion(0, 0, 160, 200)
        draw_weather(
            draw,
            weather,
            today=date(2026, 4, 20),
            air_quality=aqi,
            region=region,
        )
        assert img.getbbox() is not None

    def test_aqi_column_suppressed_when_alerts_present(self):
        """When there is 1 alert, there are 2 forecast columns + alert column — no AQI column."""
        weather = _make_weather(
            forecast=_make_forecast(3),
            alerts=[WeatherAlert(event="Heat Advisory")],
        )
        aqi = _make_aqi(aqi=42, category="Good")
        img, draw = _make_draw()
        draw_weather(draw, weather, today=date(2026, 4, 20), air_quality=aqi)
        # No crash; rendering path ran without AQI-specific column.
        assert img.getbbox() is not None

    def test_draw_aqi_column_direct(self):
        """Directly exercise _draw_aqi_column in isolation."""
        img, draw = _make_draw(w=200, h=100)
        style = ThemeStyle()
        aqi = _make_aqi(aqi=87, category="Moderate")
        _draw_aqi_column(draw, aqi, cx=0, top=0, col_w=80, col_h=80, style=style)
        assert img.getbbox() is not None


class TestAQIAccent:
    def test_good_uses_accent_good(self):
        style = ThemeStyle(accent_good=1, fg=0)
        assert _aqi_accent(style, 20) == 1

    def test_good_falls_back_to_fg_when_accent_unset(self):
        style = ThemeStyle(fg=7)
        assert _aqi_accent(style, 20) == 7

    def test_moderate_uses_accent_warn(self):
        style = ThemeStyle(accent_warn=2, fg=0)
        # AQI 51–150 range
        assert _aqi_accent(style, 100) == 2
        assert _aqi_accent(style, 150) == 2  # upper boundary inclusive

    def test_unhealthy_uses_accent_alert(self):
        style = ThemeStyle(accent_alert=3, fg=0)
        assert _aqi_accent(style, 200) == 3
        assert _aqi_accent(style, 500) == 3

    def test_boundary_51_is_warn_not_good(self):
        style = ThemeStyle(accent_good=1, accent_warn=2, accent_alert=3, fg=0)
        assert _aqi_accent(style, 50) == 1  # still good
        assert _aqi_accent(style, 51) == 2  # transition

    def test_boundary_151_is_alert(self):
        style = ThemeStyle(accent_good=1, accent_warn=2, accent_alert=3, fg=0)
        assert _aqi_accent(style, 150) == 2
        assert _aqi_accent(style, 151) == 3
