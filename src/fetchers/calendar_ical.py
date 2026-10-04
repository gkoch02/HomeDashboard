"""ICS feed fetcher — fetch and parse calendar events from iCalendar URLs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import urlparse

import requests  # type: ignore[import-untyped]

from src._time import event_window_utc, week_start
from src.data.models import CalendarEvent
from src.fetchers import request_counter
from src.fetchers.calendar_google import _today
from src.fetchers.errors import CalendarFetchError

logger = logging.getLogger(__name__)

# Padding applied to the recurrence-expansion span (see _expand_components).
# One day comfortably exceeds the largest real UTC offset (+14:00).
_EXPAND_PAD = timedelta(days=1)

# Per-request ceiling. The whole call costs one of these plus the single retry
# retry_fetch performs, because the first failing feed ends the walk — see the
# comment in the fetch loop.
_REQUEST_TIMEOUT_SECONDS = 30

# Per-series ceiling on expanded occurrences (see _cap_runaway_series). The
# densest legitimate pattern in an 8-day window is FREQ=HOURLY at 192; this
# leaves huge headroom while still stopping an unbounded rule dead.
_MAX_OCCURRENCES_PER_SERIES = 500


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

    Raises:
        CalendarFetchError: as soon as *any* feed cannot be fetched or parsed.
            The return value is the caller's complete calendar — it gets
            cached, marked fresh, and counted as a breaker success — so a feed
            that failed cannot simply be omitted from it; failing lets the
            pipeline fall back to the last complete calendar and flag it
            stale. Raising at the first failure keeps the call bounded by one
            request timeout — the other feeds' results would be discarded
            anyway.
        RuntimeError: if the ``icalendar`` package is not installed.
    """
    try:
        from icalendar import Calendar as ICalendar  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "The 'icalendar' package is required for ICS feed support. "
            "Run: pip install icalendar>=5.0"
        )

    today = _today(tz)
    window_start = start_date if start_date is not None else week_start(today)
    time_min, time_max = event_window_utc(window_start, days, tz)

    all_events: list[CalendarEvent] = []
    for url in urls:
        # Stop at the first failure: any failure discards the whole result,
        # and the pipeline's 120 s per-source ceiling releases the render but
        # cannot kill this thread, so one feed's timeout (retried once) must
        # be the whole bound.
        try:
            request_counter.count_request()
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch ICS feed %s: %s", url, exc)
            # Chained so retry_fetch can read the feed's HTTP status.
            raise CalendarFetchError(
                f"ICS feed {_url_hostname(url)} could not be read: {exc}"
            ) from exc

        try:
            cal = ICalendar.from_ical(_feed_body(resp))
        except Exception as exc:
            logger.warning("Failed to parse ICS feed %s: %s", url, exc)
            raise CalendarFetchError(f"ICS feed {_url_hostname(url)} could not be parsed: {exc}")

        # Prefer X-WR-CALNAME if present, fall back to URL hostname
        cal_name = str(cal.get("X-WR-CALNAME", "")) or _url_hostname(url)

        feed_events: list[CalendarEvent] = []
        for component in _expand_components(cal, time_min, time_max, url):
            event = _parse_ical_event(component, cal_name, tz=tz)
            if event is not None and _in_window(event, time_min, time_max, tz):
                feed_events.append(event)
        all_events.extend(_cap_runaway_series(feed_events, url))

    all_events.sort(key=lambda e: e.start)
    return all_events


def _feed_body(resp) -> bytes | str:
    """Return the payload to hand to ``Calendar.from_ical``.

    RFC 5545 mandates UTF-8, but ``resp.text`` decodes with whatever requests
    infers, and for ``text/calendar`` with no ``charset`` parameter (common
    for iCloud/Nextcloud/Google exports behind CDNs) that is ISO-8859-1 per
    RFC 2616, which mangles every non-ASCII character. The raw bytes
    let ``icalendar`` decode UTF-8 itself; ``resp.text`` is used only when the
    server names a charset. A response whose ``content`` is not bytes (a test
    double that sets only ``.text``) falls back to the text.
    """
    content_type = str(resp.headers.get("content-type", "")) if resp.headers else ""
    body = getattr(resp, "content", None)
    if "charset=" in content_type.lower() or not isinstance(body, (bytes, bytearray)):
        return resp.text
    return bytes(body)


