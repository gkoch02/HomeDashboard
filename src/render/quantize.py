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

# SATURATED_PALETTE from InkyE673 (inky_e673.py) — the correct driver for the
# Inky Impression 7.3" 2025 Spectra 6 panel.  Ordering matches the controller's
# color LUT; controller position 4 is unused (skipped by the e673 remap).
#   0=Black, 1=White, 2=Yellow, 3=Red, 4=Blue, 5=Green
#
# These are the PHYSICAL display output colors — dark/muted values that match
# what the ink actually produces.  They are used by InkyDisplay.show() for the
# final palette-index lookup.  Do NOT use these alone as the quantization
# reference palette for photos: because these values are so dark, many vivid or
# mid-tone pixels end up closest to "white" and map incorrectly.  Instead, use
# blend_inky_palette() which mixes these with INKY_SPECTRA6_DESATURATED_PALETTE
# to create better hue decision boundaries (same approach as InkyE673._palette_blend).
INKY_SPECTRA6_PALETTE: list[tuple[int, int, int]] = [
    (0, 0, 0),  # 0 black
    (161, 164, 165),  # 1 white
    (208, 190, 71),  # 2 yellow
    (156, 72, 75),  # 3 red
    (61, 59, 94),  # 4 blue
    (58, 91, 70),  # 5 green
]

# DESATURATED_PALETTE from InkyE673 — the pure/ideal hue references.
# Blending with INKY_SPECTRA6_PALETTE at 50/50 produces reference colors that
# correctly represent each hue region in RGB space (e.g. blue = ~(30,29,174)
# vs. the physical (61,59,94) which is too dark to reliably distinguish from
# white when doing nearest-color matching on typical photo pixels).
INKY_SPECTRA6_DESATURATED_PALETTE: list[tuple[int, int, int]] = [
    (0, 0, 0),  # 0 black
    (255, 255, 255),  # 1 white
    (255, 255, 0),  # 2 yellow
    (255, 0, 0),  # 3 red
    (0, 0, 255),  # 4 blue
    (0, 255, 0),  # 5 green
]


def blend_inky_palette(saturation: float = 0.5) -> list[tuple[int, int, int]]:
    """Return a quantization reference palette blended between the physical Spectra 6
    colors (saturation=1.0) and the pure ideal hues (saturation=0.0).

    Mirrors ``InkyE673._palette_blend()``.  At the default saturation=0.5 each color
    is a 50/50 mix, e.g. blue → ~(30, 29, 174) instead of the physical (61, 59, 94).
    These blended values form correct hue decision boundaries for nearest-color
    matching on typical photo pixels:

    - Sky blue (70, 130, 200): dist to blended blue=112, dist to blended white=160  → blue ✓
    - Same pixel vs SATURATED:  dist to blue=128,         dist to white=103          → white ✗

    The quantized image's pixels (snapped to blended colors) are then correctly
    remapped to hardware indices by InkyDisplay.show(), which uses Euclidean distance
    against device.SATURATED_PALETTE — each blended color is unambiguously closest
    to its corresponding SATURATED entry.
    """
    result = []
    for s, d in zip(INKY_SPECTRA6_PALETTE, INKY_SPECTRA6_DESATURATED_PALETTE):
        r = int(s[0] * saturation + d[0] * (1.0 - saturation))
        g = int(s[1] * saturation + d[1] * (1.0 - saturation))
        b = int(s[2] * saturation + d[2] * (1.0 - saturation))
        result.append((r, g, b))
    return result


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


def _redmean_sq(
    r1: int,
    g1: int,
    b1: int,
    r2: int,
    g2: int,
    b2: int,
) -> float:
    """Perceptually-weighted squared color distance (redmean approximation).

    More accurate than Euclidean RGB for perceived hue differences, especially
    in the red channel.  No trigonometry or expensive colour-space conversions.
    """
    r_mean = (r1 + r2) * 0.5
    dr = r1 - r2
    dg = g1 - g2
    db = b1 - b2
    return (
        (2.0 + r_mean * (1.0 / 256.0)) * dr * dr
        + 4.0 * dg * dg
        + (2.0 + (255.0 - r_mean) * (1.0 / 256.0)) * db * db
    )


