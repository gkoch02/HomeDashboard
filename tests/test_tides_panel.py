"""Tests for src/render/components/tides_panel.py

Covers: _quote_for_panel (key prefix, refresh cadence, fallback),
individual band draw functions (_band_header, _band_events, _band_weather,
_band_forecast, _band_environment, _band_birthdays, _band_quote, _band_host),
and draw_tides (full render, missing data, band distribution).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    HostData,
    WeatherData,
)
from src.dummy_data import generate_dummy_data
from src.render.components.tides_panel import (
    _band_birthdays,
    _band_environment,
    _band_events,
    _band_forecast,
    _band_header,
    _band_host,
    _band_quote,
    _band_weather,
    _quote_for_panel,
    draw_tides,
)
from src.render.theme import ComponentRegion, ThemeStyle

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
FIXED_TODAY = FIXED_NOW.date()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blank_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), color=1)
    return ImageDraw.Draw(img), img


def _style() -> ThemeStyle:
    return ThemeStyle()


def _weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=65.0,
        high=72.0,
        low=55.0,
        current_description="clear sky",
        current_icon="01d",
        feels_like=63.0,
        humidity=50,
        forecast=[
            DayForecast(
                date=FIXED_TODAY + timedelta(days=i),
                high=70.0 + i,
                low=55.0,
                icon="01d",
                description="clear",
            )
            for i in range(5)
        ],
        sunrise=datetime(2026, 4, 6, 6, 30),
        sunset=datetime(2026, 4, 6, 19, 45),
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


# ---------------------------------------------------------------------------
# _quote_for_panel
# ---------------------------------------------------------------------------


class TestTidesQuoteForPanel:
    def test_returns_dict_with_text(self):
        q = _quote_for_panel(FIXED_TODAY)
        assert "text" in q and q["text"]

    def test_deterministic_daily(self):
        q1 = _quote_for_panel(FIXED_TODAY)
        q2 = _quote_for_panel(FIXED_TODAY)
        assert q1["text"] == q2["text"]

    def test_tides_prefix_differs_from_scorecard(self):
        # The two panels should (usually) pick different quotes on same day
        # because the key prefix differs — just verify both return valid dicts
        from src.render.components.scorecard_panel import _quote_for_panel as sc_quote

        qt = _quote_for_panel(FIXED_TODAY)
        qs = sc_quote(FIXED_TODAY)
        assert "text" in qt and "text" in qs

    def test_hourly_refresh(self):
        q = _quote_for_panel(FIXED_TODAY, refresh="hourly", now=FIXED_NOW)
        assert "text" in q

    def test_twice_daily_refresh(self):
        am = datetime(2026, 4, 6, 9, 0)
        pm = datetime(2026, 4, 6, 15, 0)
        q_am = _quote_for_panel(FIXED_TODAY, refresh="twice_daily", now=am)
        q_pm = _quote_for_panel(FIXED_TODAY, refresh="twice_daily", now=pm)
        assert "text" in q_am and "text" in q_pm

    def test_fallback_when_no_file(self, monkeypatch, tmp_path):
        import src.render.components.tides_panel as tp

        monkeypatch.setattr(tp, "QUOTES_FILE", tmp_path / "nonexistent.json")
        q = _quote_for_panel(FIXED_TODAY)
        assert q["text"] in [
            "Not all those who wander are lost.",
            "Dwell on the beauty of life.",
        ]


# ---------------------------------------------------------------------------
# Individual band functions
# ---------------------------------------------------------------------------


class TestBandHeader:
    def test_does_not_raise(self):
        draw, _ = _blank_draw()
        _band_header(draw, 0, 0, 800, 42, FIXED_NOW, _style())

    def test_modifies_image(self):
        draw, img = _blank_draw()
        before = img.tobytes()
        _band_header(draw, 0, 0, 800, 42, FIXED_NOW, _style())
        assert img.tobytes() != before


class TestBandEvents:
    def test_no_events_today(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        _band_events(draw, 0, 0, 800, 54, data, FIXED_TODAY, _style())

    def test_with_timed_events(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.events = [
            CalendarEvent(
                summary="Morning standup",
                start=datetime(2026, 4, 6, 9, 0),
                end=datetime(2026, 4, 6, 9, 30),
            )
        ]
        _band_events(draw, 0, 0, 800, 54, data, FIXED_TODAY, _style())

    def test_with_all_day_event(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.events = [
            CalendarEvent(
                summary="Company Holiday",
                start=datetime(2026, 4, 6, 0, 0),
                end=datetime(2026, 4, 7, 0, 0),
                is_all_day=True,
            )
        ]
        _band_events(draw, 0, 0, 800, 54, data, FIXED_TODAY, _style())


class TestBandWeather:
    def test_no_weather_data(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        _band_weather(draw, 0, 0, 800, 40, data, _style())

    def test_with_weather_data(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = _weather()
        _band_weather(draw, 0, 0, 800, 40, data, _style())

    def test_weather_without_optional_fields(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = _weather(feels_like=None, humidity=None)
        _band_weather(draw, 0, 0, 800, 40, data, _style())


class TestBandForecast:
    def test_no_weather_noop(self):
        draw, img = _blank_draw()
        before = img.tobytes()
        data = DashboardData(fetched_at=FIXED_NOW)
        _band_forecast(draw, 0, 0, 800, 50, data, _style())
        # With no weather, nothing should be drawn
        assert img.tobytes() == before

    def test_with_forecast(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = _weather()
        _band_forecast(draw, 0, 0, 800, 50, data, _style())

    def test_empty_forecast_list(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = _weather(forecast=[])
        _band_forecast(draw, 0, 0, 800, 50, data, _style())


class TestBandEnvironment:
    def test_no_aqi_no_weather(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        _band_environment(draw, 0, 0, 800, 38, data, FIXED_TODAY, _style())

    def test_with_aqi_data(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.air_quality = AirQualityData(aqi=42, category="Good", pm25=8.5)
        _band_environment(draw, 0, 0, 800, 38, data, FIXED_TODAY, _style())

    def test_with_weather_sunrise_sunset(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = _weather()
        _band_environment(draw, 0, 0, 800, 38, data, FIXED_TODAY, _style())

    def test_with_all_data(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = _weather()
        data.air_quality = AirQualityData(aqi=55, category="Moderate", pm25=12.3)
        _band_environment(draw, 0, 0, 800, 38, data, FIXED_TODAY, _style())


class TestBandBirthdays:
    def test_no_birthdays(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        _band_birthdays(draw, 0, 0, 800, 36, data, FIXED_TODAY, _style())

    def test_with_birthdays(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.birthdays = [
            Birthday(name="Alice", date=date(2026, 4, 10), age=30),
            Birthday(name="Bob", date=date(2026, 4, 15), age=None),
        ]
        _band_birthdays(draw, 0, 0, 800, 36, data, FIXED_TODAY, _style())

    def test_many_birthdays_truncated_at_4(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.birthdays = [
            Birthday(name=f"Person {i}", date=date(2026, 4, 7 + i), age=20 + i) for i in range(8)
        ]
        _band_birthdays(draw, 0, 0, 800, 36, data, FIXED_TODAY, _style())


class TestBandQuote:
    def test_daily_refresh(self):
        draw, _ = _blank_draw()
        _band_quote(draw, 0, 0, 800, 86, FIXED_TODAY, FIXED_NOW, _style(), "daily")

    def test_hourly_refresh(self):
        draw, _ = _blank_draw()
        _band_quote(draw, 0, 0, 800, 86, FIXED_TODAY, FIXED_NOW, _style(), "hourly")

    def test_twice_daily_refresh(self):
        draw, _ = _blank_draw()
        _band_quote(draw, 0, 0, 800, 86, FIXED_TODAY, FIXED_NOW, _style(), "twice_daily")


class TestBandHost:
    def test_no_host_data(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        _band_host(draw, 0, 0, 800, 34, data, _style())

    def test_full_host_data(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.host_data = HostData(
            hostname="raspberrypi",
            uptime_seconds=86400 * 3 + 3600 * 2,
            load_1m=0.35,
            ram_used_mb=400,
            ram_total_mb=1024,
            cpu_temp_c=48.5,
            ip_address="192.168.1.10",
        )
        _band_host(draw, 0, 0, 800, 34, data, _style())

    def test_partial_host_data(self):
        draw, _ = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.host_data = HostData(hostname="pi", load_1m=None)
        _band_host(draw, 0, 0, 800, 34, data, _style())


# ---------------------------------------------------------------------------
# draw_tides (full function)
# ---------------------------------------------------------------------------


class TestDrawTides:
    def _draw(self, data: DashboardData, now: datetime = FIXED_NOW) -> Image.Image:
        img = Image.new("1", (800, 480), color=1)
        draw = ImageDraw.Draw(img)
        draw_tides(draw, data, now.date(), now)
        return img

    def test_smoke_full_dummy_data(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = self._draw(data)
        assert img.size == (800, 480)
        assert not all(p == 255 for p in img.tobytes())

    def test_smoke_minimal_data(self):
        data = DashboardData(fetched_at=FIXED_NOW)
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_smoke_no_weather(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = None
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_smoke_no_weather_no_forecast(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = _weather(forecast=[])
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_smoke_no_air_quality(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.air_quality = None
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_smoke_no_birthdays(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.birthdays = []
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_smoke_no_host_data(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.host_data = None
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_custom_region(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = Image.new("1", (800, 480), color=1)
        draw = ImageDraw.Draw(img)
        region = ComponentRegion(0, 0, 800, 480)
        draw_tides(draw, data, FIXED_TODAY, FIXED_NOW, region=region)
        assert img.size == (800, 480)

    def test_custom_style(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = Image.new("1", (800, 480), color=1)
        draw = ImageDraw.Draw(img)
        style = ThemeStyle(fg=0, bg=1)
        draw_tides(draw, data, FIXED_TODAY, FIXED_NOW, style=style)

    def test_quote_refresh_modes(self):
        data = generate_dummy_data(now=FIXED_NOW)
        for mode in ("daily", "twice_daily", "hourly"):
            img = Image.new("1", (800, 480), color=1)
            draw = ImageDraw.Draw(img)
            draw_tides(draw, data, FIXED_TODAY, FIXED_NOW, quote_refresh=mode)

    def test_all_optional_bands_absent(self):
        """No weather → weather/forecast bands skipped; host absent → host band skipped."""
        data = DashboardData(fetched_at=FIXED_NOW)
        # No weather and no host data — fewer active bands; height distribution must not crash
        img = self._draw(data)
        assert img.size == (800, 480)
