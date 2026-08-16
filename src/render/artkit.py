"""Shared helpers for the procedural art themes.

The dithered/engraved panels (``weatherglass``, ``postcard``, ``naturalist``,
``halftone``, ``almanac``) render on an ``"L"`` greyscale canvas on Waveshare
and an RGB canvas on Inky, so every colour they place must be expressed
per-mode. These helpers grew up copy-pasted in each panel; this module is the
single home for the genuinely shared ones.

It also holds the naive/aware datetime normalisation that any panel plotting
events on a time axis needs (``to_local_naive`` / ``hours_of_day``).

Panels import them under their established private aliases, e.g.::

    from src.render.artkit import grey as _grey, ink as _ink
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo

from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_RED


def grey(v: int, mode: str) -> int | tuple[int, int, int]:
    """Return *v* (0..255) as either an L-mode int or an RGB greyscale triple."""
    return v if mode == "L" else (v, v, v)


def ink(mode: str) -> int | tuple[int, int, int]:
    """Solid foreground ink (black)."""
    return 0 if mode == "L" else (0, 0, 0)


def accent_red(mode: str) -> int | tuple[int, int, int]:
    """Red accent on the Inky RGB canvas, solid black on L mode.

    L mode collapses the accent to solid ink because mid-grey would dither
    into a noisy half-tone pattern after Floyd-Steinberg — fine for
    procedural illustration but illegible for small text and thin rules.
    """
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_RED]
    return 0


def season(today: date) -> str:
    """Northern-hemisphere meteorological season: winter/spring/summer/autumn."""
    m = today.month
    if 3 <= m <= 5:
        return "spring"
    if 6 <= m <= 8:
        return "summer"
    if 9 <= m <= 11:
        return "autumn"
    return "winter"


def to_local_naive(dt: datetime, tz: tzinfo | None) -> datetime:
    """Strip tzinfo, converting into *tz* first when *tz* is known.

    Panels plot against ``CalendarEvent.start``/``end``, which fetchers store as
    naive local wall clock, while ``RenderContext.now`` and the ``src.astronomy``
    results are aware. Everything has to be normalised to one convention before
    it can be compared or laid out on a time axis; naive local is that convention.

    When *tz* is ``None`` the tzinfo is dropped without conversion, rather than
    calling a bare ``dt.astimezone()``. That bare call resolves against the host
    machine's timezone, which would make a render of identical inputs differ
    between machines — and the theme pixel snapshots hash exactly that render.
    """
    if dt.tzinfo is None:
        return dt
    if tz is None:
        return dt.replace(tzinfo=None)
    return dt.astimezone(tz).replace(tzinfo=None)


def hours_of_day(dt: datetime | None, today: date, tz: tzinfo | None) -> float | None:
    """Return *dt* as fractional hours-of-day on *today*, clamped to [0, 24].

    Returns ``None`` for datetimes that fall on neither today nor an adjacent
    day — those can't be plotted on a single 24h dial.
    """
    if dt is None:
        return None
    naive = to_local_naive(dt, tz)
    delta_days = (naive.date() - today).days
    if delta_days < -1 or delta_days > 1:
        return None
    hours = naive.hour + naive.minute / 60.0 + naive.second / 3600.0 + delta_days * 24.0
    return max(0.0, min(24.0, hours))