def _in_window(event: CalendarEvent, time_min, time_max, tz: tzinfo | None) -> bool:
    """True if *event* overlaps the half-open window ``[time_min, time_max)``.

    Both all-day and timed events use overlap semantics — an event is in the
    window if it starts before the window ends and ends after it starts — so a
    timed conference running Sunday 09:00 → Tuesday 17:00 stays in a
    Monday-anchored week, as it does under Google's full sync (whose
    ``timeMin`` bounds the *end*) and CalDAV's server search.
    """
    if event.is_all_day:
        s = event.start.date() if isinstance(event.start, datetime) else event.start
        e = event.end.date() if isinstance(event.end, datetime) else event.end
        win_start_date = time_min.astimezone(tz).date() if tz else time_min.date()
        win_end_date = time_max.astimezone(tz).date() if tz else time_max.date()
        return s < win_end_date and e > win_start_date

    start, end = event.start, event.end
    if start.tzinfo is not None:
        win_start, win_end = time_min, time_max
        if end.tzinfo is None:
            end = end.replace(tzinfo=start.tzinfo)
    elif tz is not None:
        win_start = time_min.astimezone(tz).replace(tzinfo=None)
        win_end = time_max.astimezone(tz).replace(tzinfo=None)
    else:
        win_start = time_min.replace(tzinfo=None)
        win_end = time_max.replace(tzinfo=None)
    if end.tzinfo is not None and start.tzinfo is None:
        end = end.replace(tzinfo=None)
    return start < win_end and end > win_start


def _drop_unusable_vevents(cal, url: str) -> None:
    """Remove VEVENTs with no DTSTART from *cal*, in place.

    ``recurring_ical_events`` raises ``KeyError('DTSTART')`` on such a
    component and takes the whole feed down with it — one malformed VEVENT
    would disable recurrence expansion for every series in the calendar.
    ``_parse_ical_event`` already skips these (they carry no usable time), so
    dropping them here costs nothing.

    Mutates in place: *cal* is parsed fresh per fetch and is not shared.
    Non-VEVENT subcomponents (notably VTIMEZONE) are preserved — the expander
    needs them to resolve TZIDs.
    """
    bad_ids = {
        id(c)
        for c in cal.subcomponents
        if getattr(c, "name", None) == "VEVENT" and c.get("DTSTART") is None
    }
    if not bad_ids:
        return
    cal.subcomponents = [c for c in cal.subcomponents if id(c) not in bad_ids]
    logger.warning("Skipping %d VEVENT(s) with no DTSTART in %s", len(bad_ids), url)


def _raw_vevents(cal) -> list:
    """The unexpanded walk: one component per series, no expansion."""
    return [c for c in cal.walk() if c.name == "VEVENT"]


def _expand_one_by_one(cal, module, time_min, time_max, url: str) -> list:
    """Expand each VEVENT in its own calendar so one bad series can't sink the rest.

    Slow path, reached only after a whole-calendar expansion raised. A single
    unparseable RRULE (``FREQ=BOGUS`` and friends) otherwise costs every
    recurring event in the feed; here it costs only itself, and that series
    still appears unexpanded rather than vanishing.
    """
    shared = [c for c in cal.subcomponents if getattr(c, "name", None) != "VEVENT"]
    out: list = []
    for vevent in cal.subcomponents:
        if getattr(vevent, "name", None) != "VEVENT":
            continue
        single = cal.__class__(cal)
        single.subcomponents = [*shared, vevent]
        try:
            out.extend(module.of(single).between(time_min, time_max))
        except Exception as exc:
            logger.warning(
                "Could not expand %r in %s: %s — using it unexpanded",
                str(vevent.get("SUMMARY", "(no title)")),
                url,
                exc,
            )
            out.append(vevent)
    return out


