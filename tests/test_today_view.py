"""Tests for src/render/components/today_view.py."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from PIL import Image

from src.data.models import CalendarEvent, DayForecast
from src.render.components.today_view import draw_today
from src.render.primitives import events_for_day, fmt_time
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion
from tests.conftest import make_draw
from tests.inkutils import ink, record_text


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
# fmt_time
# ---------------------------------------------------------------------------


class TestFmtTime:
    @pytest.mark.parametrize(
        "dt, fragment, suffix",
        [
            (datetime(2026, 3, 22, 9, 0), "9", "a"),
            (datetime(2026, 3, 22, 9, 30), "9:30", "a"),
            (datetime(2026, 3, 22, 14, 0), "2", "p"),
            (datetime(2026, 3, 22, 15, 45), "3:45", "p"),
            (datetime(2026, 3, 22, 12, 0), "12", "p"),
            (datetime(2026, 3, 22, 0, 0), "12", "a"),
        ],
        ids=[
            "morning_on_the_hour",
            "morning_with_minutes",
            "afternoon_on_the_hour",
            "afternoon_with_minutes",
            "noon",
            "midnight",
        ],
    )
    def test_hour_and_meridian(self, dt, fragment, suffix):
        result = fmt_time(dt)
        assert fragment in result
        assert result.endswith(suffix)

    def test_no_am_pm_suffix_in_full_string(self):
        """Result should not contain 'am' or 'pm', only 'a' or 'p'."""
        dt = datetime(2026, 3, 22, 10, 30)
        result = fmt_time(dt)
        assert "am" not in result
        assert "pm" not in result


# ---------------------------------------------------------------------------
# events_for_day
# ---------------------------------------------------------------------------


class TestEventsForToday:
    def test_empty_events(self):
        result = events_for_day([], TODAY)
        assert result == []

    def test_timed_event_on_today(self):
        evt = _timed(TODAY, 9, 10)
        result = events_for_day([evt], TODAY)
        assert len(result) == 1
        assert result[0] is evt

    @pytest.mark.parametrize("offset_days", [1, -1], ids=["tomorrow", "yesterday"])
    def test_timed_event_on_another_day_excluded(self, offset_days):
        evt = _timed(TODAY + timedelta(days=offset_days), 9, 10)
        result = events_for_day([evt], TODAY)
        assert result == []

    def test_all_day_event_spanning_today(self):
        evt = _all_day(TODAY, TODAY + timedelta(days=1))
        result = events_for_day([evt], TODAY)
        assert len(result) == 1

    def test_all_day_event_starting_tomorrow_excluded(self):
        evt = _all_day(TODAY + timedelta(days=1), TODAY + timedelta(days=2))
        result = events_for_day([evt], TODAY)
        assert result == []

    def test_all_day_event_ended_before_today_excluded(self):
        # All-day: start ≤ today < end. If end == today, it's excluded.
        evt = _all_day(TODAY - timedelta(days=2), TODAY)
        result = events_for_day([evt], TODAY)
        assert result == []

    def test_all_day_event_multi_day_spanning_today(self):
        evt = _all_day(TODAY - timedelta(days=1), TODAY + timedelta(days=2))
        result = events_for_day([evt], TODAY)
        assert len(result) == 1

    def test_sort_all_day_before_timed(self):
        timed = _timed(TODAY, 8, 9, "Early Meeting")
        allday = _all_day(TODAY, TODAY + timedelta(days=1), "Conference Day")
        result = events_for_day([timed, allday], TODAY)
        assert result[0].is_all_day is True
        assert result[1].is_all_day is False

    def test_sort_timed_events_by_start_time(self):
        e1 = _timed(TODAY, 14, 15, "Afternoon")
        e2 = _timed(TODAY, 9, 10, "Morning")
        result = events_for_day([e1, e2], TODAY)
        assert result[0].summary == "Morning"
        assert result[1].summary == "Afternoon"

    def test_multiple_events_mixed(self):
        events = [
            _timed(TODAY, 11, 12, "Midday"),
            _all_day(TODAY, TODAY + timedelta(days=1), "Full Day"),
            _timed(TODAY + timedelta(days=1), 9, 10, "Tomorrow - excluded"),
            _timed(TODAY, 8, 9, "Early"),
        ]
        result = events_for_day(events, TODAY)
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
        result = events_for_day([evt], TODAY)
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


def _divider_height(img: Image.Image) -> int:
    """Inked rows in the rule between the date panel and the event list."""
    px = flatten_pixels(img)
    width = img.width
    return sum(1 for y in range(60, 340) if px[y * width + _DATE_PANEL_W] == 0)


def _render(events=None, today=TODAY, **kwargs) -> Image.Image:
    img, draw = make_draw()
    draw_today(draw, events or [], today, **kwargs)
    return img


class TestDrawToday:
    def test_smoke_no_events(self):
        """The date panel is inverted and the event list carries the empty message."""
        img = _render()
        panel_area = _DATE_PANEL_W * 280
        assert ink(img, DATE_PANEL) > panel_area * 0.5, "date panel is not inverted"
        assert ink(img, DATE_PANEL) < panel_area, "no date text knocked out of the fill"
        assert ink(img, EVENTS) > 0, "no empty-state message"
        assert _divider_height(img) > 200, "no rule between the panels"

    def test_date_panel_tracks_the_date(self):
        """Day name, month and numeral come from the date, so they vary with it."""
        inks = {
            d: ink(_render(today=d), DATE_PANEL)
            for d in (date(2024, 3, 1), date(2024, 3, 15), date(2024, 12, 25))
        }
        assert len(set(inks.values())) == 3, f"the date panel is not date-driven: {inks}"

    def test_smoke_single_timed_event(self):
        """A timed event replaces the empty-state message."""
        assert ink(_render([_timed(TODAY, 10, 11)]), EVENTS) != ink(_render(), EVENTS)

    def test_smoke_single_all_day_event(self):
        """An all-day event draws a filled bar, so it inks far more than a timed row."""
        all_day = ink(_render([_all_day(TODAY, TODAY + timedelta(days=1))]), EVENTS)
        assert all_day > ink(_render([_timed(TODAY, 10, 11)]), EVENTS) * 5

    def test_smoke_mixed_events(self):
        """All three events are drawn, so the plate exceeds any one of them."""
        events = [
            _all_day(TODAY, TODAY + timedelta(days=1), "Holiday"),
            _timed(TODAY, 9, 10, "Standup"),
            _timed(TODAY, 14, 15, "Review"),
        ]
        mixed = ink(_render(events), EVENTS)
        assert mixed > ink(_render(events[:1]), EVENTS)
        assert mixed > ink(_render(events[1:]), EVENTS)

    def test_smoke_events_on_different_days_only_today_shown(self):
        """Yesterday's and tomorrow's events are filtered out, not merely tolerated."""
        only_today = [_timed(TODAY, 11, 12, "Today")]
        with_neighbours = [
            _timed(TODAY - timedelta(days=1), 9, 10, "Yesterday"),
            _timed(TODAY, 11, 12, "Today"),
            _timed(TODAY + timedelta(days=1), 9, 10, "Tomorrow"),
        ]
        assert ink(_render(with_neighbours), EVENTS) == ink(_render(only_today), EVENTS), (
            "an event from another day reached the plate"
        )

    def test_smoke_with_custom_region(self):
        """A taller region gives the event list more room, so more fits."""
        events = [_timed(TODAY, 8 + i, 9 + i, f"Event {i}") for i in range(10)]
        tall = ComponentRegion(0, 60, 800, 300)
        short = ComponentRegion(0, 60, 800, 140)
        tall_ink = ink(_render(events, region=tall), (240, 60, 800, 360))
        short_ink = ink(_render(events, region=short), (240, 60, 800, 360))
        assert tall_ink > short_ink, "the region height does not affect how much is listed"

    def test_smoke_many_events_overflow(self):
        """Beyond what fits, the list stops and shows a '+N more' indicator."""

        def with_events(n):
            img, draw = make_draw()
            calls = record_text(draw)
            events = [_timed(TODAY, 6 + (i % 14), 7 + (i % 14), f"E{i}") for i in range(n)]
            draw_today(draw, events, TODAY)
            texts = [t for t, _box in calls]
            return sum(t.startswith("E") for t in texts), [t for t in texts if t.endswith("more")]

        rows, more = with_events(10)
        assert more == [f"+{10 - rows} more"], "the overflow count is not being drawn"
        # The row count saturates but the "+N more" label still tracks N.
        assert with_events(20) == (rows, [f"+{20 - rows} more"]), "more rows were drawn than fit"

    def test_smoke_all_day_event_non_inverted_bars(self):
        """invert_allday_bars=False outlines the bar instead of filling it."""
        from src.render.theme import ThemeStyle

        event = [_all_day(TODAY, TODAY + timedelta(days=1), "Conference Day")]
        outlined = ink(_render(event, style=ThemeStyle(invert_allday_bars=False)), EVENTS)
        filled = ink(_render(event, style=ThemeStyle(invert_allday_bars=True)), EVENTS)
        assert outlined > 0
        assert filled > outlined * 5, "the inverted bar is not filled"

    def test_smoke_event_with_location(self):
        """A location adds a line below the title."""
        with_loc = _timed(TODAY, 9, 10, "Doctor Visit", location="123 Medical Center, Suite 4")
        assert ink(_render([with_loc]), EVENTS) > ink(
            _render([_timed(TODAY, 9, 10, "Doctor Visit")]), EVENTS
        )

    def test_location_shows_its_first_line_only(self):
        # The street, not the street with the suite run on after it — a
        # newline in the location is where the row ends, not a space.
        img, draw = make_draw()
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

        assert "123 Main St" in seen_texts
        assert not any("Suite 200" in t for t in seen_texts)
        assert all("\n" not in t for t in seen_texts)

    def test_smoke_event_with_long_title(self):
        """A long title wraps rather than being dropped or overflowing."""
        long_title = _timed(TODAY, 10, 11, "A Very Long Event Title That Should Be Wrapped")
        img = _render([long_title])
        assert ink(img, EVENTS) > ink(_render([_timed(TODAY, 10, 11, "Short")]), EVENTS)
        assert ink(img, (0, 340, 800, 480)) == 0, "the event list overflowed its region"

    def test_smoke_small_region(self):
        """A small region still renders and keeps everything inside it."""
        region = ComponentRegion(0, 60, 400, 120)
        events = [_timed(TODAY, i, i + 1, f"E{i}") for i in range(9, 14)]
        img = _render(events, region=region)
        assert ink(img, (0, 60, 400, 180)) > 0
        assert ink(img, (400, 0, 800, 480)) == 0, "content escaped a 400px-wide region"

    def test_smoke_all_day_invert_style(self):
        """The inverted all-day bar knocks its title out of the fill."""
        from src.render.theme import ThemeStyle

        evt = _all_day(TODAY, TODAY + timedelta(days=1), "Inverted")
        img = _render([evt], style=ThemeStyle(invert_allday_bars=True))
        bar_ink = ink(img, EVENTS)
        assert bar_ink > 0
        blank_title = _all_day(TODAY, TODAY + timedelta(days=1), "")
        assert bar_ink < ink(
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
        assert ink(with_fc, EVENTS) > 0

    def test_no_events_today_message_differs_from_with_events(self):
        assert _render().tobytes() != _render([_timed(TODAY, 9, 10)]).tobytes()

    def test_same_am_period_strips_redundant_suffix(self):
        """9a–11a is set as '9–11a', which is narrower than a cross-period range.

        Compared against an event of the same duration that crosses noon, so
        the only difference is the dropped suffix.
        """
        same_period = _render([_timed(TODAY, 9, 11, "Block")])
        cross_noon = _render([_timed(TODAY, 11, 13, "Block")])
        assert ink(same_period, EVENTS) < ink(cross_noon, EVENTS), (
            "the redundant am/pm suffix was not stripped"
        )

    def test_cross_noon_event(self):
        """An 11a–1p event keeps both suffixes."""
        assert ink(_render([_timed(TODAY, 11, 13, "Lunch & Meeting")]), EVENTS) > 0


class TestOverflowLine:
    """The "+N more" count sits below the last drawn event, never on top of it."""

    def _events(self) -> list[CalendarEvent]:
        events = [
            _all_day(TODAY, TODAY + timedelta(days=1), "Out of office"),
            _all_day(TODAY, TODAY + timedelta(days=1), "School holiday"),
        ]
        events += [_timed(TODAY, h, h + 1, f"Event {h}", location="Room 4B") for h in range(7, 21)]
        return events

    # Around old_fashioned's broadsheet column (490 x 400), whose geometry put
    # the count on a location line.
    @pytest.mark.parametrize("height", range(380, 421, 4))
    def test_more_line_clears_the_rows_above(self, height):
        img, draw = make_draw()
        calls = record_text(draw)
        region = ComponentRegion(0, 80, 490, height)
        draw_today(draw, self._events(), TODAY, region=region)
        listed = [(t, box) for t, box in calls if box[0] > region.w * 0.3]
        more = [box for t, box in listed if t.endswith(" more")]
        assert len(more) == 1, "the overflow count was not drawn"
        above = [box[3] for t, box in listed if not t.endswith(" more")]
        assert more[0][1] >= max(above), (
            f"count at y={more[0][1]} overlaps a row ending {max(above)}"
        )
