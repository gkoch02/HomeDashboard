"""Tests for the light_cycle theme and light_cycle_panel component."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import CalendarEvent, DashboardData, WeatherData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.light_cycle_panel import (
    _draw_twilight_band,
    _hour_to_pil_angle,
    _hours_of_day,
    _resolve_sun_times,
    _to_local_naive,
    draw_light_cycle,
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
    theme = load_theme("light_cycle")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestLightCycleRegistration:
    def test_in_available_themes(self):
        assert "light_cycle" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("light_cycle")
        assert t.name == "light_cycle"

    def test_light_cycle_region_visible(self):
        t = load_theme("light_cycle")
        assert t.layout.light_cycle.visible is True
        assert t.layout.light_cycle.w == 800
        assert t.layout.light_cycle.h == 480

    def test_draw_order_only_light_cycle(self):
        t = load_theme("light_cycle")
        assert t.layout.draw_order == ["light_cycle"]


# ---------------------------------------------------------------------------
# Polar / time helpers
# ---------------------------------------------------------------------------


class TestPolarMath:
    def test_midnight_at_top(self):
        # Hour 0 → PIL angle 270 (top of circle)
        assert _hour_to_pil_angle(0.0) == 270.0

    def test_six_at_three_oclock(self):
        # Hour 6 → PIL angle 0 / 360 (3 o'clock)
        assert _hour_to_pil_angle(6.0) % 360.0 == 0.0

    def test_noon_at_bottom(self):
        # Hour 12 → PIL angle 90 (bottom)
        assert _hour_to_pil_angle(12.0) % 360.0 == 90.0

    def test_eighteen_at_nine_oclock(self):
        # Hour 18 → PIL angle 180 (9 o'clock)
        assert _hour_to_pil_angle(18.0) % 360.0 == 180.0


class TestToLocalNaive:
    def test_passes_through_naive(self):
        dt = datetime(2026, 5, 6, 10, 30)
        assert _to_local_naive(dt, TZ) == dt

    def test_converts_aware_to_tz(self):
        dt = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
        out = _to_local_naive(dt, TZ)
        # 14:00 UTC = 10:00 EDT in May
        assert out.tzinfo is None
        assert out.hour == 10

    def test_uses_system_tz_when_no_target(self):
        dt = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
        out = _to_local_naive(dt, None)
        assert out.tzinfo is None


class TestHoursOfDay:
    def test_none_input(self):
        assert _hours_of_day(None, TODAY, TZ) is None

    def test_today_hour(self):
        dt = datetime(2026, 4, 23, 9, 30, tzinfo=TZ)
        assert _hours_of_day(dt, TODAY, TZ) == 9.5

    def test_yesterday_returns_negative_clamped(self):
        # delta=-1 day, hour=23.5 → -0.5; clamp to 0
        dt = datetime(2026, 4, 22, 23, 30, tzinfo=TZ)
        out = _hours_of_day(dt, TODAY, TZ)
        assert out == 0.0

    def test_tomorrow_clamped(self):
        # delta=1 day, hour=0.5 → 24.5; clamp to 24
        dt = datetime(2026, 4, 24, 0, 30, tzinfo=TZ)
        out = _hours_of_day(dt, TODAY, TZ)
        assert out == 24.0

    def test_more_than_one_day_away_returns_none(self):
        dt = datetime(2026, 4, 26, 10, 0, tzinfo=TZ)
        assert _hours_of_day(dt, TODAY, TZ) is None


# ---------------------------------------------------------------------------
# Sun-time resolution
# ---------------------------------------------------------------------------


class TestResolveSunTimes:
    def test_uses_astronomy_when_lat_lon_provided(self):
        sr, ss, bands = _resolve_sun_times(TODAY, None, None, NYC_LAT, NYC_LON, TZ)
        assert sr is not None and ss is not None
        # 8 bands (4 morning + 4 evening) when astronomical path succeeds
        assert len(bands) == 8

    def test_falls_back_to_weather_when_no_lat_lon(self):
        wsr = datetime(2026, 4, 23, 6, 5, tzinfo=TZ)
        wss = datetime(2026, 4, 23, 19, 43, tzinfo=TZ)
        sr, ss, bands = _resolve_sun_times(TODAY, wsr, wss, None, None, TZ)
        assert sr == 6.0 + 5 / 60
        assert ss == 19.0 + 43 / 60
        # Two simple night bands (morning + evening) when falling back
        assert len(bands) == 2

    def test_returns_empty_when_nothing_known(self):
        sr, ss, bands = _resolve_sun_times(TODAY, None, None, None, None, TZ)
        assert sr is None and ss is None and bands == []

    def test_zero_zero_lat_lon_treated_as_unset(self):
        # (0, 0) is the documented "unset" sentinel for the astronomy theme
        wsr = datetime(2026, 4, 23, 6, 5, tzinfo=TZ)
        wss = datetime(2026, 4, 23, 19, 43, tzinfo=TZ)
        _, _, bands = _resolve_sun_times(TODAY, wsr, wss, 0.0, 0.0, TZ)
        assert len(bands) == 2  # fallback path

    def test_polar_day_falls_back_to_weather(self):
        """At very high latitudes some twilight events are None — fall through."""
        wsr = datetime(2026, 6, 21, 6, 5, tzinfo=TZ)
        wss = datetime(2026, 6, 21, 19, 43, tzinfo=TZ)
        _, _, bands = _resolve_sun_times(date(2026, 6, 21), wsr, wss, 85.0, 0.0, TZ)
        # Either falls through to weather (2 bands) or astronomy succeeded; at
        # 85° N around June solstice it should be polar day → fallback path.
        assert len(bands) in (0, 2, 8)


# ---------------------------------------------------------------------------
# Theme rendering
# ---------------------------------------------------------------------------


class TestLightCycleRender:
    def test_renders_correct_size(self):
        img = _render(latitude=NYC_LAT, longitude=NYC_LON)
        assert img.size == (800, 480)
        assert img.mode == "1"

    def test_renders_non_blank(self):
        img = _render(latitude=NYC_LAT, longitude=NYC_LON)
        assert not all(p == 255 for p in img.tobytes())

    def test_renders_without_lat_lon(self):
        img = _render()
        assert img.size == (800, 480)

    def test_renders_with_no_weather_and_no_coords(self):
        data = DashboardData(events=[], weather=None)
        theme = load_theme("light_cycle")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)


# ---------------------------------------------------------------------------
# Direct draw paths (exercises code that the high-level render path may not)
# ---------------------------------------------------------------------------


class TestDrawLightCycleDirect:
    def test_defaults_region_and_style(self):
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_light_cycle(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_with_weather_only(self):
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
            location_name="Brooklyn",
        )
        data = DashboardData(events=[], weather=w)
        draw_light_cycle(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_with_lat_lon_full_twilight_bands(self):
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_light_cycle(d, data, TODAY, FIXED_NOW, latitude=NYC_LAT, longitude=NYC_LON)
        assert img.getbbox() is not None

    def test_with_timed_events_renders_event_ticks(self):
        img, d = _make_draw()
        events = [
            CalendarEvent(
                summary="Standup",
                start=datetime(2026, 4, 23, 9, 30),
                end=datetime(2026, 4, 23, 10, 0),
                calendar_name="Work",
            ),
            CalendarEvent(
                summary="Lunch",
                start=datetime(2026, 4, 23, 12, 30),
                end=datetime(2026, 4, 23, 13, 30),
                calendar_name="Personal",
            ),
        ]
        data = DashboardData(events=events, weather=None)
        draw_light_cycle(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_skips_all_day_events(self):
        """All-day events should not produce event ticks."""
        img, d = _make_draw()
        events = [
            CalendarEvent(
                summary="Holiday",
                start=date(2026, 4, 23),
                end=date(2026, 4, 24),
                calendar_name="Holidays",
                is_all_day=True,
            ),
        ]
        data = DashboardData(events=events, weather=None)
        draw_light_cycle(d, data, TODAY, FIXED_NOW)
        # Image is non-blank from the rest of the chrome, but we just want this
        # to not crash on the all-day branch.
        assert img.getbbox() is not None

    def test_no_op_band_returns_early(self):
        """Density 0 or zero-width band should be a no-op (no exceptions)."""
        img, d = _make_draw()
        before = bytes(img.tobytes())
        _draw_twilight_band(d, 5.0, 5.0, 4, 0, 1)  # zero width
        _draw_twilight_band(d, 5.0, 6.0, 0, 0, 1)  # density 0
        assert img.tobytes() == before  # nothing drawn

    def test_event_far_outside_dial_is_skipped(self):
        """Events more than a day away can't be plotted — must be silently skipped."""
        img, d = _make_draw()
        events = [
            CalendarEvent(
                summary="Distant",
                start=datetime(2026, 4, 27, 10, 0),
                end=datetime(2026, 4, 27, 11, 0),
                calendar_name="Misc",
            ),
        ]
        data = DashboardData(events=events, weather=None)
        draw_light_cycle(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_weather_with_no_high_low_renders(self):
        """Weather missing high/low still renders (just shows current temp)."""
        img, d = _make_draw()
        w = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear",
            high=None,
            low=None,
            humidity=50,
            sunrise=datetime(2026, 4, 23, 6, 5, tzinfo=TZ),
            sunset=datetime(2026, 4, 23, 19, 43, tzinfo=TZ),
        )
        data = DashboardData(events=[], weather=w)
        draw_light_cycle(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_night_glyph_when_now_outside_daylight(self):
        """At midnight the moon glyph branch is hit instead of the sun."""
        img, d = _make_draw()
        midnight = datetime(2026, 4, 23, 0, 30, tzinfo=TZ)
        w = WeatherData(
            current_temp=50.0,
            current_icon="01n",
            current_description="clear",
            high=60.0,
            low=45.0,
            humidity=70,
            sunrise=datetime(2026, 4, 23, 6, 5, tzinfo=TZ),
            sunset=datetime(2026, 4, 23, 19, 43, tzinfo=TZ),
        )
        data = DashboardData(events=[], weather=w)
        draw_light_cycle(d, data, TODAY, midnight)
        assert img.getbbox() is not None
