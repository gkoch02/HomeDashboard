"""Full-canvas Victorian-plate component for the ``naturalist`` theme.

Layout (800×480):

  ┌────────────────────────────────────────────────────────────────────┐
  │  PLATE LXXIII             ✦              MMXXVI · MAY              │
  │  ════════════════════════════════════════════════════════════════  │
  │     QUERCUS DIURNALIS      (Cinzel small caps subtitle)            │
  │                                                                    │
  │     ┌──────────────────────────┐  ╭─── EVENT  9:00a TEAM STANDUP   │
  │     │                          │  │                                │
  │     │     procedural           │  ├─── MOON   Waxing Crescent 24%  │
  │     │     branch + leaves      │  │                                │
  │     │  (Floyd-Steinberg        │  ├─── SUN    ↑ 6:24a   ↓ 7:51p   │
  │     │   dithered, varies by    │  │                                │
  │     │   season + weather)      │  ╰─── AIR    72°  Partly Cloudy   │
  │     │                          │                                   │
  │     └──────────────────────────┘                                   │
  │  ════════════════════════════════════════════════════════════════  │
  │  — "Look deep into nature, and then you will understand …" —       │
  │                                                — A. EINSTEIN       │
  └────────────────────────────────────────────────────────────────────┘

The hero is a single specimen branch whose **leaf canopy, posture, and
surface treatment** vary deterministically with the season and the
current weather icon (bare in winter, lush in summer, frost-stippled
when cold and clear, raindrops behind the foliage in rain, etc).

Leader-line callouts pin today's most important data points to specific
anatomical features on the specimen, the way a botanical engraver would
label a leaf, a node, or a flower bud.

Everything is drawn from PIL primitives — no external assets.  The
canvas is L-mode and the theme requests Floyd-Steinberg quantization,
so the leaf gradients and bark shading become engraving-style halftone
on Waveshare; Inky picks up the red plate accents while the specimen
itself stays inky black.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DashboardData
from src.render.artkit import accent_red as _accent_red
from src.render.artkit import grey as _grey
from src.render.artkit import ink as _ink
from src.render.artkit import season as _season
from src.render.components.info_panel import _quote_for_today
from src.render.moon import moon_illumination, moon_phase_name
from src.render.primitives import (
    draw_text_truncated,
    draw_text_wrapped,
    events_for_day,
    text_height,
    wrap_lines,
)
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Page layout
#
# Every absolute pixel size is multiplied by ``SS`` because the theme renders
# onto a 2× supersampled canvas (1600×960) that the display backend
# LANCZOS-downsamples to the panel's native 800×480.  That gives us free
# anti-aliasing on every engraved branch, every leaf outline, and every
# typeset glyph before the final Floyd-Steinberg quantize.
# ---------------------------------------------------------------------------

SS = 2  # supersample factor — must match the theme's canvas multiplier.

_PAD_X = 28 * SS

_HEADER_TOP = 14 * SS
_HEADER_RULE_Y = 46 * SS
_SUBTITLE_Y = 60 * SS

_BODY_TOP = 118 * SS
_BODY_BOTTOM = 390 * SS
_FOOTER_RULE_Y = 394 * SS
_QUOTE_Y = 408 * SS

# Specimen area (the branch).
_SPEC_X0 = 40 * SS
_SPEC_Y0 = _BODY_TOP + 6 * SS
_SPEC_X1 = 430 * SS
_SPEC_Y1 = _BODY_BOTTOM - 6 * SS

# Callout column anchors.
_CALLOUT_X0 = 470 * SS
_CALLOUT_W = 800 * SS - _PAD_X - _CALLOUT_X0


# ---------------------------------------------------------------------------
# Mode-aware colour helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Deterministic RNG seed — Python ``str.__hash__`` is randomized per process,
# so we need a stable hash to keep the specimen reproducible across runs and
# across the snapshot-tests CI job.
# ---------------------------------------------------------------------------


_SEASON_SEED = {"winter": 1, "spring": 2, "summer": 3, "autumn": 4}
_MODIFIER_SEED = {
    "neutral": 10,
    "rain": 20,
    "storm": 30,
    "snow": 40,
    "fog": 50,
    "frost": 60,
}


def _stable_seed(season: str, modifier: str, today: date) -> int:
    """Process-stable RNG seed derived from season + modifier + ordinal day."""
    s = _SEASON_SEED.get(season, 0)
    m = _MODIFIER_SEED.get(modifier, 0)
    return (s * 1000003 + m * 977 + today.toordinal()) & 0x7FFFFFFF


# ---------------------------------------------------------------------------
# Season + weather classification
# ---------------------------------------------------------------------------


# Freezing-point threshold per OWM unit system.  ``WeatherData.current_temp``
# is whatever value the OWM API returned for ``cfg.weather.units``, so the
# frost gate needs to know which scale it's comparing against — otherwise a
# clear 15 °C spring day would render as a frost-stippled plate in ``metric``.
_FREEZING_BY_UNIT = {
    "imperial": 32.0,  # °F
    "metric": 0.0,  # °C
    "standard": 273.15,  # K
}


def _is_freezing(temp: float | None, units: str | None) -> bool:
    """Return True when *temp* is at or below freezing for its unit system.

    Falls back to the imperial threshold when *units* is missing or unknown
    (legacy cache entries written before the field existed, or an explicit
    ``None`` from a custom data source).  This preserves the original
    behaviour for the dominant case without crashing on unfamiliar input.
    """
    if temp is None:
        return False
    threshold = _FREEZING_BY_UNIT.get(units or "imperial", _FREEZING_BY_UNIT["imperial"])
    return temp <= threshold


def _weather_modifier(icon: str | None, temp: float | None, units: str | None = None) -> str:
    """Map current weather to a specimen-surface treatment.

    ``units`` is the OWM unit system attached to *temp* (``"imperial"``,
    ``"metric"``, or ``"standard"``).  Required for the ``frost`` branch so
    that a clear day in metric mode isn't misread as freezing.
    """
    if icon is None:
        return "neutral"
    code = icon[:2]
    if code in ("09", "10"):
        return "rain"
    if code == "11":
        return "storm"
    if code == "13":
        return "snow"
    if code == "50":
        return "fog"
    if code == "01" and _is_freezing(temp, units):
        return "frost"
    return "neutral"


# ---------------------------------------------------------------------------
# Specimen Latin label by season — kept short, evocative, deterministic.
# ---------------------------------------------------------------------------


def _latin_name(season: str, modifier: str) -> str:
    by_season = {
        "spring": "QUERCUS  VERNALIS",
        "summer": "QUERCUS  AESTIVALIS",
        "autumn": "QUERCUS  AUTUMNALIS",
        "winter": "QUERCUS  HIBERNALIS",
    }
    suffix = {
        "rain": " · sub pluvia",
        "storm": " · sub fulmine",
        "snow": " · sub nive",
        "fog": " · sub nebula",
        "frost": " · sub gelu",
    }.get(modifier, "")
    return by_season.get(season, "QUERCUS  DIURNALIS") + suffix


# ---------------------------------------------------------------------------
# Plate number (deterministic from today; rolls slowly through the year).
# ---------------------------------------------------------------------------

_ROMAN = (
    ("M", 1000),
    ("CM", 900),
    ("D", 500),
    ("CD", 400),
    ("C", 100),
    ("XC", 90),
    ("L", 50),
    ("XL", 40),
    ("X", 10),
    ("IX", 9),
    ("V", 5),
    ("IV", 4),
    ("I", 1),
)


def _roman(n: int) -> str:
    out: list[str] = []
    for sym, val in _ROMAN:
        while n >= val:
            out.append(sym)
            n -= val
    return "".join(out)


def _plate_number(today: date) -> str:
    """Plate number derived from day-of-year — varies across the calendar."""
    return _roman(((today.timetuple().tm_yday - 1) % 365) + 1)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_naturalist(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    quote_refresh: str = "daily",
) -> None:
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        image = draw._image  # type: ignore[attr-defined]

    mode = image.mode
    ink = _ink(mode)
    red = _accent_red(mode)

    season = _season(today)
    weather = data.weather
    icon = weather.current_icon if weather else None
    temp = weather.current_temp if weather else None
    units = weather.units if weather else None
    modifier = _weather_modifier(icon, temp, units)

    _draw_masthead(draw, today, season, modifier, style=style, ink=ink, red=red)
    _draw_specimen(image, season, modifier, today, mode=mode)
    feature_pts = _feature_points()
    _draw_callouts(
        draw,
        data,
        today,
        now,
        feature_pts=feature_pts,
        style=style,
        ink=ink,
        red=red,
        mode=mode,
    )
    _draw_footer(
        draw,
        today,
        now,
        style=style,
        quote_refresh=quote_refresh,
        ink=ink,
        red=red,
        mode=mode,
    )
    _draw_border_ornaments(draw, mode=mode, red=red)


# ---------------------------------------------------------------------------
# Masthead — blackletter plate header
# ---------------------------------------------------------------------------


def _draw_masthead(
    draw: ImageDraw.ImageDraw,
    today: date,
    season: str,
    modifier: str,
    *,
    style: ThemeStyle,
    ink,
    red,
) -> None:
    """Plate header: PLATE no. + dateline above a triple rule, Latin specimen
    name + weekday/date beneath.  All text is solid ink at sizes chosen to
    stay legible after the final Floyd-Steinberg quantization step."""
    assert style.font_section_label is not None
    plate_label_font = style.font_section_label(16 * SS)
    dateline_font = style.font_section_label(16 * SS)
    subtitle_font = style.font_section_label(20 * SS)
    day_font = style.font_section_label(14 * SS)

    # Left:  PLATE [Roman]
    plate_text = f"PLATE  {_plate_number(today)}"
    draw.text((_PAD_X, _HEADER_TOP), plate_text, font=plate_label_font, fill=ink)

    # Right:  date in small caps — YEAR (Roman) · MONTH
    year_roman = _roman(today.year)
    month_text = today.strftime("%B").upper()
    dateline_text = f"{year_roman}  ·  {month_text}"
    db = draw.textbbox((0, 0), dateline_text, font=dateline_font)
    canvas_w = 800 * SS
    draw.text(
        (canvas_w - _PAD_X - (db[2] - db[0]) - db[0], _HEADER_TOP),
        dateline_text,
        font=dateline_font,
        fill=ink,
    )

    # Centre rule — heavy + thin double rule.
    draw.line(
        [(_PAD_X, _HEADER_RULE_Y), (canvas_w - _PAD_X, _HEADER_RULE_Y)],
        fill=ink,
        width=2 * SS,
    )
    draw.line(
        [(_PAD_X, _HEADER_RULE_Y + 5 * SS), (canvas_w - _PAD_X, _HEADER_RULE_Y + 5 * SS)],
        fill=ink,
        width=SS,
    )
    # Centred ornament breaking the rule.
    cx = canvas_w // 2
    glyph_font = style.font_section_label(18 * SS)
    glyph = "✦"
    gb = draw.textbbox((0, 0), glyph, font=glyph_font)
    pad = 16 * SS
    gx = cx - (gb[2] - gb[0]) // 2 - gb[0]
    gy = _HEADER_RULE_Y - 12 * SS
    draw.rectangle(
        (cx - pad, _HEADER_RULE_Y - 4 * SS, cx + pad, _HEADER_RULE_Y + 8 * SS),
        fill=style.bg,
    )
    draw.text((gx, gy), glyph, font=glyph_font, fill=red)

    # Subtitle — small-caps Latin specimen name centred under the masthead.
    latin = _latin_name(season, modifier)
    sb = draw.textbbox((0, 0), latin, font=subtitle_font)
    sx = cx - (sb[2] - sb[0]) // 2 - sb[0]
    draw.text((sx, _SUBTITLE_Y), latin, font=subtitle_font, fill=ink)

    # Weekday + day under the Latin name.
    day_label = today.strftime("%A · %B %-d").upper()
    db2 = draw.textbbox((0, 0), day_label, font=day_font)
    dx = cx - (db2[2] - db2[0]) // 2 - db2[0]
    draw.text((dx, _SUBTITLE_Y + 32 * SS), day_label, font=day_font, fill=ink)


# ---------------------------------------------------------------------------
# Specimen — the procedural branch
# ---------------------------------------------------------------------------

# Anatomical feature points on the specimen — leader lines from the right-
# column callouts end at these (x, y) anchors.  Tuned to land on the upper
# canopy, mid trunk, a lower branch, and the root crown of the procedural
# specimen for any season.
_FEATURE_POINTS = {
    "leaf_top": (315 * SS, _BODY_TOP + 50 * SS),
    "node_mid": (290 * SS, _BODY_TOP + 130 * SS),
    "branch_low": (220 * SS, _BODY_TOP + 195 * SS),
    "root": (200 * SS, _BODY_TOP + 245 * SS),
}


def _feature_points() -> dict[str, tuple[int, int]]:
    return dict(_FEATURE_POINTS)


def _draw_specimen(
    image: Image.Image,
    season: str,
    modifier: str,
    today: date,
    *,
    mode: str,
) -> None:
    """Draw the procedurally-generated specimen branch into the body area."""
    rng = random.Random(_stable_seed(season, modifier, today))

    # Faint specimen plate background — a tight rectangle the branch sits in.
    bg = Image.new("L", (_SPEC_X1 - _SPEC_X0, _SPEC_Y1 - _SPEC_Y0), 248)
    if mode == "RGB":
        bg = bg.convert("RGB")
    image.paste(bg, (_SPEC_X0, _SPEC_Y0))

    draw = ImageDraw.Draw(image)
    # Tick marks at the corners of the specimen frame.
    tick_fill = _grey(120, mode)
    tl = (_SPEC_X0, _SPEC_Y0)
    tr = (_SPEC_X1, _SPEC_Y0)
    bl = (_SPEC_X0, _SPEC_Y1)
    br = (_SPEC_X1, _SPEC_Y1)
    for (x, y), dx, dy in (
        (tl, 1, 0),
        (tl, 0, 1),
        (tr, -1, 0),
        (tr, 0, 1),
        (bl, 1, 0),
        (bl, 0, -1),
        (br, -1, 0),
        (br, 0, -1),
    ):
        draw.line([(x, y), (x + dx * 8 * SS, y + dy * 8 * SS)], fill=tick_fill, width=SS)

    if modifier == "fog":
        _stipple_fog(image, rng)

    # Trunk — slightly curved vertical line, thicker toward the bottom.
    trunk_top = (_SPEC_X0 + 180 * SS, _SPEC_Y0 + 60 * SS)
    trunk_bot = (_SPEC_X0 + 160 * SS, _SPEC_Y1 - 40 * SS)
    _draw_trunk(draw, trunk_top, trunk_bot, mode=mode, rng=rng)

    # Branches — three on each side at varied heights/lengths.
    n_branches = 6
    nodes: list[tuple[int, int]] = []  # for leaves + buds
    for i in range(n_branches):
        t = (i + 1) / (n_branches + 1)
        bx = int(trunk_top[0] + (trunk_bot[0] - trunk_top[0]) * t)
        by = int(trunk_top[1] + (trunk_bot[1] - trunk_top[1]) * t)
        side = 1 if i % 2 == 0 else -1
        length = rng.randint(55 * SS, 95 * SS)
        angle_deg = rng.uniform(-65, -25) if side == 1 else rng.uniform(-155, -115)
        end_x = int(bx + length * math.cos(math.radians(angle_deg)))
        end_y = int(by + length * math.sin(math.radians(angle_deg)))
        _draw_branch(draw, (bx, by), (end_x, end_y), mode=mode, rng=rng)
        nodes.append((end_x, end_y))
        if rng.random() < 0.6:
            sub_len = rng.randint(20 * SS, 38 * SS)
            sub_angle = math.radians(angle_deg + rng.uniform(-32, 32))
            sx = int(end_x + sub_len * math.cos(sub_angle))
            sy = int(end_y + sub_len * math.sin(sub_angle))
            _draw_branch(draw, (end_x, end_y), (sx, sy), mode=mode, thin=True, rng=rng)
            nodes.append((sx, sy))

    # Roots — three sweeping curves at the base.
    _draw_roots(draw, trunk_bot, mode=mode, rng=rng)

    # Leaves — density and treatment vary by season.
    _draw_leaves(image, nodes, season, modifier, rng)

    # Weather overlay effects (rain streaks behind, snow on top, etc.)
    if modifier == "rain":
        _draw_rain_overlay(draw, rng, mode=mode)
    elif modifier == "storm":
        _draw_rain_overlay(draw, rng, mode=mode, heavy=True)
    elif modifier == "snow":
        _draw_snow_on_branches(draw, nodes, trunk_top, trunk_bot, mode=mode, rng=rng)
    elif modifier == "frost":
        _draw_frost_stipple(draw, nodes, mode=mode, rng=rng)


def _draw_trunk(
    draw: ImageDraw.ImageDraw,
    top: tuple[int, int],
    bot: tuple[int, int],
    *,
    mode: str,
    rng: random.Random,
) -> None:
    """Slightly curving trunk built from a stack of trapezoidal slabs.

    The trunk is drawn solid black so it reads as a clear silhouette after
    Floyd-Steinberg quantization (greyscale mid-tones would dither into a
    noisy speckle).  A few right-hand highlight strokes break up the silhouette
    just enough to suggest engraved cross-hatching without compromising
    legibility.
    """
    n_segs = 26
    fill = _ink(mode)
    # Trunk centreline is a quadratic Bézier — control point pushed sideways
    # so the trunk arcs gently rather than tracing a sine wiggle.
    ctrl = (
        (top[0] + bot[0]) * 0.5 + 8 * SS,
        (top[1] + bot[1]) * 0.5,
    )
    centre = _quadratic_bezier(top, ctrl, bot, n=n_segs)
    # Width tapers smoothly from top to bottom.
    widths = [(5 + 12 * (i / n_segs)) * SS for i in range(n_segs + 1)]
    # Build the silhouette as a single closed polygon walking down the right
    # edge then up the left edge.  This is smoother than stacking trapezoids
    # because the supersample LANCZOS sees a continuous outline.
    right_edge: list[tuple[float, float]] = []
    left_edge: list[tuple[float, float]] = []
    for i, ((px, py), w) in enumerate(zip(centre, widths)):
        # Tangent direction at this sample → perpendicular for the edge offset.
        if i == 0:
            nx_, ny_ = centre[1][0] - px, centre[1][1] - py
        elif i == len(centre) - 1:
            nx_, ny_ = px - centre[i - 1][0], py - centre[i - 1][1]
        else:
            nx_, ny_ = centre[i + 1][0] - centre[i - 1][0], centre[i + 1][1] - centre[i - 1][1]
        L = math.hypot(nx_, ny_) or 1.0
        perp = (-ny_ / L, nx_ / L)
        right_edge.append((px + perp[0] * w / 2, py + perp[1] * w / 2))
        left_edge.append((px - perp[0] * w / 2, py - perp[1] * w / 2))
    poly = right_edge + list(reversed(left_edge))
    draw.polygon(poly, fill=fill)

    # Bark striations — sparse, long vertical engraved highlights on the
    # right limb of the trunk.  Each stroke follows the trunk's centreline
    # tangent so they read as etched grooves rather than random hash.  We
    # use a small number of long strokes instead of many short ones —
    # botanical engravings rely on rhythm, not density.
    highlight = _grey(235, mode)
    n_marks = 8
    for i in range(n_marks):
        t = (i + 0.5) / n_marks + rng.uniform(-0.02, 0.02)
        idx = min(max(0, int(t * (len(centre) - 1))), len(centre) - 1)
        px, py = centre[idx]
        w = widths[idx]
        # Tangent of the centreline at this sample → use as the stroke axis.
        prev_idx = max(0, idx - 1)
        next_idx = min(len(centre) - 1, idx + 1)
        tx_ = centre[next_idx][0] - centre[prev_idx][0]
        ty_ = centre[next_idx][1] - centre[prev_idx][1]
        L = math.hypot(tx_, ty_) or 1.0
        tang = (tx_ / L, ty_ / L)
        # Offset toward the right limb of the trunk.
        offset = rng.uniform(0.18, 0.40) * w
        sx = px + (-tang[1]) * offset
        sy = py + (tang[0]) * offset
        seg_h = rng.randint(8 * SS, 14 * SS)
        a = (sx - tang[0] * seg_h / 2, sy - tang[1] * seg_h / 2)
        b = (sx + tang[0] * seg_h / 2, sy + tang[1] * seg_h / 2)
        draw.line([a, b], fill=highlight, width=SS)


def _quadratic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    n: int = 18,
) -> list[tuple[float, float]]:
    """Sample a quadratic Bézier curve at *n+1* points from p0 to p2 via control p1."""
    out: list[tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        one_minus = 1.0 - t
        x = one_minus * one_minus * p0[0] + 2 * one_minus * t * p1[0] + t * t * p2[0]
        y = one_minus * one_minus * p0[1] + 2 * one_minus * t * p1[1] + t * t * p2[1]
        out.append((x, y))
    return out


def _draw_branch(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    mode: str,
    thin: bool = False,
    rng: random.Random | None = None,
) -> None:
    """Tapering branch from *start* to *end* drawn as a quadratic Bézier curve.

    The control point is offset perpendicular to the start→end axis by a
    fraction of the branch length, giving each branch a natural S-curve.
    Width tapers smoothly from base to tip by drawing the polyline as a
    sequence of thick segments whose width steps down across the curve.
    """
    if rng is None:
        rng = random.Random((start[0], start[1], end[0], end[1]).__hash__())
    # Perpendicular offset for the control point — sweeps the branch into
    # a gentle curve toward "up and away" from the trunk.
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy) or 1.0
    perp_x = -dy / length
    perp_y = dx / length
    # Curl strength varies per branch so adjacent branches read differently.
    curl = (0.18 + rng.random() * 0.18) * length
    # Bias the curl so branches arc upward (negative y).
    if perp_y > 0:
        perp_x, perp_y = -perp_x, -perp_y
    cx_ctrl = (start[0] + end[0]) * 0.5 + perp_x * curl
    cy_ctrl = (start[1] + end[1]) * 0.5 + perp_y * curl
    pts = _quadratic_bezier(start, (cx_ctrl, cy_ctrl), end, n=22)

    base_w = SS if thin else 3 * SS
    fill = _ink(mode)
    for i in range(len(pts) - 1):
        t = i / max(1, len(pts) - 2)
        w = max(SS, base_w - int(t * 2 * SS))
        draw.line([pts[i], pts[i + 1]], fill=fill, width=w)


def _draw_roots(
    draw: ImageDraw.ImageDraw,
    trunk_bot: tuple[int, int],
    *,
    mode: str,
    rng: random.Random,
) -> None:
    """Curved root system: five primary roots with thin tendril offshoots.

    Each root is a quadratic Bézier curve sweeping outward from the trunk
    base.  Most primary roots spawn one or two thin tendrils mid-length
    that branch off at shallow angles, mimicking the lateral root
    structure botanical engravers exaggerate for visual depth.
    """
    fill = _ink(mode)
    n_primary = 5
    for i in range(n_primary):
        # Spread roots across the lower 180° (90° ± 70°).
        side_t = (i - (n_primary - 1) / 2) / ((n_primary - 1) / 2 or 1)
        angle = math.radians(90 + side_t * 65 + rng.uniform(-6, 6))
        length = rng.randint(45 * SS, 78 * SS)
        end_x = trunk_bot[0] + length * math.cos(angle)
        end_y = trunk_bot[1] + length * math.sin(angle)
        # Control point pulls each root into a downward sweep.
        ctrl_x = trunk_bot[0] + length * 0.55 * math.cos(angle - 0.25)
        ctrl_y = trunk_bot[1] + length * 0.55 * math.sin(angle - 0.25) + rng.randint(2 * SS, 6 * SS)
        pts = _quadratic_bezier(trunk_bot, (ctrl_x, ctrl_y), (end_x, end_y), n=20)
        for j in range(len(pts) - 1):
            t = j / max(1, len(pts) - 2)
            w = max(SS, 4 * SS - int(t * 3 * SS))
            draw.line([pts[j], pts[j + 1]], fill=fill, width=w)
        # 0–2 tendril offshoots that branch from mid-root.
        for _ in range(rng.choice((0, 1, 1, 2))):
            t_branch = rng.uniform(0.4, 0.75)
            branch_idx = int(len(pts) * t_branch)
            origin = pts[branch_idx]
            tendril_len = rng.randint(10 * SS, 22 * SS)
            tendril_angle = angle + math.radians(rng.uniform(-30, 30))
            tend_end = (
                origin[0] + tendril_len * math.cos(tendril_angle),
                origin[1] + tendril_len * math.sin(tendril_angle) + rng.randint(SS, 4 * SS),
            )
            tend_ctrl = (
                (origin[0] + tend_end[0]) * 0.5,
                (origin[1] + tend_end[1]) * 0.5 + rng.randint(SS, 3 * SS),
            )
            tpts = _quadratic_bezier(origin, tend_ctrl, tend_end, n=10)
            for j in range(len(tpts) - 1):
                draw.line([tpts[j], tpts[j + 1]], fill=fill, width=SS)


def _draw_leaves(
    image: Image.Image,
    nodes: list[tuple[int, int]],
    season: str,
    modifier: str,
    rng: random.Random,
) -> None:
    """Scatter leaves around branch endpoints, density keyed to season."""
    if season == "winter":
        count_per_node = 0 if modifier != "snow" else 1
        size_range = (6 * SS, 9 * SS)
        outline_only = True
    elif season == "spring":
        count_per_node = 4
        size_range = (7 * SS, 10 * SS)
        outline_only = False
    elif season == "summer":
        count_per_node = 8
        size_range = (8 * SS, 13 * SS)
        outline_only = False
    else:  # autumn
        count_per_node = 5
        size_range = (7 * SS, 12 * SS)
        outline_only = False

    draw = ImageDraw.Draw(image)
    mode = image.mode
    ink = _ink(mode)
    for nx, ny in nodes:
        for i in range(count_per_node):
            ox = rng.randint(-26 * SS, 26 * SS)
            oy = rng.randint(-24 * SS, 14 * SS)
            size = rng.randint(*size_range)
            if outline_only or (i % 3 == 2):
                _draw_leaf_outline(draw, nx + ox, ny + oy, size, ink, rng)
            else:
                _draw_leaf_filled(draw, nx + ox, ny + oy, size, ink, rng)

    if season == "spring":
        # Drooping oak catkins: tapered chains of small dots hanging from
        # the inner branch nodes.  Real Quercus flower in long catkins
        # before the canopy fills in.
        for nx, ny in nodes:
            if rng.random() < 0.55:
                _draw_catkin(draw, nx, ny, ink, rng)

    if season == "summer":
        # A couple of green acorn clusters tucked into the canopy.
        for nx, ny in nodes[: max(2, len(nodes) // 3)]:
            if rng.random() < 0.45:
                _draw_acorn_cluster(draw, nx, ny, ink, rng)

    if season == "autumn":
        # Mature brown acorns + scattered fallen leaves under the canopy.
        for nx, ny in nodes:
            if rng.random() < 0.35:
                _draw_acorn_cluster(draw, nx, ny, ink, rng)
        for _ in range(10):
            fx = rng.randint(_SPEC_X0 + 20 * SS, _SPEC_X1 - 20 * SS)
            fy = rng.randint(_SPEC_Y1 - 60 * SS, _SPEC_Y1 - 14 * SS)
            size = rng.randint(6 * SS, 10 * SS)
            _draw_leaf_outline(draw, fx, fy, size, ink, rng)


def _draw_catkin(
    draw: ImageDraw.ImageDraw,
    nx: int,
    ny: int,
    ink,
    rng: random.Random,
) -> None:
    """Drooping oak catkin — a chain of small dots tapering downward."""
    n_beads = rng.randint(6, 10)
    angle = math.radians(85 + rng.uniform(-8, 8))  # nearly straight down
    sx, sy = nx + rng.randint(-6 * SS, 6 * SS), ny + rng.randint(-4 * SS, 4 * SS)
    for i in range(n_beads):
        t = (i + 1) / n_beads
        bx = sx + math.cos(angle) * 3 * SS * (i + 1)
        by = sy + math.sin(angle) * 3 * SS * (i + 1)
        r = max(SS // 2, int((2 - t * 1.4) * SS))
        draw.ellipse((bx - r, by - r, bx + r, by + r), fill=ink)


def _draw_acorn_cluster(
    draw: ImageDraw.ImageDraw,
    nx: int,
    ny: int,
    ink,
    rng: random.Random,
) -> None:
    """A small cluster of 1–3 acorns — cupule (cap) + smooth nut beneath.

    Acorns hang BELOW the branch node (where light catches them in the
    real plant) and are drawn larger than the surrounding leaves so they
    stay distinct against the lobed canopy after Floyd-Steinberg dithers
    everything together.
    """
    n_acorns = rng.choice((1, 1, 2, 2, 3))
    # Hang the cluster down-and-out from the branch node so it's visible
    # against the canopy rather than buried inside it.
    base_x = nx + rng.randint(-4 * SS, 4 * SS)
    base_y = ny + rng.randint(10 * SS, 16 * SS)
    nut_w = 6 * SS
    nut_h = 9 * SS
    for i in range(n_acorns):
        ax = base_x + i * (nut_w * 2 + SS) - (n_acorns - 1) * (nut_w * 2 + SS) // 2
        ay = base_y
        # Stem from the branch node curving to this acorn.
        ctrl_x = (nx + ax) / 2 + rng.randint(-3 * SS, 3 * SS)
        ctrl_y = (ny + ay) / 2 + 4 * SS
        stem = _quadratic_bezier((nx, ny), (ctrl_x, ctrl_y), (ax, ay - nut_h - SS), n=8)
        for j in range(len(stem) - 1):
            draw.line([stem[j], stem[j + 1]], fill=ink, width=max(1, SS - 1))
        # Cupule (cap) — half-ellipse at the top.
        cap_w = nut_w + SS
        cap_h = nut_h // 2 + SS
        draw.pieslice(
            (ax - cap_w, ay - nut_h, ax + cap_w, ay - nut_h + cap_h * 2),
            start=180,
            end=360,
            fill=ink,
        )
        # Cap stippling — white dots to suggest the bumpy cupule scales.
        highlight = 255 if isinstance(ink, int) else (255, 255, 255)
        for dy_ in (-cap_h + 2 * SS, -cap_h // 2):
            for dx_ in (-cap_w + 2 * SS, 0, cap_w - 2 * SS):
                draw.ellipse(
                    (
                        ax + dx_ - SS // 2,
                        ay - nut_h + cap_h + dy_ - SS // 2,
                        ax + dx_ + SS // 2,
                        ay - nut_h + cap_h + dy_ + SS // 2,
                    ),
                    fill=highlight,
                )
        # Nut — elongated almond shape below the cap.
        draw.ellipse(
            (ax - nut_w, ay - nut_h + cap_h, ax + nut_w, ay + nut_h - cap_h),
            fill=ink,
        )
        # Highlight stroke down the nut's side for a 3D feel.
        draw.line(
            [(ax + nut_w // 3, ay - nut_h + cap_h + SS), (ax + nut_w // 3, ay - 2 * SS)],
            fill=highlight,
            width=max(1, SS - 1),
        )


def _oak_leaf_polygon(
    cx: float,
    cy: float,
    size: int,
    rng: random.Random,
) -> tuple[
    list[tuple[float, float]],
    tuple[float, float],
    tuple[float, float],
    list[tuple[tuple[float, float], tuple[float, float]]],
]:
    """Build an oak-leaf-shaped polygon with 5–7 rounded lobes.

    Returns ``(outline_points, base_point, tip_point, vein_segments)``.

    The lobe profile is generated parametrically: walking from the leaf
    base around the silhouette to the tip and back, at each step the
    radius from the central midrib alternates between a wider "lobe"
    radius and a narrower "sinus" radius, producing the characteristic
    crenelated oak silhouette.  Vein segments connect the midrib to each
    lobe tip, mimicking a real leaf's pinnate venation.
    """
    rot = rng.uniform(0, math.pi)
    n_lobes_per_side = rng.randint(2, 3)  # 4–6 lateral lobes + 1 terminal
    n_samples = n_lobes_per_side * 4 + 4  # samples per side (alternating)
    # Half-length along the midrib, in supersample px.
    rx = float(size)
    # Max lateral lobe radius from the midrib.
    ry_max = max(2.0, size * 0.55)
    ry_min = max(1.5, size * 0.22)

    # Sample the upper edge (base→tip) then the lower edge (tip→base).
    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    lobe_tips_upper: list[tuple[float, float]] = []
    lobe_tips_lower: list[tuple[float, float]] = []

    for i in range(n_samples + 1):
        t = i / n_samples  # 0 = base, 1 = tip
        # Position along the midrib axis.
        u = -rx + 2 * rx * t
        # Lobe profile: alternates wide / narrow. ``phase`` parameterises an
        # underlying sinusoid that hits its maxima at lobe centres and its
        # minima at sinus (notch) points.
        phase = t * (n_lobes_per_side * 2) * math.pi
        # Envelope tapers the leaf toward both ends.
        envelope = math.sin(math.pi * t) ** 0.65
        # Each "wide" sample is the lobe tip; each "narrow" sample is a sinus.
        wave = (math.cos(phase) + 1.0) * 0.5  # 0..1
        ry_here = (ry_min + (ry_max - ry_min) * wave) * envelope
        upper.append((u, -ry_here))
        lower.append((u, ry_here))
        # Track lobe tips for vein endpoints (where wave is near 1).
        if wave > 0.85 and 0.05 < t < 0.95:
            lobe_tips_upper.append((u, -ry_here * 0.9))
            lobe_tips_lower.append((u, ry_here * 0.9))

    # Stitch into a closed polygon: upper edge (left→right) then lower edge
    # (right→left).
    raw_pts = upper + list(reversed(lower))
    # Rotate and translate into canvas space.
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    pts = [(cx + px * cos_r - py * sin_r, cy + px * sin_r + py * cos_r) for px, py in raw_pts]

    # Base + tip points for the midrib.
    base = (cx + (-rx) * cos_r, cy + (-rx) * sin_r)
    tip = (cx + (rx) * cos_r, cy + (rx) * sin_r)

    # Side veins — short segments from the midrib axis out to each lobe tip.
    veins: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for lx, ly in lobe_tips_upper + lobe_tips_lower:
        # Midrib anchor at the same u-coordinate.
        ax = lx
        ay = 0.0
        ax_r = cx + ax * cos_r - ay * sin_r
        ay_r = cy + ax * sin_r + ay * cos_r
        lx_r = cx + lx * cos_r - ly * sin_r
        ly_r = cy + lx * sin_r + ly * cos_r
        veins.append(((ax_r, ay_r), (lx_r, ly_r)))

    return pts, base, tip, veins


def _draw_leaf_filled(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    ink,
    rng: random.Random,
) -> None:
    """Solid lobed oak leaf with a white midrib + side veins down the long axis."""
    pts, base, tip, veins = _oak_leaf_polygon(cx, cy, size, rng)
    draw.polygon(pts, fill=ink)
    highlight = 255 if isinstance(ink, int) else (255, 255, 255)
    draw.line([base, tip], fill=highlight, width=SS)
    for a, b in veins:
        draw.line([a, b], fill=highlight, width=SS)
    # Tiny stem connecting the leaf base to the branch (the ``base`` point).
    sx = base[0] + (base[0] - tip[0]) * 0.12
    sy = base[1] + (base[1] - tip[1]) * 0.12
    draw.line([base, (sx, sy)], fill=ink, width=max(SS, int(size * 0.08)))


def _draw_leaf_outline(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    ink,
    rng: random.Random,
) -> None:
    """Outline-only lobed oak leaf with midrib + side veins — reads as a paler leaf."""
    pts, base, tip, veins = _oak_leaf_polygon(cx, cy, size, rng)
    draw.polygon(pts, outline=ink)
    draw.line([base, tip], fill=ink, width=SS)
    for a, b in veins:
        draw.line([a, b], fill=ink, width=max(1, SS - 1))
    # Stem.
    sx = base[0] + (base[0] - tip[0]) * 0.12
    sy = base[1] + (base[1] - tip[1]) * 0.12
    draw.line([base, (sx, sy)], fill=ink, width=SS)


def _draw_rain_overlay(
    draw: ImageDraw.ImageDraw,
    rng: random.Random,
    *,
    mode: str,
    heavy: bool = False,
) -> None:
    streak_fill = _grey(95 if heavy else 130, mode)
    # Particle counts scale with area to keep visual density constant.
    count = (140 if heavy else 80) * SS * SS
    for _ in range(count):
        x = rng.randint(_SPEC_X0 + 4 * SS, _SPEC_X1 - 4 * SS)
        y = rng.randint(_SPEC_Y0 + 8 * SS, _SPEC_Y1 - 8 * SS)
        length = rng.randint(5 * SS, 10 * SS)
        slant = rng.choice((-2 * SS, -SS))
        draw.line([(x, y), (x + slant, y + length)], fill=streak_fill, width=SS)


def _draw_snow_on_branches(
    draw: ImageDraw.ImageDraw,
    nodes: list[tuple[int, int]],
    trunk_top: tuple[int, int],
    trunk_bot: tuple[int, int],
    *,
    mode: str,
    rng: random.Random,
) -> None:
    """Little white caps along the top of every branch endpoint + ground snow."""
    snow_fill = _grey(245, mode) if mode == "L" else (255, 255, 255)
    edge_fill = _ink(mode)
    for nx, ny in nodes:
        cap_w = rng.randint(6 * SS, 12 * SS)
        cap_h = 3 * SS
        draw.ellipse(
            (nx - cap_w // 2, ny - cap_h, nx + cap_w // 2, ny + cap_h - SS),
            fill=snow_fill,
            outline=edge_fill,
        )
    ground_y = _SPEC_Y1 - 18 * SS
    pts = [(_SPEC_X0, ground_y)]
    x = _SPEC_X0
    while x <= _SPEC_X1:
        y = ground_y + rng.randint(-3 * SS, 3 * SS)
        pts.append((x, y))
        x += 12 * SS
    pts.append((_SPEC_X1, ground_y))
    pts.append((_SPEC_X1, _SPEC_Y1))
    pts.append((_SPEC_X0, _SPEC_Y1))
    draw.polygon(pts, fill=snow_fill, outline=edge_fill)


def _draw_frost_stipple(
    draw: ImageDraw.ImageDraw,
    nodes: list[tuple[int, int]],
    *,
    mode: str,
    rng: random.Random,
) -> None:
    frost_fill = _grey(220, mode)
    for nx, ny in nodes:
        for _ in range(14 * SS * SS):
            fx = nx + rng.randint(-22 * SS, 22 * SS)
            fy = ny + rng.randint(-22 * SS, 22 * SS)
            draw.point((fx, fy), fill=frost_fill)


def _stipple_fog(image: Image.Image, rng: random.Random) -> None:
    """Light, horizontal fog bands stippled across the specimen background."""
    mode = image.mode
    base_w = _SPEC_X1 - _SPEC_X0
    base_h = _SPEC_Y1 - _SPEC_Y0
    overlay = Image.new("L", (base_w, base_h), 248)
    od = ImageDraw.Draw(overlay)
    for i in range(7):
        y = int((i + 0.5) / 7 * base_h) + rng.randint(-3 * SS, 3 * SS)
        tone = 215 + rng.randint(-8, 8)
        od.rectangle((0, y, base_w, y + base_h // 14), fill=tone)
    if mode == "RGB":
        overlay = overlay.convert("RGB")
    image.paste(overlay, (_SPEC_X0, _SPEC_Y0))


# ---------------------------------------------------------------------------
# Callouts — leader lines + labels pointing at the specimen features
# ---------------------------------------------------------------------------


def _fmt_time(dt: datetime) -> str:
    """Compact am/pm time, lowercase."""
    if dt.minute == 0:
        s = dt.strftime("%-I%p")
    else:
        s = dt.strftime("%-I:%M%p")
    return s.lower().replace("am", "a").replace("pm", "p")


def _next_event_today(
    events: list[CalendarEvent], today: date, now: datetime
) -> CalendarEvent | None:
    """First timed event today that hasn't ended yet."""
    todays = events_for_day(events, today)
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    candidates: list[CalendarEvent] = []
    for e in todays:
        if e.is_all_day:
            continue
        end = e.end.replace(tzinfo=None) if e.end.tzinfo else e.end
        if end >= now_naive:
            candidates.append(e)
    if candidates:
        return candidates[0]
    if todays:
        return todays[0]
    return None


