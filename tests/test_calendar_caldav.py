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
