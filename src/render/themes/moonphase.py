"""Moonphase theme — fairy/fantasy night-sky aesthetic.

Full-canvas theme displaying the current moon phase as a large central glyph
flanked by 3 days on each side.  Dark canvas (white-on-black) for a celestial
night-sky feel.  Whimsical vine border with leaf buds, corner flourishes,
and scattered stars drawn via the overlay function.

Paired with ``moonphase_invert`` for a light parchment variant.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from src.render.fonts import (
    cinzel_bold,
    playfair_medium,
    playfair_regular,
    regular,
    semibold,
)
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

if TYPE_CHECKING:
    from PIL import ImageDraw


# ---------------------------------------------------------------------------
# Overlay: whimsical vine border, stars, and corner flourishes
# ---------------------------------------------------------------------------

_BORDER_INSET = 8  # distance from canvas edge to vine border
_INNER_INSET = 10  # inner accent line


def _leaf_bud(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    direction: str,
    fill: int | tuple[int, int, int],
) -> None:
    """Draw a small 3px triangular leaf bud pointing outward."""
    if direction == "up":
        draw.polygon([(x, y - 3), (x - 2, y), (x + 2, y)], fill=fill)
    elif direction == "down":
        draw.polygon([(x, y + 3), (x - 2, y), (x + 2, y)], fill=fill)
    elif direction == "left":
        draw.polygon([(x - 3, y), (x, y - 2), (x, y + 2)], fill=fill)
    elif direction == "right":
        draw.polygon([(x + 3, y), (x, y - 2), (x, y + 2)], fill=fill)


def _small_star(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    fill: int | tuple[int, int, int],
) -> None:
    """Draw a small cross-shaped star."""
    draw.line([(cx - size, cy), (cx + size, cy)], fill=fill, width=1)
    draw.line([(cx, cy - size), (cx, cy + size)], fill=fill, width=1)
    if size >= 2:
        # Diagonal arms (smaller)
        s = size - 1
        draw.point((cx - s, cy - s), fill=fill)
        draw.point((cx + s, cy - s), fill=fill)
        draw.point((cx - s, cy + s), fill=fill)
        draw.point((cx + s, cy + s), fill=fill)


def _corner_flourish(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    quadrant: int,
    fill: int | tuple[int, int, int],
) -> None:
    """Draw a small floral arc flourish at a corner.

    *quadrant*: 0=top-left, 1=top-right, 2=bottom-right, 3=bottom-left.
    """
    r = 12
    # Draw concentric quarter-arcs
    for radius in (r, r - 4, r - 8):
        if radius < 2:
            continue
        # Compute arc points
        steps = max(8, radius * 2)
        # Angle range per quadrant
        start_angle = quadrant * 90
        points = []
        for i in range(steps + 1):
            angle = math.radians(start_angle + 90 * i / steps)
            px = cx + int(radius * math.cos(angle))
            py = cy + int(radius * math.sin(angle))
            points.append((px, py))
        if len(points) >= 2:
            draw.line(points, fill=fill, width=1)

    # Central dot
    draw.point((cx, cy), fill=fill)


def _draw_moonphase_overlay(
    draw: ImageDraw.ImageDraw,
    layout: ThemeLayout,
    style: ThemeStyle,
) -> None:
    """Overlay: vine border, corner flourishes, and star scatter."""
    W = layout.canvas_w
    H = layout.canvas_h
    fg = style.fg
    B = _BORDER_INSET

    # ------------------------------------------------------------------
    # 1. Vine border — single-pixel rectangle with leaf buds
    # ------------------------------------------------------------------
    draw.rectangle([B, B, W - B - 1, H - B - 1], outline=fg, width=1)

    # Leaf buds along top edge
    for x in range(B + 30, W - B - 30, 55):
        _leaf_bud(draw, x, B, "up", fg)

    # Leaf buds along bottom edge
    for x in range(B + 45, W - B - 30, 55):
        _leaf_bud(draw, x, H - B - 1, "down", fg)

    # Leaf buds along left edge
    for y in range(B + 35, H - B - 30, 50):
        _leaf_bud(draw, B, y, "left", fg)

    # Leaf buds along right edge
    for y in range(B + 45, H - B - 30, 50):
        _leaf_bud(draw, W - B - 1, y, "right", fg)

    # ------------------------------------------------------------------
    # 2. Corner flourishes
    # ------------------------------------------------------------------
    margin = B + 3
    _corner_flourish(draw, margin, margin, 2, fg)  # top-left
    _corner_flourish(draw, W - margin - 1, margin, 3, fg)  # top-right
    _corner_flourish(draw, W - margin - 1, H - margin - 1, 0, fg)  # bot-right
    _corner_flourish(draw, margin, H - margin - 1, 1, fg)  # bot-left

    # ------------------------------------------------------------------
    # 3. Star scatter in upper corners
    # ------------------------------------------------------------------
    # Deterministic positions using simple arithmetic
    star_positions = [
        (28, 24, 2),
        (65, 18, 1),
        (42, 42, 1),
        (W - 30, 22, 2),
        (W - 62, 19, 1),
        (W - 45, 38, 1),
        (22, 55, 1),
        (W - 25, 52, 1),
        (90, 28, 1),
        (W - 88, 30, 1),
        (55, 60, 1),
        (W - 58, 58, 1),
    ]
    for sx, sy, sz in star_positions:
        _small_star(draw, sx, sy, sz, fg)

    # ------------------------------------------------------------------
    # 4. Edge midpoint star accents
    # ------------------------------------------------------------------
    _small_star(draw, W // 2, B - 1, 2, fg)  # top
    _small_star(draw, W // 2, H - B, 2, fg)  # bottom
    _small_star(draw, B - 1, H // 2, 2, fg)  # left
    _small_star(draw, W - B, H // 2, 2, fg)  # right


# ---------------------------------------------------------------------------
# Theme factory
# ---------------------------------------------------------------------------


def moonphase_theme() -> Theme:
    """Return the Moonphase theme — dark canvas, celestial aesthetic."""
    return Theme(
        name="moonphase",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # All standard regions hidden
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 40, 800, 320, visible=False),
            weather=ComponentRegion(0, 360, 300, 120, visible=False),
            birthdays=ComponentRegion(300, 360, 250, 120, visible=False),
            info=ComponentRegion(550, 360, 250, 120, visible=False),
            today_view=ComponentRegion(0, 60, 800, 280, visible=False),
            qotd=ComponentRegion(0, 0, 800, 400, visible=False),
            weather_full=ComponentRegion(0, 0, 800, 480, visible=False),
            fuzzyclock=ComponentRegion(0, 0, 800, 400, visible=False),
            diags=ComponentRegion(0, 0, 800, 480, visible=False),
            air_quality_full=ComponentRegion(0, 0, 800, 480, visible=False),
            # Full-canvas moonphase region
            moonphase_full=ComponentRegion(0, 0, 800, 480),
            draw_order=["moonphase_full"],
            overlay_fn=_draw_moonphase_overlay,
        ),
        style=ThemeStyle(
            fg=1,  # white on black — night sky
            bg=0,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            show_borders=False,
            font_regular=regular,
            font_medium=playfair_medium,
            font_semibold=semibold,
            font_bold=cinzel_bold,
            font_title=cinzel_bold,
            font_section_label=cinzel_bold,
            font_quote=playfair_regular,
            font_quote_author=playfair_regular,
            label_font_size=12,
            label_font_weight="bold",
        ),
    )
