"""Tests for src.render.quantize — quantize_for_display() and helpers."""

from __future__ import annotations

import pytest
from PIL import Image

from src.render.quantize import (
    _VALID_MODES,
    _redmean_sq,
    quantize_for_display,
    quantize_to_palette_ordered,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _solid_L(value: int, w: int = 8, h: int = 8) -> Image.Image:
    """Return a solid greyscale image filled with *value* (0–255)."""
    img = Image.new("L", (w, h), value)
    return img


def _gradient_L(w: int = 16, h: int = 1) -> Image.Image:
    """Return a 1-row greyscale ramp from 0 to 255."""
    data = [int(i * 255 / (w - 1)) for i in range(w)]
    img = Image.new("L", (w, h))
    img.putdata(data)
    return img


# ---------------------------------------------------------------------------
# Return type / dimensions
# ---------------------------------------------------------------------------


class TestReturnContract:
    @pytest.mark.parametrize("mode", _VALID_MODES)
    def test_returns_mode_1(self, mode):
        result = quantize_for_display(_solid_L(128), mode=mode)
        assert result.mode == "1"

    @pytest.mark.parametrize("mode", _VALID_MODES)
    def test_preserves_dimensions(self, mode):
        img = _solid_L(128, w=100, h=60)
        result = quantize_for_display(img, mode=mode)
        assert result.size == (100, 60)

    def test_invalid_mode_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown quantization mode"):
            quantize_for_display(_solid_L(128), mode="bogus")

    def test_non_l_input_is_auto_converted(self):
        """Mode "1" input should be accepted and returned as mode "1"."""
        img = Image.new("1", (8, 8), 1)
        result = quantize_for_display(img, mode="threshold")
        assert result.mode == "1"
        assert result.size == (8, 8)


# ---------------------------------------------------------------------------
# Threshold mode
# ---------------------------------------------------------------------------


class TestThresholdMode:
    def test_pure_black_stays_black(self):
        result = quantize_for_display(_solid_L(0), mode="threshold")
        pixels = list(result.getdata())
        assert all(p == 0 for p in pixels)

    def test_pure_white_stays_white(self):
        result = quantize_for_display(_solid_L(255), mode="threshold")
        pixels = list(result.getdata())
        assert all(p != 0 for p in pixels)

    def test_below_midpoint_maps_to_black(self):
        """Values ≤ 128 should produce black pixels under NONE dithering."""
        result = quantize_for_display(_solid_L(127), mode="threshold")
        pixels = list(result.getdata())
        assert all(p == 0 for p in pixels)

    def test_above_midpoint_maps_to_white(self):
        """Values > 128 should produce white pixels."""
        result = quantize_for_display(_solid_L(129), mode="threshold")
        pixels = list(result.getdata())
        assert all(p != 0 for p in pixels)

    def test_gradient_produces_both_values(self):
        """A greyscale ramp must contain both black and white pixels after threshold."""
        result = quantize_for_display(_gradient_L(w=256, h=1), mode="threshold")
        pixels = set(result.getdata())
        assert 0 in pixels
        assert any(p != 0 for p in result.getdata())


# ---------------------------------------------------------------------------
# Floyd-Steinberg mode
# ---------------------------------------------------------------------------


class TestFloydSteinbergMode:
    def test_pure_black_stays_black(self):
        result = quantize_for_display(_solid_L(0), mode="floyd_steinberg")
        pixels = list(result.getdata())
        assert all(p == 0 for p in pixels)

    def test_pure_white_stays_white(self):
        result = quantize_for_display(_solid_L(255), mode="floyd_steinberg")
        pixels = list(result.getdata())
        assert all(p != 0 for p in pixels)

    def test_gradient_produces_both_values(self):
        result = quantize_for_display(_gradient_L(w=256, h=4), mode="floyd_steinberg")
        pixels = list(result.getdata())
        assert 0 in pixels
        assert any(p != 0 for p in pixels)


# ---------------------------------------------------------------------------
# Ordered (Bayer) mode
# ---------------------------------------------------------------------------


class TestOrderedMode:
    def test_pure_black_stays_black(self):
        result = quantize_for_display(_solid_L(0), mode="ordered")
        pixels = list(result.getdata())
        assert all(p == 0 for p in pixels)

    def test_pure_white_stays_white(self):
        result = quantize_for_display(_solid_L(255), mode="ordered")
        pixels = list(result.getdata())
        assert all(p != 0 for p in pixels)

    def test_midgrey_produces_mixed_pattern(self):
        """Mid-grey should produce a mix of black and white under Bayer dithering."""
        result = quantize_for_display(_solid_L(128), mode="ordered")
        pixels = list(result.getdata())
        assert 0 in pixels
        assert any(p != 0 for p in pixels)

    def test_gradient_produces_both_values(self):
        result = quantize_for_display(_gradient_L(w=256, h=4), mode="ordered")
        pixels = list(result.getdata())
        assert 0 in pixels
        assert any(p != 0 for p in pixels)

    def test_tiling_is_4x4_periodic(self):
        """Solid mid-grey: the 4×4 Bayer pattern repeats exactly across tiles."""
        img = _solid_L(128, w=8, h=8)
        result = quantize_for_display(img, mode="ordered")
        pixels = list(result.getdata())
        # Row 0 and row 4 must be identical (4×4 tile repeats vertically)
        row0 = pixels[0:8]
        row4 = pixels[32:40]
        assert row0 == row4
        # Column 0 and column 4 must be identical (repeats horizontally)
        col0 = [pixels[r * 8 + 0] for r in range(8)]
        col4 = [pixels[r * 8 + 4] for r in range(8)]
        assert col0 == col4


# ---------------------------------------------------------------------------
# _redmean_sq
# ---------------------------------------------------------------------------

_SMALL_PALETTE = [
    (0, 0, 0),  # black
    (255, 255, 255),  # white
    (255, 0, 0),  # red
    (0, 0, 255),  # blue
]


class TestRedmeanSq:
    def test_identical_colors_are_zero(self):
        assert _redmean_sq(100, 150, 200, 100, 150, 200) == 0.0

    def test_black_to_white_is_large(self):
        assert _redmean_sq(0, 0, 0, 255, 255, 255) > 1000

    def test_red_closer_to_red_than_blue(self):
        """Pure red should be perceptually closer to red palette than to blue palette."""
        dist_to_red = _redmean_sq(220, 30, 30, 255, 0, 0)
        dist_to_blue = _redmean_sq(220, 30, 30, 0, 0, 255)
        assert dist_to_red < dist_to_blue

    def test_blue_closer_to_blue_than_red(self):
        dist_to_blue = _redmean_sq(20, 20, 220, 0, 0, 255)
        dist_to_red = _redmean_sq(20, 20, 220, 255, 0, 0)
        assert dist_to_blue < dist_to_red


# ---------------------------------------------------------------------------
# quantize_to_palette_ordered
# ---------------------------------------------------------------------------


class TestQuantizeToPaletteOrdered:
    def _solid_rgb(self, r: int, g: int, b: int, w: int = 8, h: int = 8) -> Image.Image:
        return Image.new("RGB", (w, h), (r, g, b))

    def test_returns_rgb_image(self):
        img = self._solid_rgb(128, 128, 128)
        result = quantize_to_palette_ordered(img, _SMALL_PALETTE)
        assert result.mode == "RGB"

    def test_preserves_size(self):
        img = self._solid_rgb(128, 128, 128, w=40, h=30)
        result = quantize_to_palette_ordered(img, _SMALL_PALETTE)
        assert result.size == (40, 30)

    def test_all_pixels_are_palette_colors(self):
        img = Image.new("RGB", (32, 32))
        # Fill with a gradient so the Bayer matrix has something to work with
        pixels = [(x * 8, y * 8, 128) for y in range(32) for x in range(32)]
        img.putdata(pixels)
        result = quantize_to_palette_ordered(img, _SMALL_PALETTE)
        palette_set = set(_SMALL_PALETTE)
        assert set(result.getdata()) <= palette_set

    def test_pure_red_maps_to_red(self):
        """A fully saturated red image should map entirely to the red palette entry."""
        img = self._solid_rgb(255, 0, 0)
        result = quantize_to_palette_ordered(img, _SMALL_PALETTE, bayer_strength=0)
        assert set(result.getdata()) == {(255, 0, 0)}

    def test_pure_black_maps_to_black(self):
        img = self._solid_rgb(0, 0, 0)
        result = quantize_to_palette_ordered(img, _SMALL_PALETTE, bayer_strength=0)
        assert set(result.getdata()) == {(0, 0, 0)}

    def test_bayer_strength_zero_is_nearest_neighbor(self):
        """With bayer_strength=0 every pixel maps to its nearest palette colour."""
        img = self._solid_rgb(200, 50, 50)  # clearly closest to red
        result = quantize_to_palette_ordered(img, _SMALL_PALETTE, bayer_strength=0)
        pixels = set(result.getdata())
        assert pixels == {(255, 0, 0)}

    def test_inky_palette_all_pixels_valid(self):
        """Using the real Inky Spectra 6 palette, all output pixels must be palette members."""
        from src.render.quantize import INKY_SPECTRA6_PALETTE

        img = Image.new("RGB", (16, 16))
        pixels = [(x * 16, y * 16, (x + y) * 8) for y in range(16) for x in range(16)]
        img.putdata(pixels)
        result = quantize_to_palette_ordered(img, INKY_SPECTRA6_PALETTE)
        palette_set = set(INKY_SPECTRA6_PALETTE)
        assert set(result.getdata()) <= palette_set
