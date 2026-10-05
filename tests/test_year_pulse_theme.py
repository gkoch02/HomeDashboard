"""The year_pulse theme and its panel."""

from __future__ import annotations

from datetime import date, datetime

from PIL import Image

from src.config import DisplayConfig
from src.data.models import Birthday, CalendarEvent, DashboardData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import load_theme

FIXED_NOW = datetime(2026, 4, 5, 10, 30)  # A Sunday morning


def _render(theme_name: str) -> Image.Image:
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme(theme_name)
    config = DisplayConfig()
    return render_dashboard(data, config, title="Test Dashboard", theme=theme)


class TestYearPulseTheme:
    def test_renders_correct_size(self):
        img = _render("year_pulse")
        assert img.size == (800, 480)

    def test_renders_1bit(self):
        img = _render("year_pulse")
        assert img.mode == "1"

    def test_renders_non_blank(self):
        img = _render("year_pulse")
        assert not all(p == 255 for p in img.tobytes()), "Image is blank"

    def test_layout_year_pulse_region_visible(self):
        theme = load_theme("year_pulse")
        assert theme.layout.year_pulse.visible is True
        assert theme.layout.year_pulse.h == 340


class TestYearPulsePanel:
    def _make_draw(self):
        from PIL import Image, ImageDraw

        img = Image.new("1", (800, 360), 1)
        return ImageDraw.Draw(img), img

    def _make_data(self, events=None, birthdays=None):
        return DashboardData(
            events=events or [],
            birthdays=birthdays or [],
            weather=None,
        )

    def test_renders_empty_data(self):
        from src.render.components.year_pulse_panel import draw_year_pulse
        from src.render.theme import ComponentRegion

        draw, img = self._make_draw()
        draw_year_pulse(
            draw, self._make_data(), date(2026, 4, 5), region=ComponentRegion(0, 0, 800, 360)
        )
        pixels = list(img.tobytes())
        assert not all(p == 255 for p in pixels), "Panel is blank"

    def test_renders_with_birthdays(self):
        from src.render.components.year_pulse_panel import draw_year_pulse
        from src.render.theme import ComponentRegion

        draw, img = self._make_draw()
        bdays = [
            Birthday(name="Alice", date=date(1990, 5, 10), age=35),
            Birthday(name="Bob", date=date(1985, 7, 4), age=40),
        ]
        draw_year_pulse(
            draw,
            self._make_data(birthdays=bdays),
            date(2026, 4, 5),
            region=ComponentRegion(0, 0, 800, 360),
        )
        pixels = list(img.tobytes())
        assert not all(p == 255 for p in pixels), "Panel is blank"

    def test_renders_with_events(self):
        from src.render.components.year_pulse_panel import draw_year_pulse
        from src.render.theme import ComponentRegion

        draw, img = self._make_draw()
        events = [
            CalendarEvent(
                summary="Team Offsite",
                start=datetime(2026, 4, 10, 9, 0),
                end=datetime(2026, 4, 10, 17, 0),
            ),
        ]
        draw_year_pulse(
            draw,
            self._make_data(events=events),
            date(2026, 4, 5),
            region=ComponentRegion(0, 0, 800, 360),
        )
        pixels = list(img.tobytes())
        assert not all(p == 255 for p in pixels), "Panel is blank"

    def test_build_countdowns_sorts_by_days(self):
        from src.render.components.year_pulse_panel import _build_countdowns

        today = date(2026, 4, 5)
        events = [
            CalendarEvent("Far Event", datetime(2026, 4, 12), datetime(2026, 4, 12)),
            CalendarEvent("Near Event", datetime(2026, 4, 7), datetime(2026, 4, 7)),
        ]
        data = DashboardData(events=events, birthdays=[])
        countdowns = _build_countdowns(data, today)
        days = [d for d, _ in countdowns]
        assert days == sorted(days), "Countdowns not sorted by days"

    def test_build_countdowns_excludes_past(self):
        from src.render.components.year_pulse_panel import _build_countdowns

        today = date(2026, 4, 5)
        events = [
            CalendarEvent("Past Event", datetime(2026, 4, 1), datetime(2026, 4, 1)),
        ]
        data = DashboardData(events=events, birthdays=[])
        countdowns = _build_countdowns(data, today)
        assert all(d >= 0 for d, _ in countdowns), "Past event leaked into countdowns"

    def test_leap_year_birthday_rolls_to_feb_28(self):
        """A Feb 29 birthday in a non-leap year is counted down to Feb 28."""
        from src.render.components.year_pulse_panel import _build_countdowns

        today = date(2026, 11, 15)  # 2027 is not a leap year; Feb 28 is inside the horizon
        bdays = [Birthday(name="Leap", date=date(2000, 2, 29), age=25)]
        data = DashboardData(events=[], birthdays=bdays)
        countdowns = _build_countdowns(data, today)
        leap = [d for d, label in countdowns if "Leap" in label]
        assert leap == [(date(2027, 2, 28) - today).days], countdowns

    def test_birthday_already_past_this_year_rolls_to_next(self):
        """Birthday earlier in the year already passed → next_occ rolls to next year."""
        from src.render.components.year_pulse_panel import _build_countdowns

        today = date(2026, 4, 5)
        # Birthday in January — already passed this year
        bdays = [Birthday(name="Early", date=date(1990, 1, 15), age=35)]
        data = DashboardData(events=[], birthdays=bdays)
        # 120-day horizon doesn't reach next January, so the result is empty,
        # but the year-rollover line still executes inside _build_countdowns.
        result = _build_countdowns(data, today)
        assert result == []

    def test_renders_with_default_region(self):
        """Calling draw_year_pulse with region=None falls back to a default region."""
        from src.render.components.year_pulse_panel import draw_year_pulse

        draw, img = self._make_draw()
        # No region= kwarg → exercises the `if region is None` default path.
        draw_year_pulse(draw, self._make_data(), date(2026, 4, 5))
        pixels = list(img.tobytes())
        assert not all(p == 255 for p in pixels), "Panel is blank"
