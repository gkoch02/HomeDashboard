"""``quantize_to_palette_nearest`` — the colour panel's finalize step."""

from __future__ import annotations

from PIL import Image

from src.display.driver import WAVESHARE_G_PALETTE
from src.render.quantize import (
    _quantize_palette_nearest_python,
    flatten_pixels,
    quantize_to_palette_nearest,
)

PALETTE = list(WAVESHARE_G_PALETTE)


def _ramp() -> Image.Image:
    """Every grey level plus the four inks and a few mixes, one pixel each."""
    img = Image.new("RGB", (256 + 8, 1))
    for v in range(256):
        img.putpixel((v, 0), (v, v, v))
    extras = [
        (255, 0, 0),
        (255, 255, 0),
        (255, 128, 128),
        (128, 128, 0),
        (61, 59, 94),
        (58, 91, 70),
        (208, 190, 71),
        (156, 72, 75),
    ]
    for i, c in enumerate(extras):
        img.putpixel((256 + i, 0), c)
    return img


def test_output_uses_only_palette_colours():
    out = quantize_to_palette_nearest(_ramp(), PALETTE)
    assert out.mode == "RGB"
    assert set(flatten_pixels(out)) <= set(PALETTE)


def test_neutral_greys_never_land_on_a_coloured_ink():
    out = quantize_to_palette_nearest(_ramp(), PALETTE)
    greys = flatten_pixels(out)[:256]
    assert set(greys) == {(0, 0, 0), (255, 255, 255)}
    # And the cut is at mid-grey, like the 1-bit threshold.
    assert greys[127] == (0, 0, 0)
    assert greys[128] == (255, 255, 255)


def test_pure_python_fallback_agrees_with_numpy():
    ramp = _ramp()
    fast = flatten_pixels(quantize_to_palette_nearest(ramp, PALETTE))
    slow = flatten_pixels(_quantize_palette_nearest_python(ramp, PALETTE))
    assert fast == slow


def test_l_and_one_bit_inputs_are_accepted():
    grey = Image.new("L", (4, 1), 200)
    assert set(flatten_pixels(quantize_to_palette_nearest(grey, PALETTE))) == {(255, 255, 255)}
    bilevel = Image.new("1", (4, 1), 0)
    assert set(flatten_pixels(quantize_to_palette_nearest(bilevel, PALETTE))) == {(0, 0, 0)}


class TestNearestQuantizerMatchesBruteForce:
    def test_matches_a_brute_force_argmin(self):
        import numpy as np

        rng = np.random.default_rng(7)
        arr = rng.integers(0, 256, size=(40, 60, 3), dtype=np.uint8)
        img = Image.fromarray(arr, mode="RGB")
        out = np.asarray(quantize_to_palette_nearest(img, list(WAVESHARE_G_PALETTE)))
        pal = np.array(WAVESHARE_G_PALETTE, dtype=np.int32)
        diff = arr.astype(np.int32)[:, :, None, :] - pal[None, None, :, :]
        expected = pal[np.argmin(np.sum(diff * diff, axis=3), axis=2)].astype(np.uint8)
        assert (out == expected).all()
