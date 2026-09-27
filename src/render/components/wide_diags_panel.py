"""wide_diags_panel.py — the swatch half of the ``wide_diags`` theme.

The left 800 px of the strip are the ``diags`` readout, unchanged; this panel
is the 560 px beside it: a test plate for the panel's inks, top to bottom —

* **INKS** — one solid swatch per ink the panel actually has, named and with
  the value the plate draws it in;
* **PAIR RAMPS** — every pair of those inks mixed through an 8x8 ordered
  (Bayer) screen in eighths, 0% to 100%;
* **TEXTURES** — fine ink-on-paper patterns (checkerboards, line screens, a
  dot grid, a diagonal) that show how the panel holds single-pixel detail;
* **DIFFUSED** — a continuous gradient left for the display backend to
  Floyd-Steinberg onto the inks, so the plate shows the pipeline's own
  dither beside the hand-screened ones above.

The ink set is read from the resolved style, not assumed: on a colour panel
``_resolve_style`` maps the accent roles to the panel's palette, and on the
four-ink Waveshare (G) the two inks it lacks resolve to black, so
de-duplicating the six roles leaves exactly the four it has (six on Inky, two
on monochrome). Everything above the DIFFUSED row is drawn in exact inks with
unantialiased type, so the backend's nearest-ink snap is the identity there;
the DIFFUSED row is the one art region (see ``diffused_rect``).
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from PIL import Image, ImageDraw

from src.render.components.wide_horizon_panel import bayer_field
from src.render.primitives import hline, text_height, text_width, vline
from src.render.theme import ComponentRegion, ThemeStyle

Fill = int | tuple[int, int, int]
Rect = tuple[int, int, int, int]

PAD = 12
HEADER_H = 28  # matches diags_panel's header so the rule runs straight across
LABEL_PT = 11
DATA_PT = 11

INK_TOP = 34
INK_H = 44
INK_GAP = 8

RAMP_LEVELS = 9  # 0/8 .. 8/8
RAMP_LABEL_W = 60
RAMP_MAX_PITCH = 56
RAMP_GAP = 3
RAMP_COL_GAP = 16
RAMP_MAX_ROWS = 8  # more pairs than this split into two columns
FINE_MAX_PAIRS = 3  # this few pairs leaves room for a continuous ramp under each

TEXTURE_H = 28
DIFFUSED_H = 34
BOTTOM_PAD = 8


@dataclass(frozen=True)
class Ink:
    name: str
    short: str
    value: Fill


def panel_inks(style: ThemeStyle) -> list[Ink]:
    """The distinct inks the panel has, in palette order.

    The resolved style carries one value per role; roles the panel has no ink
    for collapse onto black (colour) or ``fg`` (monochrome), so keeping the
    first of each value leaves the physical ink set.
    """
    roles = [
        ("BLACK", "BLK", style.fg),
        ("WHITE", "WHT", style.bg),
        ("YELLOW", "YEL", style.accent_warn),
        ("RED", "RED", style.accent_alert),
        ("BLUE", "BLU", style.accent_info),
        ("GREEN", "GRN", style.accent_good),
    ]
    inks: list[Ink] = []
    seen: set = set()
    for name, short, value in roles:
        if value is None or value in seen:
            continue
        seen.add(value)
        inks.append(Ink(name, short, value))
    return inks


def ink_pairs(inks: list[Ink]) -> list[tuple[Ink, Ink]]:
    return list(combinations(inks, 2))


def _content_x(region: ComponentRegion) -> tuple[int, int]:
    return region.x + PAD, region.x + region.w - PAD


def diffused_rect(region: ComponentRegion) -> Rect:
    """The DIFFUSED row, in canvas coordinates — the panel's one art region."""
    x0, x1 = _content_x(region)
    y1 = region.y + region.h - BOTTOM_PAD
    return (x0, y1 - DIFFUSED_H, x1, y1)


def _texture_rect(region: ComponentRegion) -> Rect:
    x0, x1 = _content_x(region)
    y1 = diffused_rect(region)[1] - LABEL_PT - 10
    return (x0, y1 - TEXTURE_H, x1, y1)


def ramp_cover(level: int) -> float:
    """Screen coverage of ramp step *level*, 0..RAMP_LEVELS-1 → 0.0..1.0."""
    return level / (RAMP_LEVELS - 1)


