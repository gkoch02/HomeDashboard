"""Fuzzy-clock panel for the ``fuzzyclock`` theme.

Displays the current time as a human-readable phrase ("half past seven",
"quarter to nine") rendered large and centred on the canvas, with the day
name and date shown below in smaller text.

The time phrase snaps to the nearest 5-minute bucket, so the display content
only changes twelve times per hour.  Combined with the existing image-hash
comparison in main.py, the eInk panel is refreshed only when the phrase
actually changes — no wasted full-refresh cycles.

Recommended cron / systemd-timer interval: every 5 minutes.
"""

from __future__ import annotations

from datetime import datetime

from PIL import ImageDraw

from src.render.fonts import dm_bold as _dm_bold, dm_regular as _dm_regular
from src.render.primitives import text_height
from src.render.theme import ComponentRegion, ThemeStyle


# ---------------------------------------------------------------------------
# Fuzzy time logic
# ---------------------------------------------------------------------------

_HOURS = [
    "twelve", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven",
]

_PHRASES = {
    0:  "{hour} o'clock",
    5:  "five past {hour}",
    10: "ten past {hour}",
    15: "quarter past {hour}",
    20: "twenty past {hour}",
    25: "twenty five past {hour}",
    30: "half past {hour}",
    35: "twenty five to {next}",
    40: "twenty to {next}",
    45: "quarter to {next}",
    50: "ten to {next}",
    55: "five to {next}",
}


def fuzzy_time(dt: datetime) -> str:
    """Return a human-readable fuzzy time phrase for *dt*.

    Minutes are snapped to the nearest 5-minute bucket.  Midnight (00:00) and
    noon (12:00) receive special single-word labels.

    Examples::

        fuzzy_time(datetime(2026, 3, 23, 7, 32))  -> "half past seven"
        fuzzy_time(datetime(2026, 3, 23, 8, 58))  -> "five to nine"
        fuzzy_time(datetime(2026, 3, 23, 0,  1))  -> "midnight"
        fuzzy_time(datetime(2026, 3, 23, 12, 2))  -> "noon"
    """
    h = dt.hour % 12   # 0–11 (0 = 12 o'clock, either midnight or noon)
    m = dt.minute
    # Round to nearest 5-minute bucket
    bucket = ((m + 2) // 5) * 5
    if bucket == 60:
        bucket = 0
        h = (h + 1) % 12

    # Special labels for the top of 12 o'clock hours
    if bucket == 0 and dt.hour == 0:
        return "midnight"
    if bucket == 0 and dt.hour == 12:
        return "noon"

    hour_name = _HOURS[h]
    next_hour = _HOURS[(h + 1) % 12]
    return _PHRASES[bucket].format(hour=hour_name, next=next_hour)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def draw_fuzzyclock(
    draw: ImageDraw.ImageDraw,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the fuzzy-clock panel: large time phrase + date line, centred.

    The time phrase is rendered as large as possible (trying sizes 96 → 20 px)
    while still fitting within the region width.  The day name and date are
    drawn below the phrase in a smaller weight, and the combined block is
    vertically centred within *region*.
    """
    if region is None:
        region = ComponentRegion(0, 0, 800, 400)
    if style is None:
        style = ThemeStyle()

    phrase = fuzzy_time(now)
    date_line = now.strftime("%A  \u00b7  %-d %B")   # e.g. "Wednesday  ·  23 March"

    h_pad = 48
    v_pad = 24
    max_w = region.w - h_pad * 2

    # Font callables — prefer the style's bold/regular; fall back to DM Sans
    phrase_font_fn = style.font_bold or _dm_bold
    date_font_fn = style.font_regular or _dm_regular

    # Find the largest phrase size that fits within max_w
    best_phrase_size = 20
    for size in (96, 88, 80, 72, 64, 56, 48, 40, 32, 24, 20):
        f = phrase_font_fn(size)
        if int(f.getlength(phrase)) <= max_w:
            best_phrase_size = size
            break

    phrase_font = phrase_font_fn(best_phrase_size)
    # Date line at ~30 % of phrase size, minimum 16 px
    date_size = max(16, int(best_phrase_size * 0.30))
    date_font = date_font_fn(date_size)

    phrase_h = text_height(phrase_font)
    date_h = text_height(date_font)
    gap = max(16, best_phrase_size // 3)   # gap between phrase and date line
    block_h = phrase_h + gap + date_h

    # Reject if block overflows region (fall back to smallest sizes)
    if block_h > region.h - v_pad * 2:
        best_phrase_size = 20
        date_size = 16
        phrase_font = phrase_font_fn(best_phrase_size)
        date_font = date_font_fn(date_size)
        phrase_h = text_height(phrase_font)
        date_h = text_height(date_font)
        gap = 12
        block_h = phrase_h + gap + date_h

    # Vertical centering
    block_top = region.y + (region.h - block_h) // 2

    # Phrase — centred horizontally
    phrase_w = int(phrase_font.getlength(phrase))
    phrase_x = region.x + (region.w - phrase_w) // 2
    draw.text((phrase_x, block_top), phrase, font=phrase_font, fill=style.fg)

    # Date line — centred horizontally, below phrase
    date_w = int(date_font.getlength(date_line))
    date_x = region.x + (region.w - date_w) // 2
    date_y = block_top + phrase_h + gap
    draw.text((date_x, date_y), date_line, font=date_font, fill=style.fg)
