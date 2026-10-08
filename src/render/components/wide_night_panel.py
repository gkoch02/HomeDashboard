"""wide_night_panel.py — a near-empty night plate for the 1360x480 strip.

Four marks and nothing else: the moon's phase, the temperature now, the
air-quality index and the current weather glyph, centred on the strip's
midline with equal gaps between them and at both ends. Everything else is
ground — on the four-ink panel a solid red field with the marks in black.

**Size.** Every mark is drawn at one shared ink height: ``BAND_FRACTION`` of
the plate when the four fit across it, otherwise the tallest height at which
they do with at least ``MIN_GAP`` between them — in practice the width of
tonight's readings decides, via ``fit_height``. Numerals are set in
``style.font_date_number``; each mark carries a fixed-size tracked-caps label
in ``style.font_bold`` on one shared baseline, and the row plus labels is
centred on the plate.

**Colour** comes from the theme's style, not from here: on a colour panel the
ground is the primary accent (red) and the marks ``style.bg`` (black); on
monochrome the accent resolves to ``fg`` and the plate falls back to the
dark-canvas convention, a black ground with marks knocked out in white.

A mark whose data is missing is dropped and the rest re-spaced; the moon is
computed from the date and always present. Nothing reads the clock, so an
idle tick renders byte-identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache

from PIL import Image, ImageDraw

from src.data.models import DashboardData
from src.render.fonts import weather_icon as weather_icon_font
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_phase_glyph
from src.render.theme import ComponentRegion, ThemeStyle

# The share of the plate's height each mark spans when the row fits at it.
# Width binds first for three or four marks (about 225 and 165 px), so this
# binds only when sources drop out; set just above the three-mark size so an
# offline moon keeps the plate's scale instead of filling it.
BAND_FRACTION = 0.5
# The narrowest gap the row will accept between marks (and at either end)
# before the shared height is reduced: a share of the height, so the gaps
# grow with the type — a fixed gap is overtaken by the space inside a mark
# (a numeral and its degree sign) as the marks get taller, and the row stops
# reading as four things — with a floor for very short rows. At 0.5 a
# four-mark row (with AQI) sets ~169 px marks, ~94% of the three-mark size;
# 0.9 shrank them to 135 px the moment PurpleAir added the fourth.
MIN_GAP_FRACTION = 0.5
MIN_GAP = 48
# The labels: a fixed size rather than a share of the mark height, so they
# stay deliberate at any row height; tracked out as a fraction of that size.
LABEL_PT = 20
LABEL_TRACKING = 0.4
# Space between the bottom of the marks and the labels' cap tops.
LABEL_GAP = 26
# Font size the measurements are taken at before scaling to the target height.
_PROBE_PT = 200
# The weather-icons new-moon glyph: a ring the size of every phase glyph. It is
# only ever measured, to size the moon by its whole disc and centre it on the
# disc's height — never drawn: the plate shows the lit part alone, with no
# outline on the dark limb. The moon's *width* in the row is its lit part's, so
# the gaps between marks are even to the eye rather than to an invisible disc.
_MOON_RING = "\uf095"


@dataclass(frozen=True)
class Mark:
    """One item on the plate: its text and the label set beneath it."""

    kind: str  # "moon" | "temperature" | "aqi" | "weather"
    text: str
    caption: str


def marks_for(data: DashboardData, today: date) -> list[Mark]:
    """The marks to draw, left to right, skipping any without data."""
    out = [Mark("moon", moon_phase_glyph(today), "MOON")]
    weather = data.weather
    if weather is not None:
        out.append(Mark("temperature", f"{weather.current_temp:.0f}°", "TEMP"))
    if data.air_quality is not None:
        out.append(Mark("aqi", str(data.air_quality.aqi), "AQI"))
    if weather is not None:
        out.append(Mark("weather", OWM_ICON_MAP.get(weather.current_icon, FALLBACK_ICON), "SKY"))
    return out


def colours(style: ThemeStyle, *, invert: bool = False):
    """``(ground, ink)`` for this plate on the resolved style.

    *invert* swaps the two: red marks on a black ground on a colour panel,
    black on white on monochrome (``wide_night_invert``).
    """
    accent = style.primary_accent_fill()
    if accent == style.fg:
        # Monochrome: the accent collapsed onto fg, so there is no red.
        ground, ink = style.bg, style.fg
    else:
        ground, ink = accent, style.bg
    return (ink, ground) if invert else (ground, ink)


def draw_wide_night(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    invert: bool = False,
) -> None:
    """Draw the full ``wide_night`` plate into *region*.

    *invert* draws ``wide_night_invert``: the same plate with ground and ink
    swapped.
    """
    if region is None:
        region = ComponentRegion(0, 0, 1360, 480)
    if style is None:
        style = ThemeStyle(fg=1, bg=0)

    x0, y0, w, h = region.x, region.y, region.w, region.h
    ground, ink = colours(style, invert=invert)
    draw.rectangle((x0, y0, x0 + w - 1, y0 + h - 1), fill=ground)

    marks = marks_for(data, today)
    height = fit_height(marks, style, w, int(h * BAND_FRACTION))
    placed = [_measure(m, style, height) for m in marks]
    gap = (w - sum(p.width for p in placed)) / (len(placed) + 1)
    label_font = style.font_bold(LABEL_PT)
    cap_h = ink_box("M", label_font)[3] - ink_box("M", label_font)[1]
    # Centre the marks and their labels as one group; the marks' own centre
    # sits above the plate's midline by half the label band.
    mid_y = y0 + h / 2 - (LABEL_GAP + cap_h) / 2
    label_top = mid_y + height / 2 + LABEL_GAP
    # Unantialiased type: on an RGB canvas an antialiased edge is cut at
    # mid-grey by the panel's ink snap, which thins the strokes.
    previous_mode = draw.fontmode
    draw.fontmode = "1"
    try:
        x = x0 + gap
        for p in placed:
            _draw_placed(draw, p, x, mid_y, ink)
            _draw_label(draw, p.mark.caption, x + p.width / 2, label_top, label_font, ink)
            x += p.width + gap
    finally:
        draw.fontmode = previous_mode


@dataclass(frozen=True)
class Placed:
    """A mark measured at the shared height: its font and layout boxes.

    ``box`` is the ink box that sets the mark's width and horizontal position;
    ``ref`` the one that sets its vertical centre — a digit's box for the
    numerals, so the degree sign does not lift them off a shared baseline, and
    the full disc for the moon.
    """

    mark: Mark
    font: object
    box: tuple[int, int, int, int]
    ref: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]


def _font_for(mark: Mark, style: ThemeStyle):
    if mark.kind in ("moon", "weather"):
        return weather_icon_font
    # Both numerals are set in the hero numeral face, so the row is one face.
    return style.font_date_number or style.font_bold


def _refs(mark: Mark) -> tuple[str, str]:
    """``(horizontal, vertical)`` reference strings for *mark*'s boxes."""
    if mark.kind == "moon":
        return mark.text, _MOON_RING
    if mark.kind == "weather":
        return mark.text, mark.text
    return mark.text, "0"