def _screen(image: Image.Image, box: Rect, base: Fill, over: Fill, cover: float) -> None:
    """Fill *box* with *base*, then *over* through the Bayer screen at *cover*."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    image.paste(Image.new(image.mode, (w, h), base), (x0, y0))
    if cover <= 0:
        return
    thr = bayer_field(w, h, x0, y0)
    mask = Image.fromarray(np.where(thr < cover, 255, 0).astype(np.uint8), mode="L")
    image.paste(Image.new(image.mode, (w, h), over), (x0, y0), mask)


def ramp_rows(
    pairs: list[tuple[Ink, Ink]], x0: int, y0: int, width: int, bottom: int
) -> list[tuple[Rect, str, Ink, Ink, bool]]:
    """Lay the ramp rows out: ``((x, y, col_w, h), label, a, b, fine)`` each.

    Every pair gets a stepped row. With few pairs (monochrome has one) each
    also gets a continuous row beneath it, screened across all 65 Bayer
    levels, so the band is not left mostly empty. More than
    ``RAMP_MAX_ROWS`` rows split into two columns (Inky's fifteen pairs).
    """
    fine = len(pairs) <= FINE_MAX_PAIRS
    specs: list[tuple[str, Ink, Ink, bool]] = []
    for a, b in pairs:
        specs.append((f"{a.short}/{b.short}", a, b, False))
        if fine:
            specs.append(("64THS", a, b, True))
    cols = 2 if len(specs) > RAMP_MAX_ROWS else 1
    rows = -(-len(specs) // cols) if specs else 1
    pitch = min(RAMP_MAX_PITCH, (bottom - y0) // rows)
    col_w = (width - (cols - 1) * RAMP_COL_GAP) // cols
    out = []
    for idx, (label, a, b, is_fine) in enumerate(specs):
        col, row = divmod(idx, rows)
        box = (x0 + col * (col_w + RAMP_COL_GAP), y0 + row * pitch, col_w, pitch - RAMP_GAP)
        out.append((box, label, a, b, is_fine))
    return out


def _screen_ramp(image: Image.Image, box: Rect, base: Fill, over: Fill) -> None:
    """*base* to *over* left to right through the Bayer screen, continuously."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    cover = (np.arange(w) + 0.5) / w
    on = bayer_field(w, h, x0, y0) < cover[None, :]
    image.paste(Image.new(image.mode, (w, h), base), (x0, y0))
    mask = Image.fromarray(np.where(on, 255, 0).astype(np.uint8), mode="L")
    image.paste(Image.new(image.mode, (w, h), over), (x0, y0), mask)


def _pattern(image: Image.Image, box: Rect, kind: str, ink: Fill, paper: Fill) -> None:
    """Fill *box* with a fixed ink-on-paper test texture, phased to the canvas."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    ys = (np.arange(h) + y0)[:, None]
    xs = (np.arange(w) + x0)[None, :]
    on = {
        "checker1": (xs + ys) % 2 == 0,
        "checker2": (xs // 2 + ys // 2) % 2 == 0,
        "hlines": np.broadcast_to(ys % 2 == 0, (h, w)),
        "vlines": np.broadcast_to(xs % 2 == 0, (h, w)),
        "grid": (xs % 2 == 0) & (ys % 2 == 0),
        "diagonal": (xs + ys) % 4 == 0,
    }[kind]
    image.paste(Image.new(image.mode, (w, h), paper), (x0, y0))
    mask = Image.fromarray(np.where(on, 255, 0).astype(np.uint8), mode="L")
    image.paste(Image.new(image.mode, (w, h), ink), (x0, y0), mask)


TEXTURES = ["checker1", "checker2", "hlines", "vlines", "grid", "diagonal"]


def _fmt_value(value: Fill) -> str:
    if isinstance(value, tuple):
        return ",".join(str(c) for c in value)
    return str(value)


def _label(draw, x: int, y: int, text: str, style: ThemeStyle, note: str = "", right=0) -> int:
    f = style.font_bold(LABEL_PT)
    draw.text((x, y), text, font=f, fill=style.primary_accent_fill())
    if note:
        nf = style.font_regular(DATA_PT - 1)
        nw = text_width(draw, note, nf)
        ny = y + (text_height(f) - text_height(nf)) // 2
        draw.text((right - nw, ny), note, font=nf, fill=style.fg)
    return y + text_height(f) + 5


def draw_wide_diags(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the swatch plate into *region* (default: the right 560 px of the strip)."""
    if region is None:
        region = ComponentRegion(800, 0, 560, 480)
    if style is None:
        style = ThemeStyle()
    saved_fontmode = draw.fontmode
    draw.fontmode = "1"
    try:
        _draw_plate(image, draw, region, style)
    finally:
        draw.fontmode = saved_fontmode


def _draw_plate(image, draw, region: ComponentRegion, style: ThemeStyle) -> None:
    fg, bg = style.fg, style.bg
    inks = panel_inks(style)
    x0, x1 = _content_x(region)
    width = x1 - x0
    colour = image.mode == "RGB"

    # Header, rule and divider — continuing diags' header across the strip.
    title_font = style.font_bold(LABEL_PT + 3)
    ty = region.y + (HEADER_H - text_height(title_font)) // 2
    draw.text((x0, ty), "SWATCHES", font=title_font, fill=style.primary_accent_fill())
    kind = f"{len(inks)} INKS · {image.mode} CANVAS"
    kf = style.font_regular(DATA_PT)
    kw = text_width(draw, kind, kf)
    draw.text((x1 - kw, region.y + (HEADER_H - text_height(kf)) // 2), kind, font=kf, fill=fg)
    rule_y = region.y + HEADER_H
    hline(draw, rule_y, region.x, region.x + region.w, fill=fg)
    vline(draw, region.x, rule_y, region.y + region.h - 1, fill=fg)

    # INKS
    y = _label(draw, x0, region.y + INK_TOP, "INKS", style)
    n = len(inks)
    sw = (width - (n - 1) * INK_GAP) // n
    df = style.font_regular(DATA_PT)
    for i, ink in enumerate(inks):
        sx = x0 + i * (sw + INK_GAP)
        draw.rectangle((sx, y, sx + sw - 1, y + INK_H - 1), fill=ink.value, outline=fg)
        ny = y + INK_H + 3
        draw.text((sx, ny), ink.name, font=df, fill=fg)
        draw.text((sx, ny + text_height(df) + 2), _fmt_value(ink.value), font=df, fill=fg)
    y = y + INK_H + 3 + 2 * text_height(df) + 2 + 8
    hline(draw, y, x0, x1, fill=fg)
    y += 6

    # PAIR RAMPS
    pairs = ink_pairs(inks)
    y = _label(draw, x0, y, "PAIR RAMPS", style, note="8x8 BAYER · 0-100% IN EIGHTHS", right=x1)
    tex_box = _texture_rect(region)
    ramps_bottom = tex_box[1] - LABEL_PT - 20
    for (cx, cy, col_w, ch), label, a, b, fine in ramp_rows(pairs, x0, y, width, ramps_bottom):
        draw.text((cx, cy + (ch - text_height(df)) // 2), label, font=df, fill=fg)
        rx0 = cx + RAMP_LABEL_W
        if fine:
            rx1 = cx + col_w
            _screen_ramp(image, (rx0, cy, rx1, cy + ch), a.value, b.value)
        else:
            cell_w = (col_w - RAMP_LABEL_W) // RAMP_LEVELS
            for level in range(RAMP_LEVELS):
                lx = rx0 + level * cell_w
                box = (lx, cy, lx + cell_w, cy + ch)
                _screen(image, box, a.value, b.value, ramp_cover(level))
            rx1 = rx0 + RAMP_LEVELS * cell_w
        draw.rectangle((rx0 - 1, cy - 1, rx1, cy + ch), outline=fg)
    y = ramps_bottom + 6
    hline(draw, y, x0, x1, fill=fg)

    # TEXTURES
    tx0, ty0, tx1, ty1 = tex_box
    _label(
        draw,
        x0,
        ty0 - LABEL_PT - 9,
        "TEXTURES",
        style,
        note="CHECKER 1 · 2 · LINES H · V · GRID · DIAGONAL",
        right=x1,
    )
    cw = ((tx1 - tx0) - (len(TEXTURES) - 1) * INK_GAP) // len(TEXTURES)
    for i, kind_name in enumerate(TEXTURES):
        cx = tx0 + i * (cw + INK_GAP)
        _pattern(image, (cx, ty0, cx + cw, ty1), kind_name, fg, bg)
        draw.rectangle((cx - 1, ty0 - 1, cx + cw, ty1), outline=fg)

    # DIFFUSED
    dx0, dy0, dx1, dy1 = diffused_rect(region)
    note = "BACKEND FLOYD-STEINBERG" if colour else "FLOYD-STEINBERG GREY RAMP"
    _label(draw, x0, dy0 - LABEL_PT - 9, "DIFFUSED", style, note=note, right=x1)
    image.paste(gradient(dx1 - dx0, dy1 - dy0, image.mode), (dx0, dy0))
    draw.rectangle((dx0 - 1, dy0 - 1, dx1, dy1), outline=fg)


def gradient(w: int, h: int, mode: str) -> Image.Image:
    """The DIFFUSED row's contents in *mode*.

    Colour: a full-saturation hue sweep over a neutral grey ramp, left
    continuous for the backend to diffuse onto the inks. Monochrome: the grey
    ramp alone, diffused here, since a 1-bit canvas cannot hold a gradient.
    """
    ramp = np.linspace(0, 255, w).astype(np.uint8)
    if mode != "RGB":
        grey = Image.fromarray(np.tile(ramp, (h, 1)), mode="L")
        dithered = grey.convert("1")
        return dithered if mode == "1" else dithered.convert(mode)
    top = h // 2
    hues = np.array([colorsys.hsv_to_rgb(i / w, 1.0, 1.0) for i in range(w)], dtype=np.float64)
    out = np.empty((h, w, 3), dtype=np.uint8)
    out[:top] = (hues * 255).round().astype(np.uint8)[None, :, :]
    out[top:] = ramp[None, :, None]
    return Image.fromarray(out, mode="RGB")
