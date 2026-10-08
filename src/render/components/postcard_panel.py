"""Full-canvas dithered postcard component for the ``postcard`` theme.

The composition is a divided rectangle:

  ┌─────────────────────────────────┬──────────────────────────────────┐
  │                                 │  Greeting (Playfair italic)      │
  │   Procedural dithered scene     │  ────────────────────────────    │
  │   (sky + horizon + landscape    │  POSTMARK    [ STAMP w/ MOON ]   │
  │   + foreground), keyed to the   │                                  │
  │   weather icon and daypart.     │  TODAY  •  May 23, 2026          │
  │                                 │  9:00a  TEAM STANDUP             │
  │   Floyd-Steinberg-dithered      │  12:30p LUNCH WITH SARA          │
  │   greyscale gradients become    │  2:00p  DENTIST                  │
  │   engraving on Waveshare;       │  6:00p  YOGA — STUDIO 12         │
  │   stay grey on Inky RGB so the  │                                  │
  │   stamp's red accent reads.     │  "Wish you were here"            │
  │                                 │   — quote / signature            │
  └─────────────────────────────────┴──────────────────────────────────┘

Drawing happens at L-mode (8-bit greyscale) by default; on Inky RGB
canvases the same greyscale values are emitted as ``(v, v, v)`` triples
plus a warm red accent for the postmark and stamp border, so the eInk
panel's color story stays consistent with the rest of the dashboard.

The scene is painted by ``postcard_scene`` with no external assets, so the
component is fully offline and deterministic for a given date, weather icon
and hour.
"""

from __future__ import annotations

import math
from datetime import date, datetime

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DashboardData
from src.render.artkit import accent_red as _accent_red
from src.render.artkit import grey as _grey
from src.render.artkit import ink as _ink
from src.render.artkit import to_local_naive
from src.render.components.info_panel import _quote_for_today
from src.render.components.postcard_scene import light_for, render_scene, scene_kind
from src.render.primitives import (
    draw_text_truncated,
    draw_text_wrapped,
    events_for_day,
    text_height,
    truncate_to_width,
    wrap_lines,
)
from src.render.theme import ComponentRegion, ThemeStyle

# Geometry — postcard is split at SCENE_W; everything left of it is the
# dithered view, everything right is the postcard back.
#
# Every absolute pixel size is multiplied by ``SS`` because the theme renders
# onto a 2× supersampled canvas (1600×960) that the display backend
# LANCZOS-downsamples to the panel's native 800×480.  That gives us free
# anti-aliasing on every curved edge — sun discs, mountain ridges, ripple
# lines, cloud lobes — and softens the Floyd-Steinberg quantize step that
# follows it, since the input greyscale already carries sub-pixel detail.

SS = 2  # supersample factor — must match the theme's canvas multiplier.

SCENE_W = 480 * SS
BACK_PAD_X = 20 * SS
BACK_PAD_Y = 18 * SS


# Mode-aware colour helpers (mirrors halftone_panel)


def draw_postcard(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    quote_refresh: str = "daily",
    quotes_path: str | None = None,
) -> None:
    """Draw the full postcard (dithered scene + postcard back) into *region*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        image = draw._image  # type: ignore[attr-defined]

    x0, y0, w, h = region.x, region.y, region.w, region.h

    scene_rect = (x0, y0, x0 + SCENE_W, y0 + h)
    back_rect = (x0 + SCENE_W, y0, x0 + w, y0 + h)

    _draw_scene(image, scene_rect, data, today, now)
    _draw_back(
        draw,
        image,
        data,
        today,
        now,
        rect=back_rect,
        style=style,
        quote_refresh=quote_refresh,
        quotes_path=quotes_path,
    )
    _draw_center_crease(image, x0 + SCENE_W, y0, h)


# The view (left panel)


def _draw_scene(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    data: DashboardData,
    today: date,
    now: datetime,
) -> None:
    """Paint the procedural view for today's weather and the current hour."""
    weather = data.weather
    kind, is_night = scene_kind(weather.current_icon if weather is not None else None)
    tz = now.tzinfo
    rise = weather.sunrise if weather is not None else None
    down = weather.sunset if weather is not None else None
    light = light_for(
        to_local_naive(now, tz),
        is_night,
        to_local_naive(rise, tz) if rise is not None else None,
        to_local_naive(down, tz) if down is not None else None,
    )
    scene = render_scene(rect[2] - rect[0], rect[3] - rect[1], kind=kind, light=light, today=today)
    image.paste(scene.convert(image.mode), rect[:2])


