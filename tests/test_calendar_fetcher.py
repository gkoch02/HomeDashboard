"""Tests for src/fetchers/calendar.py"""

from __future__ import annotations

import json
import tempfile
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import BirthdayConfig, GoogleConfig
from src.fetchers.calendar import (
    _apply_delta,
    _days_until,
    _fetch_full,
    _fetch_incremental,
    _filter_to_window,
    _load_sync_state,
    _parse_birthday_entry,
    _parse_contact_birthday,
    _parse_event,
    _save_sync_state,
    _ser_sync_event,
    fetch_birthdays,
)

# ---------------------------------------------------------------------------
# _parse_birthday_entry
# ---------------------------------------------------------------------------


class TestParseBirthdayEntry:
    def setup_method(self):
        self.today = date(2024, 3, 15)
        self.lookahead = self.today + timedelta(days=30)

    def test_full_date_upcoming(self):
        entry = {"name": "Alice", "date": "1990-03-20"}
        result = _parse_birthday_entry(entry, self.today, self.lookahead)
        assert result is not None
        assert result.name == "Alice"
        assert result.date == date(2024, 3, 20)
        assert result.age == 34

    def test_month_day_only(self):
        entry = {"name": "Bob", "date": "03-25"}
        result = _parse_birthday_entry(entry, self.today, self.lookahead)
        assert result is not None
        assert result.date == date(2024, 3, 25)
        assert result.age is None

    def test_past_date_rolls_to_next_year(self):
        entry = {"name": "Carol", "date": "1985-03-01"}  # already passed in 2024
        far_lookahead = self.today + timedelta(days=400)
        result = _parse_birthday_entry(entry, self.today, far_lookahead)
        assert result is not None
        assert result.date.year == 2025
        assert result.age == 40

    def test_outside_lookahead_returns_none(self):
        entry = {"name": "Dave", "date": "06-01"}  # ~78 days away
        result = _parse_birthday_entry(entry, self.today, self.lookahead)
        assert result is None

    def test_invalid_format_raises(self):
        entry = {"name": "Eve", "date": "March 15"}
        with pytest.raises(ValueError):
            _parse_birthday_entry(entry, self.today, self.lookahead)


# ---------------------------------------------------------------------------
# _days_until
# ---------------------------------------------------------------------------


class TestDaysUntil:
    def test_future(self):
        today = date(2024, 3, 15)
        future = date(2024, 3, 20)
        assert _days_until(future, today) == 5

    def test_same_day(self):
        today = date(2024, 3, 15)
        assert _days_until(today, today) == 0

    def test_past_wraps(self):
        today = date(2024, 3, 15)
        past = date(2024, 3, 10)
        assert _days_until(past, today) == 360  # 365 - 5


# ---------------------------------------------------------------------------
# _parse_event
# ---------------------------------------------------------------------------


class TestParseEvent:
    def test_timed_event(self):
        item = {
            "summary": "Team Standup",
            "start": {"dateTime": "2024-03-15T09:00:00-05:00"},
            "end": {"dateTime": "2024-03-15T09:30:00-05:00"},
        }
        result = _parse_event(item, "Work")
        assert result is not None
        assert result.summary == "Team Standup"
        assert result.is_all_day is False
        assert result.calendar_name == "Work"

    def test_all_day_event(self):
        item = {
            "summary": "Conference",
            "start": {"date": "2024-03-20"},
            "end": {"date": "2024-03-21"},
        }
        result = _parse_event(item, "Work")
        assert result is not None
        assert result.is_all_day is True

    def test_missing_time_returns_none(self):
        item = {"summary": "Weird event", "start": {}, "end": {}}
        result = _parse_event(item, "Cal")
        assert result is None

    def test_missing_summary_defaults(self):
        item = {
            "start": {"date": "2024-03-20"},
            "end": {"date": "2024-03-21"},
        }
        result = _parse_event(item, "Cal")
        assert result is not None
        assert result.summary == "(no title)"

    def test_timed_event_converted_to_local_tz(self):
        # Event at UTC midnight = March 14 23:00 in EST (UTC-5)
        item = {
            "summary": "Late Event",
            "start": {"dateTime": "2024-03-15T00:00:00+00:00"},
            "end": {"dateTime": "2024-03-15T01:00:00+00:00"},
        }
        est = zoneinfo.ZoneInfo("America/New_York")
        result = _parse_event(item, "Cal", tz=est)
        assert result is not None
        assert result.start.tzinfo is None  # stripped to naive
        assert result.start.date() == date(2024, 3, 14)  # local date in EST

    def test_timed_event_no_tz_preserves_aware(self):
        item = {
            "summary": "Event",
            "start": {"dateTime": "2024-03-15T09:00:00-05:00"},
            "end": {"dateTime": "2024-03-15T10:00:00-05:00"},
        }
        result = _parse_event(item, "Cal", tz=None)
        assert result is not None
        assert result.start.tzinfo is not None  # tz-aware preserved when no local tz given


# ---------------------------------------------------------------------------
# fetch_birthdays from file
# ---------------------------------------------------------------------------


class TestFetchBirthdaysFromFile:
    def test_loads_valid_file(self):
        today = date.today()
        upcoming = today + timedelta(days=5)
        entries = [{"name": "Alice", "date": upcoming.strftime("%m-%d")}]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(entries, f)
            tmp_path = f.name

        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="file", file_path=tmp_path, lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)

        assert len(results) == 1
        assert results[0].name == "Alice"

    def test_missing_file_returns_empty(self):
        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="file", file_path="/nonexistent/path.json")
        results = fetch_birthdays(cfg_google, cfg_bday)
        assert results == []

    def test_skips_malformed_entries(self):
        today = date.today()
        upcoming = today + timedelta(days=5)
        entries = [
            {"name": "Good", "date": upcoming.strftime("%m-%d")},
            {"name": "Bad"},  # missing date key
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(entries, f)
            tmp_path = f.name

        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="file", file_path=tmp_path, lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)
        assert len(results) == 1
        assert results[0].name == "Good"


