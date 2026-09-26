"""Per-thread count of the HTTP requests a fetch makes.

The quota tracker used to add one per successful *fetch*, but a weather fetch
is two OpenWeatherMap requests plus One Call (four on a stormy 4.0 day), a
Google fetch is a request per page, and a failed fetch — the 401 retried on
every run — cost requests it never recorded. So the daily threshold could
not fire (#296).

The pipeline runs each source's fetch in its own worker thread inside
:func:`counting`; the fetcher bumps the tally at each request it sends, via
:func:`count_request` or by :func:`attach`-ing its HTTP session. Counting
happens as a request is *sent*, so one that times out or never connects still
counts — those are the runs a quota warning is for. A call outside
:func:`counting` (a test, a direct fetcher call) is a no-op.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

_local = threading.local()


@dataclass
class Tally:
    count: int = 0


def count_request(n: int = 1) -> None:
    """Record *n* requests against the fetch running on this thread."""
    tally = getattr(_local, "tally", None)
    if tally is not None:
        tally.count += n


def attach(session) -> None:
    """Count every request *session* sends, redirect hops included.

    Wraps ``session.send`` — the one method every ``requests``-style session
    funnels each request through (``niquests``, which newer ``caldav`` uses,
    included). A session without one is left alone; its fetch then records
    only what its caller counts explicitly.
    """
    send = getattr(session, "send", None)
    if not callable(send):
        return

    def counted_send(request, *args, **kwargs):
        count_request()
        return send(request, *args, **kwargs)

    session.send = counted_send


@contextmanager
def counting() -> Iterator[Tally]:
    """Collect the requests made on this thread until the block exits."""
    tally = Tally()
    previous = getattr(_local, "tally", None)
    _local.tally = tally
    try:
        yield tally
    finally:
        _local.tally = previous
