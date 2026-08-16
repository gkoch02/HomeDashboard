"""Full-canvas dithered weather plate for the ``halftone`` theme.

The panel draws a procedural illustration that varies by weather icon code
into an 800×320 hero region, a 6-px ordered-Bayer rule, and a 154-px margin
band of typeset data below.

Drawing is L-mode by default (8-bit greyscale). When the canvas is RGB
(Inky panels with ``prefer_color_on_inky=True``), the greyscale tones are
emitted as ``(v, v, v)`` triples and the warm sun/moon highlight uses a
yellow accent. Floyd-Steinberg quantization (configured by the theme's
``preferred_quantization_mode``) turns the smooth greyscale gradients into
engraving-style halftone on Waveshare.

No external assets — every illustration is generated from PIL primitives.
"""

from __future__ import annotations

from datetime import date, datetime

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DashboardData
from src.render.artkit import ink as _ink
from src.render.fonts import weather_icon
from src.render.primitives import content_time, draw_text_truncated
from src.render.quantize import _BAYER_4X4

# The procedural illustration vocabulary lives in ``src.render.skyart`` so the
# ``day_arc`` theme can share it. Imported under the private aliases this
# module has always used, so the drawing code below reads unchanged.
#
# ``_accent_yellow`` / ``_moon_disc`` / ``_radial_gradient_disc`` are no longer
# called here but stay re-exported: they were part of this module's surface
# before the move and existing tests import them from it.
from src.render.skyart import accent_yellow as _accent_yellow  # noqa: F401
from src.render.skyart import draw_bayer_rule as _draw_bayer_rule
from src.render.skyart import draw_cloud as _draw_cloud  # noqa: F401
from src.render.skyart import draw_fog as _draw_fog  # noqa: F401
from src.render.skyart import draw_lightning as _draw_lightning  # noqa: F401
from src.render.skyart import draw_missing as _draw_missing  # noqa: F401
from src.render.skyart import draw_moon as _draw_moon  # noqa: F401
from src.render.skyart import draw_precip as _draw_precip  # noqa: F401
from src.render.skyart import draw_sky as _draw_sky  # noqa: F401
from src.render.skyart import draw_sky_stormy as _draw_sky_stormy  # noqa: F401
from src.render.skyart import draw_stars as _draw_stars  # noqa: F401
from src.render.skyart import draw_sun as _draw_sun  # noqa: F401
from src.render.skyart import draw_weather_scene as _draw_weather_scene
from src.render.skyart import illustration_kind as _illustration_kind  # noqa: F401
from src.render.skyart import moon_disc as _moon_disc  # noqa: F401
from src.render.skyart import radial_gradient_disc as _radial_gradient_disc  # noqa: F401
from src.render.theme import ComponentRegion, ThemeStyle

# Weather Icons font glyphs — Righteous itself has no ↑/↓ arrows, so the
# sunrise/sunset row borrows these two glyphs from the bundled Weather
# Icons font and centers them on the Righteous text midline.
_SUNRISE_GLYPH = "\uf051"  # wi-sunrise
_SUNSET_GLYPH = "\uf052"  # wi-sunset

# ---------------------------------------------------------------------------
# Region geometry
# ---------------------------------------------------------------------------

