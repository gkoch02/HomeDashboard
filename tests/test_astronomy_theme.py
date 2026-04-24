"""Tests for the astronomy theme and astronomy_panel component."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import DashboardData, WeatherData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.astronomy_panel import (
    _fmt_delta_seconds,
    _fmt_duration,
    _fmt_time,
    _next_phase_date,
    draw_astronomy,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

NYC_LAT = 40.7128
NYC_LON = -74.0060
TZ = ZoneInfo("America/New_York")
FIXED_NOW = datetime(2026, 4, 23, 12, 0, tzinfo=TZ)
TODAY = FIXED_NOW.date()


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _render(**kwargs):
    data = generate_dummy_data(tz=TZ, now=FIXED_NOW)
    theme = load_theme("astronomy")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestAstronomyRegistration:
    def test_in_available_themes(self):
        assert "astronomy" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("astronomy")
        assert t.name == "astronomy"

    def test_astronomy_region_visible(self):
        t = load_theme("astronomy")
        assert t.layout.astronomy.visible is True


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


class TestFormatHelpers:
    def test_fmt_time_none(self):
        assert _fmt_time(None, TZ) == "—"

    def test_fmt_time_formats_am_pm_shortened(self):
        dt = datetime(2026, 4, 23, 6, 5, tzinfo=TZ)
        assert _fmt_time(dt, TZ) == "6:05a"

    def test_fmt_duration_none(self):
        from datetime import timedelta

        assert _fmt_duration(None) == "—"
        assert _fmt_duration(timedelta(hours=13, minutes=38)) == "13h 38m"

    def test_fmt_delta_seconds_positive(self):
        from datetime import timedelta

        assert _fmt_delta_seconds(timedelta(minutes=2, seconds=28)).startswith("+2m")

    def test_fmt_delta_seconds_negative(self):
        from datetime import timedelta

        s = _fmt_delta_seconds(-timedelta(minutes=2, seconds=28))
        assert s.startswith("-2m")

    def test_fmt_delta_none(self):
        assert _fmt_delta_seconds(None) == ""


class TestNextPhaseDate:
    def test_next_full_moon_within_30_days(self):
        d = _next_phase_date(TODAY, 0.5)
        delta_days = (d - TODAY).days
        assert 0 <= delta_days <= 32

    def test_next_new_moon_within_30_days(self):
        d = _next_phase_date(TODAY, 0.0)
        delta_days = (d - TODAY).days
        assert 0 <= delta_days <= 32


# ---------------------------------------------------------------------------
# Theme rendering
# ---------------------------------------------------------------------------


class TestAstronomyRender:
    def test_renders_correct_size(self):
        img = _render(latitude=NYC_LAT, longitude=NYC_LON)
        assert img.size == (800, 480)
        assert img.mode == "1"

    def test_renders_non_blank(self):
        img = _render(latitude=NYC_LAT, longitude=NYC_LON)
        assert not all(p == 255 for p in img.tobytes())

    def test_renders_without_lat_lon(self):
        """Should still produce an image (falls back to OWM sunrise/sunset)."""
        img = _render()
        assert img.size == (800, 480)

    def test_renders_with_no_weather_and_no_coords(self):
        data = DashboardData(events=[], weather=None)
        theme = load_theme("astronomy")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)


class TestDrawAstronomyDirect:
    def test_defaults_region_and_style(self):
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_astronomy(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_with_weather_supplied_sun_times(self):
        """With weather data providing sunrise/sunset, no coords needed."""
        img, d = _make_draw()
        w = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear",
            high=70.0,
            low=50.0,
            humidity=50,
            sunrise=datetime(2026, 4, 23, 6, 5, tzinfo=TZ),
            sunset=datetime(2026, 4, 23, 19, 43, tzinfo=TZ),
        )
        data = DashboardData(events=[], weather=w)
        draw_astronomy(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_polar_day_gracefully_handled(self):
        """At very high latitudes the sun never sets — panel still renders."""
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_astronomy(
            d,
            data,
            date(2026, 6, 21),
            datetime(2026, 6, 21, 12, 0, tzinfo=TZ),
            latitude=85.0,
            longitude=0.0,
        )
        assert img.getbbox() is not None