def quantize_to_palette_ordered(
    image: Image.Image,
    colors: list[tuple[int, int, int]],
    *,
    bayer_strength: int = 24,
) -> Image.Image:
    """Palette-quantize using 4×4 Bayer ordered dithering and perceptual colour matching.

    Unlike Floyd-Steinberg, ordered dithering produces a regular halftone-like
    pattern instead of chaotic error-diffusion streaks, which looks significantly
    cleaner on sparse palettes like the Inky Spectra 6.  Colour matching uses the
    redmean perceptual distance approximation for more accurate hue mapping than
    Euclidean RGB.

    Uses a numpy fast path when numpy is importable; falls back to pure Python.

    Args:
        image:          Source image (any mode; converted to RGB internally).
        colors:         Target palette as a list of (R, G, B) tuples.
        bayer_strength: Per-channel dither magnitude in [0, 127].  Default 24 gives
                        ±12 per channel — enough to smooth palette boundaries without
                        obvious noise.

    Returns:
        PIL Image in ``"RGB"`` mode with all pixels snapped to *colors*.
    """
    try:
        import numpy as np

        return _quantize_palette_ordered_numpy(image, colors, bayer_strength, np)
    except ImportError:
        return _quantize_palette_ordered_python(image, colors, bayer_strength)


def _quantize_palette_ordered_numpy(
    image: Image.Image,
    colors: list[tuple[int, int, int]],
    bayer_strength: int,
    np,  # passed in to avoid re-importing
) -> Image.Image:
    w, h = image.size
    rgb = np.array(image.convert("RGB"), dtype=np.float32)  # H×W×3

    # Build tiled Bayer offset map (same 4×4 tile repeated across the canvas)
    bayer_base = np.array(_BAYER_4X4, dtype=np.float32)
    bayer_tiled = np.tile(bayer_base, ((h + 3) // 4, (w + 3) // 4))[:h, :w]  # H×W
    offset = (bayer_tiled - 120.0) * (bayer_strength / 240.0)
    rgb_d = np.clip(rgb + offset[:, :, np.newaxis], 0.0, 255.0)  # H×W×3

    pal = np.array(colors, dtype=np.float32)  # N×3
    # Redmean: weight depends on mean of image-pixel red and palette red channels
    r_d = rgb_d[:, :, 0]  # H×W
    r_p = pal[:, 0]  # N
    r_mean = (r_d[:, :, np.newaxis] + r_p[np.newaxis, np.newaxis, :]) * 0.5  # H×W×N

    diff = rgb_d[:, :, np.newaxis, :] - pal[np.newaxis, np.newaxis, :, :]  # H×W×N×3
    dr, dg, db = diff[:, :, :, 0], diff[:, :, :, 1], diff[:, :, :, 2]
    dist = (
        (2.0 + r_mean / 256.0) * dr * dr
        + 4.0 * dg * dg
        + (2.0 + (255.0 - r_mean) / 256.0) * db * db
    )  # H×W×N

    pal_u8 = np.array(colors, dtype=np.uint8)
    result = pal_u8[np.argmin(dist, axis=2)]  # H×W×3
    return Image.fromarray(result, mode="RGB")


def _quantize_palette_ordered_python(
    image: Image.Image,
    colors: list[tuple[int, int, int]],
    bayer_strength: int,
) -> Image.Image:
    w, h = image.size
    rgb_img = image.convert("RGB")
    # Avoid deprecated getdata() by using tobytes + frombytes round-trip via getdata fallback
    raw = list(rgb_img.getdata())  # list of (r,g,b) tuples
    result: list[tuple[int, int, int]] = []

    x = y = 0
    for pix in raw:
        r, g, b = pix[0], pix[1], pix[2]
        offset = (_BAYER_4X4[y & 3][x & 3] - 120) * bayer_strength // 240
        r2 = r + offset
        g2 = g + offset
        b2 = b + offset
        if r2 < 0:
            r2 = 0
        elif r2 > 255:
            r2 = 255
        if g2 < 0:
            g2 = 0
        elif g2 > 255:
            g2 = 255
        if b2 < 0:
            b2 = 0
        elif b2 > 255:
            b2 = 255

        best_dist = 1e18
        best_color = colors[0]
        for c in colors:
            d = _redmean_sq(r2, g2, b2, c[0], c[1], c[2])
            if d < best_dist:
                best_dist = d
                best_color = c
        result.append(best_color)

        x += 1
        if x == w:
            x = 0
            y += 1

    out = Image.new("RGB", (w, h))
    out.putdata(result)
    return out


def quantize_to_palette_fs(
    image: Image.Image,
    colors: list[tuple[int, int, int]],
) -> Image.Image:
    """Palette-quantize using Floyd-Steinberg error diffusion.

    Produces more natural-looking dither for photographic content than ordered
    Bayer dithering — error is distributed to neighbouring pixels rather than
    applied as a fixed threshold pattern, so colour transitions look organic
    rather than grid-like.

    This is the same dithering method used by ``InkyE673.set_image()`` but
    implemented without PIL's ``quantize(palette=...)`` API, which calls a
    deprecated internal C path that assigns wrong palette indices with Pillow 10+.

    Args:
        image:  Source image (any mode; converted to RGB internally).
        colors: Target palette as a list of (R, G, B) tuples.

    Returns:
        PIL Image in ``"RGB"`` mode with all pixels snapped to *colors*.
    """
    try:
        import numpy as np

        return _quantize_palette_fs_numpy(image, colors, np)
    except ImportError:
        return _quantize_palette_fs_python(image, colors)


def _quantize_palette_fs_numpy(
    image: Image.Image,
    colors: list[tuple[int, int, int]],
    np,  # passed in to avoid re-importing
) -> Image.Image:
    w, h = image.size
    # Float32 buffer accumulates error in-place across the whole image.
    buf = np.array(image.convert("RGB"), dtype=np.float32)  # H×W×3
    pal = np.array(colors, dtype=np.float32)  # N×3

    for y in range(h):
        for x in range(w):
            old = buf[y, x].clip(0.0, 255.0)
            # Nearest palette color by Euclidean squared distance.
            diff = pal - old  # N×3
            dist = (diff * diff).sum(axis=1)  # N
            idx = int(dist.argmin())
            new = pal[idx]
            buf[y, x] = new
            err = old - new  # quantization error
            # Distribute error: right=7/16, below-left=3/16, below=5/16, below-right=1/16
            if x + 1 < w:
                buf[y, x + 1] += err * (7.0 / 16.0)
            if y + 1 < h:
                if x > 0:
                    buf[y + 1, x - 1] += err * (3.0 / 16.0)
                buf[y + 1, x] += err * (5.0 / 16.0)
                if x + 1 < w:
                    buf[y + 1, x + 1] += err * (1.0 / 16.0)

    return Image.fromarray(buf.clip(0.0, 255.0).astype(np.uint8), mode="RGB")


def _quantize_palette_fs_python(
    image: Image.Image,
    colors: list[tuple[int, int, int]],
) -> Image.Image:
    """Pure-Python Floyd-Steinberg fallback (no numpy required)."""
    w, h = image.size
    raw = list(image.convert("RGB").getdata())
    # Mutable float buffer; each entry is [r, g, b].
    buf: list[list[float]] = [[float(p[0]), float(p[1]), float(p[2])] for p in raw]
    result: list[tuple[int, int, int]] = [(0, 0, 0)] * (w * h)

    for y in range(h):
        for x in range(w):
            i = y * w + x
            or_ = max(0.0, min(255.0, buf[i][0]))
            og = max(0.0, min(255.0, buf[i][1]))
            ob = max(0.0, min(255.0, buf[i][2]))
            # Nearest palette color by Euclidean squared distance.
            best_d = 1e18
            best_c = colors[0]
            for c in colors:
                dr = or_ - c[0]
                dg = og - c[1]
                db = ob - c[2]
                d = dr * dr + dg * dg + db * db
                if d < best_d:
                    best_d = d
                    best_c = c
            result[i] = best_c
            er = or_ - best_c[0]
            eg = og - best_c[1]
            eb = ob - best_c[2]
            if x + 1 < w:
                j = y * w + x + 1
                buf[j][0] += er * (7.0 / 16.0)
                buf[j][1] += eg * (7.0 / 16.0)
                buf[j][2] += eb * (7.0 / 16.0)
            if y + 1 < h:
                row_below = (y + 1) * w
                if x > 0:
                    j = row_below + x - 1
                    buf[j][0] += er * (3.0 / 16.0)
                    buf[j][1] += eg * (3.0 / 16.0)
                    buf[j][2] += eb * (3.0 / 16.0)
                j = row_below + x
                buf[j][0] += er * (5.0 / 16.0)
                buf[j][1] += eg * (5.0 / 16.0)
                buf[j][2] += eb * (5.0 / 16.0)
                if x + 1 < w:
                    j = row_below + x + 1
                    buf[j][0] += er * (1.0 / 16.0)
                    buf[j][1] += eg * (1.0 / 16.0)
                    buf[j][2] += eb * (1.0 / 16.0)

    out = Image.new("RGB", (w, h))
    out.putdata(result)
    return out


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
