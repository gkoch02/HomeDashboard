"""Canonical data-source names for the web layer.

The v5 fetcher registry made sources pluggable, but the web UI used to name
them in three hardcoded lists (breaker/cache actions, cache-age reads, and the
status payload). A fetcher added per the documented recipe then rendered and
cached correctly while staying invisible in the UI and unresettable from it.

Everything here derives from the registry instead, so registering a fetcher is
still the only step required.
"""

from __future__ import annotations

# Importing the package runs the side-effect imports that populate the
# registry. The web process already pays this cost via
# ``src.web.state_reader``'s import of ``src.fetchers.cache``.
import src.fetchers  # noqa: F401
from src.fetchers.registry import all_fetchers, registered_names

# Display order for the sources the dashboard has always shipped. Registration
# order is an accident of import order in ``src.fetchers.__init__``, and these
# names drive a user-facing table, so pin the familiar order and let anything
# newly registered fall in behind it.
_PREFERRED_ORDER = ("events", "weather", "birthdays", "air_quality")


def source_names() -> tuple[str, ...]:
    """Every registered fetcher name, built-ins first in their usual order."""
    registered = registered_names()
    known = [name for name in _PREFERRED_ORDER if name in registered]
    extra = [name for name in registered if name not in _PREFERRED_ORDER]
    return tuple(known + extra)


def is_known_source(name: str) -> bool:
    """True when *name* is a registered fetcher."""
    return name in source_names()


def source_ttls(cfg) -> dict[str, int]:
    """Return ``{source: ttl_minutes}`` for every registered fetcher.

    The staleness a source is reported with has to be the staleness the
    pipeline computed, and the pipeline reads ``Fetcher.ttl_minutes(cfg)``.
    Naming the four built-ins here instead would leave a new fetcher on
    ``read_cache_ages``'s 60-minute fallback, so the status page could call its
    cache stale while the renderer still considered it fresh.
    """
    ttls: dict[str, int] = {}
    for fetcher in all_fetchers():
        try:
            ttls[fetcher.name] = fetcher.ttl_minutes(cfg)
        except Exception:  # pragma: no cover - a plugin's own config lookup failed
            continue
    return ttls
