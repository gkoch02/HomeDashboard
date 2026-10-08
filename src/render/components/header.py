from __future__ import annotations

from datetime import datetime

from PIL import ImageDraw

from src.data.models import StalenessLevel
from src.render import layout as L
from src.render.primitives import (
    draw_text_truncated,
    filled_rect,
    hline,
    text_height,
    text_width,
)
from src.render.theme import ComponentRegion, ThemeStyle

_SEVERITY = {
    StalenessLevel.FRESH: 0,
    StalenessLevel.AGING: 1,
    StalenessLevel.STALE: 2,
    StalenessLevel.EXPIRED: 3,
}


def status_label(is_stale: bool, source_staleness: dict[str, StalenessLevel] | None) -> str:
    """The caption prefix for the "updated" stamp: stale beats cached beats fresh."""
    worst = max(
        (source_staleness or {}).values(),
        key=lambda level: _SEVERITY.get(level, 0),
        default=StalenessLevel.FRESH,
    )
    if worst in (StalenessLevel.STALE, StalenessLevel.EXPIRED):
        return "! Stale  "
    if is_stale:
        return "! Cached  "
    return "Updated  "


def draw_header(
    draw: ImageDraw.ImageDraw,
    now: datetime,
    is_stale: bool = False,
    title: str = "Home Dashboard",
    source_staleness: dict[str, StalenessLevel] | None = None,
    *,
    content_at: datetime | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
):
    if region is None:
        region = ComponentRegion(0, L.HEADER_Y, L.WIDTH, L.HEADER_H)
    if style is None:
        style = ThemeStyle()

    x = region.x
    y = region.y
    w = region.w
    h = region.h
    pad = L.PAD

    # Filled header band (may be skipped for no-bar themes)
    if style.invert_header:
        filled_rect(draw, (x, y, x + w - 1, y + h - 1), fill=style.fg)
        text_fill = style.bg
        _accent = style.primary_accent_fill()
        # On non-Inky displays, accent_primary falls back to fg, which is invisible
        # against the filled header bar. Use bg (contrasting) in that case.
        title_fill = _accent if _accent != style.fg else style.bg
    else:
        text_fill = style.fg
        title_fill = style.primary_accent_fill()
        # Draw a bottom border line for visual separation when there's no filled bar
        if style.show_borders:
            hline(draw, y + h - 1, x, x + w - 1, fill=style.fg)

    # Title (left)
    _title_fn = style.font_title if style.font_title is not None else style.font_bold
    title_font = _title_fn(20)
    th = text_height(title_font)
    title_y = y + (h - th) // 2

    # Last updated (right) — "Updated  Mar 15 · 9:43p"
    label_font = style.font_regular(11)
    time_font = style.font_semibold(13)
    # This label reports when the *data* last changed, not when the frame was
    # painted: `now` advances every run whether or not anything was fetched, so
    # reading it here would change these pixels on every tick and force a panel
    # refresh for content that has not moved. See primitives.content_time.
    stamp = content_at if content_at is not None else now
    time_str = stamp.strftime("%-I:%M%p").replace("AM", "a").replace("PM", "p")
    date_str = stamp.strftime("%b %-d")
    ts = f"{date_str}  ·  {time_str}"

    updated_label = status_label(is_stale, source_staleness)

    label_w = text_width(draw, updated_label, label_font)
    ts_w = text_width(draw, ts, time_font)
    total_w = label_w + ts_w

    label_h = text_height(label_font)
    ts_h = text_height(time_font)
    label_y = y + (h - label_h) // 2 + 1
    ts_y = y + (h - ts_h) // 2

    right_edge = x + w - pad
    # The title yields to the timestamp: drawn at full width, a long title
    # would run under the right-aligned block and overprint it.
    draw_text_truncated(
        draw,
        (x + pad, title_y),
        title,
        title_font,
        max(0, right_edge - total_w - pad - (x + pad)),
        fill=title_fill,
    )
    draw.text((right_edge - total_w, label_y), updated_label, font=label_font, fill=text_fill)
    draw.text((right_edge - ts_w, ts_y), ts, font=time_font, fill=text_fill)
