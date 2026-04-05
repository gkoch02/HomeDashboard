"""Smoke tests for the timeline and year_pulse themes.

Each test renders the theme with dummy data and asserts basic image properties:
correct size, 1-bit mode, and non-blank output.  Component-level unit tests
verify specific drawing logic.
"""

from __future__ import annotations

from datetime import date, datetime

from PIL import Image

from src.config import DisplayConfig
from src.data.models import Birthday, CalendarEvent, DashboardData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 5, 10, 30)  # A Sunday morning


def _render(theme_name: str) -> Image.Image:
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme(theme_name)
    config = DisplayConfig()
    return render_dashboard(data, config, title="Test Dashboard", theme=theme)


# ---------------------------------------------------------------------------
# Theme registration
# ---------------------------------------------------------------------------


class TestThemeRegistration:
    def test_timeline_in_available_themes(self):
        assert "timeline" in AVAILABLE_THEMES

    def test_year_pulse_in_available_themes(self):
        assert "year_pulse" in AVAILABLE_THEMES

    def test_load_timeline(self):
        theme = load_theme("timeline")
        assert theme.name == "timeline"

    def test_load_year_pulse(self):
        theme = load_theme("year_pulse")
        assert theme.name == "year_pulse"


# ---------------------------------------------------------------------------
# Timeline theme smoke tests
# ---------------------------------------------------------------------------


class TestTimelineTheme:
    def test_renders_correct_size(self):
        img = _render("timeline")
        assert img.size == (800, 480)

    def test_renders_1bit(self):
        img = _render("timeline")
        assert img.mode == "1"

    def test_renders_non_blank(self):
        img = _render("timeline")
        assert not all(p == 255 for p in img.tobytes()), "Image is blank"

    def test_layout_timeline_region_visible(self):
        theme = load_theme("timeline")
        assert theme.layout.timeline.visible is True
        assert theme.layout.timeline.h == 340


# ---------------------------------------------------------------------------
# Year Pulse theme smoke tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Timeline panel unit tests
# ---------------------------------------------------------------------------


class TestTimelinePanel:
    def _make_draw(self):
        from PIL import Image, ImageDraw

        img = Image.new("1", (800, 360), 1)
        return ImageDraw.Draw(img), img

    def test_renders_empty(self):
        from src.render.components.timeline_panel import draw_timeline
        from src.render.theme import ComponentRegion

        draw, img = self._make_draw()
        draw_timeline(draw, [], date(2026, 4, 5), FIXED_NOW, region=ComponentRegion(0, 0, 800, 360))
        assert img.mode == "1"

    def test_renders_with_events(self):
        from src.render.components.timeline_panel import draw_timeline
        from src.render.theme import ComponentRegion

        draw, img = self._make_draw()
        events = [
            CalendarEvent(
                summary="Standup",
                start=datetime(2026, 4, 5, 9, 0),
                end=datetime(2026, 4, 5, 9, 30),
            ),
            CalendarEvent(
                summary="Lunch",
                start=datetime(2026, 4, 5, 12, 0),
                end=datetime(2026, 4, 5, 13, 0),
            ),
        ]
        draw_timeline(
            draw, events, date(2026, 4, 5), FIXED_NOW, region=ComponentRegion(0, 0, 800, 360)
        )
        pixels = list(img.tobytes())
        assert not all(p == 255 for p in pixels), "Timeline is blank"

    def test_renders_overlapping_events(self):
        """Overlapping events should be assigned separate columns without crashing."""
        from src.render.components.timeline_panel import draw_timeline
        from src.render.theme import ComponentRegion

        draw, img = self._make_draw()
        events = [
            CalendarEvent(
                summary="Event A",
                start=datetime(2026, 4, 5, 10, 0),
                end=datetime(2026, 4, 5, 11, 30),
            ),
            CalendarEvent(
                summary="Event B",
                start=datetime(2026, 4, 5, 10, 30),
                end=datetime(2026, 4, 5, 12, 0),
            ),
        ]
        draw_timeline(
            draw, events, date(2026, 4, 5), FIXED_NOW, region=ComponentRegion(0, 0, 800, 360)
        )
        assert img.mode == "1"

    def test_column_assignment_no_overlap(self):
        """Non-overlapping events should all be in column 0."""
        from src.render.components.timeline_panel import _assign_columns

        events = [
            CalendarEvent("A", datetime(2026, 4, 5, 9, 0), datetime(2026, 4, 5, 10, 0)),
            CalendarEvent("B", datetime(2026, 4, 5, 11, 0), datetime(2026, 4, 5, 12, 0)),
        ]
        cols = _assign_columns(events)
        # cols maps original index → column; both should be 0
        assert all(v == 0 for v in cols.values())

    def test_column_assignment_overlap(self):
        """Overlapping events should be in different columns."""
        from src.render.components.timeline_panel import _assign_columns

        events = [
            CalendarEvent("A", datetime(2026, 4, 5, 9, 0), datetime(2026, 4, 5, 11, 0)),
            CalendarEvent("B", datetime(2026, 4, 5, 10, 0), datetime(2026, 4, 5, 12, 0)),
        ]
        cols = _assign_columns(events)
        col_values = sorted(cols.values())
        assert col_values == [0, 1]


# ---------------------------------------------------------------------------
# Year pulse panel unit tests
# ---------------------------------------------------------------------------


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

    def test_leap_year_birthday_handled(self):
        """Feb 29 birthdays should not crash when the current year is not a leap year."""
        from src.render.components.year_pulse_panel import _build_countdowns

        today = date(2026, 4, 5)  # 2026 is not a leap year
        bdays = [Birthday(name="Leap", date=date(2000, 2, 29), age=25)]
        data = DashboardData(events=[], birthdays=bdays)
        # Should not raise
        _build_countdowns(data, today)
