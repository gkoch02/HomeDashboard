"""Tests for the old_fashioned theme's broadsheet masthead component."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from PIL import Image, ImageDraw

from src.data.models import StalenessLevel
from src.render.components.broadsheet_masthead import (
    BAND_H,
    draw_broadsheet_masthead,
    roman,
)
from src.render.components.header import status_label
from src.render.theme import ComponentRegion, load_theme
from tests.inkutils import ink, record_text

TODAY = date(2026, 4, 6)
STAMP = datetime(2026, 4, 6, 10, 30)
REGION = ComponentRegion(0, 0, 800, 80)


def _draw(**kwargs):
    img = Image.new("1", (800, 80), 1)
    draw = ImageDraw.Draw(img)
    calls = record_text(draw)
    style = load_theme("old_fashioned").style
    draw_broadsheet_masthead(
        draw, kwargs.pop("today", TODAY), STAMP, region=REGION, style=style, **kwargs
    )
    return img, [text for text, _ in calls]


class TestRoman:
    @pytest.mark.parametrize(
        ("n", "numeral"), [(1, "I"), (4, "IV"), (9, "IX"), (26, "XXVI"), (49, "XLIX"), (100, "C")]
    )
    def test_numerals(self, n, numeral):
        assert roman(n) == numeral


class TestStatusLabel:
    def test_fresh(self):
        assert status_label(False, {"weather": StalenessLevel.AGING}) == "Updated  "

    def test_cached(self):
        assert status_label(True, None) == "! Cached  "

    def test_stale_beats_cached(self):
        assert status_label(True, {"weather": StalenessLevel.EXPIRED}) == "! Stale  "


class TestMasthead:
    def test_sets_the_nameplate_ears_and_dateline(self):
        _, texts = _draw(title="Home Dashboard")
        assert "Home Dashboard" in texts
        assert "VOL. XXVI" in texts
        assert "No. 96" in texts
        assert "MONDAY, APRIL 6, 2026" in texts
        assert "UPDATED APR 6 · 10:30A" in texts

    def test_stale_sources_mark_the_stamp(self):
        _, texts = _draw(source_staleness={"calendar": StalenessLevel.STALE})
        assert "! STALE APR 6 · 10:30A" in texts

    def test_the_band_is_inverted_and_the_strip_is_paper(self):
        img, _ = _draw()
        band = (0, 0, 800, BAND_H)
        assert ink(img, band) > 0.6 * 800 * BAND_H, "the nameplate band is not inverted"
        strip = (0, BAND_H + 6, 800, 78)
        assert ink(img, strip) < 0.2 * 800 * (78 - BAND_H - 6)

    def test_a_long_title_shrinks_to_clear_the_ears(self):
        """The nameplate never runs under the ear boxes."""
        img, texts = _draw(title="The Extraordinarily Verbose Household Information Gazette")
        ear_gap = (8 + 92 + 2, 10, 8 + 92 + 12, BAND_H - 10)
        # Inside the band, ink is the fill; a glyph knocked out of it is paper.
        paper = ear_gap[2] - ear_gap[0]
        paper *= ear_gap[3] - ear_gap[1]
        assert ink(img, ear_gap) == paper, "the title runs into the left ear"
        assert any("Gazette" in t or t.endswith("...") for t in texts)

    def test_a_title_too_long_at_the_smallest_size_is_ellipsised(self):
        _, texts = _draw(title="Gazette " * 20)
        assert any(t.endswith("...") for t in texts), "an overlong title was not truncated"

    def test_defaults_are_supplied(self):
        img = Image.new("1", (800, 80), 1)
        draw_broadsheet_masthead(ImageDraw.Draw(img), TODAY, STAMP)
        assert ink(img) > 0
