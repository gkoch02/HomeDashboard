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
from src.render.components.info_panel import _quote_for_today
from src.render.moon import moon_illumination, moon_phase_name
from src.render.primitives import (
    draw_text_truncated,
    draw_text_wrapped,
    events_for_day,
    text_height,
    wrap_lines,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import INKY_RED, ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

_PAD_X = 28

_HEADER_TOP = 14
_HEADER_RULE_Y = 46
_SUBTITLE_Y = 60

_BODY_TOP = 118
_BODY_BOTTOM = 390
_FOOTER_RULE_Y = 394
_QUOTE_Y = 408

# Specimen area (the branch).  The right column carries the leader-line
# callouts, sized to fit four data rows.
_SPEC_X0 = 40
_SPEC_Y0 = _BODY_TOP + 6
_SPEC_X1 = 430
_SPEC_Y1 = _BODY_BOTTOM - 6

# Callout column anchors.
_CALLOUT_X0 = 470
_CALLOUT_W = 800 - _PAD_X - _CALLOUT_X0


# ---------------------------------------------------------------------------
# Mode-aware colour helpers
# ---------------------------------------------------------------------------


def _grey(v: int, mode: str) -> int | tuple[int, int, int]:
    return v if mode == "L" else (v, v, v)


def _ink(mode: str) -> int | tuple[int, int, int]:
    return 0 if mode == "L" else (0, 0, 0)


def _accent_red(mode: str) -> int | tuple[int, int, int]:
    """Plate accent — red on Inky, solid black on L mode so it stays crisp
    after Floyd-Steinberg quantization (mid-grey would dither into hash)."""
    if mode == "RGB":
        return INKY_SPECTRA6_PALETTE[INKY_RED]
    return 0


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


def _season(today: date) -> str:
    """Meteorological season for the northern hemisphere."""
    m = today.month
    if 3 <= m <= 5:
        return "spring"
    if 6 <= m <= 8:
        return "summer"
    if 9 <= m <= 11:
        return "autumn"
    return "winter"


def _weather_modifier(icon: str | None, temp: float | None) -> str:
    """Map current weather to a specimen-surface treatment."""
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
    if code == "01" and (temp is not None) and temp <= 32:
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
    modifier = _weather_modifier(icon, temp)

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
    plate_label_font = style.font_section_label(16)
    dateline_font = style.font_section_label(16)
    subtitle_font = style.font_section_label(20)
    day_font = style.font_section_label(14)

    # Left:  PLATE [Roman]
    plate_text = f"PLATE  {_plate_number(today)}"
    draw.text((_PAD_X, _HEADER_TOP), plate_text, font=plate_label_font, fill=ink)

    # Right:  date in small caps — YEAR (Roman) · MONTH
    year_roman = _roman(today.year)
    month_text = today.strftime("%B").upper()
    dateline_text = f"{year_roman}  ·  {month_text}"
    db = draw.textbbox((0, 0), dateline_text, font=dateline_font)
    draw.text(
        (800 - _PAD_X - (db[2] - db[0]) - db[0], _HEADER_TOP),
        dateline_text,
        font=dateline_font,
        fill=ink,
    )

    # Centre rule under the labels — a heavy + thin double rule.
    draw.line([(_PAD_X, _HEADER_RULE_Y), (800 - _PAD_X, _HEADER_RULE_Y)], fill=ink, width=2)
    draw.line(
        [(_PAD_X, _HEADER_RULE_Y + 5), (800 - _PAD_X, _HEADER_RULE_Y + 5)],
        fill=ink,
        width=1,
    )
    # A centred ornament between the two rules — bigger so it reads as a
    # printed mark, not noise.
    cx = 400
    glyph_font = style.font_section_label(18)
    glyph = "✦"
    gb = draw.textbbox((0, 0), glyph, font=glyph_font)
    pad = 16
    gx = cx - (gb[2] - gb[0]) // 2 - gb[0]
    gy = _HEADER_RULE_Y - 12
    draw.rectangle((cx - pad, _HEADER_RULE_Y - 4, cx + pad, _HEADER_RULE_Y + 8), fill=style.bg)
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
    draw.text((dx, _SUBTITLE_Y + 32), day_label, font=day_font, fill=ink)


# ---------------------------------------------------------------------------
# Specimen — the procedural branch
# ---------------------------------------------------------------------------

# Anatomical feature points on the specimen — leader lines from the right-
# column callouts end at these (x, y) anchors.  Tuned to land on the upper
# canopy, mid trunk, a lower branch, and the root crown of the procedural
# specimen for any season.
_FEATURE_POINTS = {
    "leaf_top": (315, _BODY_TOP + 50),
    "node_mid": (290, _BODY_TOP + 130),
    "branch_low": (220, _BODY_TOP + 195),
    "root": (200, _BODY_TOP + 245),
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
        draw.line([(x, y), (x + dx * 8, y + dy * 8)], fill=tick_fill, width=1)

    if modifier == "fog":
        _stipple_fog(image, rng)

    # Trunk — slightly curved vertical line, thicker toward the bottom.
    trunk_top = (_SPEC_X0 + 180, _SPEC_Y0 + 60)
    trunk_bot = (_SPEC_X0 + 160, _SPEC_Y1 - 40)
    _draw_trunk(draw, trunk_top, trunk_bot, mode=mode, rng=rng)

    # Branches — three on each side at varied heights/lengths.
    n_branches = 6
    nodes: list[tuple[int, int]] = []  # for leaves + buds
    for i in range(n_branches):
        t = (i + 1) / (n_branches + 1)
        bx = int(trunk_top[0] + (trunk_bot[0] - trunk_top[0]) * t)
        by = int(trunk_top[1] + (trunk_bot[1] - trunk_top[1]) * t)
        side = 1 if i % 2 == 0 else -1
        # Slight upward angle, varying length
        length = rng.randint(55, 95)
        angle_deg = rng.uniform(-65, -25) if side == 1 else rng.uniform(-155, -115)
        end_x = int(bx + length * math.cos(math.radians(angle_deg)))
        end_y = int(by + length * math.sin(math.radians(angle_deg)))
        _draw_branch(draw, (bx, by), (end_x, end_y), mode=mode)
        nodes.append((end_x, end_y))
        # Add a sub-branch occasionally for visual richness.
        if rng.random() < 0.5:
            sub_len = rng.randint(20, 35)
            sub_angle = math.radians(angle_deg + rng.uniform(-30, 30))
            sx = int(end_x + sub_len * math.cos(sub_angle))
            sy = int(end_y + sub_len * math.sin(sub_angle))
            _draw_branch(draw, (end_x, end_y), (sx, sy), mode=mode, thin=True)
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
    n_segs = 18
    fill = _ink(mode)
    for i in range(n_segs):
        t0 = i / n_segs
        t1 = (i + 1) / n_segs
        x0 = top[0] + (bot[0] - top[0]) * t0 + math.sin(t0 * math.pi * 1.5) * 4
        y0 = top[1] + (bot[1] - top[1]) * t0
        x1 = top[0] + (bot[0] - top[0]) * t1 + math.sin(t1 * math.pi * 1.5) * 4
        y1 = top[1] + (bot[1] - top[1]) * t1
        # Trunk thickness grows from top to bottom.
        w0 = 5 + int(11 * t0)
        w1 = 5 + int(11 * t1)
        poly = [
            (x0 - w0 / 2, y0),
            (x0 + w0 / 2, y0),
            (x1 + w1 / 2, y1),
            (x1 - w1 / 2, y1),
        ]
        draw.polygon(poly, fill=fill)
    # Right-hand highlight strokes — small white hatches that suggest a
    # rounded trunk surface in classic engraving style.
    highlight_fill = _grey(220, mode)
    for i in range(22):
        t = i / 22
        cx = top[0] + (bot[0] - top[0]) * t + math.sin(t * math.pi * 1.5) * 4
        cy = top[1] + (bot[1] - top[1]) * t
        w = 5 + int(11 * t)
        # Stagger position toward the right limb of the trunk.
        sx = cx + (w / 2) - 2 - rng.random() * 2
        if rng.random() < 0.55:
            draw.line(
                [(sx - 2, cy - 1), (sx, cy + 1)],
                fill=highlight_fill,
                width=1,
            )


def _draw_branch(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    mode: str,
    thin: bool = False,
) -> None:
    """Curved branch from *start* to *end* as a thinning polyline."""
    n = 12
    segs: list[tuple[int, int]] = []
    for i in range(n + 1):
        t = i / n
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        # Mild upward arc.
        arc = -math.sin(t * math.pi) * 8 * (1 - t * 0.4)
        segs.append((int(x), int(y + arc)))
    base_w = 1 if thin else 3
    for i in range(len(segs) - 1):
        t = i / max(1, len(segs) - 2)
        w = max(1, base_w - int(t * 2))
        draw.line([segs[i], segs[i + 1]], fill=_ink(mode), width=w)


def _draw_roots(
    draw: ImageDraw.ImageDraw,
    trunk_bot: tuple[int, int],
    *,
    mode: str,
    rng: random.Random,
) -> None:
    """Three curving roots spreading from the base."""
    for i, side in enumerate((-1, 0, 1)):
        angle = math.radians(90 + side * 60)
        length = rng.randint(40, 70)
        n = 10
        prev = trunk_bot
        for j in range(1, n + 1):
            t = j / n
            x = trunk_bot[0] + length * t * math.cos(angle)
            # Add downward arc.
            y = trunk_bot[1] + length * t * math.sin(angle) + (1 - (1 - t) ** 2) * 8
            now = (int(x), int(y))
            w = max(1, 3 - int(t * 2))
            draw.line([prev, now], fill=_ink(mode), width=w)
            prev = now


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
        size_range = (6, 9)
        outline_only = True
    elif season == "spring":
        count_per_node = 4
        size_range = (7, 10)
        outline_only = False  # mix of filled and outlined for fresh look
    elif season == "summer":
        count_per_node = 8
        size_range = (8, 13)
        outline_only = False
    else:  # autumn
        count_per_node = 5
        size_range = (7, 12)
        outline_only = False

    draw = ImageDraw.Draw(image)
    mode = image.mode
    ink = _ink(mode)
    # Two tones for the leaves — solid black silhouettes plus a lighter
    # outline-only treatment for visual depth (some leaves "in front", others
    # "behind").
    for nx, ny in nodes:
        for i in range(count_per_node):
            ox = rng.randint(-26, 26)
            oy = rng.randint(-24, 14)
            size = rng.randint(*size_range)
            if outline_only or (i % 3 == 2):
                _draw_leaf_outline(draw, nx + ox, ny + oy, size, ink, rng)
            else:
                _draw_leaf_filled(draw, nx + ox, ny + oy, size, ink, rng)

    # Spring: add a sprinkle of buds (tiny circles) hugging the branches.
    if season == "spring":
        for nx, ny in nodes:
            for _ in range(3):
                ox = rng.randint(-10, 10)
                oy = rng.randint(-10, 10)
                draw.ellipse(
                    (nx + ox - 2, ny + oy - 2, nx + ox + 2, ny + oy + 2),
                    fill=ink,
                )

    # Autumn: scatter a few fallen leaves under the canopy.
    if season == "autumn":
        for _ in range(10):
            fx = rng.randint(_SPEC_X0 + 20, _SPEC_X1 - 20)
            fy = rng.randint(_SPEC_Y1 - 60, _SPEC_Y1 - 14)
            size = rng.randint(6, 10)
            _draw_leaf_outline(draw, fx, fy, size, ink, rng)


def _leaf_polygon(
    cx: int, cy: int, size: int, rng: random.Random
) -> tuple[list[tuple[float, float]], tuple[float, float], tuple[float, float]]:
    """Build a rotated almond-shaped leaf polygon plus its two vein endpoints."""
    rot = rng.uniform(0, math.pi)
    n = 18
    pts: list[tuple[float, float]] = []
    rx = size
    ry = max(2, size // 2)
    for i in range(n):
        a = i / n * 2 * math.pi
        px = rx * math.cos(a)
        py = ry * math.sin(a)
        rxp = px * math.cos(rot) - py * math.sin(rot)
        ryp = px * math.sin(rot) + py * math.cos(rot)
        pts.append((cx + rxp, cy + ryp))
    vx0 = cx - rx * math.cos(rot)
    vy0 = cy - rx * math.sin(rot)
    vx1 = cx + rx * math.cos(rot)
    vy1 = cy + rx * math.sin(rot)
    return pts, (vx0, vy0), (vx1, vy1)


def _draw_leaf_filled(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    ink,
    rng: random.Random,
) -> None:
    """Solid black almond leaf with a thin white vein down the long axis."""
    pts, v0, v1 = _leaf_polygon(cx, cy, size, rng)
    draw.polygon(pts, fill=ink)
    # Vein: a thin highlight inside the dark leaf.
    draw.line([v0, v1], fill=(255 if isinstance(ink, int) else (255, 255, 255)), width=1)


def _draw_leaf_outline(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    ink,
    rng: random.Random,
) -> None:
    """Outlined almond leaf with a central vein — reads as a paler 'background' leaf."""
    pts, v0, v1 = _leaf_polygon(cx, cy, size, rng)
    draw.polygon(pts, outline=ink)
    draw.line([v0, v1], fill=ink, width=1)


def _draw_rain_overlay(
    draw: ImageDraw.ImageDraw,
    rng: random.Random,
    *,
    mode: str,
    heavy: bool = False,
) -> None:
    streak_fill = _grey(95 if heavy else 130, mode)
    count = 140 if heavy else 80
    for _ in range(count):
        x = rng.randint(_SPEC_X0 + 4, _SPEC_X1 - 4)
        y = rng.randint(_SPEC_Y0 + 8, _SPEC_Y1 - 8)
        length = rng.randint(5, 10)
        slant = rng.choice((-2, -1))
        draw.line([(x, y), (x + slant, y + length)], fill=streak_fill, width=1)


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
        cap_w = rng.randint(6, 12)
        cap_h = 3
        draw.ellipse(
            (nx - cap_w // 2, ny - cap_h, nx + cap_w // 2, ny + cap_h - 1),
            fill=snow_fill,
            outline=edge_fill,
        )
    # Ground snow line — a wavy band along the bottom of the specimen frame.
    ground_y = _SPEC_Y1 - 18
    pts = [(_SPEC_X0, ground_y)]
    x = _SPEC_X0
    while x <= _SPEC_X1:
        y = ground_y + rng.randint(-3, 3)
        pts.append((x, y))
        x += 12
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
        for _ in range(14):
            fx = nx + rng.randint(-22, 22)
            fy = ny + rng.randint(-22, 22)
            draw.point((fx, fy), fill=frost_fill)


def _stipple_fog(image: Image.Image, rng: random.Random) -> None:
    """Light, horizontal fog bands stippled across the specimen background."""
    mode = image.mode
    base_w = _SPEC_X1 - _SPEC_X0
    base_h = _SPEC_Y1 - _SPEC_Y0
    overlay = Image.new("L", (base_w, base_h), 248)
    od = ImageDraw.Draw(overlay)
    for i in range(7):
        y = int((i + 0.5) / 7 * base_h) + rng.randint(-3, 3)
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
    label_font = style.font_section_label(14)
    value_font = style.font_semibold(16) if style.font_semibold else style.font_regular(16)

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
    row_h = (_BODY_BOTTOM - _BODY_TOP - 16) // 4
    figure_gutter = 78  # space reserved for "FIG. I" before the KEY column
    for i, (figure, key, value, anchor) in enumerate(rows):
        row_y0 = _BODY_TOP + 8 + i * row_h
        row_cy = row_y0 + row_h // 2
        # Leader line from a feature point → bend → label start.
        feature = feature_pts.get(anchor, (_SPEC_X1 - 30, row_cy))
        bend_x = _CALLOUT_X0 - 18
        draw.line([feature, (bend_x, feature[1])], fill=red, width=1)
        draw.line([(bend_x, feature[1]), (bend_x, row_cy)], fill=red, width=1)
        draw.line([(bend_x, row_cy), (_CALLOUT_X0 - 4, row_cy)], fill=red, width=1)
        # Anchor dot at the feature point.
        fx, fy = feature
        draw.ellipse((fx - 3, fy - 3, fx + 3, fy + 3), fill=red)
        # Figure label (small caps, red).
        draw.text((_CALLOUT_X0, row_y0 + 2), figure, font=label_font, fill=red)
        # Key (small caps).
        draw.text(
            (_CALLOUT_X0 + figure_gutter, row_y0 + 2),
            key,
            font=label_font,
            fill=ink,
        )
        # Value (body Playfair semibold for legibility).
        draw_text_truncated(
            draw,
            (_CALLOUT_X0, row_y0 + 24),
            value,
            value_font,
            _CALLOUT_W,
            fill=ink,
        )
        # Underline — near-black so it dithers to a near-solid line.
        rule_y = row_y0 + row_h - 4
        draw.line(
            [(_CALLOUT_X0, rule_y), (_CALLOUT_X0 + _CALLOUT_W, rule_y)],
            fill=_grey(40, mode),
            width=1,
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
    draw.line(
        [(_PAD_X, _FOOTER_RULE_Y), (800 - _PAD_X, _FOOTER_RULE_Y)],
        fill=ink,
        width=2,
    )
    draw.line(
        [(_PAD_X, _FOOTER_RULE_Y + 5), (800 - _PAD_X, _FOOTER_RULE_Y + 5)],
        fill=ink,
        width=1,
    )

    # Quote in Playfair, larger so it carries the footer without crowding.
    quote = _quote_for_today(today, refresh=quote_refresh, now=now)
    quote_font = style.font_quote(17) if style.font_quote else style.font_regular(17)
    author_font = (
        style.font_quote_author(13) if style.font_quote_author else style.font_semibold(13)
    )
    quote_text = f"“{quote['text']}”"
    author_text = f"— {quote['author'].upper()}"
    quote_w = 800 - _PAD_X * 2
    lines = wrap_lines(quote_text, quote_font, quote_w)[:2]
    line_h = text_height(quote_font)
    line_spacing = 2
    block_h = line_h * len(lines) + line_spacing * max(0, len(lines) - 1)
    qy = _QUOTE_Y + 6
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
    ax = 800 - _PAD_X - (ab[2] - ab[0]) - ab[0]
    ay = qy + block_h + 4
    draw.text((ax, ay), author_text, font=author_font, fill=red)


# ---------------------------------------------------------------------------
# Border ornaments — small corner glyphs framing the plate
# ---------------------------------------------------------------------------


def _draw_border_ornaments(draw: ImageDraw.ImageDraw, *, mode: str, red) -> None:
    """Tiny diamond marks at the four corners."""
    fill = red
    for cx, cy in ((10, 10), (790, 10), (10, 470), (790, 470)):
        draw.polygon(
            [(cx, cy - 4), (cx + 4, cy), (cx, cy + 4), (cx - 4, cy)],
            fill=fill,
        )
