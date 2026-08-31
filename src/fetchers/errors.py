"""Exception types shared by the fetcher layer.

Kept in its own module so the calendar backends can raise a common type
without importing each other (``calendar_ical`` and ``calendar_caldav`` are
siblings, and ``calendar`` imports both).
"""

from __future__ import annotations


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
