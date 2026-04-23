"""D&D Fantasy theme — swords & sorcery aesthetic for the eInk dashboard.

Layout: left sidebar (220px) containing the arcane tower panels stacked vertically,
with the quest log (week view) dominating the right 580px.  A thick ornamental
double-frame border and runic diamond ornaments are drawn on top of all components
via ``ThemeLayout.overlay_fn``.

Visual style:
- Cinzel (Roman inscription caps) for all headers and section labels.
- Plus Jakarta Sans for body text (events, weather details) — legible at small sizes.
- Black canvas (inverted fg/bg) with white text and ornaments.
- Thick filled header with title flanked by drawn sword glyphs.
- Sidebar panels: "THE ORACLE'S OMEN", "THE FELLOWSHIP", "ANCIENT WISDOM".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.render.fonts import cinzel_bold, medium, regular, semibold
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

if TYPE_CHECKING:
    from PIL import ImageDraw


# ---------------------------------------------------------------------------
# Layout geometry
# ---------------------------------------------------------------------------

_CANVAS_W = 800
_CANVAS_H = 480

_HEADER_H = 50  # tall masthead for the fantasy title
_SIDEBAR_W = 240  # arcane tower on the left

_BODY_Y = _HEADER_H
_BODY_H = _CANVAS_H - _HEADER_H  # 430px

_QUEST_X = _SIDEBAR_W
_QUEST_W = _CANVAS_W - _SIDEBAR_W  # 585px

# Sidebar panels stacked vertically; heights must sum to _BODY_H
_WEATHER_H = 180  # oracle's omen — weather
_BIRTHDAY_H = 130  # the fellowship — birthdays
_INFO_H = _BODY_H - _WEATHER_H - _BIRTHDAY_H  # ancient wisdom — quote

# The ornamental double-frame uses an inner border at inset 6 and an outer
# border at inset 2.  Component regions are inset by one extra pixel so that
# solid-filled rectangles (inverted header, alert bars, month band, today
# column) never reach the frame band and visually overwrite the border lines.
_CI = 7  # content inset — one pixel inside the inner border (INNER=6)


# ---------------------------------------------------------------------------
# Ornamental drawing helpers
# ---------------------------------------------------------------------------


def _diamond(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill: int | tuple[int, int, int]
) -> None:
    """Draw a solid diamond (rotated square) ornament."""
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill)


def _corner_ornament(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    fill: int | tuple[int, int, int],
    contrast: int | tuple[int, int, int],
) -> None:
    """Draw a corner ornament: concentric diamond + inner dot in the contrasting colour."""
    _diamond(draw, cx, cy, 7, fill)
    _diamond(draw, cx, cy, 3, contrast)


def _draw_fantasy_overlay(
    draw: ImageDraw.ImageDraw,
    layout: ThemeLayout,
    style: ThemeStyle,
) -> None:
    """Overlay function: draws all D&D ornamental elements on top of components."""
    W = layout.canvas_w
    H = layout.canvas_h
    fg = style.fg  # WHITE (1) on dark canvas
    bg = style.bg  # BLACK (0)

    # ------------------------------------------------------------------
    # 1. Outer double-frame border
    # ------------------------------------------------------------------
    OUTER = 2  # outer border inset from canvas edge
    INNER = 6  # inner accent line inset

    # Clear the entire frame band to bg before drawing borders.  Component
    # fills (inverted header, alert columns, month band, today column) may
    # have painted white over the black gap between the two border lines,
    # making the double-frame effect invisible.  Resetting those strips here
    # ensures the gap is always bg (black) regardless of component content.
    draw.rectangle([OUTER, OUTER, W - OUTER - 1, INNER], fill=bg)  # top strip
    draw.rectangle([OUTER, H - INNER - 1, W - OUTER - 1, H - OUTER - 1], fill=bg)  # bottom
    draw.rectangle([OUTER, OUTER, INNER, H - OUTER - 1], fill=bg)  # left strip
    draw.rectangle([W - INNER - 1, OUTER, W - OUTER - 1, H - OUTER - 1], fill=bg)  # right

    draw.rectangle([OUTER, OUTER, W - OUTER - 1, H - OUTER - 1], outline=fg, width=2)
    draw.rectangle([INNER, INNER, W - INNER - 1, H - INNER - 1], outline=fg, width=1)

    # ------------------------------------------------------------------
    # 2. Corner ornaments (at inner-frame corners)
    # ------------------------------------------------------------------
    for cx, cy in [
        (INNER, INNER),
        (W - INNER - 1, INNER),
        (INNER, H - INNER - 1),
        (W - INNER - 1, H - INNER - 1),
    ]:
        _corner_ornament(draw, cx, cy, fg, bg)

    # ------------------------------------------------------------------
    # 3. Header bottom border — double rule with centre ornament
    # ------------------------------------------------------------------
    hdr_bottom = _HEADER_H - 1
    # Erase the default single line; replace with a decorative thick rule
    draw.rectangle([INNER + 1, hdr_bottom - 2, W - INNER - 2, hdr_bottom + 3], fill=bg)
    draw.line([(INNER + 1, hdr_bottom - 1), (W - INNER - 2, hdr_bottom - 1)], fill=fg, width=1)
    draw.line([(INNER + 1, hdr_bottom + 2), (W - INNER - 2, hdr_bottom + 2)], fill=fg, width=1)
    mid_x = W // 2
    _diamond(draw, mid_x, hdr_bottom, 5, fg)

    # ------------------------------------------------------------------
    # 4. Decorative diamond ticks centred on the top header border
    # ------------------------------------------------------------------
    # Small diamonds at the 1/4 and 3/4 horizontal positions of the header
    # bottom rule — purely ornamental, placed away from title and timestamp.
    hdr_mid_y = _HEADER_H // 2
    for tick_x in (W // 4, W * 3 // 4):
        _diamond(draw, tick_x, hdr_mid_y, 3, fg)

    # ------------------------------------------------------------------
    # 5. Vertical divider between sidebar and quest log
    # ------------------------------------------------------------------
    div_x = _SIDEBAR_W
    # Draw a triple-line divider: thick | thin | thin
    draw.line([(div_x, _HEADER_H), (div_x, H - INNER - 1)], fill=fg, width=2)
    draw.line([(div_x + 4, _HEADER_H + 8), (div_x + 4, H - INNER - 9)], fill=fg, width=1)

    # Diamond ornaments along the divider at 1/3, 1/2, 2/3 of body height
    for frac in (0.33, 0.5, 0.67):
        oy = int(_HEADER_H + _BODY_H * frac)
        # Small gap in the thin inner line around each ornament
        draw.line([(div_x + 4, oy - 6), (div_x + 4, oy + 6)], fill=bg, width=1)
        _diamond(draw, div_x + 2, oy, 5, fg)

    # ------------------------------------------------------------------
    # 6. Horizontal dividers within the sidebar
    # ------------------------------------------------------------------
    weather_bottom = _BODY_Y + _WEATHER_H
    birthday_bottom = weather_bottom + _BIRTHDAY_H

    for rule_y in (weather_bottom, birthday_bottom):
        # Double horizontal rule spanning sidebar width (minus frame inset)
        x_lo = INNER + 1
        x_hi = _SIDEBAR_W - 1
        draw.rectangle([x_lo, rule_y - 1, x_hi, rule_y + 3], fill=bg)
        draw.line([(x_lo, rule_y), (x_hi, rule_y)], fill=fg, width=1)
        draw.line([(x_lo, rule_y + 2), (x_hi, rule_y + 2)], fill=fg, width=1)
        # Diamond at centre
        csx = (x_lo + x_hi) // 2
        _diamond(draw, csx, rule_y + 1, 4, fg)

    # ------------------------------------------------------------------
    # 7. Small diamond tick-marks along canvas mid-edges for flair
    # ------------------------------------------------------------------
    # Top and bottom edge midpoints
    for mx, my in [
        (W // 2, INNER),
        (W // 2, H - INNER - 1),
        (INNER, H // 2),
        (W - INNER - 1, H // 2),
    ]:
        _diamond(draw, mx, my, 4, fg)


# ---------------------------------------------------------------------------
# Theme factory
# ---------------------------------------------------------------------------


def fantasy_theme() -> Theme:
    """Return the Fantasy theme — dark canvas, Cinzel headers, ornamental borders."""

    layout = ThemeLayout(
        canvas_w=_CANVAS_W,
        canvas_h=_CANVAS_H,
        # Inset all regions by _CI so solid-filled boxes end before the frame band.
        header=ComponentRegion(_CI, _CI, _CANVAS_W - 2 * _CI, _HEADER_H - _CI),
        # Week view — "quest log" on the right; inset from right canvas edge only
        week_view=ComponentRegion(_QUEST_X, _BODY_Y, _CANVAS_W - _QUEST_X - _CI, _BODY_H),
        # Sidebar panels stacked on the left (the "arcane tower"); inset from left edge
        weather=ComponentRegion(_CI, _BODY_Y, _SIDEBAR_W - _CI, _WEATHER_H),
        birthdays=ComponentRegion(_CI, _BODY_Y + _WEATHER_H, _SIDEBAR_W - _CI, _BIRTHDAY_H),
        info=ComponentRegion(_CI, _BODY_Y + _WEATHER_H + _BIRTHDAY_H, _SIDEBAR_W - _CI, _INFO_H),
        today_view=ComponentRegion(0, 0, 0, 0, visible=False),
        draw_order=["header", "weather", "birthdays", "info", "week_view"],
        overlay_fn=_draw_fantasy_overlay,
    )

    style = ThemeStyle(
        fg=1,  # WHITE on black canvas
        bg=0,  # BLACK background
        invert_header=True,  # filled black header bar (already black = canvas bg)
        invert_today_col=True,  # white-filled today column with black text
        invert_allday_bars=True,  # solid white bars for all-day events
        spacing_scale=1.0,
        label_font_size=10,
        label_font_weight="bold",
        # Cinzel Bold for large display text (day numbers, MARCH label, section headers).
        # Cinzel SemiBold for section label text (THE ORACLE'S OMEN etc.).
        # Plus Jakarta Sans for all event/body text — legible at small sizes in narrow columns.
        font_regular=regular,
        font_medium=medium,
        font_semibold=semibold,  # event titles stay in Plus Jakarta Sans
        font_bold=cinzel_bold,  # day numbers, MARCH, header title in Cinzel
        component_labels={
            "weather": "THE ORACLE'S OMEN",
            "birthdays": "THE FELLOWSHIP",
            "info": "ANCIENT WISDOM",
        },
    )

    return Theme(name="fantasy", style=style, layout=layout)
