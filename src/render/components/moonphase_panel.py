"""Moonphase panel — full-canvas moon phase display.

Renders the current moon phase as a large central glyph flanked by 3 days
on each side showing the lunar progression.  Peripheral info includes
illumination percentage, sunrise/sunset, moon age, weather, and a small
daily quote.

Used by the ``moonphase`` and ``moonphase_invert`` themes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from src.render.fonts import (
    cinzel_bold, playfair_regular, playfair_medium, weather_icon,
)
from src.render.icons import OWM_ICON_MAP, FALLBACK_ICON
from src.render.moon import (
    moon_illumination, moon_phase_age, moon_phase_glyph, moon_phase_name,
)
from src.render.primitives import (
    fmt_time, text_height, text_width, wrap_lines,
)

if TYPE_CHECKING:
    from PIL import ImageDraw
    from src.data.models import DashboardData, WeatherData
    from src.render.theme import ComponentRegion, ThemeStyle

QUOTES_FILE = Path(__file__).parent.parent.parent.parent / "config" / "quotes.json"

_DEFAULT_QUOTES = [
    {"text": "Not all those who wander are lost.", "author": "J.R.R. Tolkien"},
    {"text": "The moon is a friend for the lonesome to talk to.",
     "author": "Carl Sandburg"},
    {"text": "We are all in the gutter, but some of us are looking at the stars.",
     "author": "Oscar Wilde"},
    {"text": "Dwell on the beauty of life.", "author": "Marcus Aurelius"},
    {"text": "The purpose of our lives is to be happy.", "author": "Dalai Lama"},
]


def _quote_for_panel(today: date, refresh: str = "daily",
                     now: datetime | None = None) -> dict:
    """Pick a quote deterministically, same logic as info_panel."""
    if refresh == "hourly":
        dt = now if now is not None else datetime.now()
        key = f"moonphase-{today.isoformat()}T{dt.hour:02d}"
    elif refresh == "twice_daily":
        dt = now if now is not None else datetime.now()
        period = "am" if dt.hour < 12 else "pm"
        key = f"moonphase-{today.isoformat()}-{period}"
    else:
        key = f"moonphase-{today.isoformat()}"

    if QUOTES_FILE.exists():
        try:
            quotes = json.loads(QUOTES_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            quotes = _DEFAULT_QUOTES
    else:
        quotes = _DEFAULT_QUOTES

    day_hash = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return quotes[day_hash % len(quotes)]


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _ordinal_suffix(n: int) -> str:
    """Return ordinal suffix for a day number (1st, 2nd, 3rd, 4th, ...)."""
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _draw_date_line(
    draw: "ImageDraw.ImageDraw", today: date,
    cx: int, y: int, style: "ThemeStyle",
) -> int:
    """Draw formatted date centered at cx, return y after the line."""
    font = cinzel_bold(14)
    day_name = today.strftime("%A")
    month = today.strftime("%B")
    day_num = today.day
    suffix = _ordinal_suffix(day_num)
    text = f"{day_name}, {month} {day_num}{suffix}, {today.year}"
    tw = text_width(draw, text, font)
    draw.text((cx - tw // 2, y), text, font=font, fill=style.fg)
    return y + text_height(font) + 6


def _draw_phase_name(
    draw: "ImageDraw.ImageDraw", today: date,
    cx: int, y: int, style: "ThemeStyle",
) -> int:
    """Draw the phase name with decorative tildes, return y after."""
    font = cinzel_bold(18)
    name = moon_phase_name(today).upper()
    text = f"~ {name} ~"
    tw = text_width(draw, text, font)
    draw.text((cx - tw // 2, y), text, font=font, fill=style.fg)
    return y + text_height(font) + 10


def _draw_moon_row(
    draw: "ImageDraw.ImageDraw", today: date,
    cx: int, y_top: int, row_h: int, style: "ThemeStyle",
) -> None:
    """Draw the hero moon and 3 flanking moons per side."""
    hero_size = 140
    hero_font = weather_icon(hero_size)
    hero_glyph = moon_phase_glyph(today)

    # Center the hero glyph vertically and horizontally
    hbbox = draw.textbbox((0, 0), hero_glyph, font=hero_font)
    hero_w = hbbox[2] - hbbox[0]
    hero_h = hbbox[3] - hbbox[1]
    hero_x = cx - hero_w // 2 - hbbox[0]
    hero_y = y_top + (row_h - hero_h) // 2 - hbbox[1] - 8

    draw.text((hero_x, hero_y), hero_glyph, font=hero_font, fill=style.fg)

    # Flanking moons: offsets from center, sizes, and day deltas
    flanks = [
        (-1, 42, -110),
        (-2, 36, -180),
        (-3, 30, -245),
        (1, 42, 110),
        (2, 36, 180),
        (3, 30, 245),
    ]

    label_font = playfair_regular(10)

    for delta, size, x_off in flanks:
        d = today + timedelta(days=delta)
        glyph = moon_phase_glyph(d)
        font = weather_icon(size)
        bbox = draw.textbbox((0, 0), glyph, font=font)
        gw = bbox[2] - bbox[0]
        gh = bbox[3] - bbox[1]

        gx = cx + x_off - gw // 2 - bbox[0]
        gy = y_top + (row_h - gh) // 2 - bbox[1] - 4
        draw.text((gx, gy), glyph, font=font, fill=style.fg)

        # Day label directly below the glyph
        day_label = d.strftime("%a")
        lw = text_width(draw, day_label, label_font)
        lx = cx + x_off - lw // 2
        glyph_bottom = gy + bbox[1] + gh
        ly = glyph_bottom + 4
        draw.text((lx, ly), day_label, font=label_font, fill=style.fg)


def _draw_illumination(
    draw: "ImageDraw.ImageDraw", today: date,
    cx: int, y: int, style: "ThemeStyle",
) -> int:
    """Draw illumination percentage with star decorations."""
    font = playfair_medium(18)
    pct = moon_illumination(today)
    text = f"* {pct:.0f}% illuminated *"
    tw = text_width(draw, text, font)
    draw.text((cx - tw // 2, y), text, font=font, fill=style.fg)
    return y + text_height(font) + 10


def _draw_celestial_strip(
    draw: "ImageDraw.ImageDraw", weather: "WeatherData | None",
    today: date, cx: int, y: int, style: "ThemeStyle",
) -> int:
    """Draw sunrise/sunset times and moon age."""
    font = playfair_regular(16)
    age = moon_phase_age(today)

    parts = []
    if weather is not None:
        if weather.sunrise:
            parts.append(f"sunrise {fmt_time(weather.sunrise)}")
        if weather.sunset:
            parts.append(f"sunset {fmt_time(weather.sunset)}")
    parts.append(f"Age: {age:.1f} days")

    text = "  ~  ".join(parts)
    tw = text_width(draw, text, font)
    draw.text((cx - tw // 2, y), text, font=font, fill=style.fg)
    return y + text_height(font) + 10


def _draw_weather_strip(
    draw: "ImageDraw.ImageDraw", weather: "WeatherData | None",
    cx: int, y: int, style: "ThemeStyle",
) -> int:
    """Draw weather icon, temp, description, and hi/lo."""
    if weather is None:
        return y

    # Weather icon glyph
    icon_font = weather_icon(26)
    icon_glyph = OWM_ICON_MAP.get(weather.current_icon, FALLBACK_ICON)

    text_font = playfair_regular(16)
    temp = f"{weather.current_temp:.0f}°"
    desc = weather.current_description.title()
    hilo = f"H:{weather.high:.0f}° L:{weather.low:.0f}°"
    info = f"  {temp}  {desc}   {hilo}"

    icon_bbox = draw.textbbox((0, 0), icon_glyph, font=icon_font)
    icon_w = icon_bbox[2] - icon_bbox[0]
    info_w = text_width(draw, info, text_font)
    total_w = icon_w + info_w

    start_x = cx - total_w // 2

    # Draw icon
    icon_h = icon_bbox[3] - icon_bbox[1]
    th = text_height(text_font)
    icon_y = y + (th - icon_h) // 2 - icon_bbox[1]
    draw.text((start_x - icon_bbox[0], icon_y), icon_glyph,
              font=icon_font, fill=style.fg)

    # Draw text
    draw.text((start_x + icon_w, y), info, font=text_font, fill=style.fg)
    return y + th + 10


def _draw_separator(
    draw: "ImageDraw.ImageDraw",
    cx: int, y: int, w: int, style: "ThemeStyle",
) -> int:
    """Draw a decorative dot-star separator line."""
    sep_w = min(w - 40, 500)
    x0 = cx - sep_w // 2
    x1 = cx + sep_w // 2

    # Draw dotted line with star accents
    spacing = 6
    star_interval = 48
    x = x0
    i = 0
    while x <= x1:
        if i > 0 and i % (star_interval // spacing) == 0:
            # Draw a small cross/star
            draw.line([(x - 2, y + 2), (x + 2, y + 2)], fill=style.fg, width=1)
            draw.line([(x, y), (x, y + 4)], fill=style.fg, width=1)
        else:
            draw.ellipse([(x, y + 1), (x + 1, y + 2)], fill=style.fg)
        x += spacing
        i += 1

    return y + 10


def _draw_quote(
    draw: "ImageDraw.ImageDraw", today: date,
    cx: int, y: int, max_w: int, max_h: int,
    style: "ThemeStyle", quote_refresh: str,
) -> None:
    """Draw a small wrapped quote at the bottom, centered."""
    quote = _quote_for_panel(today, refresh=quote_refresh)
    text = f'"{quote["text"]}"'

    quote_font = playfair_regular(15)
    lines_h = text_height(quote_font)

    # Wrap into lines, then draw each line centered
    lines = wrap_lines(text, quote_font, max_w)[:2]

    cur_y = y
    for line in lines:
        lw = text_width(draw, line, quote_font)
        draw.text((cx - lw // 2, cur_y), line,
                  font=quote_font, fill=style.fg)
        cur_y += lines_h + 4

    # Attribution
    attr_font = playfair_regular(13)
    attr = f'-- {quote["author"]}'
    attr_w = text_width(draw, attr, attr_font)
    attr_y = cur_y + 4
    if attr_y + lines_h < y + max_h:
        draw.text((cx - attr_w // 2, attr_y), attr,
                  font=attr_font, fill=style.fg)


# ---------------------------------------------------------------------------
# Main draw function
# ---------------------------------------------------------------------------

def draw_moonphase(
    draw: "ImageDraw.ImageDraw",
    data: "DashboardData",
    today: date,
    *,
    region: "ComponentRegion | None" = None,
    style: "ThemeStyle | None" = None,
    quote_refresh: str = "daily",
) -> None:
    """Draw the full-canvas moonphase display."""
    from src.render.theme import ComponentRegion as CR, ThemeStyle as TS
    if region is None:
        region = CR(0, 0, 800, 480)
    if style is None:
        style = TS()

    x0 = region.x
    y0 = region.y
    w = region.w
    cx = x0 + w // 2

    weather = data.weather

    # Date line
    y = y0 + 20
    y = _draw_date_line(draw, today, cx, y, style)

    # Phase name
    y = _draw_phase_name(draw, today, cx, y, style)

    # Hero moon + flanking moons (fixed 200px zone)
    moon_row_y = y + 2
    moon_row_h = 200
    _draw_moon_row(draw, today, cx, moon_row_y, moon_row_h, style)
    y = moon_row_y + moon_row_h + 4

    # Illumination
    y = _draw_illumination(draw, today, cx, y, style)

    # Celestial strip (sunrise/sunset + moon age)
    y = _draw_celestial_strip(draw, weather, today, cx, y, style)

    # Weather strip
    y = _draw_weather_strip(draw, weather, cx, y, style)

    # Separator
    y = _draw_separator(draw, cx, y, w, style)

    # Quote at bottom
    _draw_quote(draw, today, cx, y, w - 60, region.y + region.h - y,
                style, quote_refresh)
