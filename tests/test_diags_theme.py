"""Tests for the diags theme and its render pipeline integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from PIL import Image

from src.config import DisplayConfig
from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    StalenessLevel,
    WeatherAlert,
    WeatherData,
)
from src.render.canvas import render_dashboard
from src.render.theme import AVAILABLE_THEMES, load_theme
from src.render.themes.diags import diags_theme

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _make_data(today: date | None = None) -> DashboardData:
    today = today or date(2026, 3, 24)  # Monday
    now = datetime.combine(today, datetime.min.time().replace(hour=9, minute=15))
    return DashboardData(
        fetched_at=now,
        events=[
            CalendarEvent(
                summary="Team Standup",
                start=datetime.combine(today, datetime.min.time().replace(hour=9)),
                end=datetime.combine(today, datetime.min.time().replace(hour=9, minute=30)),
            ),
            CalendarEvent(
                summary="Design review",
                start=datetime.combine(
                    today + timedelta(days=2), datetime.min.time().replace(hour=14)
                ),
                end=datetime.combine(
                    today + timedelta(days=2), datetime.min.time().replace(hour=15)
                ),
            ),
        ],
        weather=WeatherData(
            current_temp=72.0,
            current_icon="02d",
            current_description="partly cloudy",
            high=78.0,
            low=61.0,
            humidity=54,
            feels_like=69.0,
            wind_speed=12.0,
            wind_deg=315.0,
            pressure=1013.0,
            uv_index=4.0,
            sunrise=datetime.combine(today, datetime.min.time().replace(hour=6, minute=42)),
            sunset=datetime.combine(today, datetime.min.time().replace(hour=19, minute=18)),
            forecast=[
                DayForecast(
                    date=today + timedelta(days=i + 1),
                    high=70.0 + i,
                    low=55.0 + i,
                    icon="02d",
                    description="partly cloudy",
                    precip_chance=0.20,
                )
                for i in range(5)
            ],
        ),
        air_quality=AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            pm10=14.2,
            pm1=6.1,
            sensor_id=99999,
            temperature=68.4,
            humidity=52.0,
            pressure=1014.3,
        ),
        birthdays=[
            Birthday(name="Alice Smith", date=today + timedelta(days=1), age=34),
            Birthday(name="Bob Jones", date=today + timedelta(days=9)),
        ],
        source_staleness={
            "weather": StalenessLevel.FRESH,
            "events": StalenessLevel.AGING,
        },
    )


# ---------------------------------------------------------------------------
# Theme structure
# ---------------------------------------------------------------------------


class TestDiagsTheme:
    def test_name(self):
        assert diags_theme().name == "diags"

    def test_in_available_themes(self):
        assert "diags" in AVAILABLE_THEMES

    def test_load_theme(self):
        assert load_theme("diags").name == "diags"

    def test_diags_region_visible(self):
        assert diags_theme().layout.diags.visible is True

    def test_diags_region_full_canvas(self):
        layout = diags_theme().layout
        assert layout.diags.x == 0
        assert layout.diags.y == 0
        assert layout.diags.w == 800
        assert layout.diags.h == 480

    def test_standard_regions_hidden(self):
        layout = diags_theme().layout
        assert layout.header.visible is False
        assert layout.week_view.visible is False
        assert layout.weather.visible is False
        assert layout.birthdays.visible is False
        assert layout.info.visible is False

    def test_draw_order(self):
        assert diags_theme().layout.draw_order == ["diags"]

    def test_canvas_size(self):
        layout = diags_theme().layout
        assert layout.canvas_w == 800
        assert layout.canvas_h == 480

    def test_no_inversion(self):
        style = diags_theme().style
        assert style.invert_header is False
        assert style.invert_today_col is False
        assert style.invert_allday_bars is False

    def test_no_borders(self):
        assert diags_theme().style.show_borders is False


# ---------------------------------------------------------------------------
# Render smoke tests
# ---------------------------------------------------------------------------


class TestDiagsRender:
    def test_render_returns_image(self):
        result = render_dashboard(_make_data(), DisplayConfig(), theme=diags_theme())
        assert isinstance(result, Image.Image)

    def test_render_correct_size(self):
        result = render_dashboard(
            _make_data(),
            DisplayConfig(width=800, height=480),
            theme=diags_theme(),
        )
        assert result.size == (800, 480)

    def test_render_no_weather(self):
        data = _make_data()
        data.weather = None
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_no_air_quality(self):
        data = _make_data()
        data.air_quality = None
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_empty_events(self):
        data = _make_data()
        data.events = []
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_empty_birthdays(self):
        data = _make_data()
        data.birthdays = []
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_stale_data(self):
        data = _make_data()
        data.is_stale = True
        data.stale_sources = ["weather"]
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_all_sources_stale(self):
        data = _make_data()
        data.is_stale = True
        data.source_staleness = {
            "weather": StalenessLevel.STALE,
            "events": StalenessLevel.EXPIRED,
            "air_quality": StalenessLevel.AGING,
        }
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_minimal_weather(self):
        """Weather with only required fields (no optional fields)."""
        data = _make_data()
        data.weather = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear sky",
            high=65.0,
            low=50.0,
            humidity=45,
        )
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_weather_with_alerts(self):
        data = _make_data()
        data.weather.alerts = [WeatherAlert(event="Flood Watch")]
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_aq_partial_fields(self):
        """AirQualityData with only required fields (no pm1, pm10, temp, etc.)."""
        data = _make_data()
        data.air_quality = AirQualityData(aqi=55, category="Moderate", pm25=12.5)
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_aq_all_sensor_fields(self):
        """AirQualityData with all new PurpleAir sensor fields populated."""
        data = _make_data()
        data.air_quality = AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            pm10=14.2,
            pm1=6.1,
            sensor_id=12345,
            temperature=71.2,
            humidity=48.0,
            pressure=1012.5,
        )
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_many_birthdays(self):
        """Test with max birthdays to ensure no vertical overflow crash."""
        data = _make_data()
        today = data.fetched_at.date()
        data.birthdays = [
            Birthday(name=f"Person {i}", date=today + timedelta(days=i + 1), age=30 + i)
            for i in range(5)
        ]
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_via_load_theme(self):
        result = render_dashboard(_make_data(), DisplayConfig(), theme=load_theme("diags"))
        assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# AirQualityData model — new fields
# ---------------------------------------------------------------------------


class TestAirQualityDataNewFields:
    def test_new_fields_default_to_none(self):
        aq = AirQualityData(aqi=42, category="Good", pm25=9.8)
        assert aq.temperature is None
        assert aq.humidity is None
        assert aq.pressure is None

    def test_new_fields_can_be_set(self):
        aq = AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            temperature=68.4,
            humidity=52.0,
            pressure=1014.3,
        )
        assert aq.temperature == 68.4
        assert aq.humidity == 52.0
        assert aq.pressure == 1014.3


# ---------------------------------------------------------------------------
# Cache roundtrip for new AirQualityData fields
# ---------------------------------------------------------------------------


class TestAirQualityCacheRoundtrip:
    def test_roundtrip_with_new_fields(self):
        from src.fetchers.cache import _deser_air_quality, _ser_air_quality  # noqa: PLC0415

        original = AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            pm10=14.2,
            pm1=6.1,
            sensor_id=99999,
            temperature=68.4,
            humidity=52.0,
            pressure=1014.3,
        )
        serialized = _ser_air_quality(original)
        restored = _deser_air_quality(serialized)
        assert restored.temperature == pytest.approx(68.4)
        assert restored.humidity == pytest.approx(52.0)
        assert restored.pressure == pytest.approx(1014.3)

    def test_roundtrip_without_new_fields(self):
        """Old cache entries (missing new keys) deserialize without error."""
        from src.fetchers.cache import _deser_air_quality  # noqa: PLC0415

        old_dict = {"aqi": 30, "category": "Good", "pm25": 8.0}
        restored = _deser_air_quality(old_dict)
        assert restored.temperature is None
        assert restored.humidity is None
        assert restored.pressure is None

    def test_serialized_dict_includes_new_keys(self):
        from src.fetchers.cache import _ser_air_quality  # noqa: PLC0415

        aq = AirQualityData(
            aqi=42,
            category="Good",
            pm25=9.8,
            temperature=70.0,
            humidity=55.0,
            pressure=1010.0,
        )
        d = _ser_air_quality(aq)
        assert "temperature" in d
        assert "humidity" in d
        assert "pressure" in d
        assert d["temperature"] == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# Random pool exclusion
# ---------------------------------------------------------------------------


class TestDiagsPanelDefaults:
    """Call draw_diags directly to cover default region/style/today branches."""

    def _make_draw(self):
        from PIL import ImageDraw

        img = Image.new("1", (800, 480), 1)
        return img, ImageDraw.Draw(img)

    def test_default_region_and_style(self):
        """region=None and style=None trigger the default assignment branches."""
        from src.render.components.diags_panel import draw_diags

        _, draw = self._make_draw()
        draw_diags(draw, _make_data(), region=None, style=None)

    def test_today_derived_from_datetime_fetched_at(self):
        """today=None with a datetime fetched_at uses now.date()."""
        from src.render.components.diags_panel import draw_diags
        from src.render.theme import ComponentRegion, ThemeStyle

        _, draw = self._make_draw()
        data = _make_data()
        draw_diags(
            draw, data, today=None, region=ComponentRegion(0, 0, 800, 480), style=ThemeStyle()
        )

    def test_today_derived_from_date_fetched_at(self):
        """today=None with a plain date fetched_at falls back to date.today() (line 60)."""
        from datetime import date

        from src.render.components.diags_panel import draw_diags

        _, draw = self._make_draw()
        data = _make_data()
        data.fetched_at = date(2026, 3, 24)  # plain date, not datetime
        draw_diags(draw, data, today=None)

    def test_header_non_datetime_fetched_at(self):
        """fetched_at as a plain date renders header via str(now) branch (line 126)."""
        from datetime import date

        data = _make_data()
        data.fetched_at = date(2026, 3, 24)
        render_dashboard(data, DisplayConfig(), theme=diags_theme())


class TestFmtUptime:
    def test_with_days(self):
        from src.render.components.diags_panel import _fmt_uptime

        result = _fmt_uptime(90061)  # 1 day, 1 hour, 1 minute
        assert "1d" in result
        assert "1h" in result
        assert "1m" in result

    def test_without_days(self):
        from src.render.components.diags_panel import _fmt_uptime

        result = _fmt_uptime(3661)  # 1 hour, 1 minute, no days
        assert "d" not in result
        assert "1h" in result
        assert "1m" in result

    def test_zero_seconds(self):
        from src.render.components.diags_panel import _fmt_uptime

        result = _fmt_uptime(0)
        assert "0h" in result
        assert "0m" in result


class TestHostSectionFullData:
    """Render diags with a fully populated HostData to cover _host_section lines."""

    def test_render_with_all_host_fields(self):
        from src.data.models import HostData

        data = _make_data()
        data.host_data = HostData(
            hostname="pi-dashboard",
            uptime_seconds=90061.0,  # 1d 1h 1m — exercises the days branch
            load_1m=0.42,
            load_5m=0.38,
            load_15m=0.31,
            ram_total_mb=4096.0,
            ram_used_mb=1024.0,
            disk_total_gb=32.0,
            disk_used_gb=12.0,
            cpu_temp_c=42.7,
            ip_address="192.168.1.100",
        )
        render_dashboard(data, DisplayConfig(), theme=diags_theme())

    def test_render_with_none_host_data(self):
        """host_data=None renders the 'unavailable' row."""
        data = _make_data()
        data.host_data = None
        render_dashboard(data, DisplayConfig(), theme=diags_theme())


class TestDiagsNotInRandomPool:
    def test_diags_excluded_from_pool_by_default(self):
        from src.render.random_theme import eligible_themes  # noqa: PLC0415

        pool = eligible_themes(include=[], exclude=[])
        assert "diags" not in pool

    def test_diags_excluded_even_with_include(self):
        """diags is a hard exclusion (like 'random') — include list cannot override it."""
        from src.render.random_theme import eligible_themes  # noqa: PLC0415

        pool = eligible_themes(include=["diags"], exclude=[])
        assert "diags" not in pool
