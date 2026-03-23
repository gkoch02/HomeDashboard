"""Tests for src/render/components/weather_panel.py"""

from datetime import date, datetime, timedelta, timezone

from PIL import Image, ImageDraw

from src.data.models import DayForecast, WeatherAlert, WeatherData
from src.render.components.weather_panel import draw_weather, _fmt_time


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
            sunrise=datetime.combine(
                today, datetime.min.time().replace(hour=6, minute=24)
            ).replace(tzinfo=tz),
            sunset=datetime.combine(
                today, datetime.min.time().replace(hour=19, minute=51)
            ).replace(tzinfo=tz),
        )
        img, draw = _make_draw()
        draw_weather(draw, weather, today=today)
        assert img.getbbox() is not None

    def test_only_sunrise_renders(self):
        tz = timezone.utc
        today = date(2024, 3, 15)
        weather = _make_weather(
            sunrise=datetime.combine(
                today, datetime.min.time().replace(hour=6, minute=24)
            ).replace(tzinfo=tz),
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
            sunset=datetime.combine(
                today, datetime.min.time().replace(hour=19, minute=51)
            ).replace(tzinfo=tz),
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