# ---------------------------------------------------------------------------
# _parse_contact_birthday
# ---------------------------------------------------------------------------


class TestParseContactBirthday:
    def setup_method(self):
        self.today = date(2024, 3, 15)
        self.lookahead = self.today + timedelta(days=30)

    def _person(self, name: str, month: int, day: int, year: int = 0) -> dict:
        bday_date: dict = {"month": month, "day": day}
        if year:
            bday_date["year"] = year
        return {
            "names": [{"displayName": name}],
            "birthdays": [{"date": bday_date}],
        }

    def test_upcoming_with_year(self):
        person = self._person("Alice", 3, 20, year=1990)
        result = _parse_contact_birthday(person, self.today, self.lookahead)
        assert result is not None
        assert result.name == "Alice"
        assert result.date == date(2024, 3, 20)
        assert result.age == 34

    def test_upcoming_without_year(self):
        person = self._person("Bob", 3, 25)
        result = _parse_contact_birthday(person, self.today, self.lookahead)
        assert result is not None
        assert result.date == date(2024, 3, 25)
        assert result.age is None

    def test_past_rolls_to_next_year(self):
        person = self._person("Carol", 3, 1, year=1985)
        far_lookahead = self.today + timedelta(days=400)
        result = _parse_contact_birthday(person, self.today, far_lookahead)
        assert result is not None
        assert result.date.year == 2025
        assert result.age == 40

    def test_outside_lookahead_returns_none(self):
        person = self._person("Dave", 6, 1)
        result = _parse_contact_birthday(person, self.today, self.lookahead)
        assert result is None

    def test_no_names_returns_none(self):
        person = {"names": [], "birthdays": [{"date": {"month": 3, "day": 20}}]}
        assert _parse_contact_birthday(person, self.today, self.lookahead) is None

    def test_no_birthdays_returns_none(self):
        person = {"names": [{"displayName": "Alice"}], "birthdays": []}
        assert _parse_contact_birthday(person, self.today, self.lookahead) is None

    def test_birthday_missing_month_returns_none(self):
        person = {"names": [{"displayName": "Alice"}], "birthdays": [{"date": {"day": 15}}]}
        assert _parse_contact_birthday(person, self.today, self.lookahead) is None

    def test_birthday_missing_day_returns_none(self):
        person = {"names": [{"displayName": "Alice"}], "birthdays": [{"date": {"month": 3}}]}
        assert _parse_contact_birthday(person, self.today, self.lookahead) is None

    def test_year_zero_treated_as_no_year(self):
        # Some Google Contacts entries have year=0 instead of omitting the field
        person = self._person("Eve", 3, 20, year=0)
        result = _parse_contact_birthday(person, self.today, self.lookahead)
        assert result is not None
        assert result.age is None


# ---------------------------------------------------------------------------
# fetch_birthdays from contacts (mocked People API)
# ---------------------------------------------------------------------------


