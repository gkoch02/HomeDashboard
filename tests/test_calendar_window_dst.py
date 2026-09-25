"""The calendar window's end bound must be a local midnight (#258).

``time_max = time_min + timedelta(days=days)`` is ``days × 24 h``, which is
not *days* local days across a DST change. In the US fall-back week
(2026-10-26 → 11-01, New York) the window ended at Sunday 23:00 local, so the
all-day filter's ``win_end_date`` became Sunday and every Sunday all-day
event was dropped, along with timed events after 23:00. Spring-forward has
the mirror problem. Google full sync was unaffected (the API filters
server-side), but the incremental path's ``_filter_to_window`` reproduced
the drop, so the same event appeared on the first tick and vanished once
incremental sync engaged.
"""

from __future__ import annotations

import json
import zoneinfo
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src._time import day_start_utc, event_window_utc
from src.data.models import CalendarEvent
from src.fetchers.calendar_caldav import fetch_from_caldav
from src.fetchers.calendar_google import (
    _SYNC_STATE_FILENAME,
    _ser_sync_event,
    fetch_google_events,
)
from src.fetchers.calendar_ical import fetch_from_ical

NY = zoneinfo.ZoneInfo("America/New_York")
FALL_BACK_WEEK = date(2026, 10, 26)  # Mon; DST ends Sun 2026-11-01 02:00
SPRING_FORWARD_WEEK = date(2027, 3, 8)  # Mon; DST starts Sun 2027-03-14 02:00
PLAIN_WEEK = date(2026, 11, 9)


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------


class TestEventWindowUtc:
    @pytest.mark.parametrize("week", [FALL_BACK_WEEK, SPRING_FORWARD_WEEK, PLAIN_WEEK])
    def test_both_bounds_are_local_midnights(self, week):
        time_min, time_max = event_window_utc(week, 7, NY)
        assert time_min == day_start_utc(week, NY)
        assert time_max.astimezone(NY).time() == datetime.min.time()
        assert time_max.astimezone(NY).date() == week + timedelta(days=7)

    def test_fall_back_week_is_an_hour_longer_than_seven_days(self):
        time_min, time_max = event_window_utc(FALL_BACK_WEEK, 7, NY)
        assert time_max - time_min == timedelta(days=7, hours=1)

    def test_spring_forward_week_is_an_hour_shorter(self):
        time_min, time_max = event_window_utc(SPRING_FORWARD_WEEK, 7, NY)
        assert time_max - time_min == timedelta(days=7) - timedelta(hours=1)

    def test_plain_week_is_exactly_seven_days(self):
        time_min, time_max = event_window_utc(PLAIN_WEEK, 7, NY)
        assert time_max - time_min == timedelta(days=7)


# ---------------------------------------------------------------------------
# ICS
# ---------------------------------------------------------------------------


def _ics(sunday: date) -> str:
    nxt = sunday + timedelta(days=1)
    ymd = sunday.strftime("%Y%m%d")
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:x\r\nX-WR-CALNAME:T\r\n"
        f"BEGIN:VEVENT\r\nUID:a\r\nSUMMARY:Sunday allday\r\n"
        f"DTSTART;VALUE=DATE:{ymd}\r\nDTEND;VALUE=DATE:{nxt.strftime('%Y%m%d')}\r\nEND:VEVENT\r\n"
        f"BEGIN:VEVENT\r\nUID:b\r\nSUMMARY:Sunday late\r\n"
        f"DTSTART;TZID=America/New_York:{ymd}T231500\r\n"
        f"DTEND;TZID=America/New_York:{ymd}T234500\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def _ics_response(text: str):
    resp = MagicMock()
    resp.text = text
    resp.content = text.encode()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


