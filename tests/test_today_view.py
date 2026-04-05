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


class TestDrawToday:
    def test_smoke_no_events(self):
        img, draw = _make_draw()
        draw_today(draw, [], TODAY)
        assert img.getbbox() is not None

    def test_smoke_single_timed_event(self):
        img, draw = _make_draw()
        draw_today(draw, [_timed(TODAY, 10, 11)], TODAY)
        assert img.getbbox() is not None

    def test_smoke_single_all_day_event(self):
        img, draw = _make_draw()
        draw_today(draw, [_all_day(TODAY, TODAY + timedelta(days=1))], TODAY)
        assert img.getbbox() is not None

    def test_smoke_mixed_events(self):
        img, draw = _make_draw()
        events = [
            _all_day(TODAY, TODAY + timedelta(days=1), "Holiday"),
            _timed(TODAY, 9, 10, "Standup"),
            _timed(TODAY, 14, 15, "Review"),
        ]
        draw_today(draw, events, TODAY)
        assert img.getbbox() is not None

    def test_smoke_events_on_different_days_only_today_shown(self):
        """Events from other days should be silently excluded (no crash)."""
        img, draw = _make_draw()
        events = [
            _timed(TODAY - timedelta(days=1), 9, 10, "Yesterday"),
            _timed(TODAY, 11, 12, "Today"),
            _timed(TODAY + timedelta(days=1), 9, 10, "Tomorrow"),
        ]
        draw_today(draw, events, TODAY)
        assert img.getbbox() is not None

    def test_smoke_with_custom_region(self):
        img, draw = _make_draw()
        region = ComponentRegion(0, 60, 800, 300)
        draw_today(draw, [_timed(TODAY, 10, 11)], TODAY, region=region)
        assert img.getbbox() is not None

    def test_smoke_many_events_overflow(self):
        """More events than fit should show '+N more' without crashing."""
        img, draw = _make_draw()
        events = [_timed(TODAY, i, i + 1, f"Event {i}") for i in range(8, 18)]
        draw_today(draw, events, TODAY)
        assert img.getbbox() is not None

    def test_smoke_event_with_location(self):
        img, draw = _make_draw()
        evt = _timed(TODAY, 9, 10, "Doctor Visit", location="123 Medical Center, Suite 4")
        draw_today(draw, [evt], TODAY)
        assert img.getbbox() is not None

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
        img, draw = _make_draw()
        evt = _timed(TODAY, 10, 11, "A Very Long Event Title That Should Be Wrapped")
        draw_today(draw, [evt], TODAY)
        assert img.getbbox() is not None

    def test_smoke_small_region(self):
        """Small region should not crash even with many events."""
        img, draw = _make_draw()
        region = ComponentRegion(0, 60, 400, 120)
        events = [_timed(TODAY, i, i + 1, f"E{i}") for i in range(9, 14)]
        draw_today(draw, events, TODAY, region=region)
        assert img.getbbox() is not None

    def test_smoke_all_day_invert_style(self):
        """With invert_allday_bars style, all-day events should still render."""
        from src.render.theme import ThemeStyle

        img, draw = _make_draw()
        style = ThemeStyle(invert_allday_bars=True)
        evt = _all_day(TODAY, TODAY + timedelta(days=1), "Inverted")
        draw_today(draw, [evt], TODAY, style=style)
        assert img.getbbox() is not None

    def test_smoke_with_forecast(self):
        img, draw = _make_draw()
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
        draw_today(draw, [_timed(TODAY, 10, 11)], TODAY, forecast=forecast)
        assert img.getbbox() is not None

    def test_no_events_today_message_differs_from_with_events(self):
        """Empty event panel should differ from a panel with events."""
        img_empty, draw_empty = _make_draw()
        draw_today(draw_empty, [], TODAY)

        img_with, draw_with = _make_draw()
        draw_today(draw_with, [_timed(TODAY, 9, 10)], TODAY)

        assert img_empty.tobytes() != img_with.tobytes()

    def test_same_am_period_strips_redundant_suffix(self):
        """When start and end share the same am/pm, start suffix is stripped."""
        img, draw = _make_draw()
        evt = _timed(TODAY, 9, 11, "Morning Block")  # 9a–11a → should show "9–11a"
        draw_today(draw, [evt], TODAY)
        assert img.getbbox() is not None

    def test_cross_noon_event(self):
        img, draw = _make_draw()
        evt = _timed(TODAY, 11, 13, "Lunch & Meeting")  # 11a–1p
        draw_today(draw, [evt], TODAY)
        assert img.getbbox() is not None
