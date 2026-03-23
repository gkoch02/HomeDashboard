from functools import lru_cache

from PIL import ImageDraw, ImageFont

BLACK = 0
WHITE = 1


def draw_text_truncated(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    fill: int = BLACK,
) -> int:
    """Draw text, truncating with ellipsis if needed. Returns actual width drawn."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]

    if text_w <= max_width:
        draw.text(xy, text, font=font, fill=fill)
        return text_w

    ellipsis = "..."
    lo, hi, best_i = 1, len(text), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        truncated = text[:mid] + ellipsis
        bbox = draw.textbbox((0, 0), truncated, font=font)
        if bbox[2] - bbox[0] <= max_width:
            best_i = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if best_i > 0:
        truncated = text[:best_i] + ellipsis
        draw.text(xy, truncated, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), truncated, font=font)
        return bbox[2] - bbox[0]

    draw.text(xy, ellipsis, font=font, fill=fill)
    bbox = draw.textbbox((0, 0), ellipsis, font=font)
    return bbox[2] - bbox[0]


def draw_text_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int = 3,
    line_spacing: int = 2,
    fill: int = BLACK,
) -> int:
    """Draw wrapped text. Returns total height used."""
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    lines = lines[:max_lines]
    if len(lines) == max_lines and len(words) > sum(len(ln.split()) for ln in lines):
        # Truncate last line with ellipsis
        last = lines[-1]
        while last:
            test = last + "..."
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                lines[-1] = test
                break
            last = last[:-1]

    x, y = xy
    line_h = text_height(font)
    total_h = 0

    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + line_spacing
        total_h += line_h + line_spacing

    return total_h


@lru_cache(maxsize=32)
def text_height(font: ImageFont.FreeTypeFont) -> int:
    """Get the height of a line of text for a given font (approximate)."""
    from PIL import Image, ImageDraw as ID
    img = Image.new("1", (1, 1))
    d = ID.Draw(img)
    bbox = d.textbbox((0, 0), "Ag", font=font)
    return bbox[3] - bbox[1]


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def hline(draw: ImageDraw.ImageDraw, y: int, x0: int, x1: int, fill: int = BLACK):
    draw.line([(x0, y), (x1, y)], fill=fill, width=1)


def vline(draw: ImageDraw.ImageDraw, x: int, y0: int, y1: int, fill: int = BLACK):
    draw.line([(x, y0), (x, y1)], fill=fill, width=1)


def dashed_vline(
    draw: ImageDraw.ImageDraw,
    x: int,
    y0: int,
    y1: int,
    on: int = 2,
    off: int = 4,
    fill: int = BLACK,
) -> None:
    """Draw a vertical dashed line with configurable on/off segment lengths."""
    y = y0
    while y <= y1:
        draw.line([(x, y), (x, min(y + on - 1, y1))], fill=fill, width=1)
        y += on + off


def filled_rect(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], fill: int = BLACK):
    draw.rectangle(rect, fill=fill)


def inverted_text(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    pad_h: int = 2,
):
    """Draw white text on a black-filled rectangle."""
    filled_rect(draw, rect, fill=BLACK)
    x0, y0, x1, y1 = rect
    tw = text_width(draw, text, font)
    th = text_height(font)
    tx = x0 + (x1 - x0 - tw) // 2
    ty = y0 + (y1 - y0 - th) // 2
    draw.text((tx, ty), text, font=font, fill=WHITE)
