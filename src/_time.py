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

from datetime import datetime, timezone, tzinfo


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


def assert_aware(value: datetime, name: str = "datetime") -> datetime:
    """Raise ``ValueError`` if *value* is naive; return it unchanged otherwise."""
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware, got naive: {value!r}")
    return value
