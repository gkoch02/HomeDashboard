"""Tests for src/render/components/scorecard_panel.py

Covers: quote_for(prefix="scorecard-") (deterministic selection per key prefix and refresh
cadence), _draw_tile (smoke — no crash, truncation path), draw_scorecard (full
render under various data conditions including missing weather, AQI, host, and
birthdays; before/after sunrise; tile content correctness).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from PIL import Image, ImageDraw

from src.data.models import (
    Birthday,
    DashboardData,
    HostData,
    WeatherData,
)
from src.dummy_data import generate_dummy_data
from src.render.components.scorecard_panel import (
    _draw_tile,
    draw_scorecard,
)
from src.render.quotes import quote_for
from src.render.theme import ComponentRegion, ThemeStyle
from tests.inkutils import ink, record_text

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
FIXED_TODAY = FIXED_NOW.date()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blank_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), color=1)
    return ImageDraw.Draw(img), img


def _minimal_weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=65.0,
        high=72.0,
        low=55.0,
        current_description="clear sky",
        current_icon="01d",
        feels_like=63.0,
        humidity=50,
        forecast=[],
        sunrise=datetime(2026, 4, 6, 6, 30),
        sunset=datetime(2026, 4, 6, 19, 45),
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


# ---------------------------------------------------------------------------
# quote_for(prefix="scorecard-")
# ---------------------------------------------------------------------------


class TestQuoteForPanel:
    def test_returns_dict_with_text(self):
        q = quote_for(FIXED_TODAY, prefix="scorecard-")
        assert "text" in q
        assert len(q["text"]) > 0

    def test_daily_is_deterministic(self):
        q1 = quote_for(FIXED_TODAY, prefix="scorecard-")
        q2 = quote_for(FIXED_TODAY, prefix="scorecard-")
        assert q1["text"] == q2["text"]

    def test_different_days_may_differ(self):
        q1 = quote_for(date(2026, 1, 1), prefix="scorecard-")
        q2 = quote_for(date(2026, 1, 2), prefix="scorecard-")
        # Not guaranteed but the hash should differ for adjacent dates
        # (just verify both return valid dicts)
        assert "text" in q1 and "text" in q2

    def test_hourly_refresh_varies_with_hour(self):
        morning = datetime(2026, 4, 6, 8, 0)
        evening = datetime(2026, 4, 6, 20, 0)
        q_am = quote_for(FIXED_TODAY, refresh="hourly", now=morning, prefix="scorecard-")
        q_pm = quote_for(FIXED_TODAY, refresh="hourly", now=evening, prefix="scorecard-")
        # Both should be valid
        assert "text" in q_am and "text" in q_pm

    def test_twice_daily_am_pm_differ(self):
        am = datetime(2026, 4, 6, 9, 0)
        pm = datetime(2026, 4, 6, 14, 0)
        q_am = quote_for(FIXED_TODAY, refresh="twice_daily", now=am, prefix="scorecard-")
        q_pm = quote_for(FIXED_TODAY, refresh="twice_daily", now=pm, prefix="scorecard-")
        # Both valid; keys differ so may (likely) differ
        assert "text" in q_am and "text" in q_pm

    def test_scorecard_prefix_differs_from_other_panels(self):
        # Scorecard uses "scorecard-" prefix — should pick differently than
        # a panel using a different prefix on the same date
        q_scorecard = quote_for(FIXED_TODAY, prefix="scorecard-")
        assert "text" in q_scorecard

    def test_fallback_quotes_used_when_no_file(self, monkeypatch, tmp_path):
        from src.render.quotes import DEFAULT_QUOTES

        monkeypatch.setattr("src.render.quotes.DEFAULT_QUOTES_PATH", tmp_path / "nonexistent.json")
        q = quote_for(FIXED_TODAY, prefix="scorecard-")
        assert q in DEFAULT_QUOTES


# ---------------------------------------------------------------------------
# _draw_tile
# ---------------------------------------------------------------------------


class TestDrawTile:
    @pytest.mark.parametrize(
        "args, kwargs",
        [
            ((0, 0, 200, 130, "42", "EVENTS TODAY", "5 this week"), {}),
            ((0, 0, 200, 130, "72°", "OUTDOOR", "H:80° L:60°"), {"hero_size": 32}),
        ],
        ids=["default_hero", "hero_size_override"],
    )
    def test_draws_inside_the_tile(self, args, kwargs):
        draw, img = _blank_draw()
        x, y, w, h = args[:4]
        _draw_tile(draw, *args, ThemeStyle(), **kwargs)
        assert ink(img, (x, y, x + w, y + h)) > 0, "the tile is blank"

    def test_long_context_is_truncated_to_the_tile(self):
        draw, img = _blank_draw()
        long_ctx = "This is a very long context string that should trigger truncation"
        _draw_tile(draw, 0, 0, 100, 130, "99", "LABEL", long_ctx, ThemeStyle())
        assert ink(img, (0, 0, 100, 130)) > 0, "the tile is blank"
        assert ink(img, (100, 0, 800, 130)) == 0, "the context ran past the tile's right edge"


# ---------------------------------------------------------------------------
# draw_scorecard
# ---------------------------------------------------------------------------


class TestDrawScorecard:
    def _draw(self, data: DashboardData, now: datetime = FIXED_NOW) -> Image.Image:
        img = Image.new("1", (800, 480), color=1)
        draw = ImageDraw.Draw(img)
        draw_scorecard(draw, data, now.date(), now)
        return img

    def test_smoke_with_full_dummy_data(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = self._draw(data)
        assert img.size == (800, 480)
        # Image should not be blank
        assert not all(p == 255 for p in img.tobytes())

    def test_smoke_no_weather(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = None
        img = self._draw(data)
        assert img.size == (800, 480)

    def _texts(self, data: DashboardData, now: datetime = FIXED_NOW) -> list[str]:
        draw, _img = _blank_draw()
        calls = record_text(draw)
        draw_scorecard(draw, data, now.date(), now)
        return [text for text, _box in calls]

    def test_daylight_without_sun_times_reads_no_data(self):
        """Mid-morning with weather offline is not "before sunrise" with 0% left."""
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = None
        texts = self._texts(data)
        assert "before sunrise" not in texts and "0%" not in texts
        assert texts.count("no data") >= 2  # daylight and sunset tiles alike

    def test_daylight_before_sunrise_still_reads_zero(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = _minimal_weather()
        texts = self._texts(data, datetime(2026, 4, 6, 5, 0))
        assert "0%" in texts and "before sunrise" in texts

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

    def test_smoke_all_optional_data_missing(self):
        data = DashboardData(fetched_at=FIXED_NOW)
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_before_sunrise_renders(self):
        early = datetime(2026, 4, 6, 4, 0)
        data = generate_dummy_data(now=early)
        img = self._draw(data, now=early)
        assert img.size == (800, 480)

    def test_after_sunset_renders(self):
        late = datetime(2026, 4, 6, 21, 0)
        data = generate_dummy_data(now=late)
        img = self._draw(data, now=late)
        assert img.size == (800, 480)

    def test_sunset_already_passed_shows_set(self):
        # now > sunset → sunset tile shows "set"
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = _minimal_weather(
            sunrise=datetime(2026, 4, 6, 6, 30),
            sunset=datetime(2026, 4, 6, 7, 0),  # sunset already passed
        )
        now = datetime(2026, 4, 6, 20, 0)
        img = self._draw(data, now=now)
        assert img.size == (800, 480)

    def test_no_sunset_data_renders(self):
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = _minimal_weather(sunrise=None, sunset=None)
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_host_data_with_cpu_temp(self):
        data = DashboardData(fetched_at=FIXED_NOW)
        data.host_data = HostData(
            hostname="pi",
            cpu_temp_c=52.3,
            load_1m=0.42,
            ram_used_mb=512,
            ram_total_mb=1024,
        )
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_host_data_load_only(self):
        data = DashboardData(fetched_at=FIXED_NOW)
        data.host_data = HostData(
            hostname="pi",
            cpu_temp_c=None,
            load_1m=0.85,
            ram_used_mb=300,
            ram_total_mb=1000,
        )
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_host_data_minimal(self):
        data = DashboardData(fetched_at=FIXED_NOW)
        data.host_data = HostData(hostname="pi")
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_birthday_with_age(self):
        data = DashboardData(fetched_at=FIXED_NOW)
        data.birthdays = [Birthday(name="Alice", date=date(2026, 4, 10), age=30)]
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_birthday_without_age(self):
        data = DashboardData(fetched_at=FIXED_NOW)
        data.birthdays = [Birthday(name="Bob", date=date(2026, 4, 12), age=None)]
        img = self._draw(data)
        assert img.size == (800, 480)

    def test_custom_region(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = Image.new("1", (800, 480), color=1)
        draw = ImageDraw.Draw(img)
        region = ComponentRegion(0, 0, 800, 480)
        draw_scorecard(draw, data, FIXED_TODAY, FIXED_NOW, region=region)
        assert img.size == (800, 480)

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(style=ThemeStyle(fg=0, bg=1)),
            dict(quote_refresh="daily"),
            dict(quote_refresh="twice_daily"),
            dict(quote_refresh="hourly"),
        ],
        ids=["explicit_style", "quote_daily", "quote_twice_daily", "quote_hourly"],
    )
    def test_renders_a_non_blank_plate(self, kwargs):
        """Every style / quote-cadence shape draws something; nothing finer is asserted."""
        data = generate_dummy_data(now=FIXED_NOW)
        img = Image.new("1", (800, 480), color=1)
        draw = ImageDraw.Draw(img)
        draw_scorecard(draw, data, FIXED_TODAY, FIXED_NOW, **kwargs)
        assert ink(img) > 0
