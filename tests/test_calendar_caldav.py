"""Tests for ``src.fetchers.calendar_caldav``.

The CalDAV server is mocked end-to-end via ``unittest.mock.patch`` on
``caldav.DAVClient`` — no network required.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.config import GoogleConfig
from src.fetchers.calendar import fetch_events
from src.fetchers.calendar_caldav import (
    _parse_caldav_event,
    _read_password,
    fetch_from_caldav,
)

# ---------------------------------------------------------------------------
# password file
# ---------------------------------------------------------------------------


class TestReadPassword:
    def test_reads_one_line(self, tmp_path):
        f = tmp_path / "pw.txt"
        f.write_text("hunter2\n")
        assert _read_password(str(f)) == "hunter2"

    def test_strips_whitespace(self, tmp_path):
        f = tmp_path / "pw.txt"
        f.write_text("  hunter2  \n\n")
        assert _read_password(str(f)) == "hunter2"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="not found"):
            _read_password(str(tmp_path / "missing.txt"))

    def test_empty_file_raises(self, tmp_path):
        f = tmp_path / "pw.txt"
        f.write_text("\n\n")
        with pytest.raises(RuntimeError, match="empty"):
            _read_password(str(f))


# ---------------------------------------------------------------------------
# fetch_from_caldav — mocked DAVClient
# ---------------------------------------------------------------------------


def _make_vevent(summary, start, end, *, uid="abc", all_day=False, location=None):
    """Build a fake icalendar VEVENT-like object (just `.get`-able properties)."""

    class Prop:
        def __init__(self, dt):
            self.dt = dt

    component = MagicMock()
    component.name = "VEVENT"

    def _get(key, default=None):
        return {
            "SUMMARY": summary,
            "DTSTART": Prop(start),
            "DTEND": Prop(end),
            "UID": uid,
            "LOCATION": location or "",
        }.get(key, default)

    component.get.side_effect = _get
    return component


def _make_search_result(*vevents):
    """Wrap fake VEVENTs in an entry that quacks like caldav search results."""
    ical = MagicMock()
    ical.walk.return_value = list(vevents)
    entry = MagicMock()
    entry.icalendar_instance = ical
    return entry


def _patch_caldav(calendars):
    """Patch the caldav module at the import site inside fetch_from_caldav."""
    fake_client_cls = MagicMock()
    fake_client = MagicMock()
    fake_principal = MagicMock()
    fake_principal.calendars.return_value = calendars
    fake_client.principal.return_value = fake_principal
    fake_client_cls.return_value = fake_client
    fake_module = MagicMock()
    fake_module.DAVClient = fake_client_cls
    return patch.dict("sys.modules", {"caldav": fake_module})


def _make_calendar(name, results):
    cal = MagicMock()
    cal.name = name
    cal.search.return_value = results
    return cal


class TestFetchFromCalDAV:
    def test_search_called_with_server_expand(self, tmp_path):
        """Regression: caldav>=3 ignores ``expand=`` (it's not a real kwarg) and
        falls into ``**searchargs`` silently. The correct kwarg is
        ``server_expand``; without it the server returns one VEVENT per RRULE
        instead of one per recurrence in the window."""
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")
        cal = _make_calendar("Work", [])

        with _patch_caldav([cal]):
            fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
                days=7,
                start_date=date(2026, 5, 4),
            )

        cal.search.assert_called_once()
        kwargs = cal.search.call_args.kwargs
        assert kwargs.get("server_expand") is True, (
            "server_expand=True must be passed; bare expand=True is silently "
            "ignored on caldav>=3 and leaves recurring events unexpanded"
        )
        assert "expand" not in kwargs, "the v4 typo'd kwarg must not slip back in"

    def test_returns_events_from_principal_calendars(self, tmp_path):
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")
        vevent = _make_vevent(
            "Standup",
            datetime(2026, 5, 4, 9, 0),
            datetime(2026, 5, 4, 9, 30),
            uid="abc-1",
        )
        cal = _make_calendar("Work", [_make_search_result(vevent)])

        with _patch_caldav([cal]):
            events = fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
                days=7,
                start_date=date(2026, 5, 4),
            )

        assert len(events) == 1
        assert events[0].summary == "Standup"
        assert events[0].calendar_name == "Work"
        assert events[0].is_all_day is False

    def test_specific_calendar_url_skips_principal_calendars(self, tmp_path):
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")
        vevent = _make_vevent(
            "Solo",
            datetime(2026, 5, 4, 10, 0),
            datetime(2026, 5, 4, 10, 30),
        )
        chosen_cal = _make_calendar("Personal", [_make_search_result(vevent)])

        fake_client_cls = MagicMock()
        fake_client = MagicMock()
        fake_principal = MagicMock()
        fake_principal.calendars.return_value = [_make_calendar("Wrong", [])]
        fake_client.principal.return_value = fake_principal
        fake_client.calendar.return_value = chosen_cal
        fake_client_cls.return_value = fake_client
        fake_module = MagicMock(DAVClient=fake_client_cls)

        with patch.dict("sys.modules", {"caldav": fake_module}):
            events = fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
                calendar_url="https://example.com/dav/calendars/personal",
                days=7,
                start_date=date(2026, 5, 4),
            )

        assert len(events) == 1
        assert events[0].calendar_name == "Personal"
        # Principal's calendars() never read because calendar_url short-circuits.
        fake_principal.calendars.assert_not_called()

    def test_auth_failure_returns_empty(self, tmp_path, caplog):
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")

        fake_client_cls = MagicMock(side_effect=RuntimeError("401"))
        fake_module = MagicMock(DAVClient=fake_client_cls)
        with patch.dict("sys.modules", {"caldav": fake_module}):
            events = fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
            )

        assert events == []
        assert "auth/principal failed" in caplog.text or "401" in caplog.text

    def test_search_failure_skips_calendar(self, tmp_path):
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")
        good = _make_calendar(
            "Good",
            [
                _make_search_result(
                    _make_vevent(
                        "Ok",
                        datetime(2026, 5, 4, 9, 0),
                        datetime(2026, 5, 4, 9, 30),
                    )
                )
            ],
        )
        broken = _make_calendar("Broken", [])
        broken.search.side_effect = RuntimeError("server error")

        with _patch_caldav([broken, good]):
            events = fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
                days=7,
                start_date=date(2026, 5, 4),
            )

        # Broken calendar skipped; good calendar's event still surfaces.
        assert len(events) == 1
        assert events[0].calendar_name == "Good"

    def test_caldav_package_missing_raises_runtime_error(self, tmp_path):
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")

        # Make `import caldav` raise ImportError.
        with patch.dict("sys.modules", {"caldav": None}):
            with pytest.raises(RuntimeError, match="caldav"):
                fetch_from_caldav(
                    url="https://example.com/dav/",
                    username="alice",
                    password_file=str(pw),
                )


class TestParseCalDAVEvent:
    def test_timed_event_naive_local(self):
        v = _make_vevent(
            "Lunch",
            datetime(2026, 5, 4, 12, 0),
            datetime(2026, 5, 4, 13, 0),
        )
        e = _parse_caldav_event(v, "Cal", tz=None)
        assert e is not None
        assert e.summary == "Lunch"
        assert e.is_all_day is False
        assert e.start == datetime(2026, 5, 4, 12, 0)

    def test_aware_event_normalised_to_naive_local(self):
        import zoneinfo

        ny = zoneinfo.ZoneInfo("America/New_York")
        utc_start = datetime(2026, 5, 4, 14, 0, tzinfo=timezone.utc)
        utc_end = utc_start + timedelta(hours=1)
        v = _make_vevent("Mtg", utc_start, utc_end)
        e = _parse_caldav_event(v, "Cal", tz=ny)
        assert e is not None
        # 14:00 UTC = 10:00 EDT in May 2026
        assert e.start == datetime(2026, 5, 4, 10, 0)
        assert e.end == datetime(2026, 5, 4, 11, 0)
        assert e.start.tzinfo is None  # naive local

    def test_all_day_event(self):
        v = _make_vevent("Holiday", date(2026, 5, 4), date(2026, 5, 5), all_day=True)
        e = _parse_caldav_event(v, "Cal", tz=None)
        assert e is not None
        assert e.is_all_day is True
        assert e.start.date() == date(2026, 5, 4)
        assert e.end.date() == date(2026, 5, 5)

    def test_missing_dtstart_returns_none(self):
        v = MagicMock()
        v.get.return_value = None
        assert _parse_caldav_event(v, "Cal", tz=None) is None

    def test_unknown_dtstart_type_returns_none(self):
        class Prop:
            def __init__(self, dt):
                self.dt = dt

        v = MagicMock()
        v.name = "VEVENT"
        v.get.side_effect = lambda key, default=None: {
            "SUMMARY": "X",
            "DTSTART": Prop("not-a-date"),
            "UID": "u",
        }.get(key, default)
        assert _parse_caldav_event(v, "Cal", tz=None) is None


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


class TestDispatcherUsesCalDAV:
    def test_caldav_url_takes_precedence_over_ical(self, tmp_path):
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")
        cfg = GoogleConfig(
            service_account_path="missing",
            ical_url="https://example.com/calendar.ics",
            caldav_url="https://example.com/dav/",
            caldav_username="alice",
            caldav_password_file=str(pw),
        )

        with (
            patch(
                "src.fetchers.calendar_caldav.fetch_from_caldav", return_value=["caldav-event"]
            ) as mock_caldav,
            patch("src.fetchers.calendar.fetch_from_ical") as mock_ical,
            patch("src.fetchers.calendar.fetch_google_events") as mock_google,
        ):
            result = fetch_events(cfg, days=7, start_date=date(2026, 5, 4))

        mock_caldav.assert_called_once()
        mock_ical.assert_not_called()
        mock_google.assert_not_called()
        assert result == ["caldav-event"]


# ---------------------------------------------------------------------------
# _read_password — OSError branch
# ---------------------------------------------------------------------------


class TestReadPasswordOSError:
    def test_oserror_on_read_raises_runtime_error(self, tmp_path):
        """When the password file exists but cannot be read, raise RuntimeError."""
        f = tmp_path / "pw.txt"
        f.write_text("secret\n")
        with patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
            with pytest.raises(RuntimeError, match="Could not read"):
                _read_password(str(f))


# ---------------------------------------------------------------------------
# fetch_from_caldav — calendar lookup failure & tz-aware today branch
# ---------------------------------------------------------------------------


class TestFetchFromCalDAVAdditional:
    def test_calendar_lookup_failure_returns_empty(self, tmp_path, caplog):
        """When principal.calendars() raises, return [] and log a warning."""
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")

        fake_client_cls = MagicMock()
        fake_client = MagicMock()
        fake_principal = MagicMock()
        fake_principal.calendars.side_effect = RuntimeError("lookup failed")
        fake_client.principal.return_value = fake_principal
        fake_client_cls.return_value = fake_client
        fake_module = MagicMock(DAVClient=fake_client_cls)

        with patch.dict("sys.modules", {"caldav": fake_module}):
            events = fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
            )

        assert events == []
        assert "calendar lookup failed" in caplog.text

    def test_tz_arg_used_for_today_date(self, tmp_path):
        """When tz is supplied, 'today' is computed in that timezone."""
        import zoneinfo

        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")
        cal = _make_calendar("Work", [])

        ny = zoneinfo.ZoneInfo("America/New_York")
        with _patch_caldav([cal]):
            fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
                tz=ny,
            )

        # If tz branch didn't run, the call would still succeed; we verify
        # it ran without error and search was invoked.
        cal.search.assert_called_once()


# ---------------------------------------------------------------------------
# _calendar_name — attribute-exception fallback
# ---------------------------------------------------------------------------


class TestCalendarName:
    def test_returns_name_attribute(self):
        from src.fetchers.calendar_caldav import _calendar_name

        cal = MagicMock()
        cal.name = "Work"
        assert _calendar_name(cal) == "Work"

    def test_callable_name_method_is_called(self):
        """When cal.name is a callable (a method), it is invoked and its return used."""
        from src.fetchers.calendar_caldav import _calendar_name

        class CalWithMethod:
            def name(self):
                return "Work"

        assert _calendar_name(CalWithMethod()) == "Work"

    def test_callable_name_raises_falls_through_to_displayname(self):
        """When cal.name() raises, the except continues to 'displayname'."""
        from src.fetchers.calendar_caldav import _calendar_name

        class CalWithRaisingName:
            def name(self):
                raise RuntimeError("unavailable")

            displayname = "Fallback"

        assert _calendar_name(CalWithRaisingName()) == "Fallback"

    def test_returns_caldav_when_all_attributes_fail(self):
        from src.fetchers.calendar_caldav import _calendar_name

        class CalAllFail:
            def name(self):
                raise RuntimeError("boom")

            def displayname(self):
                raise RuntimeError("boom too")

        assert _calendar_name(CalAllFail()) == "CalDAV"


# ---------------------------------------------------------------------------
# _walk_vevents — exception branches
# ---------------------------------------------------------------------------


class TestCalendarNameNoneValue:
    def test_none_name_falls_through_to_displayname(self):
        """When getattr returns None for 'name', the loop continues to 'displayname'."""
        from src.fetchers.calendar_caldav import _calendar_name

        class CalNoneName:
            name = None
            displayname = "My Calendar"

        assert _calendar_name(CalNoneName()) == "My Calendar"


class TestWalkVevents:
    def test_icalendar_instance_exception_yields_nothing(self):
        from src.fetchers.calendar_caldav import _walk_vevents

        entry = MagicMock()
        type(entry).icalendar_instance = property(
            lambda self: (_ for _ in ()).throw(Exception("parse error"))
        )
        assert list(_walk_vevents(entry)) == []

    def test_component_walk_exception_yields_nothing(self):
        from src.fetchers.calendar_caldav import _walk_vevents

        ical = MagicMock()
        ical.walk.side_effect = Exception("walk exploded")
        entry = MagicMock()
        entry.icalendar_instance = ical
        assert list(_walk_vevents(entry)) == []

    def test_non_vevent_components_are_skipped(self):
        """Components that are not VEVENT (e.g. VCALENDAR) must be filtered out."""
        from src.fetchers.calendar_caldav import _walk_vevents

        vcal = MagicMock()
        vcal.name = "VCALENDAR"
        vevent = MagicMock()
        vevent.name = "VEVENT"

        ical = MagicMock()
        ical.walk.return_value = [vcal, vevent]
        entry = MagicMock()
        entry.icalendar_instance = ical

        results = list(_walk_vevents(entry))
        assert results == [vevent]


# ---------------------------------------------------------------------------
# _parse_caldav_event — duration-based end times & all-day edge cases
# ---------------------------------------------------------------------------


class TestParseCalDAVEventExtended:
    def _vevent_with_duration(self, summary, start, duration_td):
        """Build a VEVENT mock using DURATION instead of DTEND."""

        class Prop:
            def __init__(self, dt):
                self.dt = dt

        component = MagicMock()
        component.name = "VEVENT"

        def _get(key, default=None):
            mapping = {
                "SUMMARY": summary,
                "DTSTART": Prop(start),
                "DURATION": Prop(duration_td),
                "UID": "dur-uid",
            }
            return mapping.get(key, default)

        component.get.side_effect = _get
        return component

    def test_timed_event_duration_used_when_no_dtend(self):
        """When DTEND is absent but DURATION is set, end = start + duration."""
        from datetime import timedelta

        v = self._vevent_with_duration(
            "Long meeting", datetime(2026, 5, 5, 9, 0), timedelta(hours=2)
        )
        e = _parse_caldav_event(v, "Cal", tz=None)
        assert e is not None
        assert e.end == datetime(2026, 5, 5, 11, 0)

    def test_all_day_event_dtend_is_datetime(self):
        """All-day DTSTART (date) with a datetime DTEND should parse correctly."""

        class Prop:
            def __init__(self, dt):
                self.dt = dt

        component = MagicMock()
        component.name = "VEVENT"

        def _get(key, default=None):
            return {
                "SUMMARY": "Holiday",
                "DTSTART": Prop(date(2026, 5, 5)),
                # DTEND is a datetime rather than a date (non-standard but seen)
                "DTEND": Prop(datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc)),
                "UID": "allday-dt",
            }.get(key, default)

        component.get.side_effect = _get
        e = _parse_caldav_event(component, "Cal", tz=None)
        assert e is not None
        assert e.is_all_day is True

    def test_all_day_event_duration_used_when_no_dtend(self):
        """All-day event without DTEND falls back to start + DURATION."""
        from datetime import timedelta

        v = self._vevent_with_duration("Multi-day", date(2026, 5, 5), timedelta(days=3))
        e = _parse_caldav_event(v, "Cal", tz=None)
        assert e is not None
        assert e.is_all_day is True
        assert e.end.date() == date(2026, 5, 8)

    def test_general_exception_returns_none(self):
        """A component that blows up during parsing returns None gracefully."""
        component = MagicMock()
        component.get.side_effect = Exception("unexpected crash")
        assert _parse_caldav_event(component, "Cal", tz=None) is None

    def test_timed_event_no_dtend_no_duration_defaults_to_one_hour(self):
        """When neither DTEND nor DURATION is present, end defaults to start + 1 hour."""

        class Prop:
            def __init__(self, dt):
                self.dt = dt

        component = MagicMock()
        component.name = "VEVENT"

        def _get(key, default=None):
            return {
                "SUMMARY": "Quick call",
                "DTSTART": Prop(datetime(2026, 5, 5, 10, 0)),
                "UID": "no-end",
            }.get(key, default)

        component.get.side_effect = _get
        e = _parse_caldav_event(component, "Cal", tz=None)
        assert e is not None
        assert e.end == datetime(2026, 5, 5, 11, 0)

    def test_all_day_event_no_dtend_no_duration_defaults_to_one_day(self):
        """All-day event with neither DTEND nor DURATION defaults to start + 1 day."""

        class Prop:
            def __init__(self, dt):
                self.dt = dt

        component = MagicMock()
        component.name = "VEVENT"

        def _get(key, default=None):
            return {
                "SUMMARY": "Holiday",
                "DTSTART": Prop(date(2026, 5, 5)),
                "UID": "all-day-noend",
            }.get(key, default)

        component.get.side_effect = _get
        e = _parse_caldav_event(component, "Cal", tz=None)
        assert e is not None
        assert e.is_all_day is True
        assert e.end.date() == date(2026, 5, 6)


class TestFetchSkipsUnparsableVEvents:
    def test_none_parse_result_is_skipped(self, tmp_path):
        """When _parse_caldav_event returns None the entry is silently skipped."""
        pw = tmp_path / "pw.txt"
        pw.write_text("secret\n")

        # Build an entry whose VEVENT has no DTSTART (returns None from parser)
        class Prop:
            def __init__(self, dt):
                self.dt = dt

        bad_vevent = MagicMock()
        bad_vevent.name = "VEVENT"
        bad_vevent.get.return_value = None  # every .get() returns None → no DTSTART

        ical = MagicMock()
        ical.walk.return_value = [bad_vevent]
        bad_entry = MagicMock()
        bad_entry.icalendar_instance = ical

        good_vevent = MagicMock()
        good_vevent.name = "VEVENT"

        def _get_good(key, default=None):
            return {
                "SUMMARY": "Good event",
                "DTSTART": Prop(datetime(2026, 5, 5, 9, 0)),
                "DTEND": Prop(datetime(2026, 5, 5, 10, 0)),
                "UID": "good-uid",
            }.get(key, default)

        good_vevent.get.side_effect = _get_good
        good_ical = MagicMock()
        good_ical.walk.return_value = [good_vevent]
        good_entry = MagicMock()
        good_entry.icalendar_instance = good_ical

        cal = _make_calendar("Work", [bad_entry, good_entry])

        with _patch_caldav([cal]):
            events = fetch_from_caldav(
                url="https://example.com/dav/",
                username="alice",
                password_file=str(pw),
                days=7,
                start_date=date(2026, 5, 4),
            )

        # The bad entry is skipped; the good one surfaces.
        assert len(events) == 1
        assert events[0].summary == "Good event"
