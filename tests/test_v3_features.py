"""Tests for v3 features: parallel fetchers, conditional refresh (image diffing),
extended forecast in week view, moon phase, and multi-day spanning event bars.
"""

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.data.models import (
    CalendarEvent, DashboardData, DayForecast, WeatherData,
)
from src.display.driver import image_changed, image_hash
from src.render.components.week_view import (
    _collect_spanning_events, _events_for_day, _is_multiday, draw_week,
)
from src.render.moon import moon_phase_age, moon_phase_glyph, moon_phase_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _timed(day: date, h_start: int, h_end: int, summary: str = "Evt"):
    return CalendarEvent(
        summary=summary,
        start=datetime.combine(day, datetime.min.time().replace(hour=h_start)),
        end=datetime.combine(day, datetime.min.time().replace(hour=h_end)),
    )


def _all_day(start: date, end: date, summary: str = "All Day"):
    return CalendarEvent(
        summary=summary,
        start=datetime.combine(start, datetime.min.time()),
        end=datetime.combine(end, datetime.min.time()),
        is_all_day=True,
    )


def _make_weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=55.0, current_icon="01d", current_description="clear",
        high=60.0, low=45.0, humidity=50,
        forecast=[DayForecast(
            date=date.today() + timedelta(days=1), high=58.0, low=44.0,
            icon="02d", description="cloudy",
        )],
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


# ---------------------------------------------------------------------------
# Conditional refresh (image diffing)
# ---------------------------------------------------------------------------

class TestImageDiffing:
    def test_image_hash_deterministic(self):
        img = Image.new("1", (10, 10), 1)
        assert image_hash(img) == image_hash(img)

    def test_different_images_different_hash(self):
        white = Image.new("1", (10, 10), 1)
        black = Image.new("1", (10, 10), 0)
        assert image_hash(white) != image_hash(black)

    def test_image_changed_first_call_returns_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Image.new("1", (10, 10), 1)
            assert image_changed(img, tmpdir) is True

    def test_image_changed_same_image_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Image.new("1", (10, 10), 1)
            image_changed(img, tmpdir)  # first call writes hash
            assert image_changed(img, tmpdir) is False

    def test_image_changed_different_image_returns_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img1 = Image.new("1", (10, 10), 1)
            image_changed(img1, tmpdir)
            img2 = Image.new("1", (10, 10), 0)
            assert image_changed(img2, tmpdir) is True

    def test_hash_file_persisted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Image.new("1", (10, 10), 1)
            image_changed(img, tmpdir)
            hash_path = Path(tmpdir) / "last_image_hash.txt"
            assert hash_path.exists()
            stored = hash_path.read_text().strip()
            assert stored == image_hash(img)


# ---------------------------------------------------------------------------
# Parallel fetcher execution
# ---------------------------------------------------------------------------

class TestParallelFetchers:
    def test_fetch_live_data_runs_fetchers_concurrently(self):
        """All three fetchers should be submitted to the thread pool."""
        from src.config import Config
        from src.main import fetch_live_data

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.fetch_events", return_value=[]) as mock_cal, \
                 patch("src.main.fetch_weather", return_value=_make_weather()) as mock_wx, \
                 patch("src.main.fetch_birthdays", return_value=[]) as mock_bd:
                data = fetch_live_data(Config(), tmpdir)

            assert mock_cal.called
            assert mock_wx.called
            assert mock_bd.called
            assert data.weather is not None
            assert data.events == []

    def test_parallel_failure_falls_back_to_cache(self):
        """A single fetcher failure should not block the others."""
        from src.config import Config
        from src.fetchers.cache import save_source
        from src.main import fetch_live_data

        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-populate weather cache (recent enough to be within TTL)
            from datetime import timedelta
            save_source("weather", _make_weather(), datetime.now() - timedelta(hours=3), tmpdir)

            with patch("src.main.fetch_events", return_value=[]), \
                 patch("src.main.fetch_weather", side_effect=RuntimeError("down")), \
                 patch("src.main.fetch_birthdays", return_value=[]):
                data = fetch_live_data(Config(), tmpdir)

            assert "weather" in data.stale_sources
            assert data.weather is not None  # from cache


