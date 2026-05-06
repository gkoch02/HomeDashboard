"""Combine Waveshare and Inky theme previews into a single split image.

For every theme that has both ``output/theme_<name>.png`` and
``output/theme_<name>_inky.png``, write ``output/theme_<name>_split.png``
showing the Waveshare render on one half and the Inky render on the other.

Each theme picks the split orientation that best surfaces its Inky color
treatment via ``_THEME_SPLIT_MODES``. Anything not listed defaults to the
anti-diagonal cut used by the original implementation.

Supported modes (Waveshare side / Inky side / divider):

- ``anti_diagonal``: top-left triangle / bottom-right triangle / TR↔BL line
- ``main_diagonal``: bottom-left triangle / top-right triangle / TL↔BR line
- ``vertical``:      left half / right half / vertical mid-line
- ``horizontal``:    top half / bottom half / horizontal mid-line
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
DIVIDER_WIDTH = 2
DIVIDER_COLOR = (128, 128, 128)

DEFAULT_MODE = "anti_diagonal"
SUPPORTED_MODES = ("anti_diagonal", "main_diagonal", "vertical", "horizontal")

# Per-theme split orientation. Themes not listed use DEFAULT_MODE.
# Cross-reference _INKY_THEME_KEY_COLORS in src/render/canvas.py when
# adding entries — only themes with a color story need an override.
_THEME_SPLIT_MODES: dict[str, str] = {
    # Full-canvas centered content: a vertical cut puts the Inky accent
    # color and the Waveshare baseline next to each other instead of
    # bisecting the centerpiece.
    "fuzzyclock": "vertical",
    "fuzzyclock_invert": "vertical",
    "qotd": "vertical",
    "qotd_invert": "vertical",
    "moonphase": "vertical",
    "moonphase_invert": "vertical",
    "countdown": "vertical",
    "message": "vertical",
    "today": "vertical",
    "monthly": "vertical",
    "light_cycle": "vertical",
    "almanac": "vertical",
    # Strong horizontal banding (header / hero / footer strip): a
    # horizontal cut keeps each band intact on each side.
    "weather": "horizontal",
    "air_quality": "horizontal",
    "scorecard": "horizontal",
    "sunrise": "horizontal",
    "tides": "horizontal",
    "astronomy": "horizontal",
}


def _split_mask(size: tuple[int, int], mode: str) -> Image.Image:
    """Return an 'L' mask: 255 on the Waveshare side, 0 on the Inky side."""
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if mode == "anti_diagonal":
        draw.polygon([(0, 0), (width, 0), (0, height)], fill=255)
    elif mode == "main_diagonal":
        draw.polygon([(0, 0), (0, height), (width, height)], fill=255)
    elif mode == "vertical":
        draw.rectangle([(0, 0), (width // 2, height)], fill=255)
    elif mode == "horizontal":
        draw.rectangle([(0, 0), (width, height // 2)], fill=255)
    else:
        raise ValueError(f"unsupported split mode: {mode!r}")
    return mask


def _divider_endpoints(size: tuple[int, int], mode: str) -> tuple[tuple[int, int], tuple[int, int]]:
    width, height = size
    if mode == "anti_diagonal":
        return (width - 1, 0), (0, height - 1)
    if mode == "main_diagonal":
        return (0, 0), (width - 1, height - 1)
    if mode == "vertical":
        x = width // 2
        return (x, 0), (x, height - 1)
    if mode == "horizontal":
        y = height // 2
        return (0, y), (width - 1, y)
    raise ValueError(f"unsupported split mode: {mode!r}")


def _combine(waveshare_path: Path, inky_path: Path, out_path: Path, mode: str) -> None:
    waveshare = Image.open(waveshare_path).convert("RGB")
    inky = Image.open(inky_path).convert("RGB")
    if waveshare.size != inky.size:
        inky = inky.resize(waveshare.size, Image.LANCZOS)

    mask = _split_mask(waveshare.size, mode)
    combined = inky.copy()
    combined.paste(waveshare, (0, 0), mask)

    draw = ImageDraw.Draw(combined)
    start, end = _divider_endpoints(combined.size, mode)
    draw.line([start, end], fill=DIVIDER_COLOR, width=DIVIDER_WIDTH)

    combined.save(out_path, format="PNG", optimize=True)


def main() -> int:
    if not OUTPUT_DIR.is_dir():
        print(f"output directory not found: {OUTPUT_DIR}", file=sys.stderr)
        return 1

    pairs: list[tuple[str, Path, Path]] = []
    for inky_path in sorted(OUTPUT_DIR.glob("theme_*_inky.png")):
        theme = inky_path.name[len("theme_") : -len("_inky.png")]
        waveshare_path = OUTPUT_DIR / f"theme_{theme}.png"
        if waveshare_path.exists():
            pairs.append((theme, waveshare_path, inky_path))

    if not pairs:
        print(f"no theme preview pairs found under {OUTPUT_DIR}", file=sys.stderr)
        return 1

    for theme, waveshare_path, inky_path in pairs:
        mode = _THEME_SPLIT_MODES.get(theme, DEFAULT_MODE)
        out_path = OUTPUT_DIR / f"theme_{theme}_split.png"
        _combine(waveshare_path, inky_path, out_path, mode)
        print(f"wrote {out_path.relative_to(OUTPUT_DIR.parent)} ({mode})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
