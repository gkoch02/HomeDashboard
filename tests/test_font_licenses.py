"""Every bundled font ships with the license that permits bundling it.

`docs/development.md` states the rule ("Don't ship a font without its license"),
but nothing enforced it, and the tree drifted: 20 of 29 font files shipped with
no license text at all, and five of those were display faces whose name tables
carried no copyright, no license description, and no license URL — no grant of
any kind. They were removed rather than documented, because a font you cannot
show a licence for is not a font you can redistribute under this project's MIT
grant.

The SIL Open Font License makes this a licence condition rather than good
housekeeping: OFL 1.1 §2 requires that the license text accompany any
redistribution of the font, so an OFL face bundled without its `OFL.txt` is a
compliance failure that ships in every clone, wheel, and `make deploy` rsync.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FONT_DIR = Path(__file__).parent.parent / "fonts"

FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".woff", ".woff2")

# A family's license file is named "<Family>-OFL.txt" beside the font, matching
# the flat layout of fonts/. The family is the part of the filename before the
# first "-" (PlayfairDisplay-Bold.ttf -> PlayfairDisplay), or the whole stem
# when there is no weight suffix (Cinzel.ttf -> Cinzel).
_LICENSE_RE = re.compile(r"-(OFL|LICENSE)\.txt$", re.IGNORECASE)


def _family(font: Path) -> str:
    return font.stem.split("-")[0]


def _font_files() -> list[Path]:
    return sorted(p for p in FONT_DIR.iterdir() if p.suffix.lower() in FONT_SUFFIXES)


def _license_for(font: Path) -> Path | None:
    family = _family(font).lower()
    for candidate in FONT_DIR.iterdir():
        if not _LICENSE_RE.search(candidate.name):
            continue
        if candidate.name.split("-")[0].lower() == family:
            return candidate
    return None


def test_fonts_directory_is_not_empty():
    """Guard against the sweep below passing because it found nothing."""
    assert len(_font_files()) >= 20


@pytest.mark.parametrize("font", _font_files(), ids=lambda p: p.name)
def test_every_bundled_font_ships_its_license(font: Path):
    licence = _license_for(font)
    assert licence is not None, (
        f"{font.name} is bundled with no license file. Add the upstream "
        f"license text as fonts/{_family(font)}-OFL.txt (see the procedure in "
        f"docs/development.md). If the upstream project grants no redistribution "
        f"licence, the font cannot ship here at all."
    )
    text = licence.read_text(encoding="utf-8")
    assert text.strip(), f"{licence.name} is empty"
    assert "SIL OPEN FONT LICENSE" in text.upper(), (
        f"{licence.name} does not contain the SIL Open Font License text. "
        f"A face under different terms needs its own entry in the "
        f"'Third-party content' section of LICENSE."
    )


# Faces whose binary asserts no licence but whose grant has been verified at a
# primary upstream source. Copyright ownership is not permission, so a font that
# names only its owner cannot pass on its metadata alone — but a genuinely
# OFL-licensed family whose build predates the convention of filling nameID
# 13/14 should not be barred either. Each entry names where the grant was read.
# Adding one is a deliberate act: check upstream yourself, and do not take a
# sibling licence file's word for it.
GRANT_VERIFIED_UPSTREAM = {
    # google/fonts ofl/astloch/METADATA.pb records `license: "OFL"`.
    "Astloch-Regular.ttf": "https://github.com/google/fonts/blob/main/ofl/astloch/METADATA.pb",
    "Astloch-Bold.ttf": "https://github.com/google/fonts/blob/main/ofl/astloch/METADATA.pb",
    # google/fonts ofl/tangerine/METADATA.pb records `license: "OFL"`. The
    # binary's copyright reads "All rights reserved", the pre-2012 Google Fonts
    # convention — the grant is upstream, not in the file.
    "Tangerine-Regular.ttf": "https://github.com/google/fonts/blob/main/ofl/tangerine/METADATA.pb",
}


def _asserts_a_licence(declared: dict[int, str]) -> bool:
    """True when the name table asserts a licence rather than only ownership.

    A licence description (13) or URL (14) is the conventional place. Some
    fonts instead state the grant inside the copyright string (nameID 0) —
    Weather Icons does — and that counts, because it is still the font
    declaring its own terms.
    """
    if declared.get(13) or declared.get(14):
        return True
    return "licen" in declared.get(0, "").lower()


@pytest.mark.parametrize("font", _font_files(), ids=lambda p: p.name)
def test_every_bundled_font_declares_a_licence_in_its_metadata(font: Path):
    """The font's own name table must carry a licence, not just a sibling file.

    This is what actually caught the five unlicensed faces: each shipped a
    plausible-looking display font whose name table held a designer URL and
    nothing else — no copyright (nameID 0), no license description (13), no
    license URL (14). A sibling `OFL.txt` proves only that someone put a file
    there; the embedded record is the font's own claim about its terms.

    The bar is a **licence**, not a copyright. An earlier revision accepted any
    non-empty value across 0/13/14, so an ordinary `Copyright (c) 2025 Foo`
    passed with both licence fields blank — certifying a font that grants
    nothing, which is the exact hole this test exists to close. Ownership and
    permission are different claims.
    """
    names = _name_table(font)
    declared = {nid: names.get(nid, "").strip() for nid in (0, 13, 14)}

    if font.name in GRANT_VERIFIED_UPSTREAM:
        # Recorded exception: the binary is silent, the grant is not.
        return

    assert any(declared.values()), (
        f"{font.name} carries no copyright, license description, or license URL "
        f"in its name table — the font itself asserts no terms. Verify its "
        f"provenance before bundling it; do not rely on a sibling license file."
    )
    assert _asserts_a_licence(declared), (
        f"{font.name} names a copyright holder but asserts no licence: nameID "
        f"13 (license description) and 14 (license URL) are both empty and the "
        f"copyright string does not mention one. Copyright states ownership, "
        f"not permission, so this font cannot be redistributed under this "
        f"project's MIT licence on its own say-so. Its copyright reads: "
        f"{declared.get(0, '')!r}. If the family really is OFL and merely has "
        f"an old build, verify the grant at a primary upstream source and "
        f"record it in GRANT_VERIFIED_UPSTREAM in this module, naming where "
        f"you checked."
    )


def test_every_recorded_exception_is_still_needed():
    """An allowlist entry must correspond to a font that actually needs it.

    Two ways it rots: the file is replaced by a build that fills in nameID
    13/14, in which case the entry now silently exempts a font that would pass
    on its own; or the file leaves the tree entirely and the entry lingers.
    Either way the list stops describing the bundle.
    """
    present = {p.name for p in _font_files()}
    for name in GRANT_VERIFIED_UPSTREAM:
        assert name in present, (
            f"GRANT_VERIFIED_UPSTREAM names {name}, which is not in fonts/. Drop the entry."
        )
        declared = {nid: _name_table(FONT_DIR / name).get(nid, "").strip() for nid in (0, 13, 14)}
        assert not _asserts_a_licence(declared), (
            f"{name} now declares a licence in its own metadata, so its "
            f"GRANT_VERIFIED_UPSTREAM entry is obsolete — remove it and let the "
            f"font pass on its own record."
        )


def _name_table(path: Path) -> dict[int, str]:
    """Minimal OpenType `name` table reader.

    Hand-rolled rather than pulled from fontTools: this suite must not grow a
    dependency purely to assert a licensing invariant, and the parse is a
    fixed-layout table walk.
    """
    import struct

    data = path.read_bytes()
    (num_tables,) = struct.unpack(">H", data[4:6])
    offset = None
    for i in range(num_tables):
        rec = 12 + 16 * i
        tag, _checksum, off, _len = struct.unpack(">4sIII", data[rec : rec + 16])
        if tag == b"name":
            offset = off
            break
    if offset is None:
        return {}

    _fmt, count, string_offset = struct.unpack(">HHH", data[offset : offset + 6])
    out: dict[int, str] = {}
    for i in range(count):
        rec = offset + 6 + 12 * i
        platform, _enc, _lang, name_id, ln, str_off = struct.unpack(">HHHHHH", data[rec : rec + 12])
        start = offset + string_offset + str_off
        raw = data[start : start + ln]
        try:
            value = raw.decode("utf-16-be") if platform == 3 else raw.decode("latin-1")
        except UnicodeDecodeError:
            continue
        out.setdefault(name_id, value)
    return out


def _font_filename_literals() -> list[tuple[Path, str]]:
    """Every bare `"Something.ttf"` string literal under src/ and scripts/.

    Deliberately a source scan rather than an import: `scripts/build_banner.py`
    is standalone (it does not import `src.render.fonts`) and nothing in the
    suite executes it, so an import-based check cannot see the filenames it
    holds.
    """
    root = FONT_DIR.parent
    pattern = re.compile(r'"([^"/]+\.(?:ttf|otf|ttc))"')
    found: list[tuple[Path, str]] = []
    for directory in ("src", "scripts"):
        for path in sorted((root / directory).rglob("*.py")):
            for name in pattern.findall(path.read_text(encoding="utf-8")):
                found.append((path, name))
    return found


def test_the_scan_finds_the_font_loaders():
    """Guard against the sweep below passing because the regex matched nothing."""
    referenced = {name for _, name in _font_filename_literals()}
    assert "weathericons-regular.ttf" in referenced
    assert len(referenced) >= 20


@pytest.mark.parametrize(
    ("source", "name"),
    _font_filename_literals(),
    ids=lambda v: v.name if isinstance(v, Path) else v,
)
def test_every_font_named_in_source_is_bundled(source: Path, name: str):
    """A deleted face must leave no dangling reference behind.

    `src/render/fonts.py` is covered by its own accessor tests, but
    `scripts/build_banner.py` loads faces by bare filename and is imported by
    nothing — so a reference there survives the removal of the file it names and
    stays invisible until someone runs `make banner`, where it surfaces as a
    Pillow "cannot open resource". That happened: the banner still asked for two
    faces this project removed for having no licence.
    """
    assert (FONT_DIR / name).is_file(), (
        f"{source.name} loads {name!r}, which is not in fonts/. A font removed "
        f"from the bundle has to be replaced everywhere it is named — including "
        f"scripts/ that load faces by filename rather than through "
        f"src/render/fonts.py."
    )


class TestAssertsALicence:
    """The copyright-is-not-a-licence rule, tested independently of the bundle.

    The parametrized sweep cannot demonstrate rejection on its own: every face
    that would fail is in `GRANT_VERIFIED_UPSTREAM`, so the sweep is all-green
    by construction. These cases pin the distinction directly, including the
    exact shape that slipped past the earlier revision — a plain copyright with
    both licence fields empty.
    """

    def test_copyright_alone_is_not_a_licence(self):
        assert not _asserts_a_licence({0: "Copyright (c) 2025 Foo", 13: "", 14: ""})

    def test_reserved_rights_alone_is_not_a_licence(self):
        assert not _asserts_a_licence({0: "(c) 2025 foundry. All rights reserved.", 13: "", 14: ""})

    def test_empty_metadata_is_not_a_licence(self):
        assert not _asserts_a_licence({0: "", 13: "", 14: ""})

    def test_licence_description_counts(self):
        assert _asserts_a_licence(
            {0: "Copyright (c) 2025 Foo", 13: "Licensed under the SIL OFL", 14: ""}
        )

    def test_licence_url_counts(self):
        assert _asserts_a_licence(
            {0: "Copyright (c) 2025 Foo", 13: "", 14: "https://openfontlicense.org"}
        )

    def test_grant_stated_in_the_copyright_string_counts(self):
        # Weather Icons puts its grant in nameID 0 and leaves 13/14 empty.
        assert _asserts_a_licence({0: "Weather Icons licensed under SIL OFL 1.1", 13: "", 14: ""})
