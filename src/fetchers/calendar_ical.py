"""ICS feed fetcher — fetch and parse calendar events from iCalendar URLs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import urlparse

import requests  # type: ignore[import-untyped]

from src._time import day_start_utc
from src.data.models import CalendarEvent
from src.fetchers.calendar_google import _today

logger = logging.getLogger(__name__)


def fetch_from_ical(
    urls: list[str],
    days: int = 7,
    start_date=None,
    tz: tzinfo | None = None,
) -> list[CalendarEvent]:
    """Fetch and parse calendar events from one or more ICS feed URLs.

    Each URL is fetched via HTTP(S) and parsed with the ``icalendar`` library.
    Events are filtered to the current-week window (Monday through Monday+days)
    and returned sorted by start time.  No sync tokens or caching at this layer —
    the caller's cache handles freshness.
    """
    try:
        from icalendar import Calendar as ICalendar  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "The 'icalendar' package is required for ICS feed support. "
            "Run: pip install icalendar>=5.0"
        )

    today = _today(tz)
    window_start = start_date if start_date is not None else today - timedelta(days=today.weekday())
    time_min = day_start_utc(window_start, tz)
    time_max = time_min + timedelta(days=days)

    all_events: list[CalendarEvent] = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch ICS feed %s: %s", url, exc)
            continue

        try:
            cal = ICalendar.from_ical(resp.text)
        except Exception as exc:
            logger.warning("Failed to parse ICS feed %s: %s", url, exc)
            continue

        # Prefer X-WR-CALNAME if present, fall back to URL hostname
        cal_name = str(cal.get("X-WR-CALNAME", "")) or _url_hostname(url)

        for component in _expand_components(cal, time_min, time_max, url):
            event = _parse_ical_event(component, cal_name, tz=tz)
            if event is None:
                continue
            # Filter to week window
            if event.is_all_day:
                s = event.start.date() if isinstance(event.start, datetime) else event.start
                e = event.end.date() if isinstance(event.end, datetime) else event.end
                win_start_date = time_min.astimezone(tz).date() if tz else time_min.date()
                win_end_date = time_max.astimezone(tz).date() if tz else time_max.date()
                if s < win_end_date and e > win_start_date:
                    all_events.append(event)
            else:
                start = event.start
                if start.tzinfo is not None:
                    if time_min <= start < time_max:
                        all_events.append(event)
                else:
                    if tz is not None:
                        win_start = time_min.astimezone(tz).replace(tzinfo=None)
                        win_end = time_max.astimezone(tz).replace(tzinfo=None)
                    else:
                        win_start = time_min.replace(tzinfo=None)
                        win_end = time_max.replace(tzinfo=None)
                    if win_start <= start < win_end:
                        all_events.append(event)

    all_events.sort(key=lambda e: e.start)
    return all_events


def _expand_components(cal, time_min, time_max, url: str) -> list:
    """Yield VEVENT components with recurrence rules expanded to occurrences.

    A raw ``cal.walk()`` sees one VEVENT per recurring series, carrying only
    the series' original DTSTART — so a weekly standup exported from
    Google/Outlook appeared in the week of its first occurrence and never
    again (issue #212). ``recurring_ical_events`` expands RRULE / RDATE /
    EXDATE / RECURRENCE-ID into one component per occurrence inside the
    window, matching the CalDAV backend's ``server_expand=True`` behaviour so
    both backends agree on the same calendar. Occurrences still flow through
    the existing per-event window filter, so boundary semantics for
    non-recurring events are unchanged.

    Falls back to the raw walk with a warning if the library is unavailable
    (an old deployment whose requirements weren't refreshed) — recurring
    events degrade to the old behaviour rather than dropping the feed.
    """
    try:
        import recurring_ical_events  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "recurring-ical-events not installed; recurring events in %s will "
            "only appear in their first week (pip install recurring-ical-events)",
            url,
        )
        return [c for c in cal.walk() if c.name == "VEVENT"]
    try:
        return list(recurring_ical_events.of(cal).between(time_min, time_max))
    except Exception as exc:
        logger.warning("Recurrence expansion failed for %s: %s — using raw events", url, exc)
        return [c for c in cal.walk() if c.name == "VEVENT"]


def _parse_ical_event(
    component: Any, calendar_name: str, tz: tzinfo | None = None
) -> CalendarEvent | None:
    """Parse a single VEVENT component into a CalendarEvent, or None if unusable."""
    from datetime import date

    summary = str(component.get("SUMMARY", "(no title)"))
    location = str(component.get("LOCATION", "")) or None

    dtstart = component.get("DTSTART")
    dtend = component.get("DTEND")
    duration = component.get("DURATION")

    if dtstart is None:
        logger.debug("Skipping VEVENT with no DTSTART: %s", summary)
        return None

    dt_val = dtstart.dt

    # All-day events have a plain date; timed events have a datetime
    if isinstance(dt_val, datetime):
        is_all_day = False
        start: datetime = dt_val
        if dtend is not None:
            end: datetime = dtend.dt
            if not isinstance(end, datetime):
                end = datetime.combine(end, datetime.min.time())
        elif duration is not None:
            end = start + duration.dt
        else:
            end = start + timedelta(hours=1)

        # Convert tz-aware datetimes to naive local wall-clock time
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
        logger.debug("Skipping VEVENT with unrecognised DTSTART type: %s", summary)
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


def _url_hostname(url: str) -> str:
    """Extract a human-readable name from a URL (hostname only)."""
    try:
        return urlparse(url).hostname or url
    except Exception:
        return url
