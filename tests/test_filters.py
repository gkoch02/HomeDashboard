"""Tests for event filtering (src/filters.py)."""

from __future__ import annotations

from datetime import datetime

from src.config import FilterConfig
from src.data.models import CalendarEvent
from src.filters import filter_events


def _event(
    summary: str = "Meeting",
    calendar_name: str | None = None,
    is_all_day: bool = False,
) -> CalendarEvent:
    return CalendarEvent(
        summary=summary,
        start=datetime(2026, 3, 18, 9, 0),
        end=datetime(2026, 3, 18, 10, 0),
        is_all_day=is_all_day,
        calendar_name=calendar_name,
    )


class TestFilterEvents:
    def test_no_filters_returns_all(self):
        events = [_event("A"), _event("B")]
        result = filter_events(events, FilterConfig())
        assert len(result) == 2

    def test_no_filters_returns_copy(self):
        events = [_event("A")]
        result = filter_events(events, FilterConfig())
        assert result is not events

    def test_exclude_calendar_by_name(self):
        events = [
            _event("Work", calendar_name="Work"),
            _event("Personal", calendar_name="Personal"),
        ]
        result = filter_events(events, FilterConfig(exclude_calendars=["Work"]))
        assert len(result) == 1
        assert result[0].summary == "Personal"

    def test_exclude_calendar_case_insensitive(self):
        events = [_event("Holiday", calendar_name="US Holidays")]
        result = filter_events(events, FilterConfig(exclude_calendars=["holidays"]))
        assert len(result) == 0

    def test_exclude_calendar_substring_match(self):
        events = [_event("Event", calendar_name="US Holidays")]
        result = filter_events(events, FilterConfig(exclude_calendars=["Holiday"]))
        assert len(result) == 0

    def test_exclude_calendar_none_calendar_name(self):
        """Events with calendar_name=None should never be excluded by calendar filter."""
        events = [_event("Meeting", calendar_name=None)]
        result = filter_events(
            events,
            FilterConfig(exclude_calendars=["Anything"]),
        )
        assert len(result) == 1

    def test_exclude_keyword_in_summary(self):
        events = [
            _event("OOO - John"),
            _event("Team Standup"),
        ]
        result = filter_events(events, FilterConfig(exclude_keywords=["OOO"]))
        assert len(result) == 1
        assert result[0].summary == "Team Standup"

    def test_exclude_keyword_case_insensitive(self):
        events = [_event("ooo - vacation")]
        result = filter_events(events, FilterConfig(exclude_keywords=["OOO"]))
        assert len(result) == 0

    def test_exclude_all_day(self):
        events = [
            _event("All Day Event", is_all_day=True),
            _event("Timed Meeting", is_all_day=False),
        ]
        result = filter_events(events, FilterConfig(exclude_all_day=True))
        assert len(result) == 1
        assert result[0].summary == "Timed Meeting"

    def test_combined_filters(self):
        events = [
            _event("OOO", calendar_name="Work"),
            _event("Meeting", calendar_name="Work"),
            _event("All Day", calendar_name="Personal", is_all_day=True),
            _event("Dinner", calendar_name="Personal"),
        ]
        result = filter_events(
            events,
            FilterConfig(
                exclude_keywords=["OOO"],
                exclude_all_day=True,
            ),
        )
        assert len(result) == 2
        summaries = {e.summary for e in result}
        assert summaries == {"Meeting", "Dinner"}

    def test_filter_does_not_modify_original(self):
        events = [_event("OOO"), _event("Meeting")]
        original_len = len(events)
        filter_events(events, FilterConfig(exclude_keywords=["OOO"]))
        assert len(events) == original_len

    def test_multiple_keywords(self):
        events = [
            _event("Focus Time"),
            _event("Block: Deep Work"),
            _event("Standup"),
        ]
        result = filter_events(
            events,
            FilterConfig(exclude_keywords=["Focus", "Block"]),
        )
        assert len(result) == 1
        assert result[0].summary == "Standup"

    def test_empty_events_list(self):
        result = filter_events([], FilterConfig(exclude_keywords=["OOO"]))
        assert result == []
