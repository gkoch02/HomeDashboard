"""Tests for src/fetchers/calendar_google.py

Covers: _parse_event, _ser_sync_event, _deser_sync_event, _load_sync_state,
_save_sync_state, _apply_delta, _filter_to_window, _fetch_full,
_fetch_incremental, fetch_google_events, clear_service_caches.
"""

from __future__ import annotations

import json
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.config import GoogleConfig
from src.fetchers.calendar_google import (
    _apply_delta,
    _deser_sync_event,
    _fetch_full,
    _fetch_incremental,
    _filter_to_window,
    _load_sync_state,
    _parse_event,
    _save_sync_state,
    _ser_sync_event,
    _today,
    clear_service_caches,
    fetch_google_events,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EST = zoneinfo.ZoneInfo("America/New_York")


def _google_cfg(**kwargs) -> GoogleConfig:
    defaults = dict(
        service_account_path="/fake/creds.json",
        calendar_id="primary",
        additional_calendars=[],
        ical_url="",
    )
    defaults.update(kwargs)
    return GoogleConfig(**defaults)


def _timed_item(summary: str, start_dt: str, end_dt: str, event_id: str = "abc123") -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
    }


def _allday_item(summary: str, start_date: str, end_date: str, event_id: str = "def456") -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"date": start_date},
        "end": {"date": end_date},
    }


# ---------------------------------------------------------------------------
# _parse_event
# ---------------------------------------------------------------------------


class TestParseEvent:
    def test_timed_event_basic(self):
        item = _timed_item("Meeting", "2024-03-15T09:00:00-05:00", "2024-03-15T10:00:00-05:00")
        event = _parse_event(item, "Work")
        assert event is not None
        assert event.summary == "Meeting"
        assert event.calendar_name == "Work"
        assert event.is_all_day is False
        assert event.event_id == "abc123"

    def test_timed_event_with_tz_conversion(self):
        # UTC+0 = EST-5 so 00:00 UTC = previous day 19:00 EST
        item = _timed_item(
            "Late night",
            "2024-03-15T00:00:00+00:00",
            "2024-03-15T01:00:00+00:00",
        )
        event = _parse_event(item, "Cal", tz=_EST)
        assert event is not None
        # Should be March 14 19:00 local
        assert event.start.date() == date(2024, 3, 14)
        assert event.start.tzinfo is None  # stripped to naive

    def test_all_day_event(self):
        item = _allday_item("Holiday", "2024-12-25", "2024-12-26")
        event = _parse_event(item, "Personal")
        assert event is not None
        assert event.is_all_day is True
        assert event.start == datetime(2024, 12, 25, 0, 0, 0)

    def test_missing_start_returns_none(self):
        item = {"id": "x", "summary": "Bad event", "start": {}, "end": {}}
        assert _parse_event(item, "Cal") is None

    def test_missing_summary_defaults(self):
        item = _allday_item("", "2024-03-15", "2024-03-16")
        item.pop("summary")
        event = _parse_event(item, "Cal")
        assert event is not None
        assert event.summary == "(no title)"

    def test_location_captured(self):
        item = _timed_item("Dentist", "2024-03-15T09:00:00+00:00", "2024-03-15T10:00:00+00:00")
        item["location"] = "123 Main St"
        event = _parse_event(item, "Cal")
        assert event is not None
        assert event.location == "123 Main St"

    def test_no_id_event(self):
        item = {
            "summary": "No ID event",
            "start": {"date": "2024-03-15"},
            "end": {"date": "2024-03-16"},
        }
        event = _parse_event(item, "Cal")
        assert event is not None
        assert event.event_id is None


# ---------------------------------------------------------------------------
# _ser_sync_event / _deser_sync_event
# ---------------------------------------------------------------------------


