"""countdown_panel.py — Full-canvas days-until tracker for the countdown theme.

Renders one or more user-configured countdowns (name + target date).  A single
event renders as a "hero" with a giant numeral; multiple events stack as rows
with a prominent day count followed by the event name and date.

Past events are dropped.  The component is fully data-independent — events are
passed in from app.py's ``cfg.countdown.events`` list.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from PIL import ImageDraw

from src.render.primitives import (
    draw_text_truncated,
    hline,
    text_height,
    text_width,
)
from src.render.theme import ComponentRegion, ThemeStyle

_MAX_EVENTS = 5
_PAD = 32


@dataclass
class _Resolved:
    name: str
    target: date
    days_until: int


def _parse_events(events: Sequence[object], today: date) -> list[_Resolved]:
    """Parse config CountdownEvent instances, drop invalid/past ones, sort by date."""
    out: list[_Resolved] = []
    for ev in events:
        name = getattr(ev, "name", "")
        raw = getattr(ev, "date", "")
        if not name or not raw:
            continue
        try:
            target = datetime.strptime(raw, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        days = (target - today).days
        if days < 0:
            continue
        out.append(_Resolved(name=name, target=target, days_until=days))
    out.sort(key=lambda r: r.days_until)
    return out[:_MAX_EVENTS]


def _format_date(d: date) -> str:
    """Render '%B %-d, %Y' (e.g. 'June 4, 2026')."""
    return d.strftime("%B %-d, %Y")


def _draw_empty(
    draw: ImageDraw.ImageDraw,
    region: ComponentRegion,
    style: ThemeStyle,
) -> None:
    msg_font = style.font_semibold(28)
    hint_font = style.font_regular(14)
    msg = "No countdowns configured"
    hint = "Add entries under `countdown.events:` in config.yaml"
    msg_w = text_width(draw, msg, msg_font)
    hint_w = text_width(draw, hint, hint_font)
    cx = region.x + region.w // 2
    cy = region.y + region.h // 2
    msg_h = text_height(msg_font)
    draw.text(
        (cx - msg_w // 2, cy - msg_h),
        msg,
        font=msg_font,
        fill=style.fg,
    )
    draw.text(
        (cx - hint_w // 2, cy + 6),
        hint,
        font=hint_font,
        fill=style.fg,
    )


def _draw_hero(
    draw: ImageDraw.ImageDraw,
    event: _Resolved,
    today: date,
    region: ComponentRegion,
    style: ThemeStyle,
) -> None:
    """Draw a single event as a huge centered numeral."""
    cx = region.x + region.w // 2
    # Top: label
    label = "COUNTING DOWN TO" if event.days_until > 0 else "ARRIVED"
    label_font = style.label_font()
    draw.text((cx, region.y + 48), label, font=label_font, fill=style.fg, anchor="mm")

    # Centered giant numeral using mm anchor so the numeral sits exactly where we place it.
    num_str = str(event.days_until) if event.days_until > 0 else "0"
    num_font = style.font_bold(200)
    num_cy = region.y + 200
    draw.text(
        (cx, num_cy),
        num_str,
        font=num_font,
        fill=style.primary_accent_fill(),
        anchor="mm",
    )

    # "DAYS" subtitle just below numeral (clear separation from the glyph descenders)
    days_label = "DAYS" if event.days_until != 1 else "DAY"
    days_font = style.font_semibold(22)
    days_cy = region.y + 320
    draw.text((cx, days_cy), days_label, font=days_font, fill=style.fg, anchor="mm")

    # Event name — large, centered
    name_font = style.font_bold(34)
    name_max_w = region.w - _PAD * 2
    name_str = event.name.upper()
    name_cy = region.y + 380
    if text_width(draw, name_str, name_font) > name_max_w:
        # Fall back to truncated left-anchored layout (draw_text_truncated uses top-left).
        nh = text_height(name_font)
        draw_text_truncated(
            draw,
            (region.x + _PAD, name_cy - nh // 2),
            name_str,
            name_font,
            name_max_w,
            fill=style.fg,
        )
    else:
        draw.text((cx, name_cy), name_str, font=name_font, fill=style.fg, anchor="mm")

    # Target date line
    date_str = _format_date(event.target)
    date_font = style.font_regular(16)
    draw.text((cx, region.y + 428), date_str, font=date_font, fill=style.fg, anchor="mm")

    # Small "as of TODAY" footnote bottom-right
    foot = f"As of {today.strftime('%b %-d, %Y')}"
    foot_font = style.font_regular(11)
    draw.text(
        (region.x + region.w - 12, region.y + region.h - 10),
        foot,
        font=foot_font,
        fill=style.fg,
        anchor="rb",
    )


def _draw_list(
    draw: ImageDraw.ImageDraw,
    events: list[_Resolved],
    today: date,
    region: ComponentRegion,
    style: ThemeStyle,
) -> None:
    """Draw 2–5 events stacked vertically."""
    title_font = style.label_font()
    title = "COUNTDOWNS"
    draw.text(
        (region.x + _PAD, region.y + 24),
        title,
        font=title_font,
        fill=style.fg,
    )

    # Subtitle: "as of ..."
    sub_font = style.font_regular(12)
    sub = f"As of {today.strftime('%A, %b %-d, %Y')}"
    sub_w = text_width(draw, sub, sub_font)
    draw.text(
        (region.x + region.w - sub_w - _PAD, region.y + 26),
        sub,
        font=sub_font,
        fill=style.fg,
    )

    # Underline
    underline_y = region.y + 24 + text_height(title_font) + 10
    hline(draw, underline_y, region.x + _PAD, region.x + region.w - _PAD, fill=style.fg)

    # Rows distributed across remaining vertical space
    list_top = underline_y + 16
    list_bottom = region.y + region.h - 24
    row_h = (list_bottom - list_top) // max(1, len(events))

    for idx, event in enumerate(events):
        row_y = list_top + row_h * idx
        row_cy = row_y + row_h // 2

        # Days number (big, left-aligned)
        days_str = str(event.days_until) if event.days_until > 0 else "0"
        days_font = style.font_bold(min(72, max(42, row_h - 12)))
        days_bb = draw.textbbox((0, 0), days_str, font=days_font)
        days_h = days_bb[3] - days_bb[1]
        draw.text(
            (region.x + _PAD, row_cy - days_h // 2 - days_bb[1]),
            days_str,
            font=days_font,
            fill=style.primary_accent_fill(),
        )
        days_w = days_bb[2] - days_bb[0]

        # "d" suffix next to number (small)
        suffix = "day" if event.days_until == 1 else "days"
        suffix_font = style.font_medium(14)
        suffix_bb = draw.textbbox((0, 0), suffix, font=suffix_font)
        suffix_h = suffix_bb[3] - suffix_bb[1]
        draw.text(
            (
                region.x + _PAD + days_w + 6,
                row_cy + days_h // 2 - suffix_h - 2,
            ),
            suffix,
            font=suffix_font,
            fill=style.fg,
        )

        # Name (large)
        name_x = region.x + _PAD + days_w + 60
        name_max_w = region.x + region.w - _PAD - name_x
        name_font = style.font_semibold(22)
        name_h = text_height(name_font)
        draw_text_truncated(
            draw,
            (name_x, row_cy - name_h - 2),
            event.name,
            name_font,
            name_max_w,
            fill=style.fg,
        )

        # Date (small, right-below name)
        date_str = _format_date(event.target)
        date_font = style.font_regular(12)
        draw_text_truncated(
            draw,
            (name_x, row_cy + 4),
            date_str,
            date_font,
            name_max_w,
            fill=style.fg,
        )

        # Divider between rows (not after last)
        if idx < len(events) - 1:
            hline(
                draw,
                row_y + row_h - 2,
                region.x + _PAD,
                region.x + region.w - _PAD,
                fill=style.fg,
            )


def draw_countdown(
    draw: ImageDraw.ImageDraw,
    events: Sequence[object],
    today: date,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the countdown panel inside *region*.

    *events* is a sequence of objects with ``name`` and ``date`` attributes
    (the ``CountdownEvent`` config dataclass, but accepted structurally).
    Past and malformed entries are silently skipped.
    """
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    resolved = _parse_events(events or [], today)

    if not resolved:
        _draw_empty(draw, region, style)
        return

    if len(resolved) == 1:
        _draw_hero(draw, resolved[0], today, region, style)
        return

    _draw_list(draw, resolved, today, region, style)