class TestFetchBirthdaysFromContacts:
    def _make_connections_response(
        self,
        connections: list,
        next_page_token: str | None = None,
    ) -> dict:
        result: dict = {"connections": connections}
        if next_page_token:
            result["nextPageToken"] = next_page_token
        return result

    def _person(self, name: str, month: int, day: int, year: int = 0) -> dict:
        bday_date: dict = {"month": month, "day": day}
        if year:
            bday_date["year"] = year
        return {
            "names": [{"displayName": name}],
            "birthdays": [{"date": bday_date}],
        }

    @patch("src.fetchers.calendar._build_people_service")
    def test_returns_upcoming_birthdays(self, mock_build):
        today = date.today()
        upcoming = today + timedelta(days=5)

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.people().connections().list().execute.return_value = (
            self._make_connections_response(
                [
                    self._person("Alice", upcoming.month, upcoming.day, year=1990),
                ]
            )
        )

        cfg_google = GoogleConfig(contacts_email="user@example.com")
        cfg_bday = BirthdayConfig(source="contacts", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)

        assert len(results) == 1
        assert results[0].name == "Alice"

    @patch("src.fetchers.calendar._build_people_service")
    def test_skips_contacts_without_birthday(self, mock_build):
        today = date.today()
        upcoming = today + timedelta(days=5)

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.people().connections().list().execute.return_value = (
            self._make_connections_response(
                [
                    {"names": [{"displayName": "No Birthday"}], "birthdays": []},
                    self._person("Alice", upcoming.month, upcoming.day),
                ]
            )
        )

        cfg_google = GoogleConfig(contacts_email="user@example.com")
        cfg_bday = BirthdayConfig(source="contacts", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)

        assert len(results) == 1
        assert results[0].name == "Alice"

    @patch("src.fetchers.calendar._build_people_service")
    def test_api_failure_propagates(self, mock_build):
        """Regression for issue #146: an API failure must propagate so the
        pipeline falls back to cached birthdays instead of overwriting the
        cache with an empty (or, mid-pagination, partial) list."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.people().connections().list().execute.side_effect = Exception("API error")

        cfg_google = GoogleConfig(contacts_email="user@example.com")
        cfg_bday = BirthdayConfig(source="contacts", lookahead_days=30)
        with pytest.raises(Exception, match="API error"):
            fetch_birthdays(cfg_google, cfg_bday)

    @patch("src.fetchers.calendar._build_people_service")
    def test_partial_pagination_failure_propagates(self, mock_build):
        """Regression for issue #146: when a later pagination page fails, the
        earlier pages' contacts must NOT be silently committed to cache via
        ``break`` — propagate instead so the pipeline preserves the previous
        complete list."""
        today = date.today()
        upcoming = today + timedelta(days=5)

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        page1 = {
            "connections": [self._person("Alice", upcoming.month, upcoming.day)],
            "nextPageToken": "token123",
        }
        mock_service.people().connections().list().execute.side_effect = [
            page1,
            Exception("network timeout on page 2"),
        ]

        cfg_google = GoogleConfig(contacts_email="user@example.com")
        cfg_bday = BirthdayConfig(source="contacts", lookahead_days=30)
        with pytest.raises(Exception, match="network timeout on page 2"):
            fetch_birthdays(cfg_google, cfg_bday)

    @patch("src.fetchers.calendar._build_people_service")
    def test_pagination(self, mock_build):
        today = date.today()
        d1 = today + timedelta(days=3)
        d2 = today + timedelta(days=7)

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        page1 = self._make_connections_response(
            [self._person("Alice", d1.month, d1.day)],
            next_page_token="token123",
        )
        page2 = self._make_connections_response(
            [self._person("Bob", d2.month, d2.day)],
        )

        mock_service.people().connections().list().execute.side_effect = [page1, page2]

        cfg_google = GoogleConfig(contacts_email="user@example.com")
        cfg_bday = BirthdayConfig(source="contacts", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)

        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"Alice", "Bob"}


# ---------------------------------------------------------------------------
# _parse_contact_birthday — empty display name
# ---------------------------------------------------------------------------


class TestParseContactBirthdayEmptyName:
    def test_empty_display_name_returns_none(self):
        today = date(2024, 3, 15)
        lookahead = today + timedelta(days=30)
        person = {
            "names": [{"displayName": "   "}],  # whitespace-only → stripped to ""
            "birthdays": [{"date": {"month": 3, "day": 20}}],
        }
        assert _parse_contact_birthday(person, today, lookahead) is None


# ---------------------------------------------------------------------------
# _fetch_full — pagination and exception
# ---------------------------------------------------------------------------


class TestFetchFull:
    def _make_service(self, pages: list[dict]):
        """Build a mock service that returns pages in sequence."""
        svc = MagicMock()
        svc.events().list().execute.side_effect = pages
        return svc

    def test_single_page_returns_events(self):
        page = {
            "summary": "Work",
            "items": [
                {
                    "id": "e1",
                    "summary": "Standup",
                    "start": {"dateTime": "2024-03-15T09:00:00+00:00"},
                    "end": {"dateTime": "2024-03-15T09:30:00+00:00"},
                }
            ],
            "nextSyncToken": "tok1",
        }
        svc = self._make_service([page])
        time_min = datetime(2024, 3, 11, tzinfo=timezone.utc)
        time_max = datetime(2024, 3, 18, tzinfo=timezone.utc)
        events, cal_name, token = _fetch_full(svc, "primary", time_min, time_max)
        assert len(events) == 1
        assert events[0].summary == "Standup"
        assert cal_name == "Work"
        assert token == "tok1"

    def test_multi_page_aggregates_all_events(self):
        page1 = {
            "summary": "Cal",
            "items": [
                {
                    "id": "e1",
                    "summary": "Event 1",
                    "start": {"dateTime": "2024-03-15T09:00:00+00:00"},
                    "end": {"dateTime": "2024-03-15T10:00:00+00:00"},
                }
            ],
            "nextPageToken": "page2",
        }
        page2 = {
            "summary": "Cal",
            "items": [
                {
                    "id": "e2",
                    "summary": "Event 2",
                    "start": {"dateTime": "2024-03-16T09:00:00+00:00"},
                    "end": {"dateTime": "2024-03-16T10:00:00+00:00"},
                }
            ],
            "nextSyncToken": "tok_final",
        }
        svc = self._make_service([page1, page2])
        time_min = datetime(2024, 3, 11, tzinfo=timezone.utc)
        time_max = datetime(2024, 3, 18, tzinfo=timezone.utc)
        events, _, token = _fetch_full(svc, "primary", time_min, time_max)
        assert len(events) == 2
        assert token == "tok_final"

    def test_api_exception_propagates(self):
        """If the API call raises, _fetch_full propagates the exception so the
        caller can fall back to cached data instead of overwriting it with an
        empty list (issue #145)."""
        svc = MagicMock()
        svc.events().list().execute.side_effect = Exception("network error")
        time_min = datetime(2024, 3, 11, tzinfo=timezone.utc)
        time_max = datetime(2024, 3, 18, tzinfo=timezone.utc)
        with pytest.raises(Exception, match="network error"):
            _fetch_full(svc, "primary", time_min, time_max)


# ---------------------------------------------------------------------------
# _fetch_incremental — multi-page and generic exception
# ---------------------------------------------------------------------------


class TestFetchIncremental:
    def test_multi_page_aggregates_delta(self):
        page1 = {
            "summary": "Cal",
            "items": [
                {
                    "id": "e1",
                    "summary": "Evt1",
                    "start": {"dateTime": "2024-03-15T09:00:00+00:00"},
                    "end": {"dateTime": "2024-03-15T10:00:00+00:00"},
                }
            ],
            "nextPageToken": "page2",
        }
        page2 = {
            "summary": "Cal",
            "items": [
                {
                    "id": "e2",
                    "summary": "Evt2",
                    "start": {"dateTime": "2024-03-16T09:00:00+00:00"},
                    "end": {"dateTime": "2024-03-16T10:00:00+00:00"},
                }
            ],
            "nextSyncToken": "newtok",
        }
        svc = MagicMock()
        svc.events().list().execute.side_effect = [page1, page2]
        delta, cal_name, new_token, needs_reset = _fetch_incremental(svc, "primary", "oldtok")
        assert len(delta) == 2
        assert new_token == "newtok"
        assert needs_reset is False

    def test_generic_exception_triggers_reset(self):
        svc = MagicMock()
        svc.events().list().execute.side_effect = Exception("timeout")
        delta, _, _, needs_reset = _fetch_incremental(svc, "primary", "tok")
        assert needs_reset is True
        assert delta == []


# ---------------------------------------------------------------------------
# _filter_to_window — tz and all-day edge cases
# ---------------------------------------------------------------------------


class TestFilterToWindowExtended:
    def test_uses_tz_to_localise_window(self):
        """When tz is given, window bounds are converted to local time."""
        est = zoneinfo.ZoneInfo("America/New_York")
        # UTC window: Mon 05:00 → next Mon 05:00 (i.e. Mon 00:00 → Sun 23:59 EST)
        week_start = datetime(2024, 3, 11, 5, 0, tzinfo=timezone.utc)
        week_end = week_start + timedelta(days=7)

        # Event at Wed 09:00 EST (naive) — within window
        from src.data.models import CalendarEvent

        event = CalendarEvent(
            summary="In Window",
            start=datetime(2024, 3, 13, 9, 0),
            end=datetime(2024, 3, 13, 10, 0),
            event_id="e1",
        )
        stored = [_ser_sync_event(event)]
        result = _filter_to_window(stored, week_start, week_end, tz=est)
        assert len(result) == 1

    def test_tz_aware_timed_event_compared_in_utc(self):
        """Timezone-aware timed events are compared directly against UTC window."""
        week_start = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)
        week_end = week_start + timedelta(days=7)

        from src.data.models import CalendarEvent

        # tz-aware event inside window
        event = CalendarEvent(
            summary="Aware Event",
            start=datetime(2024, 3, 13, 9, 0, tzinfo=timezone.utc),
            end=datetime(2024, 3, 13, 10, 0, tzinfo=timezone.utc),
            event_id="e1",
        )
        stored = [_ser_sync_event(event)]
        result = _filter_to_window(stored, week_start, week_end)
        assert len(result) == 1

    def test_all_day_event_at_window_boundary(self):
        """All-day event that ends exactly at window start should be excluded."""
        week_start = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)
        week_end = week_start + timedelta(days=7)

        from src.data.models import CalendarEvent

        # All-day event ending on the window start date is outside
        event = CalendarEvent(
            summary="Ends at window start",
            start=datetime(2024, 3, 9, 0, 0),
            end=datetime(2024, 3, 11, 0, 0),
            is_all_day=True,
            event_id="e1",
        )
        stored = [_ser_sync_event(event)]
        result = _filter_to_window(stored, week_start, week_end)
        assert len(result) == 0

    def test_all_day_event_inside_window_is_included(self):
        """All-day event fully inside the window should be included."""
        week_start = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)
        week_end = week_start + timedelta(days=7)

        from src.data.models import CalendarEvent

        event = CalendarEvent(
            summary="Conference",
            start=datetime(2024, 3, 13, 0, 0),
            end=datetime(2024, 3, 15, 0, 0),
            is_all_day=True,
            event_id="e1",
        )
        stored = [_ser_sync_event(event)]
        result = _filter_to_window(stored, week_start, week_end)
        assert len(result) == 1
        assert result[0].summary == "Conference"


