"""Unit tests for the shared art-theme helpers in src/render/artkit.py."""

from datetime import date

from src.render.artkit import accent_red, grey, ink, season
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_RED


class TestModeAwareColors:
    def test_grey_l_mode_returns_int(self):
        assert grey(128, "L") == 128

    def test_grey_rgb_mode_returns_triple(self):
        assert grey(128, "RGB") == (128, 128, 128)

    def test_ink_l_mode(self):
        assert ink("L") == 0

    def test_ink_rgb_mode(self):
        assert ink("RGB") == (0, 0, 0)

    def test_accent_red_rgb_uses_spectra6_red(self):
        assert accent_red("RGB") == INKY_SPECTRA6_PALETTE[INKY_RED]

    def test_accent_red_l_mode_collapses_to_ink(self):
        assert accent_red("L") == 0


class TestSeason:
    def test_meteorological_boundaries(self):
        assert season(date(2026, 12, 1)) == "winter"
        assert season(date(2026, 2, 28)) == "winter"
        assert season(date(2026, 3, 1)) == "spring"
        assert season(date(2026, 5, 31)) == "spring"
        assert season(date(2026, 6, 1)) == "summer"
        assert season(date(2026, 8, 31)) == "summer"
        assert season(date(2026, 9, 1)) == "autumn"
        assert season(date(2026, 11, 30)) == "autumn"
