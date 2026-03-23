"""Tests for src/fetchers/calendar.py"""

import json
import tempfile
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import BirthdayConfig, GoogleConfig
from src.fetchers.calendar import (
    _parse_birthday_entry,
    _parse_contact_birthday,
    _days_until,
    fetch_birthdays,
    _parse_event,
    _apply_delta,
    _fetch_full,
    _fetch_incremental,
    _filter_to_window,
    _ser_sync_event,
    _load_sync_state,
    _save_sync_state,
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
        self, connections: list, next_page_token: str | None = None,
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
            self._make_connections_response([
                self._person("Alice", upcoming.month, upcoming.day, year=1990),
            ])
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
            self._make_connections_response([
                {"names": [{"displayName": "No Birthday"}], "birthdays": []},
                self._person("Alice", upcoming.month, upcoming.day),
            ])
        )

        cfg_google = GoogleConfig(contacts_email="user@example.com")
        cfg_bday = BirthdayConfig(source="contacts", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)

        assert len(results) == 1
        assert results[0].name == "Alice"

    @patch("src.fetchers.calendar._build_people_service")
    def test_api_failure_returns_empty(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.people().connections().list().execute.side_effect = Exception("API error")

        cfg_google = GoogleConfig(contacts_email="user@example.com")
        cfg_bday = BirthdayConfig(source="contacts", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)

        assert results == []

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

    def test_api_exception_returns_partial_results(self):
        """If the API call raises, _fetch_full breaks and returns what it has."""
        svc = MagicMock()
        svc.events().list().execute.side_effect = Exception("network error")
        time_min = datetime(2024, 3, 11, tzinfo=timezone.utc)
        time_max = datetime(2024, 3, 18, tzinfo=timezone.utc)
        events, _, token = _fetch_full(svc, "primary", time_min, time_max)
        assert events == []
        assert token is None


# ---------------------------------------------------------------------------
# _fetch_incremental — multi-page and generic exception
# ---------------------------------------------------------------------------

class TestFetchIncremental:
    def test_multi_page_aggregates_delta(self):
        page1 = {
            "summary": "Cal",
            "items": [{"id": "e1", "summary": "Evt1",
                       "start": {"dateTime": "2024-03-15T09:00:00+00:00"},
                       "end": {"dateTime": "2024-03-15T10:00:00+00:00"}}],
            "nextPageToken": "page2",
        }
        page2 = {
            "summary": "Cal",
            "items": [{"id": "e2", "summary": "Evt2",
                       "start": {"dateTime": "2024-03-16T09:00:00+00:00"},
                       "end": {"dateTime": "2024-03-16T10:00:00+00:00"}}],
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
    @patch("src.fetchers.calendar._build_service")
    def test_expired_sync_token_falls_back_to_full_sync(self, mock_build):
        """When incremental sync returns needs_reset=True, full sync is performed."""
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        event_start = datetime.combine(
            monday + timedelta(days=1), datetime.min.time().replace(hour=9),
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
        from src.fetchers.calendar import _today
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
        result = _today(tz)
        from datetime import datetime
        expected = datetime.now(tz).date()
        assert result == expected

    def test_today_without_tz_returns_system_date(self):
        from src.fetchers.calendar import _today
        from datetime import date
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
    def test_api_failure_returns_empty(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.side_effect = Exception("API down")

        cfg_google = GoogleConfig()
        cfg_bday = BirthdayConfig(source="calendar", lookahead_days=30)
        results = fetch_birthdays(cfg_google, cfg_bday)
        assert results == []

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
    @patch("src.fetchers.calendar._build_service")
    def test_fetch_events_returns_events(self, mock_build):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        event_start = datetime.combine(
            monday + timedelta(days=1), datetime.min.time().replace(hour=9),
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

    @patch("src.fetchers.calendar._build_service")
    def test_fetch_events_uses_incremental_sync_on_second_call(self, mock_build):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        event_start = datetime.combine(
            monday + timedelta(days=1), datetime.min.time().replace(hour=9),
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