class TestSyncEventSerialization:
    def _make_event(self):
        from src.data.models import CalendarEvent

        return CalendarEvent(
            summary="Team Lunch",
            start=datetime(2024, 3, 15, 12, 0),
            end=datetime(2024, 3, 15, 13, 0),
            is_all_day=False,
            location="Cafe",
            calendar_name="Work",
            event_id="evt001",
        )

    def test_roundtrip_timed(self):
        event = self._make_event()
        d = _ser_sync_event(event)
        assert d["event_id"] == "evt001"
        assert d["summary"] == "Team Lunch"
        assert d["is_all_day"] is False

        restored = _deser_sync_event(d)
        assert restored.summary == event.summary
        assert restored.start == event.start
        assert restored.end == event.end
        assert restored.is_all_day == event.is_all_day
        assert restored.location == event.location
        assert restored.calendar_name == event.calendar_name
        assert restored.event_id == event.event_id

    def test_roundtrip_all_day(self):
        from src.data.models import CalendarEvent

        event = CalendarEvent(
            summary="Birthday",
            start=datetime(2024, 6, 15, 0, 0),
            end=datetime(2024, 6, 16, 0, 0),
            is_all_day=True,
            calendar_name="Personal",
        )
        d = _ser_sync_event(event)
        restored = _deser_sync_event(d)
        assert restored.is_all_day is True

    def test_deser_missing_optional_fields(self):
        d = {
            "summary": "Minimal",
            "start": "2024-03-15T09:00:00",
            "end": "2024-03-15T10:00:00",
        }
        event = _deser_sync_event(d)
        assert event.summary == "Minimal"
        assert event.is_all_day is False
        assert event.location is None
        assert event.calendar_name is None
        assert event.event_id is None


# ---------------------------------------------------------------------------
# _load_sync_state / _save_sync_state
# ---------------------------------------------------------------------------


