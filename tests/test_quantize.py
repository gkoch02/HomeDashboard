"""Tests for src.render.quantize — quantize_for_display() and helpers."""

from __future__ import annotations

import pytest
from PIL import Image

from src.render.quantize import _VALID_MODES, quantize_for_display

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
