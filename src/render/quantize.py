"""Final quantization step: convert a greyscale (L) image to 1-bit for eInk output.

Usage::

    from src.render.quantize import quantize_for_display
    result = quantize_for_display(grey_image, mode="threshold")   # → PIL Image mode "1"

Supported modes
---------------
threshold
    Simple 128-level split (no dithering).  Pixels > 128 → white, ≤ 128 → black.
    Preserves the look of themes that already render in strict black/white.

floyd_steinberg
    Error-diffusion dithering via Pillow's built-in Floyd–Steinberg algorithm.
    Produces better apparent grey rendering at the cost of some noise.

ordered
    4×4 Bayer ordered/threshold dithering, implemented in pure Python
    (``getdata`` / ``putdata``) — no numpy dependency required.
    Produces a regular dot-matrix pattern; useful for structured gradients.
"""

from __future__ import annotations

from PIL import Image

_VALID_MODES = ("threshold", "floyd_steinberg", "ordered")
INKY_SPECTRA6_PALETTE: list[tuple[int, int, int]] = [
    (0, 0, 0),  # black
    (255, 255, 255),  # white
    (220, 44, 44),  # red
    (44, 92, 180),  # blue
    (240, 208, 56),  # yellow
    (44, 160, 96),  # green
]

# 4×4 Bayer matrix, threshold values scaled to 0–240 (base 0–15 × 16).
# Using ×16 (not ×17) keeps the maximum threshold at 240, so a pure-white pixel
# (value 255) always exceeds every threshold and maps cleanly to white.
# Entry [r][c] = threshold for pixel at (x % 4 == c, y % 4 == r).
_BAYER_4X4: list[list[int]] = [
    [0, 128, 32, 160],
    [192, 64, 224, 96],
    [48, 176, 16, 144],
    [240, 112, 208, 80],
]


def quantize_for_display(image: Image.Image, mode: str = "threshold") -> Image.Image:
    """Convert a greyscale image to 1-bit using the specified quantization mode.

    Args:
        image: PIL Image.  If not already mode ``"L"``, it is converted first.
        mode:  One of ``"threshold"``, ``"floyd_steinberg"``, or ``"ordered"``.

    Returns:
        PIL Image in mode ``"1"``.

    Raises:
        ValueError: If *mode* is not one of the supported values.
    """
    if image.mode != "L":
        image = image.convert("L")

    if mode == "threshold":
        return image.convert("1", dither=Image.Dither.NONE)

    if mode == "floyd_steinberg":
        return image.convert("1", dither=Image.Dither.FLOYDSTEINBERG)

    if mode == "ordered":
        return _ordered_bayer(image)

    raise ValueError(f"Unknown quantization mode {mode!r}. Valid modes: {', '.join(_VALID_MODES)}")


def _ordered_bayer(image: Image.Image) -> Image.Image:
    """Apply 4×4 Bayer ordered dithering (pure Python — no numpy required)."""
    w, h = image.size
    pixels = list(image.getdata())
    thresholds = [_BAYER_4X4[y & 3][x & 3] for y in range(h) for x in range(w)]
    quantized = [255 if p > t else 0 for p, t in zip(pixels, thresholds)]
    out = Image.new("L", (w, h))
    out.putdata(quantized)
    return out.convert("1")


def build_palette_image(colors: list[tuple[int, int, int]]) -> Image.Image:
    """Return a tiny palette image usable with Pillow quantize()."""
    palette = Image.new("P", (1, 1))
    flat: list[int] = []
    for r, g, b in colors:
        flat.extend([r, g, b])
    flat.extend([0] * (768 - len(flat)))
    palette.putpalette(flat)
    return palette


def quantize_to_palette(
    image: Image.Image,
    colors: list[tuple[int, int, int]],
    *,
    dither: Image.Dither = Image.Dither.NONE,
) -> Image.Image:
    """Convert an image to a limited palette and return it as RGB."""
    palette = build_palette_image(colors)
    return image.convert("RGB").quantize(palette=palette, dither=dither).convert("RGB")
