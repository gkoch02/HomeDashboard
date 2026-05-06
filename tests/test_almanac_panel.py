"""Tests for the almanac theme and almanac_panel component."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import Birthday, CalendarEvent, DashboardData, WeatherAlert, WeatherData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.almanac_panel import (
    _fmt_clock,
    _fmt_duration,
    _fmt_signed_minutes,
    _next_phase_date,
    _roman,
    _season,
    _upcoming_calendar_summary,
    draw_almanac,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

NYC_LAT = 40.7128
NYC_LON = -74.0060
TZ = ZoneInfo("America/New_York")
FIXED_NOW = datetime(2026, 4, 23, 9, 30, tzinfo=TZ)
TODAY = FIXED_NOW.date()


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _render(**kwargs):
    data = generate_dummy_data(tz=TZ, now=FIXED_NOW)
    theme = load_theme("almanac")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestAlmanacRegistration:
    def test_in_available_themes(self):
        assert "almanac" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("almanac")
        assert t.name == "almanac"

    def test_almanac_region_visible(self):
        t = load_theme("almanac")
        assert t.layout.almanac.visible is True
        assert t.layout.almanac.w == 800
        assert t.layout.almanac.h == 480

    def test_draw_order_only_almanac(self):
        t = load_theme("almanac")
        assert t.layout.draw_order == ["almanac"]


# ---------------------------------------------------------------------------
# Pure-format helpers
# ---------------------------------------------------------------------------


class TestRoman:
    def test_basic(self):
        assert _roman(1) == "I"
        assert _roman(4) == "IV"
        assert _roman(9) == "IX"
        assert _roman(40) == "XL"
        assert _roman(90) == "XC"
        assert _roman(400) == "CD"
        assert _roman(900) == "CM"
        assert _roman(2026) == "MMXXVI"

    def test_zero_or_negative_returns_em_dash(self):
        assert _roman(0) == "—"
        assert _roman(-5) == "—"


class TestSeason:
    def test_winter(self):
        assert _season(date(2026, 1, 15)) == "Winter"
        assert _season(date(2026, 12, 31)) == "Winter"

    def test_spring(self):
        assert _season(date(2026, 4, 1)) == "Spring"

    def test_summer(self):
        assert _season(date(2026, 7, 4)) == "Summer"

    def test_autumn(self):
        assert _season(date(2026, 10, 31)) == "Autumn"


class TestFmtClock:
    def test_naive_passthrough(self):
        assert _fmt_clock(datetime(2026, 4, 23, 6, 5), None) == "6:05a"

    def test_aware_converts_to_target_tz(self):
        from datetime import timezone

        utc = datetime(2026, 4, 23, 10, 5, tzinfo=timezone.utc)
        assert _fmt_clock(utc, TZ) == "6:05a"

    def test_pm_lowercased(self):
        assert _fmt_clock(datetime(2026, 4, 23, 19, 43), None) == "7:43p"

    def test_none_input(self):
        assert _fmt_clock(None, TZ) == "—"


class TestFmtDuration:
    def test_basic(self):
        assert _fmt_duration(timedelta(hours=14, minutes=3)) == "14h 03m"

    def test_none(self):
        assert _fmt_duration(None) == "—"


class TestFmtSignedMinutes:
    def test_positive(self):
        assert _fmt_signed_minutes(timedelta(minutes=2, seconds=12)).startswith("+2m")

    def test_negative(self):
        assert _fmt_signed_minutes(-timedelta(minutes=1, seconds=4)).startswith("-1m")

    def test_zero(self):
        assert _fmt_signed_minutes(timedelta()) == "0s"

    def test_seconds_only(self):
        assert _fmt_signed_minutes(timedelta(seconds=12)) == "+12s"

    def test_none(self):
        assert _fmt_signed_minutes(None) == "—"


class TestNextPhaseDate:
    def test_full_moon_within_30_days(self):
        d = _next_phase_date(TODAY, 0.5)
        assert 0 <= (d - TODAY).days <= 32

    def test_new_moon_within_30_days(self):
        d = _next_phase_date(TODAY, 0.0)
        assert 0 <= (d - TODAY).days <= 32


# ---------------------------------------------------------------------------
# Calendar summary helper
# ---------------------------------------------------------------------------


class TestUpcomingCalendarSummary:
    def test_includes_today_first_event(self):
        events = [
            CalendarEvent(
                summary="Standup",
                start=datetime(2026, 4, 23, 9, 30),
                end=datetime(2026, 4, 23, 10, 0),
                calendar_name="Work",
            ),
        ]
        data = DashboardData(events=events)
        out = _upcoming_calendar_summary(data, TODAY, max_lines=4)
        assert any("Standup" in line and "today" in line for line in out)

    def test_includes_future_event_with_weekday_label(self):
        future = datetime(2026, 4, 26, 10, 0)  # Sunday
        events = [
            CalendarEvent(
                summary="Brunch",
                start=future,
                end=future + timedelta(hours=1),
                calendar_name="Personal",
            ),
        ]
        data = DashboardData(events=events)
        out = _upcoming_calendar_summary(data, TODAY, max_lines=4)
        assert any("Brunch" in line and "Sunday" in line for line in out)

    def test_includes_birthday_within_two_weeks(self):
        data = DashboardData(
            events=[],
            birthdays=[Birthday(name="Mom", date=TODAY + timedelta(days=3))],
        )
        out = _upcoming_calendar_summary(data, TODAY, max_lines=4)
        assert any("Mom's birthday" in line for line in out)

    def test_falls_back_to_quiet_message_when_empty(self):
        data = DashboardData(events=[], birthdays=[])
        out = _upcoming_calendar_summary(data, TODAY, max_lines=4)
        assert out == ["Quiet days ahead."]

    def test_capped_at_max_lines(self):
        # Many future events — output must not exceed max_lines.
        events = [
            CalendarEvent(
                summary=f"Event {i}",
                start=datetime(2026, 4, 24 + (i // 4), 9 + (i % 4), 0),
                end=datetime(2026, 4, 24 + (i // 4), 10 + (i % 4), 0),
                calendar_name="Work",
            )
            for i in range(8)
        ]
        data = DashboardData(events=events)
        out = _upcoming_calendar_summary(data, TODAY, max_lines=3)
        assert len(out) == 3

    def test_birthday_in_past_rolls_to_next_year(self):
        """A birthday whose this-year date is in the past should jump to next year."""
        data = DashboardData(
            events=[],
            birthdays=[Birthday(name="Old", date=date(2026, 1, 5))],  # past for our TODAY
        )
        out = _upcoming_calendar_summary(data, TODAY, max_lines=4)
        # Their next birthday is Jan 5, 2027 → 257 days away → outside the 14-day window
        assert not any("Old" in line for line in out)
        # Therefore the function falls back to the quiet message
        assert out == ["Quiet days ahead."]


# ---------------------------------------------------------------------------
# Theme rendering
# ---------------------------------------------------------------------------


class TestAlmanacRender:
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
        theme = load_theme("almanac")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)


# ---------------------------------------------------------------------------
# Direct draw paths
# ---------------------------------------------------------------------------


class TestDrawAlmanacDirect:
    def test_defaults_region_and_style(self):
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_almanac(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_with_full_weather_data(self):
        img, d = _make_draw()
        w = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="partly cloudy",
            high=72.0,
            low=55.0,
            humidity=50,
            wind_speed=12.0,
            wind_deg=315.0,
            sunrise=datetime(2026, 4, 23, 6, 5, tzinfo=TZ),
            sunset=datetime(2026, 4, 23, 19, 43, tzinfo=TZ),
            alerts=[WeatherAlert(event="Wind Advisory")],
        )
        data = DashboardData(events=[], weather=w)
        draw_almanac(d, data, TODAY, FIXED_NOW, latitude=NYC_LAT, longitude=NYC_LON)
        assert img.getbbox() is not None

    def test_with_lat_lon(self):
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_almanac(d, data, TODAY, FIXED_NOW, latitude=NYC_LAT, longitude=NYC_LON)
        assert img.getbbox() is not None

    def test_with_zero_zero_lat_lon_falls_back(self):
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
        draw_almanac(d, data, TODAY, FIXED_NOW, latitude=0.0, longitude=0.0)
        assert img.getbbox() is not None

    def test_weather_with_no_wind_or_alerts(self):
        """Weather missing the optional editorial fields still renders."""
        img, d = _make_draw()
        w = WeatherData(
            current_temp=55.0,
            current_icon="01d",
            current_description="clear",
            high=None,
            low=None,
            humidity=50,
        )
        data = DashboardData(events=[], weather=w)
        draw_almanac(d, data, TODAY, FIXED_NOW)
        assert img.getbbox() is not None

    def test_polar_day_handles_missing_day_length_delta(self):
        """At extreme latitudes day_length_delta returns None — must not crash."""
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_almanac(
            d,
            data,
            date(2026, 6, 21),
            datetime(2026, 6, 21, 12, 0, tzinfo=TZ),
            latitude=85.0,
            longitude=0.0,
        )
        assert img.getbbox() is not None