class TestSyncStatePersistence:
    def test_load_missing_file_returns_empty(self, tmp_path):
        state = _load_sync_state(str(tmp_path))
        assert state == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        payload = {"primary": {"sync_token": "token123", "events": []}}
        _save_sync_state(payload, str(tmp_path))

        loaded = _load_sync_state(str(tmp_path))
        assert loaded == payload

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        _save_sync_state({"x": 1}, str(nested))
        assert (nested / "calendar_sync_state.json").exists()

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        (tmp_path / "calendar_sync_state.json").write_text("not json{{")
        state = _load_sync_state(str(tmp_path))
        assert state == {}

    def test_save_is_atomic(self, tmp_path):
        """No partial writes — file replaces atomically."""
        _save_sync_state({"step": 1}, str(tmp_path))
        _save_sync_state({"step": 2}, str(tmp_path))
        loaded = _load_sync_state(str(tmp_path))
        assert loaded == {"step": 2}

    def test_save_cleans_up_temp_file_on_write_failure(self, tmp_path, caplog):
        """json.dump failure must unlink the temp file and be caught by the outer handler."""
        import logging

        with patch("src.fetchers.calendar_google.json.dump", side_effect=OSError("disk full")):
            with caplog.at_level(logging.WARNING, logger="src.fetchers.calendar_google"):
                _save_sync_state({"x": 1}, str(tmp_path))  # swallowed

        assert "Sync state write failed" in caplog.text
        # State file was never created; no stray .tmp left behind
        assert not (tmp_path / "calendar_sync_state.json").exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_save_cleans_up_temp_file_on_base_exception(self, tmp_path):
        """KeyboardInterrupt mid-write must still unlink the temp file and re-raise."""
        with patch("src.fetchers.calendar_google.json.dump", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                _save_sync_state({"x": 1}, str(tmp_path))

        assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# _build_service
# ---------------------------------------------------------------------------


class TestBuildService:
    """Covers the credential-loading path and its RuntimeError wrapping."""

    def setup_method(self):
        clear_service_caches()

    def teardown_method(self):
        clear_service_caches()

    def test_builds_and_caches_service(self):
        from src.fetchers import calendar_google

        cfg = _google_cfg(service_account_path="/fake/creds.json")
        fake_creds = MagicMock(name="Credentials")
        fake_service = MagicMock(name="CalendarService")

        with (
            patch.object(
                calendar_google.service_account.Credentials,
                "from_service_account_file",
                return_value=fake_creds,
            ) as from_file,
            patch.object(calendar_google, "build", return_value=fake_service) as build_mock,
        ):
            svc1 = calendar_google._build_service(cfg)
            svc2 = calendar_google._build_service(cfg)

        assert svc1 is fake_service
        assert svc2 is fake_service
        # Cached — credentials loaded once, service built once
        assert from_file.call_count == 1
        assert build_mock.call_count == 1
        build_mock.assert_called_with(
            "calendar", "v3", credentials=fake_creds, cache_discovery=False
        )

    def test_missing_credentials_raises_runtime_error(self):
        from src.fetchers import calendar_google

        cfg = _google_cfg(service_account_path="/does/not/exist.json")
        with patch.object(
            calendar_google.service_account.Credentials,
            "from_service_account_file",
            side_effect=FileNotFoundError("no such file"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                calendar_google._build_service(cfg)

        msg = str(exc_info.value)
        assert "Failed to load service account credentials" in msg
        assert "/does/not/exist.json" in msg
        # Original exception is chained via `from exc`
        assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    def test_build_failure_does_not_poison_cache(self):
        """A failed load must not leave a cache entry that masks a later successful load."""
        from src.fetchers import calendar_google

        cfg = _google_cfg(service_account_path="/fake/creds.json")

        with patch.object(
            calendar_google.service_account.Credentials,
            "from_service_account_file",
            side_effect=ValueError("malformed json"),
        ):
            with pytest.raises(RuntimeError):
                calendar_google._build_service(cfg)

        # Second attempt should retry rather than returning a stale/cached object
        fake_service = MagicMock(name="CalendarService")
        with (
            patch.object(
                calendar_google.service_account.Credentials,
                "from_service_account_file",
                return_value=MagicMock(),
            ),
            patch.object(calendar_google, "build", return_value=fake_service),
        ):
            svc = calendar_google._build_service(cfg)

        assert svc is fake_service


# ---------------------------------------------------------------------------
# _apply_delta
# ---------------------------------------------------------------------------


class TestApplyDelta:
    def _stored_event(self, event_id: str, summary: str) -> dict:
        from src.data.models import CalendarEvent

        event = CalendarEvent(
            summary=summary,
            start=datetime(2024, 3, 15, 9, 0),
            end=datetime(2024, 3, 15, 10, 0),
            is_all_day=False,
            calendar_name="Work",
            event_id=event_id,
        )
        return _ser_sync_event(event)

    def test_upsert_new_event(self):
        stored = []
        delta = [
            _timed_item(
                "New Meeting", "2024-03-15T09:00:00+00:00", "2024-03-15T10:00:00+00:00", "new1"
            )
        ]
        result = _apply_delta(stored, delta, "Work")
        assert len(result) == 1
        assert result[0]["summary"] == "New Meeting"

    def test_upsert_updates_existing(self):
        stored = [self._stored_event("evt1", "Old Title")]
        delta = [
            _timed_item(
                "New Title", "2024-03-15T09:00:00+00:00", "2024-03-15T10:00:00+00:00", "evt1"
            )
        ]
        result = _apply_delta(stored, delta, "Work")
        assert len(result) == 1
        assert result[0]["summary"] == "New Title"

    def test_cancelled_event_removed(self):
        stored = [self._stored_event("evt1", "Meeting")]
        delta = [{"id": "evt1", "status": "cancelled"}]
        result = _apply_delta(stored, delta, "Work")
        assert len(result) == 0

    def test_cancellation_of_unknown_event_noop(self):
        stored = [self._stored_event("evt1", "Meeting")]
        delta = [{"id": "unknown_id", "status": "cancelled"}]
        result = _apply_delta(stored, delta, "Work")
        assert len(result) == 1

    def test_events_without_id_preserved(self):
        stored = [
            {
                "summary": "No ID event",
                "start": "2024-03-15T09:00:00",
                "end": "2024-03-15T10:00:00",
            }
        ]
        result = _apply_delta(stored, [], "Work")
        assert len(result) == 1

    def test_delta_item_without_id_skipped(self):
        stored = []
        delta = [
            {"summary": "No ID", "start": {"date": "2024-03-15"}, "end": {"date": "2024-03-16"}}
        ]
        result = _apply_delta(stored, delta, "Work")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _filter_to_window
# ---------------------------------------------------------------------------


class TestFilterToWindow:
    def _make_stored(
        self,
        event_id: str,
        start: datetime,
        end: datetime,
        is_all_day: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict:
        from src.data.models import CalendarEvent

        if is_all_day:
            s = datetime.combine(start_date or start.date(), datetime.min.time())
            e = datetime.combine(end_date or end.date(), datetime.min.time())
        else:
            s, e = start, end
        event = CalendarEvent(
            summary="Event",
            start=s,
            end=e,
            is_all_day=is_all_day,
            calendar_name="Cal",
            event_id=event_id,
        )
        return _ser_sync_event(event)

    def _window(self, year=2024, month=3, day=11):
        """Return a Mon–Mon UTC window starting on given date."""
        time_min = datetime(year, month, day, 0, 0, tzinfo=timezone.utc)
        time_max = time_min + timedelta(days=7)
        return time_min, time_max

    def test_event_inside_window_included(self):
        stored = [self._make_stored("e1", datetime(2024, 3, 13, 10), datetime(2024, 3, 13, 11))]
        time_min, time_max = self._window()
        result = _filter_to_window(stored, time_min, time_max)
        assert len(result) == 1

    def test_event_before_window_excluded(self):
        stored = [self._make_stored("e1", datetime(2024, 3, 10, 10), datetime(2024, 3, 10, 11))]
        time_min, time_max = self._window()
        result = _filter_to_window(stored, time_min, time_max)
        assert len(result) == 0

    def test_event_after_window_excluded(self):
        stored = [self._make_stored("e1", datetime(2024, 3, 20, 10), datetime(2024, 3, 20, 11))]
        time_min, time_max = self._window()
        result = _filter_to_window(stored, time_min, time_max)
        assert len(result) == 0

    def test_all_day_event_spanning_window(self):
        # All-day event: Mar 11 (Monday) to Mar 18 (exclusive end)
        stored = [
            self._make_stored(
                "e1",
                datetime(2024, 3, 11),
                datetime(2024, 3, 18),
                is_all_day=True,
                start_date=date(2024, 3, 11),
                end_date=date(2024, 3, 18),
            )
        ]
        time_min, time_max = self._window()
        result = _filter_to_window(stored, time_min, time_max)
        assert len(result) == 1

    def test_filter_with_timezone(self):
        stored = [
            self._make_stored(
                "e1",
                datetime(2024, 3, 13, 14),  # naive local EST: 14:00
                datetime(2024, 3, 13, 15),
            )
        ]
        time_min, time_max = self._window()
        result = _filter_to_window(stored, time_min, time_max, tz=_EST)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _fetch_full
# ---------------------------------------------------------------------------


class TestFetchFull:
    def _make_service(self, items, summary="My Cal", sync_token="tok1"):
        """Build a mock service returning a single-page result."""
        result_page = {"items": items, "summary": summary, "nextSyncToken": sync_token}
        list_mock = MagicMock()
        list_mock.execute.return_value = result_page
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        service = MagicMock()
        service.events.return_value = events_mock
        return service

    def test_returns_events(self):
        items = [
            _timed_item("Event A", "2024-03-15T09:00:00+00:00", "2024-03-15T10:00:00+00:00"),
            _allday_item("Holiday", "2024-03-17", "2024-03-18"),
        ]
        service = self._make_service(items)
        time_min = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)
        time_max = time_min + timedelta(days=7)

        events, cal_name, token = _fetch_full(service, "primary", time_min, time_max)
        assert len(events) == 2
        assert cal_name == "My Cal"
        assert token == "tok1"

    def test_empty_calendar(self):
        service = self._make_service([])
        time_min = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)
        time_max = time_min + timedelta(days=7)
        events, cal_name, token = _fetch_full(service, "primary", time_min, time_max)
        assert events == []
        assert token == "tok1"

    def test_pagination(self):
        page1 = {
            "items": [
                _timed_item("Event 1", "2024-03-15T09:00:00+00:00", "2024-03-15T10:00:00+00:00")
            ],
            "summary": "Cal",
            "nextPageToken": "page2",
        }
        page2 = {
            "items": [_allday_item("Event 2", "2024-03-16", "2024-03-17")],
            "summary": "Cal",
            "nextSyncToken": "final_tok",
        }
        list_mock = MagicMock()
        list_mock.execute.side_effect = [page1, page2]
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        service = MagicMock()
        service.events.return_value = events_mock

        time_min = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)
        time_max = time_min + timedelta(days=7)
        events, _, token = _fetch_full(service, "primary", time_min, time_max)
        assert len(events) == 2
        assert token == "final_tok"

    def test_api_exception_returns_empty(self):
        list_mock = MagicMock()
        list_mock.execute.side_effect = Exception("Network error")
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        service = MagicMock()
        service.events.return_value = events_mock

        time_min = datetime(2024, 3, 11, 0, 0, tzinfo=timezone.utc)
        time_max = time_min + timedelta(days=7)
        events, cal_name, token = _fetch_full(service, "primary", time_min, time_max)
        assert events == []
        assert token is None


# ---------------------------------------------------------------------------
# _fetch_incremental
# ---------------------------------------------------------------------------


class TestFetchIncremental:
    def _make_service(self, items, cal_name="Cal", new_token="new_tok"):
        result = {"items": items, "summary": cal_name, "nextSyncToken": new_token}
        list_mock = MagicMock()
        list_mock.execute.return_value = result
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        service = MagicMock()
        service.events.return_value = events_mock
        return service

    def test_successful_incremental(self):
        items = [_timed_item("Updated", "2024-03-15T09:00:00+00:00", "2024-03-15T10:00:00+00:00")]
        service = self._make_service(items)
        delta, cal, token, needs_reset = _fetch_incremental(service, "primary", "old_token")
        assert needs_reset is False
        assert len(delta) == 1
        assert token == "new_tok"

    def test_empty_delta(self):
        service = self._make_service([])
        delta, cal, token, needs_reset = _fetch_incremental(service, "primary", "tok")
        assert needs_reset is False
        assert delta == []

    def test_410_gone_triggers_reset(self):
        from googleapiclient.errors import HttpError

        resp = MagicMock()
        resp.status = 410
        list_mock = MagicMock()
        list_mock.execute.side_effect = HttpError(resp=resp, content=b"Gone")
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        service = MagicMock()
        service.events.return_value = events_mock

        delta, _, token, needs_reset = _fetch_incremental(service, "primary", "expired_tok")
        assert needs_reset is True
        assert delta == []
        assert token is None

    def test_other_http_error_triggers_reset(self):
        from googleapiclient.errors import HttpError

        resp = MagicMock()
        resp.status = 500
        list_mock = MagicMock()
        list_mock.execute.side_effect = HttpError(resp=resp, content=b"Server Error")
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        service = MagicMock()
        service.events.return_value = events_mock

        _, _, _, needs_reset = _fetch_incremental(service, "primary", "tok")
        assert needs_reset is True

    def test_generic_exception_triggers_reset(self):
        list_mock = MagicMock()
        list_mock.execute.side_effect = RuntimeError("Unexpected")
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        service = MagicMock()
        service.events.return_value = events_mock

        _, _, _, needs_reset = _fetch_incremental(service, "primary", "tok")
        assert needs_reset is True


# ---------------------------------------------------------------------------
# fetch_google_events (integration)
# ---------------------------------------------------------------------------


class TestFetchGoogleEvents:
    def _patch_build_service(self, service):
        return patch("src.fetchers.calendar_google._build_service", return_value=service)

    def _simple_service(self, items=None):
        if items is None:
            items = []
        result = {"items": items, "summary": "My Calendar", "nextSyncToken": "tok"}
        list_mock = MagicMock()
        list_mock.execute.return_value = result
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        service = MagicMock()
        service.events.return_value = events_mock
        return service

    def test_full_sync_no_cache(self):
        svc = self._simple_service([_allday_item("Holiday", "2024-03-15", "2024-03-16")])
        cfg = _google_cfg()
        with self._patch_build_service(svc):
            events = fetch_google_events(cfg)
        assert len(events) == 1
        assert events[0].summary == "Holiday"

    def test_saves_sync_state_when_cache_dir_given(self, tmp_path):
        svc = self._simple_service()
        cfg = _google_cfg()
        with self._patch_build_service(svc):
            fetch_google_events(cfg, cache_dir=str(tmp_path))
        state_file = tmp_path / "calendar_sync_state.json"
        assert state_file.exists()

    def test_incremental_sync_used_when_token_present(self, tmp_path):
        # Seed a sync state with an existing token
        today = _today(None)
        window_start = today - timedelta(days=today.weekday())
        window_end = window_start + timedelta(days=7)
        existing_state = {
            "primary": {
                "sync_token": "existing_tok",
                "events": [],
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            }
        }
        from src.fetchers.calendar_google import _SYNC_STATE_FILENAME

        (tmp_path / _SYNC_STATE_FILENAME).write_text(json.dumps(existing_state))

        new_item = _timed_item(
            "New Event",
            "2024-03-15T10:00:00+00:00",
            "2024-03-15T11:00:00+00:00",
            "new_event",
        )
        incremental_result = {
            "items": [new_item],
            "summary": "My Calendar",
            "nextSyncToken": "new_tok",
        }
        list_mock = MagicMock()
        list_mock.execute.return_value = incremental_result
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        svc = MagicMock()
        svc.events.return_value = events_mock

        cfg = _google_cfg()
        with self._patch_build_service(svc):
            fetch_google_events(cfg, cache_dir=str(tmp_path))

        # Verify the call used a syncToken parameter (incremental path)
        call_kwargs = events_mock.list.call_args
        assert (
            "syncToken" in call_kwargs.kwargs
            or (
                call_kwargs.args and "syncToken" in call_kwargs.args[0]
                if call_kwargs.args
                else False
            )
            or any("syncToken" in str(c) for c in events_mock.list.call_args_list)
        )

    def test_additional_calendars_fetched(self):
        svc = self._simple_service()
        cfg = _google_cfg(additional_calendars=["secondary@group.v.calendar.google.com"])
        with self._patch_build_service(svc):
            fetch_google_events(cfg)
        # list() should be called twice — once per calendar
        assert svc.events.return_value.list.call_count == 2

    def test_events_sorted_by_start(self):
        items = [
            _allday_item("Thursday", "2024-03-14", "2024-03-15", "e3"),
            _allday_item("Monday", "2024-03-11", "2024-03-12", "e1"),
            _allday_item("Wednesday", "2024-03-13", "2024-03-14", "e2"),
        ]
        svc = self._simple_service(items)
        cfg = _google_cfg()
        with self._patch_build_service(svc):
            events = fetch_google_events(cfg)
        starts = [e.start for e in events]
        assert starts == sorted(starts)

    def test_sync_token_expired_falls_back_to_full(self, tmp_path):
        from googleapiclient.errors import HttpError

        from src.fetchers.calendar_google import _SYNC_STATE_FILENAME

        existing_state = {"primary": {"sync_token": "expired_tok", "events": []}}
        (tmp_path / _SYNC_STATE_FILENAME).write_text(json.dumps(existing_state))

        resp = MagicMock()
        resp.status = 410
        # First call (incremental) raises 410, second call (full sync) succeeds
        full_result = {"items": [], "summary": "Cal", "nextSyncToken": "fresh_tok"}
        list_mock = MagicMock()
        list_mock.execute.side_effect = [
            HttpError(resp=resp, content=b"Gone"),
            full_result,
        ]
        events_mock = MagicMock()
        events_mock.list.return_value = list_mock
        svc = MagicMock()
        svc.events.return_value = events_mock

        cfg = _google_cfg()
        with self._patch_build_service(svc):
            events = fetch_google_events(cfg, cache_dir=str(tmp_path))
        # Should complete without error (fell back to full sync)
        assert isinstance(events, list)


# ---------------------------------------------------------------------------
# clear_service_caches
# ---------------------------------------------------------------------------


class TestClearServiceCaches:
    def test_clear_empties_cache(self):
        from src.fetchers import calendar_google

        calendar_google._service_cache["fake_key"] = MagicMock()
        clear_service_caches()
        assert len(calendar_google._service_cache) == 0

    def test_clear_is_idempotent(self):
        clear_service_caches()
        clear_service_caches()  # no error on second call