class TestIcsWindow:
    @pytest.mark.parametrize(
        "week", [FALL_BACK_WEEK, SPRING_FORWARD_WEEK, PLAIN_WEEK], ids=["fall", "spring", "plain"]
    )
    @patch("src.fetchers.calendar_ical.requests.get")
    def test_sunday_events_survive_every_week(self, mock_get, week):
        sunday = week + timedelta(days=6)
        mock_get.return_value = _ics_response(_ics(sunday))
        events = fetch_from_ical(["https://x/c.ics"], days=7, start_date=week, tz=NY)
        assert sorted(e.summary for e in events) == ["Sunday allday", "Sunday late"]

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_next_monday_is_still_excluded_after_spring_forward(self, mock_get):
        """The window must not reach into the following Monday either."""
        monday = SPRING_FORWARD_WEEK + timedelta(days=7)
        text = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:x\r\n"
            "BEGIN:VEVENT\r\nUID:m\r\nSUMMARY:Monday early\r\n"
            f"DTSTART;TZID=America/New_York:{monday.strftime('%Y%m%d')}T003000\r\n"
            f"DTEND;TZID=America/New_York:{monday.strftime('%Y%m%d')}T010000\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        mock_get.return_value = _ics_response(text)
        events = fetch_from_ical(["https://x/c.ics"], days=7, start_date=SPRING_FORWARD_WEEK, tz=NY)
        assert events == []


# ---------------------------------------------------------------------------
# Google incremental sync
# ---------------------------------------------------------------------------


class TestGoogleIncrementalWindow:
    def _seed(self, tmp_path, week: date, stored: list[CalendarEvent]) -> None:
        state = {
            "primary": {
                "sync_token": "tok",
                "events": [_ser_sync_event(e) for e in stored],
                "window_start": week.isoformat(),
                "window_end": (week + timedelta(days=7)).isoformat(),
            }
        }
        (tmp_path / _SYNC_STATE_FILENAME).write_text(json.dumps(state))

    def _service(self):
        list_mock = MagicMock()
        list_mock.execute.return_value = {
            "items": [],
            "summary": "Cal",
            "nextSyncToken": "tok2",
        }
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        svc = MagicMock()
        svc.events.return_value = events_mock
        return svc, events_mock

    @pytest.mark.parametrize(
        "week", [FALL_BACK_WEEK, SPRING_FORWARD_WEEK, PLAIN_WEEK], ids=["fall", "spring", "plain"]
    )
    def test_incremental_sync_keeps_sunday_events(self, tmp_path, week):
        from src.config import GoogleConfig

        sunday = week + timedelta(days=6)
        stored = [
            CalendarEvent(
                summary="Sunday allday",
                start=datetime.combine(sunday, datetime.min.time()),
                end=datetime.combine(sunday + timedelta(days=1), datetime.min.time()),
                is_all_day=True,
                calendar_name="Cal",
                event_id="a",
            ),
            CalendarEvent(
                summary="Sunday late",
                start=datetime.combine(sunday, datetime.min.time())
                + timedelta(hours=23, minutes=15),
                end=datetime.combine(sunday, datetime.min.time()) + timedelta(hours=23, minutes=45),
                is_all_day=False,
                calendar_name="Cal",
                event_id="b",
            ),
        ]
        self._seed(tmp_path, week, stored)
        svc, events_mock = self._service()
        with patch("src.fetchers.calendar_google._build_service", return_value=svc):
            events = fetch_google_events(
                GoogleConfig(), days=7, start_date=week, tz=NY, cache_dir=str(tmp_path)
            )

        # It was the incremental path, not a full sync, that produced this.
        assert any("syncToken" in str(c) for c in events_mock.list.call_args_list)
        assert sorted(e.summary for e in events) == ["Sunday allday", "Sunday late"]


# ---------------------------------------------------------------------------
# CalDAV — the server does the filtering, so the bound handed to it is what
# matters.
# ---------------------------------------------------------------------------


class TestCalDavSearchBounds:
    def test_search_end_is_next_monday_local_midnight(self, tmp_path):
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")
        cal = MagicMock()
        cal.name = "Work"
        cal.search.return_value = []
        principal = MagicMock()
        principal.calendars.return_value = [cal]
        client = MagicMock()
        client.principal.return_value = principal
        fake_module = MagicMock()
        fake_module.DAVClient = MagicMock(return_value=client)

        with patch.dict("sys.modules", {"caldav": fake_module}):
            fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
                days=7,
                start_date=FALL_BACK_WEEK,
                tz=NY,
            )

        kwargs = cal.search.call_args.kwargs
        end_local = kwargs["end"].astimezone(NY)
        assert end_local == datetime(2026, 11, 2, 0, 0, tzinfo=NY)
