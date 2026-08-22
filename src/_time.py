"""Sanctioned timezone-aware datetime helpers.

Persistent timestamps in the codebase must be aware (carry tzinfo). Bare
``datetime.now()`` / ``datetime.utcnow()`` produces naive values that silently
break arithmetic against aware values from other modules — use the helpers
here instead.

The CI guard at ``tools/check_naive_datetime.py`` enforces this for files
under ``src/``. Use ``# allow-naive-datetime`` on lines where naive local
wall-clock time is genuinely what's wanted (file-name timestamps, quiet-hours
comparisons against config strings, test fallbacks).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo


def now_utc() -> datetime:
    """Return current UTC time as an aware datetime."""
    return datetime.now(timezone.utc)


def now_local(tz: tzinfo | None = None) -> datetime:
    """Return current time as an aware datetime in *tz* (UTC if None).

    Falls back to UTC rather than the system local zone when *tz* is None
    so callers don't accidentally get a host-dependent value.
    """
    return datetime.now(tz or timezone.utc)


def to_aware(value: datetime, tz: tzinfo | None = None) -> datetime:
    """Attach *tz* (or UTC) to a naive datetime; pass aware values through."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tz or timezone.utc)
    return value


def day_start_utc(day: date, tz: tzinfo | None = None) -> datetime:
    """Return midnight at the start of *day* in *tz*, expressed in UTC.

    This is the sanctioned way to build fetch-window boundaries from a local
    calendar date. ``datetime.combine(day, time.min).astimezone(timezone.utc)``
    interprets the naive midnight in the *host machine's* timezone — on the
    default Pi setup (system tz UTC, configured tz local) that shifts the
    window by the UTC offset and silently drops events at the window edges.

    When *tz* is None, midnight is interpreted in the host timezone — the
    calendar fetchers derive *day* from the host clock in that case
    (``date.today()``), so host-tz interpretation keeps the pair consistent
    and preserves the historical behaviour for unconfigured-timezone installs.
    """
    if tz is None:
        return datetime.combine(day, time.min).astimezone(timezone.utc)
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


def week_start(day: date) -> date:
    """Return the Monday of *day*'s week.

    The default anchor for the calendar event window, matching the standard
    week view. It lives here rather than in the fetchers because three of them
    (`calendar_google`, `calendar_ical`, `calendar_caldav`) resolve a `None`
    `start_date` to this value, and `DashboardApp._event_window` has to resolve
    it the same way to union a `None`-anchored window against an explicitly
    anchored one. Four independent copies of `today - timedelta(today.weekday())`
    would be free to drift apart, and the union would then size a window the
    fetchers do not actually use.
    """
    return day - timedelta(days=day.weekday())


def assert_aware(value: datetime, name: str = "datetime") -> datetime:
    """Raise ``ValueError`` if *value* is naive; return it unchanged otherwise."""
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware, got naive: {value!r}")
    return value
