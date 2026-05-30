"""Moonphase panel — full-canvas moon phase display.

Renders the current moon phase as a large, procedurally-drawn lunar disc
(true terminator, maria, craters, earthshine) flanked by 3 days on each side
showing the lunar progression.  Below the filmstrip sits a lunar data block:
illumination, moon age, moonrise/moonset, sunrise/sunset, weather, and the
countdown to the next full / new moon — with a supermoon badge when the full
moon falls near perigee.  A daily quote anchors the bottom.

The hero and flanking discs are rendered by :mod:`src.render.moon_render`,
which adapts to the canvas mode: smooth greyscale on Waveshare ("L"), a warm
yellow / cool earthshine on Inky ("RGB"), and a flat bilevel fallback on "1".

Used by the ``moonphase`` and ``moonphase_invert`` themes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.astronomy import moon_distance_earth_radii, moon_times
from src.render.fonts import (
    cinzel_bold,
    cormorant_italic,
    cormorant_medium,
    cormorant_regular,
    manufacturing_consent,
    tangerine_regular,
)
from src.render.moon import (
    moon_illumination,
    moon_phase_age,
    moon_phase_name,
    next_full_moon,
    next_new_moon,
)
from src.render.moon_render import MoonTones, render_moon_disc
from src.render.primitives import (
    fmt_time,
    text_height,
    text_width,
    wrap_lines,
)

if TYPE_CHECKING:
    from datetime import tzinfo

    from PIL import Image, ImageDraw

    from src.data.models import DashboardData, WeatherData
    from src.render.theme import ComponentRegion, ThemeStyle

QUOTES_FILE = Path(__file__).parent.parent.parent.parent / "config" / "quotes.json"

# A full moon nearer than this (Earth radii) counts as a supermoon.  ~57.4 ER
# ≈ 365,700 km, matching the common "within ~90% of perigee distance"
# definition closely enough for a celebratory badge.
_SUPERMOON_DISTANCE_ER = 57.4

_DEFAULT_QUOTES = [
    {"text": "Not all those who wander are lost.", "author": "J.R.R. Tolkien"},
    {"text": "The moon is a friend for the lonesome to talk to.", "author": "Carl Sandburg"},
    {
        "text": "We are all in the gutter, but some of us are looking at the stars.",
        "author": "Oscar Wilde",
    },
    {"text": "Dwell on the beauty of life.", "author": "Marcus Aurelius"},
    {"text": "The purpose of our lives is to be happy.", "author": "Dalai Lama"},
]


def _quote_for_panel(today: date, refresh: str = "daily", now: datetime | None = None) -> dict:
    """Pick a quote deterministically, same logic as info_panel."""
    if refresh == "hourly":
        dt = now if now is not None else datetime.now()  # allow-naive-datetime — hour bucket only
        key = f"moonphase-{today.isoformat()}T{dt.hour:02d}"
    elif refresh == "twice_daily":
        dt = now if now is not None else datetime.now()  # allow-naive-datetime — am/pm bucket only
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
# Tone + geometry helpers
# ---------------------------------------------------------------------------


def _luminance(value: int | tuple[int, int, int]) -> float:
    """Normalize an "L"/"1"/RGB colour to a 0..1 luminance."""
    if isinstance(value, tuple):
        return sum(value) / 3 / 255
    if value <= 1:  # "1" bilevel mode
        return float(value)
    return value / 255


def _moon_tones(style: ThemeStyle, mode: str, dark_canvas: bool) -> MoonTones:
    """Pick a moon palette appropriate to the canvas mode and theme polarity."""
    if mode == "RGB":
        if dark_canvas:
            return MoonTones(
                lit=(244, 224, 120),
                dark=(46, 58, 104),
                maria=(170, 150, 96),
                crater=(232, 224, 180),
                edge=(150, 150, 180),
            )
        return MoonTones(
            lit=(250, 238, 150),
            dark=(70, 84, 128),
            maria=(206, 176, 96),
            crater=(120, 110, 70),
            edge=(40, 40, 55),
        )
    if mode == "1":
        fg = 1 if dark_canvas else 0
        bg = 0 if dark_canvas else 1
        return MoonTones(lit=fg, dark=bg, maria=fg, crater=fg, edge=fg)
    # "L" greyscale.
    if dark_canvas:
        return MoonTones(lit=232, dark=58, maria=150, crater=210, edge=120)
    return MoonTones(lit=236, dark=72, maria=176, crater=120, edge=44)


def _coords_set(latitude: float | None, longitude: float | None) -> bool:
    """True when usable coordinates were supplied (exact 0,0 means unset)."""
    if latitude is None or longitude is None:
        return False
    return not (latitude == 0.0 and longitude == 0.0)


def _local(dt: datetime | None, tz: tzinfo | None) -> datetime | None:
    """Convert a UTC datetime to the display timezone for formatting."""
    if dt is None:
        return None
    if tz is None:
        return dt
    return dt.astimezone(tz)


def _ordinal_suffix(n: int) -> str:
    """Return ordinal suffix for a day number (1st, 2nd, 3rd, 4th, ...)."""
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    y: int,
    font,
    fill,
    gap: int = 6,
) -> int:
    """Draw *text* centered at *cx*; return the y below it plus *gap*."""
    tw = text_width(draw, text, font)
    draw.text((cx - tw // 2, y), text, font=font, fill=fill)
    return y + text_height(font) + gap


def _draw_date_line(
    draw: ImageDraw.ImageDraw,
    today: date,
    cx: int,
    y: int,
    style: ThemeStyle,
) -> int:
    """Draw formatted date centered at cx, return y after the line."""
    day_name = today.strftime("%A")
    month = today.strftime("%B")
    text = f"{day_name}, {month} {today.day}{_ordinal_suffix(today.day)}, {today.year}"
    return _draw_centered(draw, text, cx, y, cinzel_bold(19), style.secondary_accent_fill(), gap=6)


def _draw_phase_name(
    draw: ImageDraw.ImageDraw,
    today: date,
    cx: int,
    y: int,
    style: ThemeStyle,
    supermoon: bool,
) -> int:
    """Draw the phase name with decorative tildes, return y after."""
    name = moon_phase_name(today)
    text = f"~ {name} ~"
    y = _draw_centered(draw, text, cx, y, manufacturing_consent(36), style.primary_accent_fill(), 2)

    pct = moon_illumination(today)
    if supermoon:
        sub = f"* SUPERMOON *  {pct:.0f}% illuminated"
        sub_fill = style.primary_accent_fill()
    else:
        sub = f"{pct:.0f}% illuminated"
        sub_fill = style.fg
    return _draw_centered(draw, sub, cx, y + 2, cormorant_medium(22), sub_fill, gap=8)


def _draw_moon_row(
    draw: ImageDraw.ImageDraw,
    image: Image.Image | None,
    today: date,
    cx: int,
    y_top: int,
    row_h: int,
    tones: MoonTones,
    style: ThemeStyle,
) -> None:
    """Draw the hero moon and 3 flanking moons per side, with day labels."""
    cy = y_top + row_h // 2
    hero_r = 95
    render_moon_disc(image, draw, cx, cy, hero_r, moon_phase_age(today), tones)

    # Flanking moons: (day delta, radius, x offset from centre).
    flanks = [
        (-1, 34, -168),
        (-2, 29, -250),
        (-3, 24, -315),
        (1, 34, 168),
        (2, 29, 250),
        (3, 24, 315),
    ]
    label_font = cormorant_regular(17)
    for delta, r, x_off in flanks:
        d = today + timedelta(days=delta)
        gx = cx + x_off
        render_moon_disc(image, draw, gx, cy, r, moon_phase_age(d), tones)
        label = d.strftime("%a")
        lw = text_width(draw, label, label_font)
        draw.text((gx - lw // 2, cy + r + 5), label, font=label_font, fill=style.fg)


def _draw_separator(
    draw: ImageDraw.ImageDraw,
    cx: int,
    y: int,
    w: int,
    style: ThemeStyle,
) -> int:
    """Draw a decorative dot-star separator line."""
    sep_w = min(w - 40, 520)
    x0, x1 = cx - sep_w // 2, cx + sep_w // 2
    spacing, star_interval = 6, 48
    x, i = x0, 0
    while x <= x1:
        if i > 0 and i % (star_interval // spacing) == 0:
            draw.line([(x - 2, y + 2), (x + 2, y + 2)], fill=style.fg, width=1)
            draw.line([(x, y), (x, y + 4)], fill=style.fg, width=1)
        else:
            draw.ellipse([(x, y + 1), (x + 1, y + 2)], fill=style.fg)
        x += spacing
        i += 1
    return y + 12


def _draw_lunar_line(
    draw: ImageDraw.ImageDraw,
    today: date,
    cx: int,
    y: int,
    style: ThemeStyle,
    latitude: float | None,
    longitude: float | None,
    tz: tzinfo | None,
) -> int:
    """Draw moonrise/moonset (when located) + moon age."""
    font = cormorant_regular(22)
    parts: list[str] = []
    if _coords_set(latitude, longitude):
        times = moon_times(today, latitude, longitude, tz=tz)
        rise = _local(times.rise, tz)
        mset = _local(times.set, tz)
        if rise is not None:
            parts.append(f"moonrise {fmt_time(rise)}")
        if mset is not None:
            parts.append(f"moonset {fmt_time(mset)}")
    parts.append(f"age {moon_phase_age(today):.1f}d")
    return _draw_centered(draw, "  ~  ".join(parts), cx, y, font, style.fg, gap=6)


def _draw_sun_weather_line(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    cx: int,
    y: int,
    style: ThemeStyle,
) -> int:
    """Draw sunrise/sunset and a compact current-weather summary."""
    if weather is None:
        return y
    font = cormorant_regular(22)
    parts: list[str] = []
    if weather.sunrise:
        parts.append(f"sunrise {fmt_time(weather.sunrise)}")
    if weather.sunset:
        parts.append(f"sunset {fmt_time(weather.sunset)}")
    if weather.current_temp is not None:
        parts.append(f"{weather.current_temp:.0f}° {weather.current_description.title()}")
    if not parts:
        return y
    return _draw_centered(draw, "  ~  ".join(parts), cx, y, font, style.fg, gap=6)


def _draw_next_phase_line(
    draw: ImageDraw.ImageDraw,
    today: date,
    cx: int,
    y: int,
    style: ThemeStyle,
) -> int:
    """Draw the countdown to whichever principal phase comes first."""
    full_date, full_days = next_full_moon(today)
    new_date, new_days = next_new_moon(today)
    if full_days <= new_days:
        label, when, days = "Full Moon", full_date, full_days
    else:
        label, when, days = "New Moon", new_date, new_days
    day_word = "day" if days == 1 else "days"
    when_str = f"{when.strftime('%b')} {when.day}"
    text = f"Next {label} in {days} {day_word}  ~  {when_str}"
    return _draw_centered(
        draw, text, cx, y, cormorant_medium(22), style.secondary_accent_fill(), gap=8
    )


def _draw_quote(
    draw: ImageDraw.ImageDraw,
    today: date,
    cx: int,
    y: int,
    max_w: int,
    max_h: int,
    style: ThemeStyle,
    quote_refresh: str,
) -> None:
    """Draw a small wrapped quote at the bottom, centered."""
    quote = _quote_for_panel(today, refresh=quote_refresh)
    text = f'"{quote["text"]}"'
    quote_font = cormorant_italic(21)
    lines_h = text_height(quote_font)
    lines = wrap_lines(text, quote_font, max_w)[:2]

    cur_y = y
    for line in lines:
        lw = text_width(draw, line, quote_font)
        draw.text((cx - lw // 2, cur_y), line, font=quote_font, fill=style.fg)
        cur_y += lines_h + 4

    attr_font = tangerine_regular(28)
    attr = f"— {quote['author']}"
    attr_w = text_width(draw, attr, attr_font)
    attr_y = cur_y + 2
    if attr_y + lines_h < y + max_h:
        draw.text((cx - attr_w // 2, attr_y), attr, font=attr_font, fill=style.fg)


# ---------------------------------------------------------------------------
# Main draw function
# ---------------------------------------------------------------------------


def draw_moonphase(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    quote_refresh: str = "daily",
    image: Image.Image | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    now: datetime | None = None,
) -> None:
    """Draw the full-canvas moonphase display."""
    from src.render.theme import ComponentRegion as CR
    from src.render.theme import ThemeStyle as TS

    if region is None:
        region = CR(0, 0, 800, 480)
    if style is None:
        style = TS()

    x0, y0, w = region.x, region.y, region.w
    cx = x0 + w // 2
    weather = data.weather
    tz = now.tzinfo if now is not None else None

    image = image if image is not None else getattr(draw, "_image", None)
    mode = image.mode if image is not None else "1"
    dark_canvas = _luminance(style.bg) < 0.5
    tones = _moon_tones(style, mode, dark_canvas)

    # Supermoon = a (near-)full moon close to perigee.
    distance = moon_distance_earth_radii(
        datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc)
    )
    supermoon = moon_illumination(today) >= 97.0 and distance < _SUPERMOON_DISTANCE_ER

    # Top block: date + phase name + illumination.
    y = _draw_date_line(draw, today, cx, y0 + 10, style)
    y = _draw_phase_name(draw, today, cx, y, style, supermoon)

    # Hero + flanking filmstrip.
    moon_row_y = y
    moon_row_h = 196
    _draw_moon_row(draw, image, today, cx, moon_row_y, moon_row_h, tones, style)
    y = moon_row_y + moon_row_h + 2

    # Separator + lunar data block.
    y = _draw_separator(draw, cx, y, w, style)
    y = _draw_lunar_line(draw, today, cx, y, style, latitude, longitude, tz)
    y = _draw_sun_weather_line(draw, weather, cx, y, style)
    y = _draw_next_phase_line(draw, today, cx, y, style)

    # Quote anchored to the remaining space.
    _draw_quote(draw, today, cx, y, w - 60, region.y + region.h - y, style, quote_refresh)
