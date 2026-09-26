"""Exception types shared by the fetcher layer.

Kept in its own module so the calendar backends can raise a common type
without importing each other (``calendar_ical`` and ``calendar_caldav`` are
siblings, and ``calendar`` imports both).
"""

from __future__ import annotations


def http_status(exc: BaseException) -> int | None:
    """Return the HTTP status an exception carries, or ``None``.

    The one place a failure is classified by its HTTP status, shared by the
    pipeline's retry rule and the One Call health record. It reads the status
    the client library attached — ``requests``' ``exc.response.status_code``,
    or googleapiclient's ``exc.status_code`` / ``exc.resp.status`` — and never
    the message text, where a "401" is not evidence of a 401 response. A
    wrapper raised ``from`` the original (a ``CalendarFetchError`` around a
    feed's 404) is followed down its ``__cause__`` chain.

    Read defensively rather than by isinstance: it runs inside degradation
    boundaries, and an attribute lookup that raised would defeat them.
    """
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 8:
        for status in (
            getattr(getattr(current, "response", None), "status_code", None),
            getattr(current, "status_code", None),
            getattr(getattr(current, "resp", None), "status", None),
        ):
            if isinstance(status, int) and not isinstance(status, bool):
                return status
        current = current.__cause__
        seen += 1
    return None


class CalendarFetchError(Exception):
    """A calendar backend could not produce a *complete* answer.

    Raised instead of returning a short or empty list when a feed, server or
    calendar could not be read. The pipeline treats whatever a fetcher returns
    as complete and authoritative — it writes the value to the cache, marks the
    source FRESH and records a breaker *success* — so returning ``[]`` during an
    outage overwrote the last known good calendar with an empty one, left no
    staleness indicator, and kept the breaker closed so nothing ever fell back
    to cache (#234).

    Deliberately **not** a ``RuntimeError``/``ValueError``/``TypeError``/
    ``KeyError``: ``data_pipeline.retry_fetch`` treats those four as permanent
    and skips its retry, while most failures here are transient network errors
    worth one more attempt before the breaker starts counting.
    """
