"""Combine Waveshare and Inky theme previews into a single diagonally split image.

For every theme that has both ``output/theme_<name>.png`` and
``output/theme_<name>_inky.png``, write ``output/theme_<name>_split.png`` where
the top-left triangle is the Waveshare render and the bottom-right triangle is
the Inky render. The two triangles are separated by the anti-diagonal running
from the top-right corner to the bottom-left corner, with a thin divider line
drawn on top.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
DIVIDER_WIDTH = 2
DIVIDER_COLOR = (128, 128, 128)


def _split_mask(size: tuple[int, int]) -> Image.Image:
    """Return an 'L' mask: 255 in the top-left triangle, 0 in the bottom-right."""
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([(0, 0), (width, 0), (0, height)], fill=255)
    return mask


def _combine(waveshare_path: Path, inky_path: Path, out_path: Path) -> None:
    waveshare = Image.open(waveshare_path).convert("RGB")
    inky = Image.open(inky_path).convert("RGB")
    if waveshare.size != inky.size:
        inky = inky.resize(waveshare.size, Image.LANCZOS)

    mask = _split_mask(waveshare.size)
    combined = inky.copy()
    combined.paste(waveshare, (0, 0), mask)

    draw = ImageDraw.Draw(combined)
    width, height = combined.size
    draw.line([(width - 1, 0), (0, height - 1)], fill=DIVIDER_COLOR, width=DIVIDER_WIDTH)

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
        out_path = OUTPUT_DIR / f"theme_{theme}_split.png"
        _combine(waveshare_path, inky_path, out_path)
        print(f"wrote {out_path.relative_to(OUTPUT_DIR.parent)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
