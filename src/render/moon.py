"""Moon phase calculation — pure math, no external API needed.

Uses a simplified algorithm based on the known new-moon reference date
(2000-01-06 18:14 UTC) and the synodic month length (29.53059 days).
"""

from datetime import date, datetime, timezone

# Mean synodic month in days (new moon to new moon)
_SYNODIC_MONTH = 29.53059

# Reference new moon: 2000-01-06 18:14 UTC
_REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, 0, tzinfo=timezone.utc)

# Weather Icons font has 28 moon phase glyphs: \uf095 (new) through \uf0B0 (waning crescent)
# Index 0 = new moon, 14 = full moon
_MOON_GLYPHS = [
    "\uf095",  # 0  new moon
    "\uf096",  # 1  waxing crescent
    "\uf097",  # 2
    "\uf098",  # 3
    "\uf099",  # 4
    "\uf09a",  # 5
    "\uf09b",  # 6  first quarter
    "\uf09c",  # 7
    "\uf09d",  # 8
    "\uf09e",  # 9
    "\uf09f",  # 10
    "\uf0a0",  # 11
    "\uf0a1",  # 12
    "\uf0a2",  # 13 waxing gibbous
    "\uf0a3",  # 14 full moon
    "\uf0a4",  # 15
    "\uf0a5",  # 16
    "\uf0a6",  # 17
    "\uf0a7",  # 18
    "\uf0a8",  # 19
    "\uf0a9",  # 20
    "\uf0aa",  # 21 third quarter
    "\uf0ab",  # 22
    "\uf0ac",  # 23
    "\uf0ad",  # 24
    "\uf0ae",  # 25
    "\uf0af",  # 26
    "\uf0b0",  # 27 waning crescent
]

# Human-readable phase names (8-phase system)
_PHASE_NAMES = [
    "New Moon",
    "Waxing Crescent",
    "First Quarter",
    "Waxing Gibbous",
    "Full Moon",
    "Waning Gibbous",
    "Third Quarter",
    "Waning Crescent",
]


def moon_phase_age(d: date) -> float:
    """Return the moon's age in days (0 = new moon, ~14.76 = full moon)."""
    dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=timezone.utc)
    diff = (dt - _REFERENCE_NEW_MOON).total_seconds() / 86400.0
    return diff % _SYNODIC_MONTH


def moon_phase_name(d: date) -> str:
    """Return a human-readable phase name for the given date."""
    age = moon_phase_age(d)
    fraction = age / _SYNODIC_MONTH
    idx = int(fraction * 8 + 0.5) % 8
    return _PHASE_NAMES[idx]


def moon_phase_glyph(d: date) -> str:
    """Return the Weather Icons glyph character for the moon phase on *d*."""
    age = moon_phase_age(d)
    fraction = age / _SYNODIC_MONTH
    idx = int(fraction * 28 + 0.5) % 28
    return _MOON_GLYPHS[idx]