def _cap_runaway_series(events: list[CalendarEvent], url: str) -> list[CalendarEvent]:
    """Drop occurrences past ``_MAX_OCCURRENCES_PER_SERIES`` for any one UID.

    An unbounded rule (``FREQ=MINUTELY`` with no COUNT/UNTIL, whether broken
    or hostile) expands to five figures inside a one-week window — ~13k
    components for a 9-day span — and every one of them is then parsed,
    written into the cache JSON, sorted, and handed to a renderer sized for a
    normal week.

    The cap is per series rather than per feed because ``between()`` returns
    occurrences grouped by series, not in chronological order: a flat
    head-of-list cap would keep the whole runaway series and silently drop the
    real ones that happen to sort after it.

    It runs on the parsed events *after* the window filter, not on the padded
    expansion (which starts a day before the window), so the number in the
    log is the number the caller gets.
    """
    seen: dict[str, int] = {}
    over: set[str] = set()
    kept: list[CalendarEvent] = []
    for event in events:
        uid = event.event_id or ""
        count = seen.get(uid, 0) + 1
        seen[uid] = count
        if count > _MAX_OCCURRENCES_PER_SERIES:
            over.add(uid)
            continue
        kept.append(event)
    for uid in sorted(over):
        logger.warning(
            "Series %r in %s expands to %d occurrences in the fetch window; "
            "keeping the first %d (check its RRULE for a missing COUNT/UNTIL)",
            uid,
            url,
            seen[uid],
            _MAX_OCCURRENCES_PER_SERIES,
        )
    return kept


def _expand_components(cal, time_min, time_max, url: str) -> list:
    """Yield VEVENT components with recurrence rules expanded to occurrences.

    A raw ``cal.walk()`` sees one VEVENT per recurring series, carrying only
    the series' original DTSTART — a weekly standup would appear in the week
    of its first occurrence and never again. ``recurring_ical_events`` expands RRULE / RDATE /
    EXDATE / RECURRENCE-ID into one component per occurrence inside the
    window, matching the CalDAV backend's ``server_expand=True`` behaviour so
    both backends agree on the same calendar. Occurrences still flow through
    the existing per-event window filter, so boundary semantics for
    non-recurring events are unchanged.

    The expansion span is padded a day either side of the fetch window.
    ``between()`` resolves a *floating* DTSTART (no TZID, no ``Z``) against
    UTC, while the caller's filter resolves it against the configured zone —
    so in a western zone an unpadded span would cut short events in the first
    ``|utcoffset|`` hours of day one. The pad covers any offset; the caller's
    filter still decides what is in window.

    Falls back to the raw walk with a warning if the library is unavailable
    (a deployment whose requirements weren't refreshed) — recurring events
    then appear in their first week only, rather than dropping the feed.
    """
    try:
        import recurring_ical_events  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "recurring-ical-events not installed; recurring events in %s will "
            "only appear in their first week (pip install recurring-ical-events)",
            url,
        )
        return _raw_vevents(cal)

    _drop_unusable_vevents(cal, url)
    span_min = time_min - _EXPAND_PAD
    span_max = time_max + _EXPAND_PAD
    try:
        return list(recurring_ical_events.of(cal).between(span_min, span_max))
    except Exception as exc:
        logger.warning("Recurrence expansion failed for %s: %s — retrying event by event", url, exc)

    try:
        return _expand_one_by_one(cal, recurring_ical_events, span_min, span_max, url)
    except Exception as exc:
        logger.warning("Per-event expansion failed for %s: %s — using raw events", url, exc)
        return _raw_vevents(cal)


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