@lru_cache(maxsize=256)
def ink_box(text: str, font) -> tuple[int, int, int, int]:
    """The box *text*'s pixels actually cover, in ``textbbox`` coordinates.

    ``textbbox`` is not an ink box for the weather-icons face: every moon phase
    reports the whole disc's cell, a crescent included, so spacing by it puts
    a crescent's gap on the wrong side. Rasterising bilevel, as the plate does,
    and taking the pixels' extent is exact.
    """
    left, top, right, bottom = font.getbbox(text)
    ox, oy = max(0, -left), max(0, -top)
    img = Image.new("L", (right + ox + 2, bottom + oy + 2), 0)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    draw.text((ox, oy), text, font=font, fill=255)
    box = img.getbbox()
    if box is None:
        return (0, 0, 0, 0)
    return (box[0] - ox, box[1] - oy, box[2] - ox, box[3] - oy)


def _measure(mark: Mark, style: ThemeStyle, height: int) -> Placed:
    """*mark* at the font size whose reference box is *height* tall."""
    fn = _font_for(mark, style)
    h_ref, v_ref = _refs(mark)
    probe = ink_box(v_ref, fn(_PROBE_PT))
    size = max(1, round(_PROBE_PT * height / max(1, probe[3] - probe[1])))
    font = fn(size)
    return Placed(mark, font, ink_box(h_ref, font), ink_box(v_ref, font))


def fit_height(marks: list[Mark], style: ThemeStyle, width: int, cap: int) -> int:
    """The tallest shared mark height, up to *cap*, at which *marks* fit *width*.

    Widths and gaps both scale with height, so one proportional step gets
    close; font sizes are integers, so a few 2-px steps settle it.
    """

    def needed(height: int) -> int:
        marks_w = sum(_measure(m, style, height).width for m in marks)
        return marks_w + (len(marks) + 1) * min_gap(height)

    height = cap
    if needed(height) > width:
        height = int(height * width / needed(height))
    while height > 8 and needed(height) > width:
        height -= 2
    return height


def min_gap(height: int) -> int:
    """The narrowest gap allowed around marks *height* tall."""
    return max(MIN_GAP, round(height * MIN_GAP_FRACTION))


def _draw_placed(draw, p: Placed, x: float, cy: float, ink) -> None:
    """Draw *p* with its box's left edge at *x*, vertically centred on *cy*."""
    left = round(x - p.box[0])
    top = round(cy - (p.ref[1] + p.ref[3]) / 2)
    if not (p.mark.kind == "moon" and p.mark.text == _MOON_RING):
        # A new moon's glyph is only the ring — the dark limb's outline, which
        # this plate leaves out — so it draws nothing.
        draw.text((left, top), p.mark.text, font=p.font, fill=ink)


def tracked_width(text: str, font) -> float:
    """Advance width of *text* set with ``LABEL_TRACKING`` between letters."""
    step = font.size * LABEL_TRACKING
    return sum(font.getlength(c) for c in text) + step * (len(text) - 1)


def _draw_label(draw, text: str, cx: float, cap_top: float, font, ink) -> None:
    """Set *text* letter by letter, tracked out, centred on *cx*.

    PIL has no tracking, so each letter is placed by its own advance plus the
    tracking step; the run is centred on its advance width, which for caps is
    within a pixel of its ink.
    """
    x = cx - tracked_width(text, font) / 2
    top = cap_top - ink_box("M", font)[1]
    step = font.size * LABEL_TRACKING
    for c in text:
        draw.text((round(x), round(top)), c, font=font, fill=ink)
        x += font.getlength(c) + step
