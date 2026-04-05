"""Message panel for the ``message`` theme.

Renders arbitrary user-supplied text large and centered on the canvas, using
the same responsive typography algorithm as the ``qotd`` panel but without
an attribution line.  Decorative oversized quotation marks frame the text.

The companion weather banner is provided by ``qotd_panel.draw_qotd_weather()``.
"""

from __future__ import annotations

from PIL import ImageDraw

from src.render.primitives import text_height
from src.render.primitives import wrap_lines as _wrap_lines
from src.render.theme import ComponentRegion, ThemeStyle


def draw_message(
    draw: ImageDraw.ImageDraw,
    message: str,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw *message* typographically centered in *region*.

    Tries font sizes from large to small, picking the largest size at which the
    full message fits vertically.  Text is centered both horizontally and
    vertically within the region.
    """
    if region is None:
        region = ComponentRegion(0, 0, 800, 400)
    if style is None:
        style = ThemeStyle()

    text = message.strip() or "(no message)"

    h_pad = 52
    v_pad = 28
    max_w = region.w - h_pad * 2

    font_fn = style.font_bold
    best_size = 20
    best_lines: list[str] = []
    best_font = None

    for size in (64, 60, 56, 52, 48, 44, 40, 36, 32, 28, 24, 20):
        font = font_fn(size)
        lines = _wrap_lines(text, font, max_w)
        lh = text_height(font)
        line_gap = max(4, size // 6)
        total_h = len(lines) * lh + max(0, len(lines) - 1) * line_gap
        if total_h <= region.h - v_pad * 2:
            best_size = size
            best_lines = lines
            best_font = font
            break

    # Fallback: force size 20, allow up to 8 lines
    if not best_lines:
        best_font = font_fn(20)
        best_size = 20
        best_lines = _wrap_lines(text, best_font, max_w)[:8]

    assert best_font is not None
    lh = text_height(best_font)
    line_gap = max(4, best_size // 6)
    total_h = len(best_lines) * lh + max(0, len(best_lines) - 1) * line_gap

    # Vertical centering
    text_block_top = region.y + (region.h - total_h) // 2
    text_block_bottom = text_block_top + total_h

    # ---- Decorative oversized quotation marks ----
    mark_size = min(100, max(60, int(best_size * 3.0)))
    mark_font = style.font_bold(mark_size)

    for glyph, side in (("\u201c", "open"), ("\u201d", "close")):
        bb = draw.textbbox((0, 0), glyph, font=mark_font)
        ink_w = int(bb[2] - bb[0])
        ink_h = int(bb[3] - bb[1])

        if side == "open":
            px = region.x + h_pad // 4
            py = text_block_top - ink_h // 3
        else:
            px = region.x + region.w - h_pad // 4 - ink_w
            py = int(text_block_bottom - ink_h * 2 // 3)

        draw.text((px - bb[0], py - bb[1]), glyph, font=mark_font, fill=style.fg)

    # ---- Message lines (centered horizontally) ----
    y = text_block_top
    for line in best_lines:
        lw = int(best_font.getlength(line))  # type: ignore[union-attr]
        x = region.x + (region.w - lw) // 2
        draw.text((x, y), line, font=best_font, fill=style.fg)
        y += lh + line_gap
