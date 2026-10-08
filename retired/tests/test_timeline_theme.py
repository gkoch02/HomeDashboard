"""The timeline theme and its panel."""

from __future__ import annotations

from datetime import date, datetime

from PIL import Image

from src.config import DisplayConfig
from src.data.models import CalendarEvent
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

    def test_renders_with_default_region(self):
        """When region=None, the default ComponentRegion(0, 40, 800, 360) is used."""
        from src.render.components.timeline_panel import draw_timeline

        draw, img = self._make_draw()
        draw_timeline(draw, [], date(2026, 4, 5), FIXED_NOW, region=None, style=None)
        assert img.mode == "1"

    def test_hour_label_break_when_y_exceeds_region(self):
        """A very short region stops drawing rows once they pass the region bottom."""
        from src.render.components.timeline_panel import draw_timeline
        from src.render.theme import ComponentRegion

        draw, img = self._make_draw()
        # Tiny height means the very first hour line falls outside the region.
        draw_timeline(draw, [], date(2026, 4, 5), FIXED_NOW, region=ComponentRegion(0, 0, 800, 4))
        assert img.mode == "1"

    def test_renders_outlined_allday_bars(self):
        """invert_allday_bars=False draws all-day bars outlined rather than filled."""
        from dataclasses import replace as dc_replace

        from src.render.components.timeline_panel import draw_timeline
        from src.render.theme import ComponentRegion, ThemeStyle

        draw, img = self._make_draw()
        style = dc_replace(ThemeStyle(), invert_allday_bars=False)
        events = [
            CalendarEvent(
                summary="All-day Picnic",
                start=datetime(2026, 4, 5, 0, 0),
                end=datetime(2026, 4, 6, 0, 0),
                is_all_day=True,
            ),
        ]
        draw_timeline(
            draw,
            events,
            date(2026, 4, 5),
            FIXED_NOW,
            region=ComponentRegion(0, 0, 800, 360),
            style=style,
        )
        # No assertions on pixel content — just confirm no crash.
        assert img.mode == "1"

    def test_event_before_default_window_widens_the_axis(self):
        """An event before _START_HOUR moves the axis start to its hour, so it draws."""
        from src.render.components.timeline_panel import (
            _AXIS_W,
            _PAD_RIGHT,
            axis_hours,
            draw_timeline,
        )
        from src.render.theme import ComponentRegion

        pre_dawn = CalendarEvent(
            summary="Pre-dawn",
            start=datetime(2026, 4, 5, 3, 0),
            end=datetime(2026, 4, 5, 5, 0),
        )
        assert axis_hours([pre_dawn], date(2026, 4, 5)) == (3, 21)

        draw, img = self._make_draw()
        draw_timeline(
            draw, [pre_dawn], date(2026, 4, 5), FIXED_NOW, region=ComponentRegion(0, 0, 800, 360)
        )
        # 3a-9p over 360 px is 1/3 px per minute, so the two-hour block fills
        # the top 40 rows of the timeline, its title knocked out in white.
        block = (_AXIS_W + 2, 1, 800 - _PAD_RIGHT - 2, 39)
        area = (block[2] - block[0]) * (block[3] - block[1])
        assert ink(img, block) > area * 0.8, "the pre-dawn event drew no block"

    def test_minutes_from_start_past_day_clamps_to_zero(self):
        """A datetime on a previous day clamps to 0 (start of visible window)."""
        from src.render.components.timeline_panel import _minutes_from_start

        result = _minutes_from_start(datetime(2026, 4, 4, 14, 0), date(2026, 4, 5))
        assert result == 0

    def test_minutes_from_start_future_day_clamps_to_window_end(self):
        """A datetime on a future day clamps to _VISIBLE_HOURS * 60 (end of window)."""
        from src.render.components.timeline_panel import _minutes_from_start

        result = _minutes_from_start(datetime(2026, 4, 6, 8, 0), date(2026, 4, 5))
        assert result == 14 * 60  # _VISIBLE_HOURS * 60


class TestTimelineAxisHours:
    def _evt(self, start, end, summary="e"):
        return CalendarEvent(summary=summary, start=start, end=end)

    def test_default_window_when_events_fit(self):
        from src.render.components.timeline_panel import axis_hours

        d = date(2026, 4, 6)
        evts = [self._evt(datetime(2026, 4, 6, 9), datetime(2026, 4, 6, 10))]
        assert axis_hours(evts, d) == (7, 21)
        assert axis_hours([], d) == (7, 21)

    def test_late_and_early_events_widen_the_window(self):
        from src.render.components.timeline_panel import axis_hours

        d = date(2026, 4, 6)
        evts = [
            self._evt(datetime(2026, 4, 6, 5, 30), datetime(2026, 4, 6, 6)),
            self._evt(datetime(2026, 4, 6, 21, 30), datetime(2026, 4, 6, 22, 15)),
        ]
        assert axis_hours(evts, d) == (5, 23)

    def test_window_is_clamped_to_the_day(self):
        from src.render.components.timeline_panel import axis_hours

        d = date(2026, 4, 6)
        overnight_in = [self._evt(datetime(2026, 4, 5, 23), datetime(2026, 4, 6, 2))]
        assert axis_hours(overnight_in, d) == (0, 21)
        overnight_out = [self._evt(datetime(2026, 4, 6, 23), datetime(2026, 4, 7, 2))]
        assert axis_hours(overnight_out, d) == (7, 24)

    def test_event_covering_the_whole_day_does_not_widen_the_window(self):
        """A multi-day timed event (kept by the #275 overlap filter) is drawn
        full-height whatever the axis is; letting it stretch the axis to
        00-24 compressed the day's real schedule into a third of the strip."""
        from src.render.components.timeline_panel import axis_hours

        d = date(2026, 4, 6)
        conference = self._evt(datetime(2026, 4, 5, 9), datetime(2026, 4, 7, 17))
        assert axis_hours([conference], d) == (7, 21)
        dinner = self._evt(datetime(2026, 4, 6, 21, 30), datetime(2026, 4, 6, 22, 15))
        assert axis_hours([conference, dinner], d) == (7, 23)

    def test_evening_event_is_drawn(self):
        """A 10 PM dinner was clamped to nothing and silently dropped."""
        from PIL import ImageDraw

        from src.render.components.timeline_panel import draw_timeline
        from src.render.theme import ComponentRegion

        d = date(2026, 4, 6)
        now = datetime(2026, 4, 6, 10, 30)
        region = ComponentRegion(0, 40, 800, 340)
        dinner = self._evt(datetime(2026, 4, 6, 22), datetime(2026, 4, 7, 0), "Dinner")
        with_evt = Image.new("1", (800, 480), 1)
        draw_timeline(ImageDraw.Draw(with_evt), [dinner], d, now, region=region)
        without = Image.new("1", (800, 480), 1)
        draw_timeline(ImageDraw.Draw(without), [], d, now, region=region)
        # The event block is a solid inverted bar in the lower part of the axis.
        lower = (60, 300, 794, 380)
        assert ink(with_evt, lower) > ink(without, lower) + 500