# ---------------------------------------------------------------------------
# _apply_delta — delta item without an ID
# ---------------------------------------------------------------------------


class TestApplyDeltaNoId:
    def test_delta_item_without_id_is_skipped(self):
        """Delta items missing an 'id' field should be silently ignored."""
        stored = []
        item_no_id = {
            "summary": "Ghost Event",
            "start": {"dateTime": "2024-03-15T09:00:00+00:00"},
            "end": {"dateTime": "2024-03-15T10:00:00+00:00"},
            # no "id" key
        }
        merged = _apply_delta(stored, [item_no_id], "Cal")
        assert merged == []


# ---------------------------------------------------------------------------
# _save_sync_state — exception path
# ---------------------------------------------------------------------------


class TestSaveSyncStateException:
    def test_write_failure_logs_warning(self, caplog):
        import logging

        with tempfile.TemporaryDirectory() as tmpdir:
            with caplog.at_level(logging.WARNING, logger="src.fetchers.calendar"):
                with patch("tempfile.mkstemp", side_effect=OSError("disk full")):
                    _save_sync_state({"primary": {}}, tmpdir)
        assert "Sync state write failed" in caplog.text


class TestLoadSyncStateCorrupt:
    def test_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "calendar_sync_state.json"
            state_file.write_text("{ not valid json }")
            result = _load_sync_state(tmpdir)
            assert result == {}


class TestFetchIncrementalNon410HttpError:
    def test_non_410_http_error_triggers_reset(self):
        from googleapiclient.errors import HttpError

        svc = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 500  # server error, not 410
        svc.events().list().execute.side_effect = HttpError(mock_resp, b"Server Error")
        delta, _, _, needs_reset = _fetch_incremental(svc, "primary", "tok")
        assert needs_reset is True
        assert delta == []


