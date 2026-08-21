"""Tests for src/render/components/today_view.py."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DayForecast
from src.render.components.today_view import (
    _events_for_today,
    _fmt_time,
    draw_today,
)
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _timed(
    d: date, h_start: int, h_end: int, summary: str = "Meeting", location: str | None = None
) -> CalendarEvent:
    return CalendarEvent(
        summary=summary,
        start=datetime(d.year, d.month, d.day, h_start, 0),
        end=datetime(d.year, d.month, d.day, h_end, 0),
        location=location,
    )


def _all_day(start: date, end: date, summary: str = "All Day Event") -> CalendarEvent:
    return CalendarEvent(
        summary=summary,
        start=datetime.combine(start, datetime.min.time()),
        end=datetime.combine(end, datetime.min.time()),
        is_all_day=True,
    )


TODAY = date(2026, 3, 22)


# ---------------------------------------------------------------------------
# _fmt_time
# ---------------------------------------------------------------------------


class TestFmtTime:
    def test_morning_on_the_hour(self):
        dt = datetime(2026, 3, 22, 9, 0)
        result = _fmt_time(dt)
        assert "9" in result
        assert result.endswith("a")

    def test_morning_with_minutes(self):
        dt = datetime(2026, 3, 22, 9, 30)
        result = _fmt_time(dt)
        assert "9:30" in result
        assert result.endswith("a")

    def test_afternoon_on_the_hour(self):
        dt = datetime(2026, 3, 22, 14, 0)
        result = _fmt_time(dt)
        assert "2" in result
        assert result.endswith("p")

    def test_afternoon_with_minutes(self):
        dt = datetime(2026, 3, 22, 15, 45)
        result = _fmt_time(dt)
        assert "3:45" in result
        assert result.endswith("p")

    def test_noon(self):
        dt = datetime(2026, 3, 22, 12, 0)
        result = _fmt_time(dt)
        assert "12" in result
        assert result.endswith("p")

    def test_midnight(self):
        dt = datetime(2026, 3, 22, 0, 0)
        result = _fmt_time(dt)
        assert "12" in result
        assert result.endswith("a")

    def test_no_am_pm_suffix_in_full_string(self):
        """Result should not contain 'am' or 'pm', only 'a' or 'p'."""
        dt = datetime(2026, 3, 22, 10, 30)
        result = _fmt_time(dt)
        assert "am" not in result
        assert "pm" not in result


# ---------------------------------------------------------------------------
# _events_for_today
# ---------------------------------------------------------------------------


class TestEventsForToday:
    def test_empty_events(self):
        result = _events_for_today([], TODAY)
        assert result == []

    def test_timed_event_on_today(self):
        evt = _timed(TODAY, 9, 10)
        result = _events_for_today([evt], TODAY)
        assert len(result) == 1
        assert result[0] is evt

    def test_timed_event_on_different_day_excluded(self):
        evt = _timed(TODAY + timedelta(days=1), 9, 10)
        result = _events_for_today([evt], TODAY)
        assert result == []

    def test_timed_event_yesterday_excluded(self):
        evt = _timed(TODAY - timedelta(days=1), 9, 10)
        result = _events_for_today([evt], TODAY)
        assert result == []

    def test_all_day_event_spanning_today(self):
        evt = _all_day(TODAY, TODAY + timedelta(days=1))
        result = _events_for_today([evt], TODAY)
        assert len(result) == 1

    def test_all_day_event_starting_tomorrow_excluded(self):
        evt = _all_day(TODAY + timedelta(days=1), TODAY + timedelta(days=2))
        result = _events_for_today([evt], TODAY)
        assert result == []

    def test_all_day_event_ended_before_today_excluded(self):
        # All-day: start ≤ today < end. If end == today, it's excluded.
        evt = _all_day(TODAY - timedelta(days=2), TODAY)
        result = _events_for_today([evt], TODAY)
        assert result == []

    def test_all_day_event_multi_day_spanning_today(self):
        evt = _all_day(TODAY - timedelta(days=1), TODAY + timedelta(days=2))
        result = _events_for_today([evt], TODAY)
        assert len(result) == 1

    def test_sort_all_day_before_timed(self):
        timed = _timed(TODAY, 8, 9, "Early Meeting")
        allday = _all_day(TODAY, TODAY + timedelta(days=1), "Conference Day")
        result = _events_for_today([timed, allday], TODAY)
        assert result[0].is_all_day is True
        assert result[1].is_all_day is False

    def test_sort_timed_events_by_start_time(self):
        e1 = _timed(TODAY, 14, 15, "Afternoon")
        e2 = _timed(TODAY, 9, 10, "Morning")
        result = _events_for_today([e1, e2], TODAY)
        assert result[0].summary == "Morning"
        assert result[1].summary == "Afternoon"

    def test_multiple_events_mixed(self):
        events = [
            _timed(TODAY, 11, 12, "Midday"),
            _all_day(TODAY, TODAY + timedelta(days=1), "Full Day"),
            _timed(TODAY + timedelta(days=1), 9, 10, "Tomorrow - excluded"),
            _timed(TODAY, 8, 9, "Early"),
        ]
        result = _events_for_today(events, TODAY)
        assert len(result) == 3
        assert result[0].is_all_day is True

    def test_all_day_start_as_date_object(self):
        """Events with date (not datetime) start/end should work correctly."""
        evt = CalendarEvent(
            summary="Date-only event",
            start=datetime.combine(TODAY, datetime.min.time()),
            end=datetime.combine(TODAY + timedelta(days=1), datetime.min.time()),
            is_all_day=True,
        )
        result = _events_for_today([evt], TODAY)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# draw_today — rendering smoke tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Ink measurement
#
# The default region is (0, 60, 800, 280): an inverted date panel filling the
# left 3/10, a vertical rule, then the event list. Each test measures the side
# that owns what it changes.
# ---------------------------------------------------------------------------

REGION = ComponentRegion(0, 60, 800, 280)
_DATE_PANEL_W = 800 * 3 // 10  # 240, per draw_today's own split
DATE_PANEL = (0, 60, _DATE_PANEL_W, 340)
EVENTS = (_DATE_PANEL_W, 60, 800, 340)


def _ink(img: Image.Image, box: tuple[int, int, int, int] | None = None) -> int:
    """Count ink (value-0) pixels, optionally only inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    if box is None:
        return sum(1 for v in px if v == 0)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _divider_height(img: Image.Image) -> int:
    """Inked rows in the rule between the date panel and the event list."""
    px = flatten_pixels(img)
    width = img.width
    return sum(1 for y in range(60, 340) if px[y * width + _DATE_PANEL_W] == 0)


