"""Tests for the trends theme and trends_panel component."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import (
    CalendarEvent,
    DashboardData,
    DayForecast,
    WeatherData,
)
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.trends_panel import (
    _bayer_fill_polygon,
    _build_temp_series,
    _draw_sparkline,
    _event_count_for_day,
    _interpolate,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
TODAY = FIXED_NOW.date()
NYC_LAT = 40.7128
NYC_LON = -74.0060


def _render(**kwargs):
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme("trends")
    return render_dashboard(
        data,
        DisplayConfig(),
        theme=theme,
        latitude=NYC_LAT,
        longitude=NYC_LON,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestTrendsRegistration:
    def test_in_available_themes(self):
        assert "trends" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("trends")
        assert t.name == "trends"

    def test_trends_region_visible(self):
        t = load_theme("trends")
        assert t.layout.trends.visible is True
        assert t.layout.trends.w == 800
        assert t.layout.trends.h == 480

    def test_draw_order_only_trends(self):
        t = load_theme("trends")
        assert t.layout.draw_order == ["trends"]

    def test_uses_ordered_quantization(self):
        t = load_theme("trends")
        assert t.layout.canvas_mode == "L"
        assert t.layout.preferred_quantization_mode == "ordered"

    def test_color_on_inky(self):
        t = load_theme("trends")
        assert t.layout.prefer_color_on_inky is True


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestInterpolate:
    def test_fills_gap_between_anchors(self):
        series = [1.0, None, None, 4.0]
        _interpolate(series)
        assert series == pytest.approx([1.0, 2.0, 3.0, 4.0])

    def test_forward_fills_leading_nones(self):
        series = [None, None, 5.0, 6.0]
        _interpolate(series)
        assert series[0] == 5.0 and series[1] == 5.0

    def test_extends_trailing_nones(self):
        series = [1.0, 2.0, None, None]
        _interpolate(series)
        assert series[-1] == 2.0 and series[-2] == 2.0

    def test_all_none_is_noop(self):
        series: list[float | None] = [None, None, None]
        _interpolate(series)
        assert series == [None, None, None]


class TestBuildTempSeries:
    def test_returns_13_points_with_now_in_middle(self):
        w = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear",
            high=72.0,
            low=48.0,
            humidity=40,
            forecast=[
                DayForecast(
                    date=TODAY + timedelta(days=1),
                    high=70.0,
                    low=50.0,
                    icon="01d",
                    description="clear",
                ),
            ],
        )
        series, now_index = _build_temp_series(w)
        assert len(series) == 13
        assert now_index == 6
        # Current temp anchored at the now index.
        assert series[6] == pytest.approx(60.0)
        # All points are filled by interpolation.
        assert all(v is not None for v in series)

    def test_handles_empty_forecast(self):
        w = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear",
            high=72.0,
            low=48.0,
            humidity=40,
            forecast=[],
        )
        series, _ = _build_temp_series(w)
        # With no forecast, interpolation should still fill all values.
        assert all(v is not None for v in series)


class TestEventCountForDay:
    def test_counts_only_today(self):
        events = [
            CalendarEvent("A", datetime(2026, 4, 6, 9, 0), datetime(2026, 4, 6, 10, 0)),
            CalendarEvent("B", datetime(2026, 4, 6, 11, 0), datetime(2026, 4, 6, 12, 0)),
            CalendarEvent(
                "Tomorrow",
                datetime(2026, 4, 7, 9, 0),
                datetime(2026, 4, 7, 10, 0),
            ),
        ]
        assert _event_count_for_day(events, date(2026, 4, 6)) == 2
        assert _event_count_for_day(events, date(2026, 4, 7)) == 1
        assert _event_count_for_day(events, date(2026, 4, 8)) == 0

    def test_counts_all_day_overlap(self):
        events = [
            CalendarEvent(
                "Span",
                datetime(2026, 4, 6),
                datetime(2026, 4, 8),
                is_all_day=True,
            ),
        ]
        # All-day span April 6 (inclusive) → April 8 (exclusive) covers 6, 7.
        assert _event_count_for_day(events, date(2026, 4, 6)) == 1
        assert _event_count_for_day(events, date(2026, 4, 7)) == 1
        assert _event_count_for_day(events, date(2026, 4, 8)) == 0


# ---------------------------------------------------------------------------
# Bayer fill + sparkline helpers
# ---------------------------------------------------------------------------


class TestBayerFillPolygon:
    def test_fills_triangle_with_dots(self):
        img = Image.new("L", (40, 40), 255)
        triangle = [(0, 0), (40, 0), (40, 40)]
        _bayer_fill_polygon(img, triangle, on_color=0, threshold=128)
        # Some pixels should be black.
        black = sum(1 for p in img.getdata() if p == 0)
        # 4×4 Bayer threshold < 128 covers ~50% of cells: 8 out of 16 (0,32,48,
        # 64, 96, 112, 16, 80). Triangle covers half the image. So ~25% of
        # 1600 pixels = ~400 black.
        assert 100 < black < 800

    def test_no_op_for_degenerate_polygon(self):
        img = Image.new("L", (10, 10), 255)
        _bayer_fill_polygon(img, [(0, 0), (1, 1)], on_color=0)
        black = sum(1 for p in img.getdata() if p == 0)
        assert black == 0


class TestSparklineHelper:
    def test_handles_constant_series(self):
        img = Image.new("L", (200, 60), 255)
        draw = ImageDraw.Draw(img)
        values: list[float | None] = [50.0] * 7
        _draw_sparkline(
            img,
            draw,
            (10, 10, 190, 50),
            values,
            line_fill=0,
            fill_color=0,
            now_index=0,
            accent_now=128,
        )
        # Some ink should be present along the line.
        black = sum(1 for p in img.getdata() if p < 200)
        assert black > 50

    def test_handles_all_none_series(self):
        img = Image.new("L", (200, 60), 255)
        draw = ImageDraw.Draw(img)
        # 3 Nones: not enough data, helper should draw the midline placeholder.
        _draw_sparkline(
            img,
            draw,
            (10, 10, 190, 50),
            [None, None, None],
            line_fill=0,
            fill_color=0,
            now_index=None,
            accent_now=128,
        )
        # Just the placeholder midline should be drawn.
        black = sum(1 for p in img.getdata() if p < 200)
        assert 20 < black < 500

    def test_now_marker_drawn(self):
        img = Image.new("L", (200, 60), 255)
        draw = ImageDraw.Draw(img)
        values = [10.0, 20.0, 30.0, 40.0]
        _draw_sparkline(
            img,
            draw,
            (10, 10, 190, 50),
            values,
            line_fill=0,
            fill_color=0,
            now_index=2,
            accent_now=128,
        )
        # A pixel near the marker x position should carry the accent_now value.
        has_accent = any(128 == img.getpixel((x, y)) for x in range(60, 140) for y in range(10, 50))
        assert has_accent


# ---------------------------------------------------------------------------
# Render fallbacks per row
# ---------------------------------------------------------------------------


def _data_kwargs(**overrides) -> DashboardData:
    base = dict(
        events=[],
        weather=None,
        birthdays=[],
        air_quality=None,
        host_data=None,
        fetched_at=FIXED_NOW,
    )
    base.update(overrides)
    return DashboardData(**base)  # type: ignore[arg-type]


class TestRowFallbacks:
    def test_renders_with_all_missing(self):
        """All fallback paths active simultaneously."""
        data = _data_kwargs()
        theme = load_theme("trends")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)

    def test_renders_with_no_lat_lon(self):
        data = generate_dummy_data(now=FIXED_NOW)
        theme = load_theme("trends")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        # No lat/lon → DAYLIGHT row uses the fallback string.
        assert img.size == (800, 480)

    def test_renders_with_no_air_quality(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data = replace(data, air_quality=None)
        theme = load_theme("trends")
        img = render_dashboard(
            data, DisplayConfig(), theme=theme, latitude=NYC_LAT, longitude=NYC_LON
        )
        assert img.size == (800, 480)

    def test_renders_with_no_weather(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data = replace(data, weather=None)
        theme = load_theme("trends")
        img = render_dashboard(
            data, DisplayConfig(), theme=theme, latitude=NYC_LAT, longitude=NYC_LON
        )
        assert img.size == (800, 480)


class TestInkyPath:
    def test_renders_on_inky_rgb_canvas(self):
        data = generate_dummy_data(now=FIXED_NOW)
        cfg = DisplayConfig()
        cfg = replace(cfg, provider="inky", model="impression_7_3_2025", width=800, height=480)
        theme = load_theme("trends")
        img = render_dashboard(data, cfg, theme=theme, latitude=NYC_LAT, longitude=NYC_LON)
        assert img.mode == "RGB"
        assert img.size == (800, 480)


class TestRenderWithDummyData:
    def test_pixel_count_non_trivial(self):
        img = _render()
        assert img.size == (800, 480)
        ones = sum(1 for p in img.getdata() if not p)
        # Sparkline charts + Bayer fills should produce thousands of ink pixels.
        assert ones > 5_000
