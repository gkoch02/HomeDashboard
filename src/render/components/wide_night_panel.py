"""wide_night_panel.py — a near-empty night plate for the 1360x480 strip.

Four marks and nothing else: the moon's phase, the temperature now, the
air-quality index and the current weather glyph, spaced evenly across the
strip and centred on its midline. Everything else is ground — on the
four-ink panel a solid red field with the marks in black ink.

The colours come from the theme's style rather than being fixed here, so the
plate reads the same on every backend:

  * **colour** (four-ink G panel, Inky) — the ground is the primary accent
    (red) and the marks are ``style.bg`` (black);
  * **monochrome** — the primary accent resolves to ``fg`` and there is no red
    to fill with, so the plate falls back to the dark-canvas convention the
    ``*_invert`` themes use: a black ground with the marks knocked out in white.

A mark whose data is missing is dropped and the rest re-spaced, so a setup
without a PurpleAir sensor shows three evenly spaced marks rather than a gap.
The moon is computed from the date and is always present.

Nothing reads the clock: the marks move only when the data or the date does,
so an idle tick renders byte-identically and costs no panel write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from PIL import ImageDraw

from src.data.models import DashboardData
from src.render.fonts import weather_icon as weather_icon_font
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_phase_glyph
from src.render.theme import ComponentRegion, ThemeStyle

# Glyph size (weather icons font) and numeral size. Chosen so every mark is
# about a quarter of the plate's height: large enough to read across a dark
# room, small enough that the plate stays mostly ground.
GLYPH_PT = 128
NUMERAL_PT = 132
CAPTION_PT = 22
# Gap between the AQI numeral and its caption.
CAPTION_GAP = 18
# The weather-icons new-moon glyph: a ring the size of every phase glyph.
_MOON_RING = "\uf095"


@dataclass(frozen=True)
class Mark:
    """One item on the plate: its text, font and an optional caption."""

    kind: str  # "moon" | "temperature" | "aqi" | "weather"
    text: str
    caption: str | None = None


def marks_for(data: DashboardData, today: date) -> list[Mark]:
    """The marks to draw, left to right, skipping any without data."""
    out = [Mark("moon", moon_phase_glyph(today))]
    weather = data.weather
    if weather is not None:
        out.append(Mark("temperature", f"{weather.current_temp:.0f}°"))
    if data.air_quality is not None:
        out.append(Mark("aqi", str(data.air_quality.aqi), caption="AQI"))
    if weather is not None:
        out.append(Mark("weather", OWM_ICON_MAP.get(weather.current_icon, FALLBACK_ICON)))
    return out


def centres(n: int, x0: int, w: int) -> list[int]:
    """Horizontal centres of *n* marks spaced evenly across ``[x0, x0 + w)``.

    Each mark gets an equal slice and sits at its middle, so the outer margins
    are half the gap between neighbours — the spacing reads as even whatever
    *n* is.
    """
    return [x0 + round(w * (i + 0.5) / n) for i in range(n)]


def colours(style: ThemeStyle):
    """``(ground, ink)`` for this plate on the resolved style."""
    accent = style.primary_accent_fill()
    if accent == style.fg:
        # Monochrome: the accent collapsed onto fg, so there is no red.
        return style.bg, style.fg
    return accent, style.bg


def draw_wide_night(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full ``wide_night`` plate into *region*."""
    if region is None:
        region = ComponentRegion(0, 0, 1360, 480)
    if style is None:
        style = ThemeStyle(fg=1, bg=0)

    x0, y0, w, h = region.x, region.y, region.w, region.h
    ground, ink = colours(style)
    draw.rectangle((x0, y0, x0 + w - 1, y0 + h - 1), fill=ground)

    marks = marks_for(data, today)
    mid_y = y0 + h // 2
    # Unantialiased type: on an RGB canvas an antialiased edge is cut at
    # mid-grey by the panel's ink snap, which thins the strokes.
    previous_mode = draw.fontmode
    draw.fontmode = "1"
    try:
        for mark, cx in zip(marks, centres(len(marks), x0, w)):
            _draw_mark(draw, mark, cx, mid_y, style, ink)
    finally:
        draw.fontmode = previous_mode


def _draw_mark(draw, mark: Mark, cx: int, cy: int, style: ThemeStyle, ink) -> None:
    if mark.kind in ("moon", "weather"):
        font = weather_icon_font(GLYPH_PT)
    else:
        font = style.font_medium(NUMERAL_PT)

    if mark.kind == "moon":
        # The phase glyphs ink only the lit part, which on its own reads as a
        # blob rather than a phase; the new-moon glyph is the disc's outline,
        # so drawing it beneath shows the whole moon with its lit part filled.
        _draw_centred(draw, _MOON_RING, font, cx, cy, ink)
        _draw_centred(draw, mark.text, font, cx, cy, ink, h_ref=_MOON_RING, v_ref=_MOON_RING)
        return

    # Numerals share one baseline: centre them vertically on a digit's box
    # rather than their own, which the degree sign would lift.
    v_ref = None if mark.kind == "weather" else "0"
    bottom = _draw_centred(draw, mark.text, font, cx, cy, ink, v_ref=v_ref)
    if mark.caption:
        cap_font = style.font_semibold(CAPTION_PT)
        cb = draw.textbbox((0, 0), mark.caption, font=cap_font)
        draw.text(
            (cx - (cb[0] + cb[2]) / 2, bottom + CAPTION_GAP - cb[1]),
            mark.caption,
            font=cap_font,
            fill=ink,
        )


def _draw_centred(
    draw, text, font, cx, cy, fill, *, h_ref: str | None = None, v_ref: str | None = None
) -> int:
    """Draw *text* with its ink box centred on ``(cx, cy)``; return its bottom.

    *h_ref* / *v_ref* centre on a different string's box on that axis — a
    digit, so numerals share a baseline, or the moon disc, so a phase glyph
    lands exactly over the disc drawn beneath it.
    """
    bx = draw.textbbox((0, 0), h_ref or text, font=font)
    by = draw.textbbox((0, 0), v_ref or text, font=font)
    x = round(cx - (bx[0] + bx[2]) / 2)
    y = round(cy - (by[1] + by[3]) / 2)
    draw.text((x, y), text, font=font, fill=fill)
    return y + by[3]