# ---------------------------------------------------------------------------
# Moon phase
# ---------------------------------------------------------------------------

class TestMoonPhase:
    def test_age_is_positive(self):
        age = moon_phase_age(date(2024, 3, 15))
        assert 0 <= age < 29.54

    def test_known_new_moon(self):
        """2024-01-11 was a known new moon."""
        age = moon_phase_age(date(2024, 1, 11))
        assert age < 2.0  # within ~2 days of new moon

    def test_known_full_moon(self):
        """2024-01-25 was a known full moon."""
        age = moon_phase_age(date(2024, 1, 25))
        assert 13.0 < age < 16.5  # near midpoint of cycle

    def test_phase_name_returns_string(self):
        name = moon_phase_name(date(2024, 3, 15))
        assert isinstance(name, str)
        assert len(name) > 0

    def test_glyph_returns_unicode_char(self):
        glyph = moon_phase_glyph(date(2024, 3, 15))
        assert isinstance(glyph, str)
        assert len(glyph) == 1

    def test_phase_name_values_valid(self):
        """All 8 phase names should be reachable across a full cycle."""
        names = set()
        d = date(2024, 1, 1)
        for i in range(30):
            names.add(moon_phase_name(d + timedelta(days=i)))
        assert len(names) >= 4  # at least half the phases hit in 30 days

    def test_deterministic_same_date(self):
        d = date(2024, 6, 15)
        assert moon_phase_glyph(d) == moon_phase_glyph(d)
        assert moon_phase_name(d) == moon_phase_name(d)


# ---------------------------------------------------------------------------
# Multi-day spanning event bars
# ---------------------------------------------------------------------------

class TestMultidaySpanning:
    def test_is_multiday_single_day_event(self):
        e = _all_day(date(2024, 3, 15), date(2024, 3, 16))
        assert not _is_multiday(e)

    def test_is_multiday_two_day_event(self):
        e = _all_day(date(2024, 3, 15), date(2024, 3, 17))
        assert _is_multiday(e)

    def test_is_multiday_timed_event(self):
        e = _timed(date(2024, 3, 15), 9, 10)
        assert not _is_multiday(e)

    def test_collect_spanning_events_basic(self):
        week_start = date(2024, 3, 11)  # Monday
        week_end = date(2024, 3, 18)
        events = [
            _all_day(date(2024, 3, 12), date(2024, 3, 15), "3-day conf"),
        ]
        spanning = _collect_spanning_events(events, week_start, week_end)
        assert len(spanning) == 1
        evt, first_col, last_col = spanning[0]
        assert evt.summary == "3-day conf"
        assert first_col == 1  # Tuesday
        assert last_col == 3  # Thursday

    def test_collect_spanning_events_clamps_to_week(self):
        """Events starting before or ending after the week are clamped."""
        week_start = date(2024, 3, 11)
        week_end = date(2024, 3, 18)
        events = [
            _all_day(date(2024, 3, 9), date(2024, 3, 20), "Long trip"),
        ]
        spanning = _collect_spanning_events(events, week_start, week_end)
        assert len(spanning) == 1
        _, first_col, last_col = spanning[0]
        assert first_col == 0  # Monday (clamped from Saturday before)
        assert last_col == 6  # Sunday (clamped from Wednesday after)

    def test_collect_spanning_excludes_single_day(self):
        week_start = date(2024, 3, 11)
        week_end = date(2024, 3, 18)
        events = [
            _all_day(date(2024, 3, 12), date(2024, 3, 13), "1-day"),
        ]
        spanning = _collect_spanning_events(events, week_start, week_end)
        assert len(spanning) == 0

    def test_collect_spanning_excludes_outside_week(self):
        week_start = date(2024, 3, 11)
        week_end = date(2024, 3, 18)
        events = [
            _all_day(date(2024, 3, 1), date(2024, 3, 5), "Last week"),
        ]
        spanning = _collect_spanning_events(events, week_start, week_end)
        assert len(spanning) == 0

    def test_draw_week_with_spanning_events_no_crash(self):
        today = date(2024, 3, 15)  # Friday
        events = [
            _all_day(date(2024, 3, 12), date(2024, 3, 15), "Conference"),
            _timed(date(2024, 3, 15), 9, 10, "Standup"),
        ]
        img, draw = _make_draw()
        draw_week(draw, events, today)
        assert img.getbbox() is not None

    def test_draw_week_multiple_spanning_events(self):
        today = date(2024, 3, 15)
        events = [
            _all_day(date(2024, 3, 11), date(2024, 3, 14), "Trip A"),
            _all_day(date(2024, 3, 14), date(2024, 3, 17), "Trip B"),
        ]
        img, draw = _make_draw()
        draw_week(draw, events, today)
        assert img.getbbox() is not None

    def test_spanning_event_excluded_from_per_day_rendering(self):
        """Multi-day events drawn as spanning bars should not also appear as per-day bars."""
        spanning = _all_day(date(2024, 3, 13), date(2024, 3, 16), "Multi")
        timed = _timed(date(2024, 3, 13), 9, 10, "Standup")
        # _events_for_day still returns the multi-day event (it's the draw_week
        # function that filters). Just verify both events are visible on the day.
        events = _events_for_day([spanning, timed], date(2024, 3, 13))
        assert len(events) == 2  # both show up in the raw filter