def _draw_callouts(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    feature_pts: dict[str, tuple[int, int]],
    style: ThemeStyle,
    ink,
    red,
    mode: str,
) -> None:
    """Four leader-line callouts pointing into the specimen frame.

    Label, key, and value all render in solid ink at sizes that survive
    Floyd-Steinberg quantization.  The thin between-row underline uses a
    near-black tone (40) so it dithers to a near-solid line rather than a
    mid-grey hash.
    """
    assert style.font_section_label is not None
    label_font = style.font_section_label(14 * SS)
    value_font = style.font_semibold(16 * SS)

    rows: list[tuple[str, str, str, str]] = []
    # 1) FIG. I — Event of the day.
    ev = _next_event_today(data.events, today, now)
    if ev is not None:
        if ev.is_all_day:
            time_part = "ALL DAY"
            summary = ev.summary
        else:
            time_part = _fmt_time(ev.start)
            summary = ev.summary
        rows.append(("FIG. I", "EVENT", f"{time_part}  ·  {summary}", "leaf_top"))
    else:
        rows.append(("FIG. I", "EVENT", "no events today", "leaf_top"))

    # 2) FIG. II — Moon phase.
    illum = moon_illumination(today)
    phase = moon_phase_name(today)
    rows.append(("FIG. II", "LUNA", f"{phase}  ·  {illum:.0f}%", "node_mid"))

    # 3) FIG. III — Sun rise/set.
    weather = data.weather
    if weather and (weather.sunrise or weather.sunset):
        rise = _fmt_time(weather.sunrise) if weather.sunrise else "—"
        setp = _fmt_time(weather.sunset) if weather.sunset else "—"
        rows.append(("FIG. III", "SOL", f"rise {rise}  ·  set {setp}", "branch_low"))
    else:
        rows.append(("FIG. III", "SOL", "rise —  ·  set —", "branch_low"))

    # 4) FIG. IV — Air / conditions.
    if weather:
        t = weather.current_temp
        cond = (weather.current_description or "").strip().capitalize()
        rows.append(("FIG. IV", "AER", f"{int(round(t))}°  ·  {cond}", "root"))
    else:
        rows.append(("FIG. IV", "AER", "awaiting data", "root"))

    # Vertical layout of the four callout rows inside the right column.
    row_h = (_BODY_BOTTOM - _BODY_TOP - 16 * SS) // 4
    figure_gutter = 78 * SS
    for i, (figure, key, value, anchor) in enumerate(rows):
        row_y0 = _BODY_TOP + 8 * SS + i * row_h
        row_cy = row_y0 + row_h // 2
        # Leader line from a feature point → bend → label start.
        feature = feature_pts.get(anchor, (_SPEC_X1 - 30 * SS, row_cy))
        bend_x = _CALLOUT_X0 - 18 * SS
        draw.line([feature, (bend_x, feature[1])], fill=red, width=SS)
        draw.line([(bend_x, feature[1]), (bend_x, row_cy)], fill=red, width=SS)
        draw.line([(bend_x, row_cy), (_CALLOUT_X0 - 4 * SS, row_cy)], fill=red, width=SS)
        # Anchor dot at the feature point.
        fx, fy = feature
        draw.ellipse((fx - 3 * SS, fy - 3 * SS, fx + 3 * SS, fy + 3 * SS), fill=red)
        # Figure label (small caps, red).
        draw.text((_CALLOUT_X0, row_y0 + 2 * SS), figure, font=label_font, fill=red)
        # Key (small caps).
        draw.text(
            (_CALLOUT_X0 + figure_gutter, row_y0 + 2 * SS),
            key,
            font=label_font,
            fill=ink,
        )
        # Value (body Playfair semibold for legibility).
        draw_text_truncated(
            draw,
            (_CALLOUT_X0, row_y0 + 24 * SS),
            value,
            value_font,
            _CALLOUT_W,
            fill=ink,
        )
        # Underline — near-black so it dithers to a near-solid line.
        rule_y = row_y0 + row_h - 4 * SS
        draw.line(
            [(_CALLOUT_X0, rule_y), (_CALLOUT_X0 + _CALLOUT_W, rule_y)],
            fill=_grey(40, mode),
            width=SS,
        )