HERO_H = 296
RULE_H = 6
MARGIN_PAD_X = 28
TEMP_NUMERAL_SIZE = 128
# Fixed left-column reservation for the temperature numeral + caption.
# Sized to hold a 3-digit temp ("108°") at TEMP_NUMERAL_SIZE without
# overlapping the right-side text column, so the right column's available
# width doesn't shrink as the temp digit count grows.
TEMP_COL_W = 280
# Bottom-of-band strip reserved for the small "updated HH:MM" caption.
# The row math above subtracts this from the band height so the existing
# zones (NOW / TODAY / NEXT) never overlap the footer.
FOOTER_H = 22


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_halftone(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full ``halftone`` plate into *region* of *image*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        # The production caller (``canvas.render_dashboard``) always passes
        # the backing image via ``RenderContext.image``. This branch only
        # fires for tests that build an ``ImageDraw.Draw`` directly without
        # forwarding the image — fall back to the private attribute rather
        # than crashing so those tests keep working.
        image = draw._image  # type: ignore[attr-defined]

    mode = image.mode
    x0, y0, w, h = region.x, region.y, region.w, region.h
    hero_rect = (x0, y0, x0 + w, y0 + HERO_H)
    rule_y0 = y0 + HERO_H
    margin_y0 = rule_y0 + RULE_H

    _draw_illustration(image, hero_rect, data, today, now)
    _draw_bayer_rule(image, x0, rule_y0, w, RULE_H, mode)
    _draw_margin_band(
        draw,
        image,
        data,
        today,
        now,
        x0=x0,
        y0=margin_y0,
        w=w,
        h=h - HERO_H - RULE_H,
        style=style,
    )


# ---------------------------------------------------------------------------
# Illustration dispatch
# ---------------------------------------------------------------------------


def _draw_illustration(
    image: Image.Image,
    hero_rect: tuple[int, int, int, int],
    data: DashboardData,
    today: date,
    now: datetime,
) -> None:
    """Paint the hero engraving for the current conditions.

    The scene composition itself lives in :func:`src.render.skyart.
    draw_weather_scene` so ``halftone_agenda`` can draw the same illustration
    into its narrower plate; this hero is the nominal rect the placements were
    composed against, so it passes ``scale=1.0`` and gets them verbatim.
    """
    icon = data.weather.current_icon if data.weather is not None else None
    _draw_weather_scene(image, hero_rect, icon, today)


# ---------------------------------------------------------------------------
# Margin band — typeset weather info + next event + daily quote
# ---------------------------------------------------------------------------


def _fmt_temp(t: float | None) -> str:
    if t is None:
        return "—"
    return f"{int(round(t))}°"


def _format_event_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").lstrip("0")


def _next_event_line(events: list[CalendarEvent], now: datetime) -> str | None:
    """Find the soonest non-all-day future event and format it for the margin."""
    if not events:
        return None
    now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
    candidates: list[tuple[datetime, CalendarEvent]] = []
    for e in events:
        if e.is_all_day:
            continue
        start = e.start.replace(tzinfo=None) if e.start.tzinfo is not None else e.start
        if start >= now_naive:
            candidates.append((start, e))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    start, event = candidates[0]
    when = _format_event_time(start)
    return f"NEXT — {when}  {event.summary}"


def _draw_margin_band(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    x0: int,
    y0: int,
    w: int,
    h: int,
    style: ThemeStyle,
) -> None:
    """Paint the typeset data band below the hero illustration.

    Two-band almanac layout: the temperature numeral anchors the left
    third; the right side stacks a "NOW" line (condition + H/L/feels)
    above a thin hairline rule, then a "TODAY" pair of lines
    (sunrise/sunset + date, then the next event).

        ┌──────────────────────────────────────────────────────────────┐
        │         │ PARTLY CLOUDY · H 48° · L 35° · FEELS 38°          │
        │   42°   │ ─────────────────────────────────────────────────  │
        │         │ ☀ 6:24 AM   ☼ 7:51 PM        MON · APR 6 · 2026    │
        │         │ NEXT — 9:00 AM  ·  Farmers Market                  │
        └──────────────────────────────────────────────────────────────┘
    """
    mode = image.mode
    # Paint a clean paper background so the dithered hero never bleeds in.
    paper = Image.new("L", (w, h), 255)
    if mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x0, y0))

    # Every margin-band glyph is drawn in solid ink. Mid-grey fills get
    # mangled by Floyd-Steinberg into a halftone pattern and become
    # illegible — visual hierarchy here is carried by size and weight,
    # not by colour.
    ink = _ink(mode)

    weather = data.weather

    # All row + centring math runs against an "inner" band height so the
    # bottom FOOTER_H pixels stay reserved for the "updated" caption and
    # the primary content never overlaps it.
    inner_h = h - FOOTER_H

    # --- Temperature numeral, vertically centred in the full band. A
    # smaller "feels NN°" caption sits directly under it so the headline
    # weather summary on the right can stay tight without losing that
    # secondary reading.
    feels_caption = (
        f"feels {_fmt_temp(weather.feels_like)}"
        if weather and weather.feels_like is not None
        else ""
    )
    feels_font = style.font_semibold(20) if feels_caption else None
    feels_h: float = 0
    if feels_caption and feels_font is not None:
        fb = draw.textbbox((0, 0), feels_caption, font=feels_font)
        feels_h = (fb[3] - fb[1]) + 8  # 8 px gap above the caption

    # The temp numeral lives inside a fixed-width left column so the
    # right-side text column width is stable across 1-, 2-, and 3-digit
    # temperatures. Within that column the temp is horizontally centred
    # so 1- and 2-digit values don't look left-biased against the wide
    # blank reservation that 3-digit values would fill.
    temp_font = (style.font_title or style.font_bold)(TEMP_NUMERAL_SIZE)
    temp_text = _fmt_temp(weather.current_temp) if weather else "—"
    temp_bbox = draw.textbbox((0, 0), temp_text, font=temp_font)
    temp_visible_h = temp_bbox[3] - temp_bbox[1]
    temp_w = temp_bbox[2] - temp_bbox[0]
    temp_x = x0 + (TEMP_COL_W - temp_w) // 2 - temp_bbox[0]
    # Vertically centre the temp + caption stack in the FULL band height —
    # the footer caption is right-aligned so it never collides with this
    # left-column stack, and centring against `inner_h` would otherwise
    # bias the headline numeral upward as the footer grows.
    stack_h = temp_visible_h + feels_h
    temp_y = y0 + (h - stack_h) // 2 - temp_bbox[1]
    draw.text((temp_x, temp_y), temp_text, font=temp_font, fill=ink)
    text_col_x = x0 + TEMP_COL_W
    text_col_right = x0 + w - MARGIN_PAD_X

    # Centre the feels-like caption horizontally under the temperature
    # numeral so it reads as a footnote to the headline number.
    if feels_caption and feels_font is not None:
        fb = draw.textbbox((0, 0), feels_caption, font=feels_font)
        cap_w = fb[2] - fb[0]
        cap_x = temp_x + (temp_w - cap_w) // 2 - fb[0]
        cap_y = temp_y + temp_bbox[1] + temp_visible_h + 8 - fb[1]
        draw.text((cap_x, cap_y), feels_caption, font=feels_font, fill=ink)

    # --- Zones for the right-column text. With a NEXT event the band
    # is split into three rows: NOW (above the rule), TODAY (sun times
    # + date), NEXT (calendar). The hairline rule sits one-third down
    # and the lower pair is split evenly between TODAY and NEXT. With
    # no NEXT event the rule moves to the vertical centre so NOW and
    # TODAY breathe equally rather than leaving a jarring blank row.
    next_line = _next_event_line(data.events, now)
    inner_bottom = y0 + inner_h
    if next_line:
        rule_y = y0 + inner_h // 3
        below_top = rule_y + 1
        below_split = below_top + (inner_bottom - below_top) // 2
        now_zone = (y0, rule_y)
        today_zone = (below_top, below_split)
        next_zone: tuple[int, int] | None = (below_split, inner_bottom)
    else:
        rule_y = y0 + inner_h // 2
        below_top = rule_y + 1
        now_zone = (y0, rule_y)
        today_zone = (below_top, inner_bottom)
        next_zone = None

    def _centre_y(bbox: tuple[float, float, float, float], zone: tuple[int, int]) -> float:
        """Return the y to draw at so *bbox*'s visible ink centres in *zone*."""
        bb_h = bbox[3] - bbox[1]
        zone_mid = (zone[0] + zone[1]) // 2
        return zone_mid - bb_h // 2 - bbox[1]

    # --- NOW row: condition + H / L on one line. ``feels NN°`` lives
    # under the temperature numeral so this row can breathe at a larger
    # display size without overflowing on long condition strings (the
    # widest OWM phrase ``HEAVY INTENSITY RAIN`` plus triple-digit temps
    # still fits inside the 492 px right column at 25 pt).
    now_font = (style.font_section_label or style.font_bold)(25)
    now_parts: list[str] = []
    if weather is not None:
        if weather.current_description:
            now_parts.append(weather.current_description.upper())
        now_parts.append(f"H {_fmt_temp(weather.high)}")
        now_parts.append(f"L {_fmt_temp(weather.low)}")
    else:
        now_parts.append("AWAITING DATA")
    now_text = "  ·  ".join(now_parts)
    nb = draw.textbbox((0, 0), now_text, font=now_font)
    max_now_w = text_col_right - text_col_x
    draw_text_truncated(
        draw,
        (text_col_x, _centre_y(nb, now_zone)),
        now_text,
        now_font,
        max_now_w,
        fill=ink,
    )

    # --- Hairline rule between the NOW zone and the lower pair.
    _draw_text_band_rule(image, text_col_x, rule_y, text_col_right - text_col_x, mode)

    # --- TODAY row: sunrise + sunset on the left, date on the right,
    # both vertically centred in the TODAY zone.
    today_font = style.font_semibold(22)
    if weather and (weather.sunrise or weather.sunset):
        rise_text = _format_event_time(weather.sunrise) if weather.sunrise else "—"
        set_text = _format_event_time(weather.sunset) if weather.sunset else "—"
        icon_font = weather_icon(28)
        glyph_pad = 5
        pair_gap = 20

        chunks = [
            (_SUNRISE_GLYPH, icon_font),
            (rise_text, today_font),
            (_SUNSET_GLYPH, icon_font),
            (set_text, today_font),
        ]
        measured = [(s, f, draw.textbbox((0, 0), s, font=f)) for s, f in chunks]
        pads = (glyph_pad, pair_gap, glyph_pad, 0)

        # All chunks share the same vertical midline — derived from the
        # TODAY zone's mid Y so the row sits centred regardless of which
        # chunk (icon vs text) happens to be tallest.
        row_mid = (today_zone[0] + today_zone[1]) // 2

        cursor: float = text_col_x
        for (s, f, bb), pad in zip(measured, pads):
            glyph_mid = (bb[1] + bb[3]) // 2
            draw.text((cursor - bb[0], row_mid - glyph_mid), s, font=f, fill=ink)
            cursor += (bb[2] - bb[0]) + pad

    date_font = (style.font_section_label or style.font_bold)(22)
    date_text = today.strftime("%a · %b %-d · %Y").upper()
    db = draw.textbbox((0, 0), date_text, font=date_font)
    date_x = text_col_right - (db[2] - db[0]) - db[0]
    draw.text((date_x, _centre_y(db, today_zone)), date_text, font=date_font, fill=ink)

    # --- NEXT event, centred in the NEXT zone (only when present —
    # otherwise the layout above already absorbed the freed space).
    if next_line and next_zone is not None:
        event_font = style.font_semibold(24)
        eb = draw.textbbox((0, 0), next_line, font=event_font)
        max_w = text_col_right - text_col_x
        draw_text_truncated(
            draw,
            (text_col_x, _centre_y(eb, next_zone)),
            next_line,
            event_font,
            max_w,
            fill=ink,
        )

    # --- "updated HH:MM am" footer, right-aligned at the very bottom of
    # the margin band. Lowercase + regular weight reads as a quiet caption
    # against the uppercase semibold section labels above.
    footer_font = style.font_regular(17)
    footer_text = f"updated {_format_event_time(content_time(data, now)).lower()}"
    fb = draw.textbbox((0, 0), footer_text, font=footer_font)
    footer_x = text_col_right - (fb[2] - fb[0]) - fb[0]
    footer_y = inner_bottom + (FOOTER_H - (fb[3] - fb[1])) // 2 - fb[1]
    draw.text((footer_x, footer_y), footer_text, font=footer_font, fill=ink)


def _draw_text_band_rule(image: Image.Image, x0: int, y: int, w: int, mode: str) -> None:
    """Single-pixel dotted hairline matching the hero's Bayer rule motif.

    Pixels are drawn at the darker Bayer cells of the 4×4 matrix on a
    single row, giving a delicate halftone rule that pairs with the
    6-px engraved separator above.
    """
    on = _ink(mode)
    px = image.load()
    assert px is not None
    for xx in range(w):
        if _BAYER_4X4[0][xx & 3] < 128:
            px[x0 + xx, y] = on