# Centre crease — vertical line between scene + back


def _draw_center_crease(
    image: Image.Image,
    x: int,
    y0: int,
    h: int,
) -> None:
    """A thin dashed centre line — the crease where the postcard would fold.

    A two-pixel white gutter sits between the dithered scene and the crease
    so the crease reads cleanly against the dark side too.
    """
    mode = image.mode
    draw = ImageDraw.Draw(image)
    gutter = _grey(255, mode)
    draw.rectangle((x - 3 * SS, y0, x - SS, y0 + h), fill=gutter)
    draw.line([(x, y0), (x, y0 + h)], fill=_ink(mode), width=SS)
    shadow = _grey(150, mode)
    yy = y0 + 6 * SS
    while yy < y0 + h - 6 * SS:
        draw.line([(x + 2 * SS, yy), (x + 2 * SS, yy + 5 * SS)], fill=shadow, width=SS)
        yy += 9 * SS


# Postcard back (right panel)


def _events_today(events: list[CalendarEvent], today: date) -> list[CalendarEvent]:
    """Today's events, sorted (all-day first, then by start)."""
    return events_for_day(events, today)


def _fmt_event_time(dt: datetime) -> str:
    """Compact am/pm time, lowercase: e.g. ``9a``, ``2:30p``."""
    if dt.minute == 0:
        s = dt.strftime("%-I%p")
    else:
        s = dt.strftime("%-I:%M%p")
    return s.lower().replace("am", "a").replace("pm", "p")