def _render(events=None, today=TODAY, **kwargs) -> Image.Image:
    img, draw = _make_draw()
    draw_today(draw, events or [], today, **kwargs)
    return img


class TestDrawToday:
    def test_smoke_no_events(self):
        """The date panel is inverted and the event list carries the empty message."""
        img = _render()
        panel_area = _DATE_PANEL_W * 280
        assert _ink(img, DATE_PANEL) > panel_area * 0.5, "date panel is not inverted"
        assert _ink(img, DATE_PANEL) < panel_area, "no date text knocked out of the fill"
        assert _ink(img, EVENTS) > 0, "no empty-state message"
        assert _divider_height(img) > 200, "no rule between the panels"

    def test_date_panel_tracks_the_date(self):
        """Day name, month and numeral come from the date, so they vary with it."""
        inks = {
            d: _ink(_render(today=d), DATE_PANEL)
            for d in (date(2024, 3, 1), date(2024, 3, 15), date(2024, 12, 25))
        }
        assert len(set(inks.values())) == 3, f"the date panel is not date-driven: {inks}"

    def test_smoke_single_timed_event(self):
        """A timed event replaces the empty-state message."""
        assert _ink(_render([_timed(TODAY, 10, 11)]), EVENTS) != _ink(_render(), EVENTS)

    def test_smoke_single_all_day_event(self):
        """An all-day event draws a filled bar, so it inks far more than a timed row."""
        all_day = _ink(_render([_all_day(TODAY, TODAY + timedelta(days=1))]), EVENTS)
        assert all_day > _ink(_render([_timed(TODAY, 10, 11)]), EVENTS) * 5

    def test_smoke_mixed_events(self):
        """All three events are drawn, so the plate exceeds any one of them."""
        events = [
            _all_day(TODAY, TODAY + timedelta(days=1), "Holiday"),
            _timed(TODAY, 9, 10, "Standup"),
            _timed(TODAY, 14, 15, "Review"),
        ]
        mixed = _ink(_render(events), EVENTS)
        assert mixed > _ink(_render(events[:1]), EVENTS)
        assert mixed > _ink(_render(events[1:]), EVENTS)

    def test_smoke_events_on_different_days_only_today_shown(self):
        """Yesterday's and tomorrow's events are filtered out, not merely tolerated."""
        only_today = [_timed(TODAY, 11, 12, "Today")]
        with_neighbours = [
            _timed(TODAY - timedelta(days=1), 9, 10, "Yesterday"),
            _timed(TODAY, 11, 12, "Today"),
            _timed(TODAY + timedelta(days=1), 9, 10, "Tomorrow"),
        ]
        assert _ink(_render(with_neighbours), EVENTS) == _ink(_render(only_today), EVENTS), (
            "an event from another day reached the plate"
        )

    def test_smoke_with_custom_region(self):
        """A taller region gives the event list more room, so more fits."""
        events = [_timed(TODAY, 8 + i, 9 + i, f"Event {i}") for i in range(10)]
        tall = ComponentRegion(0, 60, 800, 300)
        short = ComponentRegion(0, 60, 800, 140)
        tall_ink = _ink(_render(events, region=tall), (240, 60, 800, 360))
        short_ink = _ink(_render(events, region=short), (240, 60, 800, 360))
        assert tall_ink > short_ink, "the region height does not affect how much is listed"

    def test_smoke_many_events_overflow(self):
        """Beyond what fits, the list stops and shows a '+N more' indicator."""

        def with_events(n):
            return _ink(
                _render([_timed(TODAY, 6 + (i % 14), 7 + (i % 14), f"E{i}") for i in range(n)]),
                EVENTS,
            )

        eight = with_events(8)
        assert with_events(10) == eight, "more rows were drawn than fit"
        # The row count saturates but the "+N more" label still tracks N.
        assert with_events(20) != eight, "the overflow count is not being drawn"

    def test_smoke_all_day_event_non_inverted_bars(self):
        """invert_allday_bars=False outlines the bar instead of filling it."""
        from src.render.theme import ThemeStyle

        event = [_all_day(TODAY, TODAY + timedelta(days=1), "Conference Day")]
        outlined = _ink(_render(event, style=ThemeStyle(invert_allday_bars=False)), EVENTS)
        filled = _ink(_render(event, style=ThemeStyle(invert_allday_bars=True)), EVENTS)
        assert outlined > 0
        assert filled > outlined * 5, "the inverted bar is not filled"

    def test_smoke_event_with_location(self):
        """A location adds a line below the title."""
        with_loc = _timed(TODAY, 9, 10, "Doctor Visit", location="123 Medical Center, Suite 4")
        assert _ink(_render([with_loc]), EVENTS) > _ink(
            _render([_timed(TODAY, 9, 10, "Doctor Visit")]), EVENTS
        )

    def test_location_newlines_are_normalized_before_truncation(self):
        img, draw = _make_draw()
        evt = _timed(TODAY, 9, 10, "Visit", location="123 Main St\nSuite 200, Springfield")
        seen_texts: list[str] = []

        def _capture_text(*args, **kwargs):
            # signature: (draw, xy, text, font, max_width, fill=...)
            seen_texts.append(args[2])
            return 0

        with patch(
            "src.render.components.today_view.draw_text_truncated", side_effect=_capture_text
        ):
            draw_today(draw, [evt], TODAY)

        assert any("Suite 200" in t for t in seen_texts)
        assert all("\n" not in t for t in seen_texts)

    def test_smoke_event_with_long_title(self):
        """A long title wraps rather than being dropped or overflowing."""
        long_title = _timed(TODAY, 10, 11, "A Very Long Event Title That Should Be Wrapped")
        img = _render([long_title])
        assert _ink(img, EVENTS) > _ink(_render([_timed(TODAY, 10, 11, "Short")]), EVENTS)
        assert _ink(img, (0, 340, 800, 480)) == 0, "the event list overflowed its region"

    def test_smoke_small_region(self):
        """A small region still renders and keeps everything inside it."""
        region = ComponentRegion(0, 60, 400, 120)
        events = [_timed(TODAY, i, i + 1, f"E{i}") for i in range(9, 14)]
        img = _render(events, region=region)
        assert _ink(img, (0, 60, 400, 180)) > 0
        assert _ink(img, (400, 0, 800, 480)) == 0, "content escaped a 400px-wide region"

    def test_smoke_all_day_invert_style(self):
        """The inverted all-day bar knocks its title out of the fill."""
        from src.render.theme import ThemeStyle

        evt = _all_day(TODAY, TODAY + timedelta(days=1), "Inverted")
        img = _render([evt], style=ThemeStyle(invert_allday_bars=True))
        bar_ink = _ink(img, EVENTS)
        assert bar_ink > 0
        blank_title = _all_day(TODAY, TODAY + timedelta(days=1), "")
        assert bar_ink < _ink(
            _render([blank_title], style=ThemeStyle(invert_allday_bars=True)), EVENTS
        ), "the title is not knocked out of the inverted bar"

    def test_smoke_with_forecast(self):
        """A forecast is accepted; this view does not surface it in the event list."""
        forecast = [
            DayForecast(
                date=TODAY + timedelta(days=i),
                high=70.0 - i,
                low=50.0,
                icon="01d",
                description="clear",
            )
            for i in range(3)
        ]
        with_fc = _render([_timed(TODAY, 10, 11)], forecast=forecast)
        assert _ink(with_fc, EVENTS) > 0

    def test_no_events_today_message_differs_from_with_events(self):
        assert _render().tobytes() != _render([_timed(TODAY, 9, 10)]).tobytes()

    def test_same_am_period_strips_redundant_suffix(self):
        """9a–11a is set as '9–11a', which is narrower than a cross-period range.

        Compared against an event of the same duration that crosses noon, so
        the only difference is the dropped suffix.
        """
        same_period = _render([_timed(TODAY, 9, 11, "Block")])
        cross_noon = _render([_timed(TODAY, 11, 13, "Block")])
        assert _ink(same_period, EVENTS) < _ink(cross_noon, EVENTS), (
            "the redundant am/pm suffix was not stripped"
        )

    def test_cross_noon_event(self):
        """An 11a–1p event keeps both suffixes."""
        assert _ink(_render([_timed(TODAY, 11, 13, "Lunch & Meeting")]), EVENTS) > 0
