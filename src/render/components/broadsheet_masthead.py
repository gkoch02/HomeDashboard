"""broadsheet_masthead.py — Newspaper front-page masthead for ``old_fashioned``.

An inverted nameplate band with the title centred between two boxed "ears",
then a ruled dateline strip carrying the full date and the "updated" stamp:

  ┌──────────────────────────────────────────────────────────────────┐
  │ ┌────────┐                                          ┌──────────┐ │
  │ │VOL. XXVI│          Home Dashboard                 │  FINAL   │ │
  │ │ No. 96 │                                          │ EDITION  │ │
  │ └────────┘                                          └──────────┘ │
  ├══════════════════════════════════════════════════════════════════┤
  │ MONDAY, APRIL 6, 2026          ✦            UPDATED APR 6 · 10:30A│
  ├──────────────────────────────────────────────────────────────────┤

Fonts come from the theme style: the nameplate from ``font_title``, the ears
and dateline from ``font_section_label``. The stamp reads the content time,
never the render clock, so an idle tick repaints nothing.
"""

from __future__ import annotations

from datetime import date, datetime

from PIL import ImageDraw

from src.data.models import StalenessLevel
from src.render.components.header import status_label
from src.render.primitives import filled_rect, hline, text_width, truncate_to_width
from src.render.theme import ComponentRegion, ThemeStyle

BAND_H = 56  # inverted nameplate band; the dateline strip fills the rest
_EAR_W = 92
_PAD = 8

_ROMAN = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def roman(n: int) -> str:
    """Upper-case Roman numeral for a positive integer."""
    out = []
    for value, glyphs in _ROMAN:
        count, n = divmod(n, value)
        out.append(glyphs * count)
    return "".join(out)


def _centred(draw, cx: float, cy: float, text: str, font, fill) -> None:
    bb = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (cx - (bb[2] - bb[0]) / 2 - bb[0], cy - (bb[3] - bb[1]) / 2 - bb[1]),
        text,
        font=font,
        fill=fill,
    )


def _ear(draw, box: tuple[int, int, int, int], lines: tuple[str, str], font, fill) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=fill)
    cx = (x0 + x1) / 2
    third = (y1 - y0) / 4
    _centred(draw, cx, y0 + third + 1, lines[0], font, fill)
    hline(draw, int((y0 + y1) / 2), x0 + 10, x1 - 10, fill=fill)
    _centred(draw, cx, y1 - third, lines[1], font, fill)


def _fit_font(draw, text: str, font_fn, size: int, max_w: int, min_size: int = 18):
    font = font_fn(size)
    while size > min_size and text_width(draw, text, font) > max_w:
        size -= 1
        font = font_fn(size)
    return font


def draw_broadsheet_masthead(
    draw: ImageDraw.ImageDraw,
    today: date,
    stamp: datetime,
    *,
    title: str = "Home Dashboard",
    is_stale: bool = False,
    source_staleness: dict[str, StalenessLevel] | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the nameplate band, its two ears and the dateline strip."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 80)
    if style is None:
        style = ThemeStyle()
    fg, bg = style.fg, style.bg
    x0, y0, w, h = region.x, region.y, region.w, region.h
    x1 = x0 + w - 1
    band_y1 = y0 + BAND_H - 1
    label_fn = style.font_section_label or style.font_bold
    title_fn = style.font_title or style.font_bold

    filled_rect(draw, (x0, y0, x1, band_y1), fill=fg)

    ear_font = label_fn(10)
    ear_y0, ear_y1 = y0 + _PAD, band_y1 - _PAD
    _ear(
        draw,
        (x0 + _PAD, ear_y0, x0 + _PAD + _EAR_W, ear_y1),
        (f"VOL. {roman(today.year % 100 or 100)}", f"No. {today.timetuple().tm_yday}"),
        ear_font,
        bg,
    )
    _ear(
        draw,
        (x1 - _PAD - _EAR_W, ear_y0, x1 - _PAD, ear_y1),
        ("FINAL", "EDITION"),
        ear_font,
        bg,
    )

    # The nameplate shrinks to clear the ears rather than running under them.
    title_max_w = w - 2 * (_PAD + _EAR_W + 14)
    title_font = _fit_font(draw, title, title_fn, 34, title_max_w)
    title = truncate_to_width(draw, title, title_font, title_max_w)
    _centred(draw, x0 + w / 2, y0 + BAND_H / 2 - 1, title, title_font, bg)

    # Dateline strip: heavy rule under the band, thin rule closing the strip.
    strip_y0 = band_y1 + 1
    strip_y1 = y0 + h - 1
    hline(draw, strip_y0 + 2, x0, x1, fill=fg)
    hline(draw, strip_y0 + 3, x0, x1, fill=fg)
    hline(draw, strip_y1, x0, x1, fill=fg)
    text_cy = (strip_y0 + 4 + strip_y1) / 2

    line_font = label_fn(11)
    date_text = f"{today:%A}, {today:%B} {today.day}, {today.year}".upper()
    db = draw.textbbox((0, 0), date_text, font=line_font)
    draw.text(
        (x0 + _PAD - db[0], text_cy - (db[3] - db[1]) / 2 - db[1]),
        date_text,
        font=line_font,
        fill=fg,
    )

    clock = stamp.strftime("%-I:%M%p").replace("AM", "A").replace("PM", "P")
    stamp_text = f"{status_label(is_stale, source_staleness).strip()} {stamp:%b} {stamp.day}"
    stamp_text = f"{stamp_text} · {clock}".upper()
    sb = draw.textbbox((0, 0), stamp_text, font=line_font)
    draw.text(
        (x1 - _PAD - (sb[2] - sb[0]) - sb[0], text_cy - (sb[3] - sb[1]) / 2 - sb[1]),
        stamp_text,
        font=line_font,
        fill=fg,
    )

    # A lozenge between the two halves of the dateline.
    cx, cy, r = x0 + w // 2, int(text_cy), 4
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fg)
    hline(draw, cy, cx - 34, cx - r - 4, fill=fg)
    hline(draw, cy, cx + r + 4, cx + 34, fill=fg)
