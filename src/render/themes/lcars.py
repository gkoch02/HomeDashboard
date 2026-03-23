"""LCARS theme — Star Trek computer interface aesthetic for the eInk dashboard.

Canonical LCARS proportions (per Memory Alpha / R lcars package):
  - Horizontal bars:  30 px tall
  - Vertical sidebar: 150 px wide (spine: 36 px, content to 190 px)
  - Inner elbow radius (ri): bar_height / 2 ≈ 15–20 px
  - Outer elbow radius (ro): sidebar_width / 2 ≈ 75 px
    (on a full-screen canvas the outer edge is flush with the display edge,
     so only the inner sweep is visible)

Layout: a 36 px structural spine bar runs the full left edge, flanked top
and bottom by large elbow caps.  Three bold 36 px pill labels jut right from
the spine (STELLAR CONDITIONS / CREW MANIFEST / STARFLEET QUERY), separating
stacked sidebar panels.  The week view fills the right 600 px.  The header
title lives in the open space inside the top elbow cap.

Decorative LCARS accents: small rectangular notch blocks on the top and
bottom bars give the characteristic "segmented bar" look.

Visual style: black canvas, white chrome (bars, caps, pills), black-on-white
pill text, white body text.  DM Sans throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

if TYPE_CHECKING:
    from PIL import ImageDraw


# ---------------------------------------------------------------------------
# Layout geometry  (all measurements in pixels)
# ---------------------------------------------------------------------------

_CANVAS_W = 800
_CANVAS_H = 480

# ── Horizontal bars (canonical LCARS: 30 px) ──────────────────────────────
_HBAR_H = 30

# ── Structural spine (vertical bar on the left) ───────────────────────────
_VBAR_W = 36          # wider than before — more dominant chrome

# ── Elbow caps ────────────────────────────────────────────────────────────
# The cap width should cover the full sidebar visual area.  Canonical LCARS
# sidebar ≈ 150 px; we go a bit wider to leave room for pill content.
_CAP_W = 160          # width of the elbow cap block
_TOP_CAP_H = 80       # total height of top elbow (bar 30 + cap body 50)
_BOT_CAP_H = 44       # total height of bottom elbow (bar 30 + cap body 14)

# Inner sweep radius  (canonical: bar_height / 2 ≈ 15 px; we use 20 for
# better visibility on the small 800×480 canvas)
_INNER_R = 20

_BOT_ELBOW_Y = _CANVAS_H - _BOT_CAP_H   # 436

# ── Section pills ─────────────────────────────────────────────────────────
_PILL_X = _VBAR_W + 2     # 38  — flush with spine + 2 px gap
_PILL_RIGHT = 190          # right edge of pills / sidebar content
_PILL_H = 36               # taller pills for better readability
_PILL_R = 6                # corner radius

# ── Main content (week view) ──────────────────────────────────────────────
_MAIN_X = 196              # starts 6 px right of pill edge
_MAIN_W = _CANVAS_W - _MAIN_X - 4   # 600

# ── Header text area (inside top elbow, right of cap) ─────────────────────
_HEADER_X = _CAP_W + 4    # 164
_HEADER_Y = _HBAR_H + 2   # 32
_HEADER_W = _CANVAS_W - _HEADER_X - 4   # 632
_HEADER_H = _TOP_CAP_H - _HBAR_H - 4    # 46

# ── Body (between top and bottom elbows) ──────────────────────────────────
_BODY_Y = _TOP_CAP_H + 2        # 82
_BODY_BOTTOM = _BOT_ELBOW_Y - 2  # 434
# Available height: 434 - 82 = 352

# Fixed overhead: top_margin(4) + 3×(pill+gap)(38) + 2×between(4) + bottom(4)
#   = 4 + 3×38 + 8 + 4 = 130
# Remaining for content: 352 - 130 = 222
# Distribution: weather 96, birthdays 70, info 56  → 222 ✓

_PILL_1_Y = _BODY_Y + 4                        # 86
_CONT_1_Y = _PILL_1_Y + _PILL_H + 2            # 124
_CONT_1_H = 96                                  # ends 220

_PILL_2_Y = _CONT_1_Y + _CONT_1_H + 4          # 224
_CONT_2_Y = _PILL_2_Y + _PILL_H + 2            # 262
_CONT_2_H = 70                                  # ends 332

_PILL_3_Y = _CONT_2_Y + _CONT_2_H + 4          # 336
_CONT_3_Y = _PILL_3_Y + _PILL_H + 2            # 374
_CONT_3_H = 56                                  # ends 430
# Bottom margin: 434 - 430 = 4 ✓   Content sum: 96+70+56 = 222 ✓

# ── Decorative bar accent blocks (small notches in the horizontal bars) ───
# These give the characteristic LCARS segmented-bar look.
_ACCENT_BLOCKS = [
    # (x_left, width)  — placed near the right end of the bars
    (_CANVAS_W - 140, 28),
    (_CANVAS_W - 104, 28),
    (_CANVAS_W - 68, 28),
]
_ACCENT_INSET = 5   # vertical inset from bar top/bottom edge

# ── Default pill label text ───────────────────────────────────────────────
_DEFAULT_LABELS: dict[str, str] = {
    "weather":   "STELLAR CONDITIONS",
    "birthdays": "CREW MANIFEST",
    "info":      "STARFLEET QUERY",
}


# ---------------------------------------------------------------------------
# Overlay drawing
# ---------------------------------------------------------------------------

def _draw_lcars_overlay(
    draw: "ImageDraw.ImageDraw",
    layout: ThemeLayout,
    style: ThemeStyle,
) -> None:
    """Draw all LCARS chrome on top of rendered component content."""
    W = layout.canvas_w
    H = layout.canvas_h
    fg = style.fg   # WHITE (1)
    bg = style.bg   # BLACK (0)

    # ==================================================================
    # TOP ELBOW
    # Full-width horizontal bar + large elbow cap + inner sweep
    # ==================================================================

    # Horizontal bar: full width, rounded right pill end, square left end.
    draw.rounded_rectangle(
        [0, 0, W - 6, _HBAR_H - 1], radius=_HBAR_H // 2, fill=fg,
    )
    draw.rectangle([0, 0, _HBAR_H, _HBAR_H - 1], fill=fg)   # square left end

    # Elbow cap: plain rectangle flush to the display edges (no rounding
    # at x=0 — rounding there would leave black notches at the canvas corner).
    draw.rectangle([0, 0, _CAP_W, _TOP_CAP_H - 1], fill=fg)

    # Black interior of the cap (right of spine, below bar).
    draw.rectangle([_VBAR_W, _HBAR_H, _CAP_W, _TOP_CAP_H - 1], fill=bg)

    # Inner sweep: white quarter-circle at the corner (VBAR_W, HBAR_H).
    # Canonical LCARS inner radius = bar_height / 2; we use _INNER_R = 20.
    # Pieslice centre: (_VBAR_W + R, _HBAR_H + R); top-left quadrant 180°→270°.
    _R = _INNER_R
    _cx = _VBAR_W + _R    # 56
    _cy = _HBAR_H + _R    # 50
    draw.pieslice(
        [_cx - _R, _cy - _R, _cx + _R, _cy + _R],
        start=180, end=270, fill=fg,
    )

    # ==================================================================
    # BOTTOM ELBOW  (mirror of top)
    # ==================================================================

    draw.rounded_rectangle(
        [0, H - _HBAR_H, W - 6, H - 1], radius=_HBAR_H // 2, fill=fg,
    )
    draw.rectangle([0, H - _HBAR_H, _HBAR_H, H - 1], fill=fg)

    draw.rectangle([0, _BOT_ELBOW_Y, _CAP_W, H - 1], fill=fg)

    # Black interior — strictly within cap bounds, never above _BOT_ELBOW_Y.
    draw.rectangle([_VBAR_W, _BOT_ELBOW_Y, _CAP_W, H - _HBAR_H - 1], fill=bg)

    # Inner sweep: bottom-left quadrant 90°→180°.
    _cx2 = _VBAR_W + _R          # 56
    _cy2 = H - _HBAR_H - _R     # 430
    draw.pieslice(
        [_cx2 - _R, _cy2 - _R, _cx2 + _R, _cy2 + _R],
        start=90, end=180, fill=fg,
    )

    # ==================================================================
    # LEFT SPINE  (connects top and bottom elbow caps)
    # ==================================================================
    draw.rectangle(
        [0, _TOP_CAP_H, _VBAR_W - 1, _BOT_ELBOW_Y - 1], fill=fg,
    )

    # ==================================================================
    # DECORATIVE ACCENT BLOCKS on top and bottom bars
    # Small black notch rectangles that give the LCARS segmented-bar look.
    # ==================================================================
    for (bx, bw) in _ACCENT_BLOCKS:
        # Top bar notches
        draw.rectangle(
            [bx, _ACCENT_INSET, bx + bw - 1, _HBAR_H - _ACCENT_INSET - 1],
            fill=bg,
        )
        # Bottom bar notches
        draw.rectangle(
            [bx, H - _HBAR_H + _ACCENT_INSET,
             bx + bw - 1, H - _ACCENT_INSET - 1],
            fill=bg,
        )

    # ==================================================================
    # SECTION LABEL PILLS
    # ==================================================================
    label_font = style.font_bold(11)
    pill_specs = [
        (_PILL_1_Y, "weather"),
        (_PILL_2_Y, "birthdays"),
        (_PILL_3_Y, "info"),
    ]
    for pill_y, key in pill_specs:
        label = style.component_labels.get(key) or _DEFAULT_LABELS[key]
        pill_bottom = pill_y + _PILL_H - 1

        draw.rounded_rectangle(
            [_PILL_X, pill_y, _PILL_RIGHT, pill_bottom],
            radius=_PILL_R, fill=fg,
        )

        bbox = draw.textbbox((0, 0), label, font=label_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        text_x = _PILL_X + (_PILL_RIGHT - _PILL_X - text_w) // 2
        text_y = pill_y + (_PILL_H - text_h) // 2 - bbox[1]
        draw.text((text_x, text_y), label, font=label_font, fill=bg)


# ---------------------------------------------------------------------------
# Theme factory
# ---------------------------------------------------------------------------

def lcars_theme() -> Theme:
    """Return the LCARS theme — black canvas, white chrome, DM Sans fonts."""

    layout = ThemeLayout(
        canvas_w=_CANVAS_W,
        canvas_h=_CANVAS_H,
        # Header: inside the top elbow cap, right of the cap block
        header=ComponentRegion(_HEADER_X, _HEADER_Y, _HEADER_W, _HEADER_H),
        # Week view: main content area to the right of the sidebar
        week_view=ComponentRegion(
            _MAIN_X, _BODY_Y, _MAIN_W, _BODY_BOTTOM - _BODY_Y,
        ),
        # Sidebar panels: below their respective pill labels
        weather=ComponentRegion(
            _PILL_X, _CONT_1_Y, _PILL_RIGHT - _PILL_X, _CONT_1_H,
        ),
        birthdays=ComponentRegion(
            _PILL_X, _CONT_2_Y, _PILL_RIGHT - _PILL_X, _CONT_2_H,
        ),
        info=ComponentRegion(
            _PILL_X, _CONT_3_Y, _PILL_RIGHT - _PILL_X, _CONT_3_H,
        ),
        today_view=ComponentRegion(0, 0, 0, 0, visible=False),
        draw_order=["header", "weather", "birthdays", "info", "week_view"],
        overlay_fn=_draw_lcars_overlay,
    )

    style = ThemeStyle(
        fg=1,
        bg=0,
        invert_header=False,
        invert_today_col=True,
        invert_allday_bars=True,
        spacing_scale=0.9,
        label_font_size=8,
        label_font_weight="bold",
        font_regular=dm_regular,
        font_medium=dm_medium,
        font_semibold=dm_semibold,
        font_bold=dm_bold,
        font_title=dm_bold,
        font_date_number=dm_bold,
        font_month_title=dm_bold,
        font_section_label=dm_bold,
        # Pills in the overlay are the sole section identifiers.
        component_labels={"weather": " ", "birthdays": " ", "info": " "},
    )

    return Theme(name="lcars", style=style, layout=layout)
