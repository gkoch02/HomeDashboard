"""The monthly theme and its panel."""

from __future__ import annotations

from datetime import date, datetime

from PIL import Image

from src.config import DisplayConfig
from src.data.models import CalendarEvent, DashboardData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import load_theme
from tests.inkutils import ink

FIXED_NOW = datetime(2026, 4, 5, 10, 30)  # A Sunday morning


def _render(theme_name: str) -> Image.Image:
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme(theme_name)
    config = DisplayConfig()
    return render_dashboard(data, config, title="Test Dashboard", theme=theme)


class TestMonthlyTheme:
    def test_renders_correct_size(self):
        img = _render("monthly")
        assert img.size == (800, 480)

    def test_renders_1bit_on_waveshare(self):
        img = _render("monthly")
        assert img.mode == "1"

    def test_renders_non_blank(self):
        img = _render("monthly")
        assert not all(p == 255 for p in img.tobytes()), "Image is blank"

    def test_layout_monthly_region_visible(self):
        theme = load_theme("monthly")
        assert theme.layout.monthly.visible is True
        assert theme.layout.monthly.h == 480
        assert theme.layout.prefer_color_on_inky is True

    def test_renders_rgb_for_inky(self):
        data = generate_dummy_data(now=FIXED_NOW)
        theme = load_theme("monthly")
        config = DisplayConfig(provider="inky", model="impression_7_3_2025", width=800, height=480)
        img = render_dashboard(data, config, title="Test Dashboard", theme=theme)
        assert img.mode == "RGB"


class TestMonthlyPanel:
    def test_month_grid_is_six_weeks(self):
        from src.render.components.monthly_panel import _month_grid_dates

        days = _month_grid_dates(date(2026, 4, 5))
        assert len(days) == 42
        assert days.count(None) > 0
        assert date(2026, 4, 1) in days

    def test_density_counts_multiday_all_day_events(self):
        from src.render.components.monthly_panel import _density_by_day, _month_grid_dates

        today = date(2026, 4, 5)
        grid = _month_grid_dates(today)
        event = CalendarEvent(
            "Trip",
            datetime(2026, 4, 7, 0, 0),
            datetime(2026, 4, 10, 0, 0),
            is_all_day=True,
        )
        counts = _density_by_day([event], grid)
        assert counts[date(2026, 4, 7)] == 1
        assert counts[date(2026, 4, 8)] == 1
        assert counts[date(2026, 4, 9)] == 1

    def test_density_counts_timed_events_on_start_day(self):
        from src.render.components.monthly_panel import _density_by_day, _month_grid_dates

        today = date(2026, 4, 5)
        grid = _month_grid_dates(today)
        event = CalendarEvent(
            "Meeting",
            datetime(2026, 4, 7, 9, 0),
            datetime(2026, 4, 7, 10, 0),
        )
        counts = _density_by_day([event], grid)
        assert counts[date(2026, 4, 7)] == 1

    def test_event_days_all_day_zero_length_returns_start_only(self):
        """An all-day event where end <= start degenerates to a single-day event."""
        from src.render.components.monthly_panel import _event_days

        event = CalendarEvent(
            "Single",
            datetime(2026, 4, 7, 0, 0),
            datetime(2026, 4, 7, 0, 0),  # end == start → no span
            is_all_day=True,
        )
        assert _event_days(event) == [date(2026, 4, 7)]

    def test_density_level_single_busy_day_uses_max_tier(self):
        """When the busiest day has 1 event, it should render at the max heatmap tier."""
        from src.render.components.monthly_panel import LEGEND_STEPS, _density_level

        # count=1, max_density=1 → top tier, not a diluted fraction
        assert _density_level(1, 1) == LEGEND_STEPS

    def test_month_meta_text_empty_month_shows_open_message(self):
        """With no events at all, the meta text should be the 'looks open' phrasing."""
        from src.render.components.monthly_panel import _month_meta_text

        out = _month_meta_text(date(2026, 4, 5), max_density=0)
        assert "open" in out.lower()
        assert "April" in out

    def test_draw_monthly_defaults_region_and_style(self):
        """draw_monthly with no region/style should fall back to defaults and not crash."""
        from PIL import Image, ImageDraw

        from src.render.components.monthly_panel import draw_monthly

        img = Image.new("1", (800, 480), 1)
        draw = ImageDraw.Draw(img)
        data = DashboardData(events=[])
        draw_monthly(draw, data, date(2026, 4, 5))
        assert ink(img) > 0, "the month grid drew nothing"

    def test_draw_monthly_empty_month_shows_today_marker(self):
        """When today has no events, the cell shows the 'today' word marker."""
        from PIL import Image, ImageDraw

        from src.render.components.monthly_panel import draw_monthly

        img = Image.new("1", (800, 480), 1)
        draw = ImageDraw.Draw(img)
        # No events at all in the month: the today marker lands on an empty cell
        # and the meta text takes its "looks open" wording.
        data = DashboardData(events=[])
        draw_monthly(draw, data, date(2026, 4, 5))
        assert ink(img) > 0, "the empty-month grid drew nothing"
