"""Fetcher plugin registry.

Each data source (calendar events, weather, birthdays, air quality, …)
registers a :class:`Fetcher` describing how to fetch, serialise, and cache
its value. :class:`~src.data_pipeline.DataPipeline` and the cache I/O layer
iterate the registry instead of naming sources directly, so adding a new
data source in v5 is a single new registration call.

The registry is populated as a side effect of importing the fetcher
modules. ``src.fetchers.__init__`` imports the built-in fetchers so any
caller that touches the package gets a fully-loaded registry.

Adding a new source is::

    from src.fetchers.registry import Fetcher, FetchContext, register_fetcher

    def _fetch_my_source(ctx: FetchContext) -> MyData:
        return ...

    register_fetcher(Fetcher(
        name="my_source",
        fetch=_fetch_my_source,
        serialize=lambda v: {"foo": v.foo},
        deserialize=lambda b: MyData(foo=b["foo"]),
        ttl_minutes=lambda cfg: cfg.cache.my_source_ttl_minutes,
        interval_minutes=lambda cfg: cfg.cache.my_source_fetch_interval,
        enabled=lambda cfg: bool(cfg.my_source.api_key),
    ))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any, Callable


@dataclass
class FetchContext:
    """Inputs handed to every fetcher invocation.

    All fields are read-only from the fetcher's perspective. The pipeline
    constructs one ``FetchContext`` per ``DataPipeline.fetch()`` call and
    shares it across every registered fetcher.
    """

    cfg: Any
    tz: tzinfo | None = None
    cache_dir: str = ""
    fetched_at: datetime | None = None
    event_window_start: date | None = None
    event_window_days: int = 7


def _always_enabled(_cfg: Any) -> bool:
    return True


def _no_metadata(_ctx: FetchContext) -> dict:
    return {}


def _metadata_always_valid(_metadata: dict, _ctx: FetchContext) -> bool:
    return True


def _no_log(_value: Any) -> str:
    return ""


@dataclass(frozen=True)
class Fetcher:
    """A pluggable data source.

    Attributes:
        name: Stable key — used as cache bucket name, breaker key, quota
            counter key, and ``DashboardData`` field name.
        fetch: Produces the fresh value given a :class:`FetchContext`.
            Exceptions propagate; the pipeline catches them and falls back
            to cache.
        serialize: Convert the value to JSON-able primitives for the cache.
        deserialize: Inverse of ``serialize``.
        ttl_minutes: Read TTL from a Config object (TTL governs staleness
            classification once a cached value is consulted).
        interval_minutes: Read fetch interval from a Config object (governs
            whether to skip the network call entirely on this run).
        enabled: Whether this fetcher should run for the given config.
            Disabled fetchers are skipped silently — no breaker entry, no
            cache miss. Defaults to always-on.
        save_metadata: Per-source extras stored alongside ``data`` in the
            cache file (e.g. events stores its window range so a window
            change invalidates the cache).
        cache_metadata_valid: Validate cached metadata against the current
            context. Return ``False`` to force a refetch.
        log_success: Render a human-readable info-log line on a fresh
            fetch (empty string ⇒ no log emitted).
    """

    name: str
    fetch: Callable[[FetchContext], Any]
    serialize: Callable[[Any], Any]
    deserialize: Callable[[Any], Any]
    ttl_minutes: Callable[[Any], int]
    interval_minutes: Callable[[Any], int]
    enabled: Callable[[Any], bool] = field(default=_always_enabled)
    save_metadata: Callable[[FetchContext], dict] = field(default=_no_metadata)
    cache_metadata_valid: Callable[[dict, FetchContext], bool] = field(
        default=_metadata_always_valid
    )
    log_success: Callable[[Any], str] = field(default=_no_log)


_REGISTRY: dict[str, Fetcher] = {}


def register_fetcher(fetcher: Fetcher) -> Fetcher:
    """Register *fetcher*; later registrations with the same name are a no-op.

    Re-registration is silently ignored so module reloads in tests don't
    raise. Use :func:`unregister_fetcher` first to genuinely replace.
    """
    if fetcher.name in _REGISTRY:
        return _REGISTRY[fetcher.name]
    _REGISTRY[fetcher.name] = fetcher
    return fetcher


def unregister_fetcher(name: str) -> None:
    """Remove *name* from the registry. Used by tests."""
    _REGISTRY.pop(name, None)


def get_fetcher(name: str) -> Fetcher | None:
    """Return the registered :class:`Fetcher` for *name*, or ``None``."""
    return _REGISTRY.get(name)


def all_fetchers() -> list[Fetcher]:
    """Return all registered fetchers in registration order."""
    return list(_REGISTRY.values())


def registered_names() -> list[str]:
    """Return all registered fetcher names in registration order."""
    return list(_REGISTRY.keys())