def _draw_back(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    rect: tuple[int, int, int, int],
    style: ThemeStyle,
    quote_refresh: str,
    quotes_path: str | None = None,
) -> None:
    """Paint the right-panel postcard back: greeting, postmark, stamp, agenda, quote."""
    mode = image.mode
    x0, y0, x1, y1 = rect
    # Clean paper background so the dithered scene never bleeds in.
    paper = Image.new("L", (x1 - x0, y1 - y0), 255)
    if mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x0, y0))

    ink = _ink(mode)
    red = _accent_red(mode)

    inner_x0 = x0 + BACK_PAD_X
    inner_x1 = x1 - BACK_PAD_X
    inner_w = inner_x1 - inner_x0

    # --- Greeting (Playfair regular, solid ink so it doesn't fuzz after dither).
    greeting_font = style.font_semibold(20 * SS)
    greeting = "Greetings from today —"
    draw.text((inner_x0, y0 + BACK_PAD_Y), greeting, font=greeting_font, fill=ink)

    # --- Postmark (circular stamp) + Stamp (rectangular, with moon glyph)
    stamp_top = y0 + 64 * SS
    _draw_postmark(image, draw, inner_x0, stamp_top, today, mode=mode, red=red, ink=ink)
    _draw_stamp(
        image,
        draw,
        inner_x1 - 90 * SS,
        stamp_top,
        today,
        mode=mode,
        red=red,
        ink=ink,
        style=style,
    )

    # --- Dividing rule under the stamps — solid black for a crisp boundary.
    rule_y = stamp_top + 94 * SS
    draw.line([(inner_x0, rule_y), (inner_x1, rule_y)], fill=ink, width=SS)

    # --- Address-line agenda (today's events)
    assert style.font_section_label is not None
    label_font = style.font_section_label(13 * SS)
    label = f"TODAY  ·  {today.strftime('%a %b %-d').upper()}"
    draw.text((inner_x0, rule_y + 6 * SS), label, font=label_font, fill=ink)

    agenda_top = rule_y + 30 * SS
    events = _events_today(data.events, today)
    _draw_address_lines(
        draw,
        events,
        x0=inner_x0,
        y0=agenda_top,
        w=inner_w,
        style=style,
        ink=ink,
        red=red,
        mode=mode,
    )

    # --- Quote at the bottom — solid ink, larger Playfair body for legibility.
    quote = _quote_for_today(today, refresh=quote_refresh, now=now, quotes_path=quotes_path)
    quote_font = style.font_quote(15 * SS) if style.font_quote else style.font_regular(15 * SS)
    author_font = (
        style.font_quote_author(12 * SS)
        if style.font_quote_author
        else style.font_semibold(12 * SS)
    )
    quote_text = f"“{quote['text']}”"
    author_text = truncate_to_width(draw, f"— {quote['author']}", author_font, inner_w)
    quote_w = inner_w
    line_h = text_height(quote_font)
    lines = wrap_lines(quote_text, quote_font, quote_w)[:3]
    line_spacing = 2 * SS
    author_bb = draw.textbbox((0, 0), author_text, font=author_font)
    author_h = author_bb[3] - author_bb[1]
    bottom_pad = 12 * SS
    block_h = line_h * len(lines) + line_spacing * max(0, len(lines) - 1)
    ay = y1 - bottom_pad - author_h - author_bb[1]
    # Text ink starts below its draw origin, so the block is lifted by that
    # offset or its last line runs into the attribution.
    quote_top = draw.textbbox((0, 0), "Ag", font=quote_font)[1]
    qy = y1 - bottom_pad - author_h - 4 * SS - block_h - quote_top
    draw_text_wrapped(
        draw,
        (inner_x0, qy),
        quote_text,
        quote_font,
        quote_w,
        max_lines=3,
        line_spacing=line_spacing,
        fill=ink,
    )
    ax = inner_x1 - (author_bb[2] - author_bb[0]) - author_bb[0]
    draw.text((ax, ay), author_text, font=author_font, fill=red)


def _draw_postmark(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    today: date,
    *,
    mode: str,
    red,
    ink,
) -> None:
    """Circular postmark with day numeral + month abbrev inside the rings."""
    r = 32 * SS
    cx, cy = x + r, y + r
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=red, width=2 * SS)
    inner_r = r - 6 * SS
    draw.ellipse(
        (cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r),
        outline=red,
        width=SS,
    )
    # Three wavy "cancellation" lines extending right from the postmark.
    wave_top = cy - 6 * SS
    wave_w = 96 * SS
    dy: float
    for i, dy in enumerate((-6 * SS, 0, 6 * SS)):
        wy = wave_top + dy + 6 * SS
        prev = None
        for j in range(0, wave_w, 3 * SS):
            xv = cx + r + 4 * SS + j
            yv = int(wy + math.sin((j + i * 4 * SS) * (0.25 / SS)) * 2 * SS)
            if prev is not None:
                draw.line([prev, (xv, yv)], fill=red, width=SS)
            prev = (xv, yv)

    # Date inside the postmark — day numeral (big) over month abbrev.
    from src.render import fonts as _fonts

    day_font = _fonts.cinzel_bold(22 * SS)
    month_font = _fonts.cinzel_semibold(12 * SS)
    month_txt = today.strftime("%b").upper()
    day_txt = today.strftime("%-d")
    db = draw.textbbox((0, 0), day_txt, font=day_font)
    mb = draw.textbbox((0, 0), month_txt, font=month_font)
    dx = cx - (db[2] - db[0]) // 2 - db[0]
    dy = cy - (db[3] - db[1]) // 2 - db[1] - 2 * SS
    draw.text((dx, dy), day_txt, font=day_font, fill=red)
    mx = cx - (mb[2] - mb[0]) // 2 - mb[0]
    my = cy + (db[3] - db[1]) // 2 - 2 * SS
    draw.text((mx, my), month_txt, font=month_font, fill=red)