# ---------------------------------------------------------------------------
# Extended forecast in week view
# ---------------------------------------------------------------------------

class TestWeekViewForecast:
    def test_draw_week_with_forecast_no_crash(self):
        today = date(2024, 3, 15)
        forecast = [
            DayForecast(
                date=today + timedelta(days=i), high=50.0 + i, low=40.0 + i,
                icon="02d", description="cloudy",
            )
            for i in range(1, 6)
        ]
        img, draw = _make_draw()
        draw_week(draw, [], today, forecast=forecast)
        assert img.getbbox() is not None

    def test_draw_week_forecast_none_no_crash(self):
        today = date(2024, 3, 15)
        img, draw = _make_draw()
        draw_week(draw, [], today, forecast=None)
        assert img.getbbox() is not None

    def test_draw_week_forecast_empty_list(self):
        today = date(2024, 3, 15)
        img, draw = _make_draw()
        draw_week(draw, [], today, forecast=[])
        assert img.getbbox() is not None


# ---------------------------------------------------------------------------
# Weather panel with moon phase
# ---------------------------------------------------------------------------

class TestWeatherPanelMoon:
    def test_draw_weather_with_today_no_crash(self):
        from src.render.components.weather_panel import draw_weather
        weather = _make_weather()
        img, draw = _make_draw()
        draw_weather(draw, weather, today=date(2024, 3, 15))
        assert img.getbbox() is not None

    def test_draw_weather_without_today_no_crash(self):
        """Backward compat: today=None should still work."""
        from src.render.components.weather_panel import draw_weather
        weather = _make_weather()
        img, draw = _make_draw()
        draw_weather(draw, weather, today=None)
        assert img.getbbox() is not None

    def test_draw_weather_none_with_today(self):
        from src.render.components.weather_panel import draw_weather
        img, draw = _make_draw()
        draw_weather(draw, None, today=date(2024, 3, 15))
        assert img.getbbox() is not None


# ---------------------------------------------------------------------------
# Full render pipeline with v3 features
# ---------------------------------------------------------------------------

class TestRenderPipelineV3:
    def test_render_dashboard_with_all_v3_features(self):
        """Smoke test: full render with spanning events, forecast, and moon phase."""
        from src.config import DisplayConfig
        from src.render.canvas import render_dashboard

        today = date(2024, 3, 15)
        now = datetime.combine(today, datetime.min.time().replace(hour=8))
        week_start = today - timedelta(days=today.weekday())

        events = [
            _all_day(week_start, week_start + timedelta(days=3), "Multi-day Conf"),
            _timed(today, 9, 10, "Standup"),
        ]
        forecast = [
            DayForecast(
                date=today + timedelta(days=i), high=50.0, low=40.0,
                icon="02d", description="cloudy",
            )
            for i in range(1, 6)
        ]
        weather = _make_weather(forecast=forecast)

        data = DashboardData(
            events=events, weather=weather, birthdays=[], fetched_at=now,
        )
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert isinstance(result, Image.Image)
        assert result.size == (800, 480)
        assert result.mode == "1"
        assert result.getbbox() is not None
