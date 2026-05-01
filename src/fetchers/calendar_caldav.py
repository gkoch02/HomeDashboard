"""CalDAV calendar source.

Connects to a CalDAV server (Nextcloud, Radicale, Fastmail, Apple iCloud,
Synology, …) and returns events for the requested window. Authenticates
with HTTP Basic via a username + password-from-file pair.

This is the v5 proof point for the fetcher registry: a new calendar
backend slots in alongside the Google API and ICS paths via the existing
``src.fetchers.calendar`` dispatcher with no changes to ``DataPipeline``
or the cache layer — the registry handles serialization, breaker, and
quota tracking.

The dependency on the ``caldav`` package is only required when CalDAV is
actually configured; the import is local to ``fetch_from_caldav`` so
users on Google API / ICS only paths don't need the wheel installed.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, cast

from src.data.models import CalendarEvent

logger = logging.getLogger(__name__)


def _read_password(password_file: str) -> str:
    """Read a CalDAV password from *password_file* (one line of secret).

    Trailing newlines are stripped. Raises :class:`RuntimeError` with a
    clear message on missing file / unreadable contents — keeps secrets
    out of config.yaml and out of process command lines.
    """
    path = Path(password_file)
    if not path.is_file():
        raise RuntimeError(
            f"CalDAV password file not found: {password_file!r}. "
            "Create it with the account's password (one line)."
        )
    try:
        text = path.read_text()
    except OSError as exc:
        raise RuntimeError(f"Could not read CalDAV password file {password_file!r}: {exc}") from exc
    text = text.strip()
    if not text:
        raise RuntimeError(
            f"CalDAV password file {password_file!r} is empty; expected one line of secret."
        )
    return text


def fetch_from_caldav(
    *,
    url: str,
    username: str,
    password_file: str,
    calendar_url: str = "",
    days: int = 7,
    start_date: date | None = None,
    tz: tzinfo | None = None,
) -> list[CalendarEvent]:
    """Fetch events from a CalDAV server for the requested window.

    Args:
        url: Base CalDAV URL (typically the principal endpoint).
        username: HTTP Basic username.
        password_file: Path to a file containing the password (one line).
        calendar_url: Optional specific calendar URL. When unset, the
            principal's first calendar is used.
        days: Window length in days from *start_date*.
        start_date: First day of the window. Defaults to the start of the
            current week (Monday).
        tz: Active timezone — tz-aware events are normalised to naive
            local wall-clock time, matching the Google API path.

    Returns:
        List of :class:`CalendarEvent` sorted by start time. An empty
        list is returned and a warning is logged on connection /
        authentication / parsing failures (graceful degradation matches
        the ICS path).
    """
    try:
        import caldav  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "The 'caldav' package is required for CalDAV calendar support. "
            "Run: pip install 'caldav>=1.5'"
        ) from exc

    today = date.today()
    if tz is not None:
        today = datetime.now(tz).date()
    window_start = start_date if start_date is not None else today - timedelta(days=today.weekday())
    time_min = datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc)
    time_max = time_min + timedelta(days=days)

    password = _read_password(password_file)
    caldav_mod = cast(Any, caldav)

    try:
        client = caldav_mod.DAVClient(url=url, username=username, password=password)
        principal = client.principal()
    except Exception as exc:
        logger.warning("CalDAV auth/principal failed for %s: %s", url, exc)
        return []

    try:
        if calendar_url:
            calendars = [client.calendar(url=calendar_url)]
        else:
            calendars = principal.calendars()
    except Exception as exc:
        logger.warning("CalDAV calendar lookup failed: %s", exc)
        return []

    all_events: list[CalendarEvent] = []
    for cal in calendars:
        cal_name = _calendar_name(cal)
        try:
            # ``server_expand=True`` asks the CalDAV server to expand recurring
            # events into individual instances within the window — the v4 code
            # used ``expand=True`` which silently fell into ``**searchargs`` on
            # caldav≥3 and produced one VEVENT per RRULE instead of one per
            # occurrence. Requires ``caldav>=1.5``.
            results = cal.search(start=time_min, end=time_max, event=True, server_expand=True)
        except Exception as exc:
            logger.warning("CalDAV search failed on %s: %s", cal_name, exc)
            continue

        for entry in results:
            for component in _walk_vevents(entry):
                event = _parse_caldav_event(component, cal_name, tz=tz)
                if event is None:
                    continue
                all_events.append(event)

    all_events.sort(key=lambda e: e.start)
    return all_events


def _calendar_name(cal) -> str:
    """Extract a human-readable name from a caldav.Calendar."""
    for attr in ("name", "displayname"):
        try:
            value = getattr(cal, attr, None)
            if callable(value):
                value = value()
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            continue
    return "CalDAV"


def _walk_vevents(entry):
    """Yield all VEVENT subcomponents for a CalDAV search result."""
    try:
        ical = entry.icalendar_instance
    except Exception as exc:
        logger.debug("Could not parse CalDAV entry: %s", exc)
        return
    try:
        for component in ical.walk():
            if getattr(component, "name", None) == "VEVENT":
                yield component
    except Exception as exc:
        logger.debug("CalDAV component walk failed: %s", exc)


def _parse_caldav_event(
    component, calendar_name: str, *, tz: tzinfo | None
) -> CalendarEvent | None:
    """Convert one VEVENT component into a :class:`CalendarEvent`.

    Returns ``None`` for components without DTSTART, with unrecognised
    DTSTART types, or that otherwise fail to parse.
    """
    try:
        summary = str(component.get("SUMMARY", "(no title)"))
        location = str(component.get("LOCATION", "")) or None

        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")
        duration = component.get("DURATION")
        if dtstart is None:
            return None

        dt_val = dtstart.dt
        if isinstance(dt_val, datetime):
            is_all_day = False
            start: datetime = dt_val
            if dtend is not None:
                end_raw = dtend.dt
                end = (
                    end_raw
                    if isinstance(end_raw, datetime)
                    else datetime.combine(end_raw, datetime.min.time())
                )
            elif duration is not None:
                end = start + duration.dt
            else:
                end = start + timedelta(hours=1)

            # Normalise tz-aware times to naive local wall-clock to match the
            # Google API path; downstream rendering treats CalendarEvent times
            # as naive local.
            if tz is not None and start.tzinfo is not None:
                start = start.astimezone(tz).replace(tzinfo=None)
                end = end.astimezone(tz).replace(tzinfo=None)
        elif isinstance(dt_val, date):
            is_all_day = True
            start = datetime.combine(dt_val, datetime.min.time())
            if dtend is not None:
                end_raw = dtend.dt
                if isinstance(end_raw, datetime):
                    end = end_raw.replace(tzinfo=None)
                else:
                    end = datetime.combine(end_raw, datetime.min.time())
            elif duration is not None:
                end = start + duration.dt
            else:
                end = start + timedelta(days=1)
        else:
            return None

        return CalendarEvent(
            summary=summary,
            start=start,
            end=end,
            is_all_day=is_all_day,
            location=location,
            calendar_name=calendar_name,
            event_id=str(component.get("UID", "")),
        )
    except Exception as exc:
        logger.debug("Failed to parse CalDAV VEVENT: %s", exc)
        return None