def _draw_stamp(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    today: date,
    *,
    mode: str,
    red,
    ink,
    style: ThemeStyle,
) -> None:
    """Rectangular postage stamp with perforated edges + moon glyph + illumination %."""
    w = 86 * SS
    h = 96 * SS
    pitch = 6 * SS
    for px in range(x, x + w + 1, pitch):
        draw.ellipse((px - 2 * SS, y - 3 * SS, px + 2 * SS, y + SS), fill=red)
        draw.ellipse((px - 2 * SS, y + h - SS, px + 2 * SS, y + h + 3 * SS), fill=red)
    for py in range(y, y + h + 1, pitch):
        draw.ellipse((x - 3 * SS, py - 2 * SS, x + SS, py + 2 * SS), fill=red)
        draw.ellipse((x + w - SS, py - 2 * SS, x + w + 3 * SS, py + 2 * SS), fill=red)
    pad = 5 * SS
    inner = (x + pad, y + pad, x + w - pad, y + h - pad)
    draw.rectangle(inner, outline=red, width=2 * SS)

    from src.render import fonts as _fonts
    from src.render.moon import moon_illumination, moon_phase_glyph

    glyph_font = _fonts.weather_icon(42 * SS)
    glyph = moon_phase_glyph(today)
    gb = draw.textbbox((0, 0), glyph, font=glyph_font)
    cx = x + w // 2
    gx = cx - (gb[2] - gb[0]) // 2 - gb[0]
    gy = y + 10 * SS - gb[1]
    draw.text((gx, gy), glyph, font=glyph_font, fill=ink)

    illum = moon_illumination(today)
    pct_font = _fonts.cinzel_bold(14 * SS)
    pct = f"{int(round(illum))}%"
    pb = draw.textbbox((0, 0), pct, font=pct_font)
    px_ = cx - (pb[2] - pb[0]) // 2 - pb[0]
    py_ = y + h - pad - (pb[3] - pb[1]) - 4 * SS - pb[1]
    draw.text((px_, py_), pct, font=pct_font, fill=ink)


def _draw_address_lines(
    draw: ImageDraw.ImageDraw,
    events: list[CalendarEvent],
    *,
    x0: int,
    y0: int,
    w: int,
    style: ThemeStyle,
    ink,
    red,
    mode: str,
) -> None:
    """Stack of address lines: time gutter + summary + ruled underline.

    Body text is solid ink and the underline rules are a darker mid-grey
    (60) — barely affected by Floyd-Steinberg quantization but visually
    softer than the body text so the rules read as "address lines" rather
    than as primary content.
    """
    assert style.font_section_label is not None
    time_font = style.font_section_label(14 * SS)
    body_font = style.font_semibold(17 * SS)
    rule_fill = _grey(60, mode)
    line_h = 30 * SS
    max_rows = 5
    rows = events[:max_rows]

    if not rows:
        for i in range(4):
            ly = y0 + i * line_h + 22 * SS
            draw.line([(x0, ly), (x0 + w, ly)], fill=rule_fill, width=SS)
        empty_label = "( nothing scheduled )"
        draw.text((x0, y0 + 2 * SS), empty_label, font=body_font, fill=ink)
        return

    gutter_w = 70 * SS
    for i, ev in enumerate(rows):
        ly = y0 + i * line_h
        rule_y = ly + line_h - 4 * SS
        draw.line([(x0, rule_y), (x0 + w, rule_y)], fill=rule_fill, width=SS)
        if ev.is_all_day:
            time_txt = "ALL DAY"
        else:
            time_txt = _fmt_event_time(ev.start).upper()
        draw.text((x0, ly + 4 * SS), time_txt, font=time_font, fill=red)
        draw_text_truncated(
            draw,
            (x0 + gutter_w, ly + 2 * SS),
            ev.summary,
            body_font,
            w - gutter_w,
            fill=ink,
        )
    extra = len(events) - len(rows)
    if extra > 0:
        ly = y0 + len(rows) * line_h
        draw.text((x0, ly + 2 * SS), f"+{extra} more", font=body_font, fill=ink)
