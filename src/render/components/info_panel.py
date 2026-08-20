from __future__ import annotations

from datetime import date, datetime

from PIL import ImageDraw

from src.render import layout as L
from src.render.primitives import draw_text_wrapped, hline, wrap_lines
from src.render.quotes import cache_clear as quotes_cache_clear
from src.render.quotes import quote_for
from src.render.theme import ComponentRegion, ThemeStyle


def _quote_for_today(
    today: date,
    refresh: str = "daily",
    now: datetime | None = None,
    quotes_path: str | None = None,
) -> dict:
    """Pick this panel's quote. Selection lives in :mod:`src.render.quotes`."""
    return quote_for(today, refresh=refresh, now=now, path=quotes_path)


# Kept for callers (including tests) that flush the cache after swapping stores.
_quote_for_today.cache_clear = quotes_cache_clear  # type: ignore[attr-defined]


def _count_lines(text: str, font, max_width: int) -> int:
    """Count lines produced by word-wrapping text at max_width (no drawing)."""
    return len(wrap_lines(text, font, max_width))


def draw_info(
    draw: ImageDraw.ImageDraw,
    today: date,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    quote_refresh: str = "daily",
    quotes_path: str | None = None,
):
    if region is None:
        region = ComponentRegion(L.INFO_X, L.INFO_Y, L.INFO_W, L.INFO_H)
    if style is None:
        style = ThemeStyle()

    x0 = region.x
    y0 = region.y
    w = region.w
    h = region.h
    pad = L.PAD

    # Top border (2px for stronger section separation)
    if style.show_borders:
        hline(draw, y0, x0, x0 + w, fill=style.fg)
        hline(draw, y0 + 1, x0, x0 + w, fill=style.fg)

    # Section label
    label_font = style.label_font()
    info_label = style.component_labels.get("info", "QUOTE OF THE DAY")
    draw.text((x0 + pad, y0 + pad), info_label, font=label_font, fill=style.primary_accent_fill())

    quote = _quote_for_today(today, refresh=quote_refresh, quotes_path=quotes_path)

    # Quote text — adapt font size so long quotes fit without truncation
    text = f'"{quote["text"]}"'
    y = y0 + 28
    max_width = w - pad * 2

    _quote_fn = style.font_quote if style.font_quote is not None else style.font_regular
    quote_font = _quote_fn(14)
    if _count_lines(text, quote_font, max_width) > 3:
        quote_font = _quote_fn(12)
        max_lines = 4
    else:
        max_lines = 3

    used_h = draw_text_wrapped(
        draw,
        (x0 + pad, y),
        text,
        quote_font,
        max_width,
        max_lines=max_lines,
        line_spacing=3,
        fill=style.fg,
    )

    # Attribution
    _author_fn = (
        style.font_quote_author if style.font_quote_author is not None else style.font_regular
    )
    author_font = _author_fn(12)
    attr_y = y + used_h + 6
    if attr_y + 16 < y0 + h:
        draw.text(
            (x0 + pad, attr_y),
            f"— {quote['author']}",
            font=author_font,
            fill=style.secondary_accent_fill(),
        )
