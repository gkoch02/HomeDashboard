"""Pixel-measurement helpers shared by the render-component tests.

Why this exists (#229)
----------------------
The render suites used to assert ``img.getbbox() is not None``. On the plates
these tests build that assertion has no failing input: ``getbbox`` reports the
bounds of *non-zero* pixels, so on a white mode-``"1"`` canvas (filled with 1)
it returns the full canvas whether or not anything was drawn. Whole files
passed with their draw function stubbed to a no-op.

These helpers replace it. ``marks`` is the general form — pixels differing
from the background — which is the only one that works across the four canvas
polarities in this suite: white ``"1"``, white ``"L"``, black ``"L"``, and the
mid-grey plate used by the moon-render tests. ``ink`` is the common special
case of zero-valued pixels on a light plate.

Watch the polarity when writing assertions. On an *inverted* band — a
filled_rect in ``fg`` with its text knocked out in ``bg`` — more content means
*less* ink, so "more data draws more" is backwards there.
"""

from __future__ import annotations

from PIL import Image

from src.render.quantize import flatten_pixels

Box = tuple[int, int, int, int]


def _pixels(img: Image.Image):
    return flatten_pixels(img), img.width


def marks(img: Image.Image, box: Box | None = None, background=None) -> int:
    """Count pixels differing from *background*, optionally inside *box*.

    *background* defaults to the value at (0, 0), which is the canvas fill for
    every plate in this suite. Pass it explicitly when the corner is drawn on.
    """
    px, width = _pixels(img)
    if background is None:
        background = px[0]
    if box is None:
        return sum(1 for v in px if v != background)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] != background)


def ink(img: Image.Image, box: Box | None = None) -> int:
    """Count ink (value-0) pixels — the light-plate special case of `marks`."""
    px, width = _pixels(img)
    if box is None:
        return sum(1 for v in px if v == 0)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def ink_bbox(img: Image.Image, box: Box | None = None):
    """Bounding box of ink as (x0, y0, x1, y1), or None if there is none.

    The honest replacement for ``Image.getbbox()`` on a light plate.
    """
    px, width = _pixels(img)
    x0, y0, x1, y1 = box if box else (0, 0, img.width, img.height)
    xs, ys = [], []
    for y in range(y0, y1):
        row = y * width
        for x in range(x0, x1):
            if px[row + x] == 0:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def ink_x_extent(img: Image.Image, box: Box):
    """(left, right) x-extent of ink inside *box*, or None if there is none."""
    px, width = _pixels(img)
    x0, y0, x1, y1 = box
    xs = [x for x in range(x0, x1) if any(px[y * width + x] == 0 for y in range(y0, y1))]
    return (xs[0], xs[-1] + 1) if xs else None


def text_line_heights(img: Image.Image, box: Box, min_h: int = 3) -> list[int]:
    """Heights of the horizontal bands of ink inside *box*.

    One band per rendered text line; each band's height tracks the font size,
    which is how "this was set larger" becomes measurable.
    """
    px, width = _pixels(img)
    x0, y0, x1, y1 = box
    hot = [any(px[y * width + x] == 0 for x in range(x0, x1)) for y in range(y0, y1)]
    runs: list[int] = []
    start = None
    for i, is_hot in enumerate(hot):
        if is_hot and start is None:
            start = i
        elif not is_hot and start is not None:
            if i - start >= min_h:
                runs.append(i - start)
            start = None
    if start is not None and len(hot) - start >= min_h:
        runs.append(len(hot) - start)
    return runs


def ink_clusters(img: Image.Image, box: Box, min_gap: int = 12) -> int:
    """Count horizontally separated groups of ink — e.g. forecast columns."""
    px, width = _pixels(img)
    x0, y0, x1, y1 = box
    cols = [x for x in range(x0, x1) if any(px[y * width + x] == 0 for y in range(y0, y1))]
    if not cols:
        return 0
    return 1 + sum(1 for p, q in zip(cols, cols[1:]) if q - p > min_gap)