class TestFetchEventsIncrementalReset:
    @patch("src.fetchers.calendar_google._build_service")
    def test_expired_sync_token_falls_back_to_full_sync(self, mock_build):
        """When incremental sync returns needs_reset=True, full sync is performed."""
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        event_start = datetime.combine(
            monday + timedelta(days=1),
            datetime.min.time().replace(hour=9),
        )

        event_end_iso = (event_start + timedelta(hours=1)).replace(tzinfo=timezone.utc).isoformat()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Full sync response — used both for initial and for the reset
        full_resp = {
            "summary": "Work",
            "items": [
                {
                    "id": "e1",
                    "summary": "Meeting",
                    "start": {"dateTime": event_start.replace(tzinfo=timezone.utc).isoformat()},
                    "end": {"dateTime": event_end_iso},
                }
            ],
            "nextSyncToken": "tok_full",
        }

        # Incremental response — 410 Gone triggers reset
        from googleapiclient.errors import HttpError

        gone_resp = MagicMock()
        gone_resp.status = 410
        http_error = HttpError(gone_resp, b"Gone")

        mock_service.events().list().execute.side_effect = [full_resp, http_error, full_resp]

        from src.fetchers.calendar import fetch_events

        cfg = GoogleConfig()
        with tempfile.TemporaryDirectory() as tmpdir:
            # First call — full sync, stores token
            events1 = fetch_events(cfg, cache_dir=tmpdir)
            # Second call — incremental with expired token → reset → full sync again
            events2 = fetch_events(cfg, cache_dir=tmpdir)

        assert len(events1) == 1
        assert len(events2) == 1


# ---------------------------------------------------------------------------
# _birthdays_from_file — corrupt file
# ---------------------------------------------------------------------------


class TestTodayWithTimezone:
    def test_today_with_tz_returns_local_date(self):
        import zoneinfo

        from src.fetchers.calendar import _today

        tz = zoneinfo.ZoneInfo("America/New_York")
        result = _today(tz)
        from datetime import datetime

        expected = datetime.now(tz).date()
        assert result == expected

    def test_today_without_tz_returns_system_date(self):
        from datetime import date

        from src.fetchers.calendar import _today

        result = _today(None)
        assert result == date.today()


class TestBirthdaysFromFileCorrupt:
    def test_corrupt_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ not valid json }")
            tmp_path = f.name

        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="file", file_path=tmp_path, lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)
        assert results == []


# ---------------------------------------------------------------------------
# _birthdays_from_calendar — mocked service
# ---------------------------------------------------------------------------