# ---------------------------------------------------------------------------
# Footer — quote + author beneath a triple rule
# ---------------------------------------------------------------------------


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    today: date,
    now: datetime,
    *,
    style: ThemeStyle,
    quote_refresh: str,
    ink,
    red,
    mode: str,
) -> None:
    # Heavy + thin double rule.
    canvas_w = 800 * SS
    draw.line(
        [(_PAD_X, _FOOTER_RULE_Y), (canvas_w - _PAD_X, _FOOTER_RULE_Y)],
        fill=ink,
        width=2 * SS,
    )
    draw.line(
        [(_PAD_X, _FOOTER_RULE_Y + 5 * SS), (canvas_w - _PAD_X, _FOOTER_RULE_Y + 5 * SS)],
        fill=ink,
        width=SS,
    )

    # Quote in Playfair, larger so it carries the footer without crowding.
    quote = _quote_for_today(today, refresh=quote_refresh, now=now)
    quote_font = style.font_quote(17 * SS) if style.font_quote else style.font_regular(17 * SS)
    author_font = (
        style.font_quote_author(13 * SS)
        if style.font_quote_author
        else style.font_semibold(13 * SS)
    )
    quote_text = f"“{quote['text']}”"
    author_text = f"— {quote['author'].upper()}"
    quote_w = canvas_w - _PAD_X * 2
    lines = wrap_lines(quote_text, quote_font, quote_w)[:2]
    line_h = text_height(quote_font)
    line_spacing = 2 * SS
    block_h = line_h * len(lines) + line_spacing * max(0, len(lines) - 1)
    qy = _QUOTE_Y + 6 * SS
    draw_text_wrapped(
        draw,
        (_PAD_X, qy),
        quote_text,
        quote_font,
        quote_w,
        max_lines=2,
        line_spacing=line_spacing,
        fill=ink,
    )
    ab = draw.textbbox((0, 0), author_text, font=author_font)
    ax = canvas_w - _PAD_X - (ab[2] - ab[0]) - ab[0]
    ay = qy + block_h + 4 * SS
    draw.text((ax, ay), author_text, font=author_font, fill=red)


# ---------------------------------------------------------------------------
# Border ornaments — small corner glyphs framing the plate
# ---------------------------------------------------------------------------


def _draw_border_ornaments(draw: ImageDraw.ImageDraw, *, mode: str, red) -> None:
    """Tiny diamond marks at the four corners of the plate."""
    fill = red
    canvas_w = 800 * SS
    canvas_h = 480 * SS
    for cx, cy in (
        (10 * SS, 10 * SS),
        (canvas_w - 10 * SS, 10 * SS),
        (10 * SS, canvas_h - 10 * SS),
        (canvas_w - 10 * SS, canvas_h - 10 * SS),
    ):
        draw.polygon(
            [
                (cx, cy - 4 * SS),
                (cx + 4 * SS, cy),
                (cx, cy + 4 * SS),
                (cx - 4 * SS, cy),
            ],
            fill=fill,
        )
