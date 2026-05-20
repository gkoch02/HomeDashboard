"""Render the project's eInk-faithful logo banner at assets/banner.png.

Standalone PIL script — does not import the rest of the project. It draws a
1600x400 wordmark + tagline + motif strip at 8-bit greyscale and then
quantizes the result to 1-bit using Floyd-Steinberg dither, mirroring how
``src/render/quantize.py::quantize_for_display()`` finalizes Waveshare output.
The result reads on screen as authentic eInk: crisp text, dithered gradients.

Run via ``python scripts/build_banner.py`` or ``make banner``. The render is
deterministic — no datetime.now() calls — so re-running produces identical
bytes.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = REPO_ROOT / "fonts"
OUT_PATH = REPO_ROOT / "assets" / "banner.png"

WIDTH, HEIGHT = 1600, 400
BORDER = 4

# Greyscale values (mode "L"): 0 = black ink, 255 = white paper.
BLACK = 0
WHITE = 255
MID = 160  # dithers to a stippled grey under Floyd-Steinberg

# Layout zones.
WORDMARK_X = 52
WORDMARK_RIGHT = 980  # right edge available to the wordmark column
MOTIF_X = 1010  # left edge of the motif column


def _font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / filename), size)


def _text_size(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _draw_frame(draw: ImageDraw.ImageDraw) -> None:
    # Outer 1px frame + inner 1px frame separated by a hairline of paper, the
    # same double-border affect themes get from show_borders=True.
    draw.rectangle([(0, 0), (WIDTH - 1, HEIGHT - 1)], outline=BLACK, width=1)
    draw.rectangle(
        [(BORDER, BORDER), (WIDTH - 1 - BORDER, HEIGHT - 1 - BORDER)], outline=BLACK, width=1
    )


def _draw_wordmark(draw: ImageDraw.ImageDraw) -> None:
    # Wordmark in Maratype (the terminal theme's display face). 130pt fits
    # "HOME DASHBOARD" comfortably within the wordmark zone (~930px wide).
    title_font = _font("Maratype.otf", 130)
    tagline_font = _font("DMSans.ttf", 30)
    eyebrow_font = _font("PlusJakartaSans-SemiBold.ttf", 22)

    eyebrow = "RASPBERRY PI · WAVESHARE & INKY · v5"
    title = "HOME DASHBOARD"
    tagline = "eInk wall display for family logistics"

    # Eyebrow tracked above the wordmark with a hairline rule trailing it.
    eyebrow_y = 78
    eyebrow_w, _ = _text_size(draw, eyebrow, eyebrow_font)
    draw.text((WORDMARK_X, eyebrow_y), eyebrow, font=eyebrow_font, fill=BLACK)
    rule_x0 = WORDMARK_X + eyebrow_w + 16
    rule_x1 = WORDMARK_RIGHT - 10
    rule_y = eyebrow_y + 13
    if rule_x1 > rule_x0:
        draw.line([(rule_x0, rule_y), (rule_x1, rule_y)], fill=BLACK, width=1)

    # Main wordmark.
    _, title_h = _text_size(draw, title, title_font)
    title_y = 122
    draw.text((WORDMARK_X, title_y), title, font=title_font, fill=BLACK)

    # Tagline beneath the wordmark.
    draw.text((WORDMARK_X, title_y + title_h + 22), tagline, font=tagline_font, fill=BLACK)


def _draw_calendar_strip(draw: ImageDraw.ImageDraw, origin: tuple[int, int]) -> None:
    # A compressed seven-day strip echoing week_view.py's day-header + cell pattern.
    x0, y0 = origin
    cell_w, cell_h = 54, 64
    head_h = 22
    days = ["S", "M", "T", "W", "T", "F", "S"]
    dates = [12, 13, 14, 15, 16, 17, 18]
    today_idx = 3  # Wednesday — the inverted "today" column.
    event_idx = 5  # Friday — gets an event bar.

    head_font = _font("PlusJakartaSans-SemiBold.ttf", 16)
    date_font = _font("PlusJakartaSans-Bold.ttf", 20)

    total_w = cell_w * len(days)
    total_h = head_h + cell_h
    # Outer frame.
    draw.rectangle([(x0, y0), (x0 + total_w, y0 + total_h)], outline=BLACK, width=1)
    # Header band fill.
    draw.rectangle([(x0, y0), (x0 + total_w, y0 + head_h)], fill=BLACK)
    for i, (dow, dom) in enumerate(zip(days, dates)):
        cx = x0 + i * cell_w
        # Vertical separators.
        if i > 0:
            draw.line([(cx, y0), (cx, y0 + total_h)], fill=BLACK, width=1)
        # Day-of-week letter (white on black band).
        dw, dh = _text_size(draw, dow, head_font)
        draw.text(
            (cx + (cell_w - dw) // 2, y0 + (head_h - dh) // 2 - 2),
            dow,
            font=head_font,
            fill=WHITE,
        )
        # Today column: fill the date cell black and invert the numeral.
        if i == today_idx:
            draw.rectangle(
                [(cx + 1, y0 + head_h + 1), (cx + cell_w - 1, y0 + total_h - 1)],
                fill=BLACK,
            )
        # Date numeral.
        text = str(dom)
        tw, _ = _text_size(draw, text, date_font)
        text_fill = WHITE if i == today_idx else BLACK
        draw.text(
            (cx + (cell_w - tw) // 2, y0 + head_h + 8),
            text,
            font=date_font,
            fill=text_fill,
        )
        # Event bar on a non-today cell.
        if i == event_idx:
            bar_y = y0 + total_h - 12
            draw.rectangle(
                [(cx + 6, bar_y), (cx + cell_w - 6, bar_y + 5)],
                fill=BLACK,
            )


def _draw_weather_block(draw: ImageDraw.ImageDraw, origin: tuple[int, int]) -> None:
    # Sunny weather glyph + temperature numeral, echoing weather_panel.py.
    x0, y0 = origin
    glyph_font = _font("weathericons-regular.ttf", 84)
    # NuCore Condensed (same family as NuCore.otf used in sunrise/tides/scorecard);
    # the non-condensed variant has an OpenType digit substitution that PIL's
    # basic shaper can't resolve, leaving digits as zero-height glyphs.
    temp_font = _font("NuCore Condensed.otf", 78)
    label_font = _font("DMSans.ttf", 16)

    glyph = ""  # Weather Icons font: OWM code "01d" (clear sky)
    draw.text((x0, y0), glyph, font=glyph_font, fill=BLACK)
    gw, _ = _text_size(draw, glyph, glyph_font)

    # Temperature numeral immediately right of the glyph. The condensed font
    # lacks a degree-symbol glyph, so we draw it as a small ring after the
    # numeral — consistent with how weather_panel.py renders the °.
    tx = x0 + gw + 14
    temp = "72"
    draw.text((tx, y0 + 4), temp, font=temp_font, fill=BLACK)
    tw, _ = _text_size(draw, temp, temp_font)
    ring_x = tx + tw + 6
    ring_y = y0 + 6
    ring_r = 10
    draw.ellipse(
        [ring_x, ring_y, ring_x + 2 * ring_r, ring_y + 2 * ring_r],
        outline=BLACK,
        width=4,
    )

    # Compact label under the glyph.
    label = "CLEAR · 72 / 51"
    draw.text((x0, y0 + 96), label, font=label_font, fill=BLACK)


def _draw_moon(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int) -> None:
    # Waxing gibbous (~70% illumination): full disc grey-dithered as the lit
    # surface, with a thin dark crescent carved out of the left limb. Geometry
    # mirrors the standard astronomy diagram — terminator is the right half of
    # a vertical ellipse with horizontal semi-axis k*R, where k = |cos(phase)|.
    cx, cy = center
    R = radius
    disc = [cx - R, cy - R, cx + R, cy + R]
    # 1. Disc filled grey (will dither to a stippled lit surface).
    draw.ellipse(disc, fill=MID)
    # 2. Left half of the disc filled black — covers what would be the dark
    #    side at exactly half phase.
    draw.pieslice(disc, 90, 270, fill=BLACK)
    # 3. Restore the part of the lit area that should still be lit at >50%
    #    phase by overpainting a central vertical ellipse in grey. The
    #    ellipse's horizontal semi-axis controls the phase (smaller → more
    #    illumination). k=0.45 reads as a healthy waxing gibbous.
    k_half_w = int(R * 0.45)
    terminator = [cx - k_half_w, cy - R, cx + k_half_w, cy + R]
    draw.ellipse(terminator, fill=MID)
    # 4. Re-stroke the disc outline so the limb stays crisp after the fills.
    draw.ellipse(disc, outline=BLACK, width=2)

    # Phase label beneath the moon.
    label_font = _font("DMSans.ttf", 16)
    label = "WAXING GIBBOUS"
    lw, _ = _text_size(draw, label, label_font)
    draw.text((cx - lw // 2, cy + R + 12), label, font=label_font, fill=BLACK)


def _draw_motif(draw: ImageDraw.ImageDraw) -> None:
    # Motif column sits to the right of the wordmark. Layout:
    #   row 1: 7-day calendar strip across the top
    #   row 2: weather block (left) | moon (right)
    # A single vertical divider separates the wordmark and motif columns.
    motif_top = 70
    motif_bottom = HEIGHT - 70

    # Divider between wordmark and motif.
    draw.line([(MOTIF_X - 20, motif_top), (MOTIF_X - 20, motif_bottom)], fill=BLACK, width=1)

    # Row 1: calendar strip (54px × 7 cells = 378px wide).
    _draw_calendar_strip(draw, origin=(MOTIF_X, motif_top + 4))

    # Row 2: weather and moon share a horizontal band below the calendar.
    band_y = motif_top + 4 + 22 + 64 + 30  # cal_top + head_h + cell_h + gap
    _draw_weather_block(draw, origin=(MOTIF_X, band_y))

    # Moon column at the right of the motif zone, vertically centered on the
    # weather band.
    moon_radius = 60
    moon_cx = WIDTH - 100
    moon_cy = band_y + 50
    _draw_moon(draw, center=(moon_cx, moon_cy), radius=moon_radius)

    # Hairline divider between weather and moon columns.
    div_x = moon_cx - moon_radius - 32
    draw.line([(div_x, band_y - 8), (div_x, band_y + 130)], fill=BLACK, width=1)


def _render_grey() -> Image.Image:
    image = Image.new("L", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    _draw_frame(draw)
    _draw_wordmark(draw)
    _draw_motif(draw)
    return image


def _quantize_floyd_steinberg(image: Image.Image) -> Image.Image:
    # Match src/render/quantize.py::quantize_for_display(mode="floyd_steinberg").
    return image.convert("1", dither=Image.Dither.FLOYDSTEINBERG)


def main() -> int:
    grey = _render_grey()
    bilevel = _quantize_floyd_steinberg(grey)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    bilevel.save(OUT_PATH, format="PNG", optimize=True)
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)} ({WIDTH}x{HEIGHT}, 1-bit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