class TestBirthdaysFromCalendar:
    @patch("src.fetchers.calendar._build_service")
    def test_returns_matching_birthday_events(self, mock_build):
        today = date.today()
        upcoming = today + timedelta(days=5)

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "Alice's Birthday",
                    "start": {"date": upcoming.isoformat()},
                    "end": {"date": (upcoming + timedelta(days=1)).isoformat()},
                }
            ]
        }

        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="calendar", calendar_keyword="Birthday", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)

        assert len(results) == 1
        assert results[0].name == "Alice"

    @patch("src.fetchers.calendar._build_service")
    def test_api_failure_propagates(self, mock_build):
        """Regression for issue #146: an API failure must propagate so the
        pipeline falls back to cached birthdays instead of overwriting the
        cache with an empty list that blanks the birthday panel."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.side_effect = Exception("API down")

        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="calendar", lookahead_days=30)
        with pytest.raises(Exception, match="API down"):
            fetch_birthdays(cfg_google, cfg_bday)

    @patch("src.fetchers.calendar._build_service")
    def test_skips_non_matching_events(self, mock_build):
        """Events not matching the keyword are skipped (continue branch)."""
        today = date.today()
        upcoming = today + timedelta(days=5)

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "Team Lunch",  # does NOT contain "Birthday"
                    "start": {"date": upcoming.isoformat()},
                    "end": {"date": (upcoming + timedelta(days=1)).isoformat()},
                }
            ]
        }

        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="calendar", calendar_keyword="Birthday", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)
        assert results == []

    @patch("src.fetchers.calendar._build_service")
    def test_skips_events_without_date(self, mock_build):
        """Events matching keyword but without a date field are ignored."""
        today = date.today()
        upcoming = today + timedelta(days=5)

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {
                    # keyword matches but start is a dateTime, not a date
                    "summary": "Alice Birthday Party",
                    "start": {"dateTime": upcoming.isoformat() + "T09:00:00"},
                    "end": {"dateTime": upcoming.isoformat() + "T10:00:00"},
                }
            ]
        }

        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="calendar", calendar_keyword="Birthday", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)
        assert results == []


# ---------------------------------------------------------------------------
# fetch_events — full integration with mocked service
# ---------------------------------------------------------------------------


class TestFetchEventsIntegration:
    @patch("src.fetchers.calendar_google._build_service")
    def test_fetch_events_returns_events(self, mock_build):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        event_start = datetime.combine(
            monday + timedelta(days=1),
            datetime.min.time().replace(hour=9),
        )

        event_end_iso = (event_start + timedelta(hours=1)).replace(tzinfo=timezone.utc).isoformat()
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "summary": "Work",
            "items": [
                {
                    "id": "e1",
                    "summary": "Team Meeting",
                    "start": {"dateTime": event_start.replace(tzinfo=timezone.utc).isoformat()},
                    "end": {"dateTime": event_end_iso},
                }
            ],
            "nextSyncToken": "tok1",
        }

        from src.fetchers.calendar import fetch_events

        cfg = GoogleConfig()
        with tempfile.TemporaryDirectory() as tmpdir:
            events = fetch_events(cfg, cache_dir=tmpdir)

        assert len(events) == 1
        assert events[0].summary == "Team Meeting"

    @patch("src.fetchers.calendar_google._build_service")
    def test_fetch_events_uses_incremental_sync_on_second_call(self, mock_build):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        event_start = datetime.combine(
            monday + timedelta(days=1),
            datetime.min.time().replace(hour=9),
        )

        event_end_iso = (event_start + timedelta(hours=1)).replace(tzinfo=timezone.utc).isoformat()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        full_resp = {
            "summary": "Work",
            "items": [
                {
                    "id": "e1",
                    "summary": "Initial Event",
                    "start": {"dateTime": event_start.replace(tzinfo=timezone.utc).isoformat()},
                    "end": {"dateTime": event_end_iso},
                }
            ],
            "nextSyncToken": "tok_after_full",
        }
        incremental_resp = {
            "summary": "Work",
            "items": [],
            "nextSyncToken": "tok_after_incremental",
        }
        mock_service.events().list().execute.side_effect = [full_resp, incremental_resp]

        from src.fetchers.calendar import fetch_events

        cfg = GoogleConfig()
        with tempfile.TemporaryDirectory() as tmpdir:
            # First call — full sync
            events1 = fetch_events(cfg, cache_dir=tmpdir)
            # Second call — incremental
            fetch_events(cfg, cache_dir=tmpdir)

        assert len(events1) == 1
        # Incremental sync: no new events, but stored event still in window
        assert mock_service.events().list().execute.call_count == 2

    @patch("src.fetchers.calendar_google._build_service")
    def test_fetch_events_window_change_forces_full_sync(self, mock_build):
        monday = date(2026, 4, 6)
        event_start = datetime.combine(
            monday + timedelta(days=1), datetime.min.time().replace(hour=9)
        )
        event_end_iso = (event_start + timedelta(hours=1)).replace(tzinfo=timezone.utc).isoformat()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        weekly_full = {
            "summary": "Work",
            "items": [
                {
                    "id": "e1",
                    "summary": "Weekly Event",
                    "start": {"dateTime": event_start.replace(tzinfo=timezone.utc).isoformat()},
                    "end": {"dateTime": event_end_iso},
                }
            ],
            "nextSyncToken": "tok_week",
        }
        monthly_full = {
            "summary": "Work",
            "items": [
                {
                    "id": "e2",
                    "summary": "Monthly Event",
                    "start": {"dateTime": event_start.replace(tzinfo=timezone.utc).isoformat()},
                    "end": {"dateTime": event_end_iso},
                }
            ],
            "nextSyncToken": "tok_month",
        }
        mock_service.events().list().execute.side_effect = [weekly_full, monthly_full]

        from src.fetchers.calendar import fetch_events

        cfg = GoogleConfig()
        with tempfile.TemporaryDirectory() as tmpdir:
            fetch_events(cfg, start_date=monday, days=7, cache_dir=tmpdir)
            events = fetch_events(cfg, start_date=date(2026, 3, 29), days=35, cache_dir=tmpdir)

        assert len(events) == 1
        assert events[0].summary == "Monthly Event"
        assert mock_service.events().list().execute.call_count == 2


# ---------------------------------------------------------------------------
# ICS feed fetching
# ---------------------------------------------------------------------------


def _make_ics(events_text: str, cal_name: str = "Test Calendar") -> str:
    """Wrap one or more VEVENT blocks in a minimal VCALENDAR envelope."""
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        f"X-WR-CALNAME:{cal_name}\r\n"
        f"{events_text}"
        "END:VCALENDAR\r\n"
    )


def _timed_vevent(
    uid: str,
    summary: str,
    dtstart: str,
    dtend: str,
    location: str = "",
) -> str:
    lines = (
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\nDTSTART:{dtstart}\r\nDTEND:{dtend}\r\n"
    )
    if location:
        lines += f"LOCATION:{location}\r\n"
    lines += "END:VEVENT\r\n"
    return lines


def _allday_vevent(uid: str, summary: str, dtstart: str, dtend: str) -> str:
    return (
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"SUMMARY:{summary}\r\n"
        f"DTSTART;VALUE=DATE:{dtstart}\r\n"
        f"DTEND;VALUE=DATE:{dtend}\r\n"
        "END:VEVENT\r\n"
    )


class TestICalFetcher:
    """Tests for ICS-feed-based calendar fetching."""

    def _make_response(self, ics_text: str):
        mock_resp = MagicMock()
        mock_resp.text = ics_text
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def _this_monday(self, tz=None):
        from src.fetchers.calendar import _today

        today = _today(tz)
        return today - timedelta(days=today.weekday())

    # --- Basic timed event ---

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_timed_event_parsed(self, mock_get):
        tz = zoneinfo.ZoneInfo("America/New_York")
        monday = self._this_monday(tz)
        tuesday = monday + timedelta(days=1)

        dtstart = datetime.combine(tuesday, datetime.min.time().replace(hour=9)).replace(tzinfo=tz)
        dtend = dtstart + timedelta(hours=1)
        # ICS format: YYYYMMDDTHHMMSSZ (UTC) or with TZID
        dtstart_str = dtstart.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dtend_str = dtend.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        ics = _make_ics(
            _timed_vevent("uid1", "Team Standup", dtstart_str, dtend_str, location="Zoom"),
            cal_name="Work",
        )
        mock_get.return_value = self._make_response(ics)

        cfg = GoogleConfig(ical_url="https://example.com/cal.ics")
        from src.fetchers.calendar import fetch_events

        events = fetch_events(cfg, tz=tz)

        assert len(events) == 1
        assert events[0].summary == "Team Standup"
        assert events[0].location == "Zoom"
        assert events[0].calendar_name == "Work"
        assert events[0].is_all_day is False
        assert events[0].start.tzinfo is None  # must be naive local

    # --- All-day event ---

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_allday_event_parsed(self, mock_get):
        tz = zoneinfo.ZoneInfo("America/New_York")
        monday = self._this_monday(tz)
        wednesday = monday + timedelta(days=2)

        ics = _make_ics(
            _allday_vevent(
                "uid2",
                "Company Holiday",
                wednesday.strftime("%Y%m%d"),
                (wednesday + timedelta(days=1)).strftime("%Y%m%d"),
            )
        )
        mock_get.return_value = self._make_response(ics)

        cfg = GoogleConfig(ical_url="https://example.com/cal.ics")
        from src.fetchers.calendar import fetch_events

        events = fetch_events(cfg, tz=tz)

        assert len(events) == 1
        assert events[0].summary == "Company Holiday"
        assert events[0].is_all_day is True

    # --- Event outside the week window is filtered out ---

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_event_outside_window_excluded(self, mock_get):
        tz = zoneinfo.ZoneInfo("America/New_York")
        monday = self._this_monday(tz)
        far_future = monday + timedelta(days=30)

        dtstart = datetime.combine(far_future, datetime.min.time().replace(hour=10)).replace(
            tzinfo=tz
        )
        dtend = dtstart + timedelta(hours=1)
        dtstart_str = dtstart.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dtend_str = dtend.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        ics = _make_ics(_timed_vevent("uid3", "Far Future Event", dtstart_str, dtend_str))
        mock_get.return_value = self._make_response(ics)

        cfg = GoogleConfig(ical_url="https://example.com/cal.ics")
        from src.fetchers.calendar import fetch_events

        events = fetch_events(cfg, tz=tz)

        assert events == []

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_event_inside_custom_start_date_window_included(self, mock_get):
        tz = zoneinfo.ZoneInfo("America/New_York")
        start_date = date(2026, 3, 29)
        inside = start_date + timedelta(days=20)

        dtstart = datetime.combine(inside, datetime.min.time().replace(hour=10)).replace(tzinfo=tz)
        dtend = dtstart + timedelta(hours=1)
        dtstart_str = dtstart.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dtend_str = dtend.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        ics = _make_ics(_timed_vevent("uid-custom", "Monthly Window Event", dtstart_str, dtend_str))
        mock_get.return_value = self._make_response(ics)

        cfg = GoogleConfig(ical_url="https://example.com/cal.ics")
        from src.fetchers.calendar import fetch_events

        events = fetch_events(cfg, start_date=start_date, days=35, tz=tz)

        assert len(events) == 1
        assert events[0].summary == "Monthly Window Event"

    # --- X-WR-CALNAME used as calendar_name ---

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_cal_name_from_xwrcalname(self, mock_get):
        tz = zoneinfo.ZoneInfo("America/New_York")
        monday = self._this_monday(tz)
        thursday = monday + timedelta(days=3)

        dtstart = datetime.combine(thursday, datetime.min.time().replace(hour=14)).replace(
            tzinfo=tz
        )
        dtend = dtstart + timedelta(hours=1)
        dtstart_str = dtstart.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dtend_str = dtend.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        ics = _make_ics(
            _timed_vevent("uid4", "Planning", dtstart_str, dtend_str),
            cal_name="My Personal Calendar",
        )
        mock_get.return_value = self._make_response(ics)

        cfg = GoogleConfig(ical_url="https://example.com/cal.ics")
        from src.fetchers.calendar import fetch_events

        events = fetch_events(cfg, tz=tz)

        assert len(events) == 1
        assert events[0].calendar_name == "My Personal Calendar"

    # --- Hostname fallback when no X-WR-CALNAME ---

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_cal_name_hostname_fallback(self, mock_get):
        tz = zoneinfo.ZoneInfo("America/New_York")
        monday = self._this_monday(tz)
        friday = monday + timedelta(days=4)

        dtstart = datetime.combine(friday, datetime.min.time().replace(hour=11)).replace(tzinfo=tz)
        dtend = dtstart + timedelta(hours=1)
        dtstart_str = dtstart.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dtend_str = dtend.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            + _timed_vevent("uid5", "Meeting", dtstart_str, dtend_str)
            + "END:VCALENDAR\r\n"
        )
        mock_get.return_value = self._make_response(ics)

        cfg = GoogleConfig(ical_url="https://calendar.google.com/calendar/ical/abc/basic.ics")
        from src.fetchers.calendar import fetch_events

        events = fetch_events(cfg, tz=tz)

        assert len(events) == 1
        assert events[0].calendar_name == "calendar.google.com"

    # --- Multiple URLs merged and sorted ---

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_multiple_urls_merged(self, mock_get):
        tz = zoneinfo.ZoneInfo("America/New_York")
        monday = self._this_monday(tz)

        def make_event(day_offset, hour, uid, summary):
            dt = datetime.combine(
                monday + timedelta(days=day_offset),
                datetime.min.time().replace(hour=hour),
            ).replace(tzinfo=tz)
            dtend = dt + timedelta(hours=1)
            return (
                dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                dtend.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                uid,
                summary,
            )

        s1, e1, u1, n1 = make_event(1, 9, "uid-a", "Early Meeting")
        s2, e2, u2, n2 = make_event(1, 14, "uid-b", "Afternoon Meeting")

        ics1 = _make_ics(_timed_vevent(u1, n1, s1, e1), cal_name="Cal A")
        ics2 = _make_ics(_timed_vevent(u2, n2, s2, e2), cal_name="Cal B")

        mock_get.side_effect = [
            self._make_response(ics1),
            self._make_response(ics2),
        ]

        cfg = GoogleConfig(
            ical_url="https://example.com/cal1.ics",
            additional_ical_urls=["https://example.com/cal2.ics"],
        )
        from src.fetchers.calendar import fetch_events

        events = fetch_events(cfg, tz=tz)

        assert len(events) == 2
        assert events[0].summary == "Early Meeting"
        assert events[1].summary == "Afternoon Meeting"
        assert mock_get.call_count == 2

    # --- HTTP error returns empty list, logs warning ---

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_http_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("connection refused")

        cfg = GoogleConfig(ical_url="https://example.com/cal.ics")
        from src.fetchers.calendar import fetch_events

        events = fetch_events(cfg)

        assert events == []

    # --- Malformed ICS returns empty list ---

    @patch("src.fetchers.calendar_ical.requests.get")
    def test_malformed_ics_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "this is not valid ics data %%% garbage"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        cfg = GoogleConfig(ical_url="https://example.com/cal.ics")
        from src.fetchers.calendar import fetch_events

        # Should not raise — logs warning and returns []
        events = fetch_events(cfg)

        assert isinstance(events, list)

    # --- Google path still works when ical_url is empty (regression) ---

    @patch("src.fetchers.calendar_google._build_service")
    def test_google_path_used_when_no_ical_url(self, mock_build):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        event_start = datetime.combine(
            monday + timedelta(days=1),
            datetime.min.time().replace(hour=10),
        ).replace(tzinfo=timezone.utc)
        event_end = (event_start + timedelta(hours=1)).isoformat()

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "summary": "Work",
            "items": [
                {
                    "id": "ev1",
                    "summary": "Regular Meeting",
                    "start": {"dateTime": event_start.isoformat()},
                    "end": {"dateTime": event_end},
                }
            ],
            "nextSyncToken": "tok1",
        }

        # ical_url is empty — must use Google API path
        cfg = GoogleConfig(ical_url="")
        from src.fetchers.calendar import fetch_events

        with tempfile.TemporaryDirectory() as tmpdir:
            events = fetch_events(cfg, cache_dir=tmpdir)

        mock_build.assert_called_once()
        assert len(events) == 1
        assert events[0].summary == "Regular Meeting"


# ---------------------------------------------------------------------------
# People API service builder — covers _build_people_service / cache helpers.
# ---------------------------------------------------------------------------


class TestBuildPeopleService:
    """Cover lines 57, 65-66, 76-93 of src/fetchers/calendar.py."""

    def test_clear_people_service_cache(self):
        from src.fetchers.calendar import _clear_people_service_cache, _people_service_cache

        _people_service_cache["sentinel"] = "value"
        _clear_people_service_cache()
        assert _people_service_cache == {}

    def test_clear_service_caches_clears_both(self):
        from src.fetchers.calendar import _people_service_cache, clear_service_caches

        _people_service_cache["foo"] = "bar"
        clear_service_caches()
        assert _people_service_cache == {}

    def test_build_people_service_loads_credentials(self):
        from src.fetchers.calendar import _build_people_service, _clear_people_service_cache

        _clear_people_service_cache()
        cfg = GoogleConfig(service_account_path="/tmp/sa.json", contacts_email="user@example.com")
        fake_creds = MagicMock()
        fake_creds.with_subject.return_value = fake_creds
        fake_service = MagicMock()
        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_file",
                return_value=fake_creds,
            ) as mock_from_file,
            patch("googleapiclient.discovery.build", return_value=fake_service) as mock_build,
        ):
            result = _build_people_service(cfg)

        assert result is fake_service
        mock_from_file.assert_called_once_with(
            "/tmp/sa.json",
            scopes=["https://www.googleapis.com/auth/contacts.readonly"],
        )
        fake_creds.with_subject.assert_called_once_with("user@example.com")
        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs["cache_discovery"] is False

    def test_build_people_service_caches_by_path_and_email(self):
        from src.fetchers.calendar import _build_people_service, _clear_people_service_cache

        _clear_people_service_cache()
        cfg = GoogleConfig(service_account_path="/tmp/sa.json", contacts_email="user@example.com")
        fake_creds = MagicMock()
        fake_creds.with_subject.return_value = fake_creds
        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_file",
                return_value=fake_creds,
            ),
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            _build_people_service(cfg)
            _build_people_service(cfg)
            assert mock_build.call_count == 1

    def test_build_people_service_skips_subject_when_no_email(self):
        from src.fetchers.calendar import _build_people_service, _clear_people_service_cache

        _clear_people_service_cache()
        cfg = GoogleConfig(service_account_path="/tmp/sa.json", contacts_email="")
        fake_creds = MagicMock()
        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_file",
                return_value=fake_creds,
            ),
            patch("googleapiclient.discovery.build"),
        ):
            _build_people_service(cfg)
        fake_creds.with_subject.assert_not_called()

    def test_build_people_service_wraps_credential_load_error(self):
        from src.fetchers.calendar import _build_people_service, _clear_people_service_cache

        _clear_people_service_cache()
        cfg = GoogleConfig(
            service_account_path="/tmp/missing.json", contacts_email="user@example.com"
        )
        with patch(
            "google.oauth2.service_account.Credentials.from_service_account_file",
            side_effect=FileNotFoundError("not found"),
        ):
            with pytest.raises(RuntimeError, match="/tmp/missing.json"):
                _build_people_service(cfg)
