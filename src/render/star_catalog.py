"""Embedded bright-star catalogue + constellation line data.

A curated subset of the Yale Bright Star Catalog (J2000 epoch) covering the
naked-eye stars and constellation outlines used by the ``constellation_map``
theme.  Coordinates are the standard astronomical:

  * ``ra``  — right ascension in **hours** (0–24)
  * ``dec`` — declination in **degrees** (−90 to +90)
  * ``mag`` — apparent V magnitude (lower = brighter)

This is intentionally a small focused set (~45 stars, 9 constellations) — the
bright "marquee" sky that most observers can find from a back yard.  Coordinate
precision is one decimal place in RA hours / two in Dec, which keeps the file
human-readable while landing every star within ~1 chart-pixel of its true
position on a 400-pixel-radius dial.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Star:
    """One naked-eye star, J2000 equatorial coordinates + visual magnitude."""

    name: str
    ra: float  # hours
    dec: float  # degrees
    mag: float


# ---------------------------------------------------------------------------
# Star catalogue (45 stars)
# ---------------------------------------------------------------------------
#
# Ordered loosely by constellation for readability; the table is consumed by
# name lookup, not by index.

STARS: list[Star] = [
    # — Ursa Major (Big Dipper) —
    Star("Dubhe", 11.062, 61.751, 1.79),
    Star("Merak", 11.031, 56.382, 2.37),
    Star("Phecda", 11.897, 53.694, 2.44),
    Star("Megrez", 12.257, 57.033, 3.32),
    Star("Alioth", 12.900, 55.960, 1.77),
    Star("Mizar", 13.399, 54.925, 2.27),
    Star("Alkaid", 13.792, 49.313, 1.85),
    # — Ursa Minor (Polaris only) —
    Star("Polaris", 2.530, 89.264, 1.97),
    # — Cassiopeia (the W) —
    Star("Caph", 0.153, 59.150, 2.27),
    Star("Schedar", 0.675, 56.537, 2.24),
    Star("Gamma Cas", 0.946, 60.717, 2.39),
    Star("Ruchbah", 1.430, 60.235, 2.68),
    Star("Segin", 1.907, 63.670, 3.38),
    # — Orion —
    Star("Betelgeuse", 5.919, 7.407, 0.42),
    Star("Bellatrix", 5.418, 6.350, 1.64),
    Star("Mintaka", 5.533, -0.299, 2.20),
    Star("Alnilam", 5.604, -1.202, 1.69),
    Star("Alnitak", 5.679, -1.943, 1.79),
    Star("Saiph", 5.796, -9.670, 2.06),
    Star("Rigel", 5.242, -8.202, 0.18),
    # — Lyra —
    Star("Vega", 18.616, 38.784, 0.03),
    Star("Sheliak", 18.835, 33.363, 3.52),
    Star("Sulafat", 18.983, 32.690, 3.25),
    Star("Zeta Lyr", 18.745, 37.605, 4.34),
    # — Cygnus (Northern Cross) —
    Star("Deneb", 20.690, 45.280, 1.25),
    Star("Sadr", 20.371, 40.257, 2.23),
    Star("Gienah", 20.770, 33.970, 2.48),
    Star("Delta Cyg", 19.749, 45.131, 2.87),
    Star("Albireo", 19.512, 27.960, 3.18),
    # — Bootes —
    Star("Arcturus", 14.261, 19.182, -0.05),
    Star("Izar", 14.750, 27.075, 2.37),
    Star("Muphrid", 13.911, 18.398, 2.68),
    Star("Seginus", 14.535, 38.308, 3.04),
    Star("Nekkar", 15.032, 40.391, 3.49),
    # — Leo —
    Star("Regulus", 10.139, 11.967, 1.36),
    Star("Denebola", 11.818, 14.572, 2.14),
    Star("Algieba", 10.333, 19.842, 2.61),
    Star("Zosma", 11.235, 20.524, 2.56),
    Star("Chertan", 11.237, 15.430, 3.33),
    # — Standalone bright stars (no full constellation drawn) —
    Star("Sirius", 6.752, -16.716, -1.46),
    Star("Procyon", 7.655, 5.225, 0.34),
    Star("Capella", 5.278, 45.998, 0.08),
    Star("Aldebaran", 4.599, 16.509, 0.85),
    Star("Pollux", 7.755, 28.026, 1.14),
    Star("Castor", 7.577, 31.888, 1.58),
    Star("Altair", 19.846, 8.868, 0.77),
    Star("Antares", 16.490, -26.432, 1.06),
    Star("Spica", 13.420, -11.161, 0.97),
    Star("Fomalhaut", 22.961, -29.622, 1.16),
]

# Fast lookup by star name
STARS_BY_NAME: dict[str, Star] = {s.name: s for s in STARS}


# ---------------------------------------------------------------------------
# Constellation outlines
# ---------------------------------------------------------------------------
#
# Each entry maps a display name to the ordered list of (star, star) line
# segments that trace out the asterism.  All referenced stars must exist in
# ``STARS_BY_NAME`` (validated by the test suite).

CONSTELLATIONS: dict[str, list[tuple[str, str]]] = {
    "Ursa Major": [
        ("Dubhe", "Merak"),
        ("Merak", "Phecda"),
        ("Phecda", "Megrez"),
        ("Megrez", "Dubhe"),
        ("Megrez", "Alioth"),
        ("Alioth", "Mizar"),
        ("Mizar", "Alkaid"),
    ],
    "Cassiopeia": [
        ("Caph", "Schedar"),
        ("Schedar", "Gamma Cas"),
        ("Gamma Cas", "Ruchbah"),
        ("Ruchbah", "Segin"),
    ],
    "Orion": [
        ("Betelgeuse", "Bellatrix"),
        ("Bellatrix", "Mintaka"),
        ("Mintaka", "Alnilam"),
        ("Alnilam", "Alnitak"),
        ("Alnitak", "Saiph"),
        ("Saiph", "Rigel"),
        ("Rigel", "Mintaka"),
        ("Betelgeuse", "Alnitak"),
    ],
    "Lyra": [
        ("Vega", "Zeta Lyr"),
        ("Zeta Lyr", "Sheliak"),
        ("Sheliak", "Sulafat"),
        ("Sulafat", "Zeta Lyr"),
    ],
    "Cygnus": [
        ("Deneb", "Sadr"),
        ("Sadr", "Gienah"),
        ("Sadr", "Delta Cyg"),
        ("Sadr", "Albireo"),
    ],
    "Bootes": [
        ("Arcturus", "Muphrid"),
        ("Arcturus", "Izar"),
        ("Izar", "Nekkar"),
        ("Nekkar", "Seginus"),
        ("Seginus", "Arcturus"),
    ],
    "Leo": [
        ("Regulus", "Algieba"),
        ("Algieba", "Zosma"),
        ("Zosma", "Denebola"),
        ("Denebola", "Chertan"),
        ("Chertan", "Regulus"),
    ],
}


# Stars to label with text on the chart (subset of the brightest / most
# recognisable; full labels would clutter the disc).
LABELED_STARS: frozenset[str] = frozenset(
    {
        "Polaris",
        "Betelgeuse",
        "Rigel",
        "Sirius",
        "Vega",
        "Deneb",
        "Altair",
        "Arcturus",
        "Capella",
        "Aldebaran",
        "Regulus",
        "Procyon",
        "Antares",
        "Spica",
    }
)
