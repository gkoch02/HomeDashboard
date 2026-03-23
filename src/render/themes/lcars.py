"""LCARS theme — Star Trek computer interface aesthetic for the eInk dashboard.

Layout: a thick vertical bar ("spine") on the left connects to a horizontal bar
at the top via a characteristic curved elbow sweep.  Section label pills jut out
to the right from the spine, separating stacked sidebar panels (weather, crew
manifest, info).  The week view occupies the main 600px area to the right.
Top and bottom elbows frame the display with rounded caps.

Visual style:
- Black canvas, white structural chrome (bars, caps, pills, elbow sweeps).
- DM Sans for all text — clean, geometric, screen-optimised.
- White body/event text; black-on-white text on pill labels.
- Inverted today column (white fill + black text).
- Section pill labels: "STELLAR CONDITIONS", "CREW MANIFEST", "STARFLEET QUERY".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

if TYPE_CHECKING:
    from PIL import ImageDraw


# ---------------------------------------------------------------------------
# Layout geometry
# ---------------------------------------------------------------------------

_CANVAS_W = 800
_CANVAS_H = 480

# Structural bar thicknesses
_HBAR_H = 18          # top / bottom horizontal bars
_VBAR_W = 24          # left vertical bar ("spine")

# Elbow caps (rounded end pieces at top-left and bottom-left)
_CAP_W = 130          # cap extends this far to the right
_TOP_CAP_H = 54       # total height of top cap area (includes hbar)
_BOT_CAP_H = 36       # total height of bottom cap area (includes hbar)
_OUTER_R = 20         # outer corner radius for caps
_INNER_R = 18         # inner sweep corner radius (the LCARS curve)

_BOT_ELBOW_Y = _CANVAS_H - _BOT_CAP_H   # 444

# Section label pills (jut right from the spine)
_PILL_X = _VBAR_W + 1    # 25 — flush with spine right edge
_PILL_RIGHT = 185         # right edge of pills
_PILL_H = 28              # pill height
_PILL_R = 4               # pill corner radius

# Main content area (right of sidebar)
_MAIN_X = 192             # week view left edge
_MAIN_W = _CANVAS_W - _MAIN_X - 4   # 604

# Header text area (in the gap between top bar and cap bottom, right of cap)
_HEADER_X = _CAP_W + 8    # 138
_HEADER_Y = _HBAR_H + 2   # 20
_HEADER_W = _CANVAS_W - _HEADER_X - 4   # 658
_HEADER_H = _TOP_CAP_H - _HBAR_H - 4    # 32

# Body area (between top and bottom elbows)
_BODY_Y = _TOP_CAP_H + 2      # 56
_BODY_BOTTOM = _BOT_ELBOW_Y - 2   # 442
# Available height: 442 - 56 = 386
# Fixed overhead: top_margin(4) + 3×pill(28) + 3×gap_after_pill(2)
#                 + 2×gap_between_sections(4) + bottom_margin(4) = 106
# Content: 386 - 106 = 280

_PILL_1_Y = _BODY_Y + 4       # 60
_CONT_1_Y = _PILL_1_Y + _PILL_H + 2   # 90
_CONT_1_H = 125               # ends at 215

_PILL_2_Y = _CONT_1_Y + _CONT_1_H + 4   # 219
_CONT_2_Y = _PILL_2_Y + _PILL_H + 2       # 249
_CONT_2_H = 90                # ends at 339

_PILL_3_Y = _CONT_2_Y + _CONT_2_H + 4   # 343
_CONT_3_Y = _PILL_3_Y + _PILL_H + 2       # 373
_CONT_3_H = 65                # ends at 438; bottom margin = 442 - 438 = 4 ✓

# Verification: 125 + 90 + 65 = 280 ✓

# Default pill label text (overridable via style.component_labels)
_DEFAULT_LABELS: dict[str, str] = {
    "weather": "STELLAR CONDITIONS",
    "birthdays": "CREW MANIFEST",
    "info": "STARFLEET QUERY",
}


# ---------------------------------------------------------------------------
# Overlay drawing
# ---------------------------------------------------------------------------

def _draw_lcars_overlay(
    draw: "ImageDraw.ImageDraw",
    layout: ThemeLayout,
    style: ThemeStyle,
) -> None:
    """Overlay: draws all LCARS chrome elements on top of component content."""
    W = layout.canvas_w
    H = layout.canvas_h
    fg = style.fg   # WHITE (1)
    bg = style.bg   # BLACK (0)

    # ==================================================================
    # TOP ELBOW — horizontal bar + cap + inner sweep
    # ==================================================================

    # Horizontal bar across the full width (rounded right end, square left end
    # since the cap covers the left portion).
    draw.rounded_rectangle(
        [0, 0, W - 6, _HBAR_H - 1], radius=_HBAR_H // 2, fill=fg,
    )
    draw.rectangle([0, 0, _HBAR_H, _HBAR_H - 1], fill=fg)  # square left end

    # Cap: plain rectangle — no rounding at the display left edge.
    # (rounded_rectangle at x=0 creates visible black notches at the corners.)
    draw.rectangle([0, 0, _CAP_W, _TOP_CAP_H - 1], fill=fg)

    # Black interior of the elbow (right of spine, below hbar, within cap bounds)
    draw.rectangle([_VBAR_W, _HBAR_H, _CAP_W, _TOP_CAP_H - 1], fill=bg)

    # LCARS sweep: white quarter-circle at the inner corner, curving from the
    # bottom of the hbar (y=HBAR_H) to the right of the spine (x=VBAR_W).
    # Pieslice centre: (VBAR_W + R, HBAR_H + R); top-left quadrant (180°→270°).
    _R = _INNER_R
    _cx = _VBAR_W + _R    # 42
    _cy = _HBAR_H + _R    # 36
    draw.pieslice([_cx - _R, _cy - _R, _cx + _R, _cy + _R],
                  start=180, end=270, fill=fg)

    # ==================================================================
    # BOTTOM ELBOW — mirror of the top
    # ==================================================================

    # Horizontal bar across the full width (rounded right end, square left end)
    draw.rounded_rectangle(
        [0, H - _HBAR_H, W - 6, H - 1], radius=_HBAR_H // 2, fill=fg,
    )
    draw.rectangle([0, H - _HBAR_H, _HBAR_H, H - 1], fill=fg)

    # Cap: plain rectangle — no rounding at the display left edge.
    draw.rectangle([0, _BOT_ELBOW_Y, _CAP_W, H - 1], fill=fg)

    # Black interior (right of spine, above hbar, strictly within cap bounds —
    # must NOT extend above _BOT_ELBOW_Y or it damages sidebar content).
    draw.rectangle([_VBAR_W, _BOT_ELBOW_Y, _CAP_W, H - _HBAR_H - 1], fill=bg)

    # LCARS sweep: white quarter-circle at the inner corner.
    # Pieslice centre: (VBAR_W + R, H - HBAR_H - R); bottom-left quadrant (90°→180°).
    _cx2 = _VBAR_W + _R         # 42
    _cy2 = H - _HBAR_H - _R     # 444
    draw.pieslice([_cx2 - _R, _cy2 - _R, _cx2 + _R, _cy2 + _R],
                  start=90, end=180, fill=fg)

    # ==================================================================
    # LEFT VERTICAL BAR (spine connecting the two elbows)
    # ==================================================================
    draw.rectangle(
        [0, _TOP_CAP_H, _VBAR_W - 1, _BOT_ELBOW_Y - 1], fill=fg,
    )

    # ==================================================================
    # SECTION LABEL PILLS (jut right from the spine, with label text)
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

        # White pill background
        draw.rounded_rectangle(
            [_PILL_X, pill_y, _PILL_RIGHT, pill_bottom],
            radius=_PILL_R, fill=fg,
        )

        # Black label text, centred on the pill
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
    """Return the LCARS theme — black canvas, white LCARS chrome, DM Sans fonts."""

    layout = ThemeLayout(
        canvas_w=_CANVAS_W,
        canvas_h=_CANVAS_H,
        # Header text area: right of cap, below top bar
        header=ComponentRegion(_HEADER_X, _HEADER_Y, _HEADER_W, _HEADER_H),
        # Week view: main content area right of sidebar
        week_view=ComponentRegion(
            _MAIN_X, _BODY_Y, _MAIN_W, _BODY_BOTTOM - _BODY_Y,
        ),
        # Sidebar panels: below their respective LCARS pill labels
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
        fg=1,                           # WHITE on black canvas
        bg=0,                           # BLACK background
        invert_header=False,            # header: white text on black
        invert_today_col=True,          # today column: white fill + black text
        invert_allday_bars=True,        # all-day event bars: solid white
        spacing_scale=0.9,              # slightly compact for narrow sidebar
        label_font_size=8,
        label_font_weight="bold",
        # DM Sans — geometric, screen-optimised (same family as minimalist theme)
        font_regular=dm_regular,
        font_medium=dm_medium,
        font_semibold=dm_semibold,
        font_bold=dm_bold,
        font_title=dm_bold,
        font_date_number=dm_bold,
        font_month_title=dm_bold,
        font_section_label=dm_bold,
        # Suppress the components' built-in section labels; the overlay pills
        # serve as the sole section identifiers.
        component_labels={"weather": " ", "birthdays": " ", "info": " "},
    )

    return Theme(name="lcars", style=style, layout=layout)
