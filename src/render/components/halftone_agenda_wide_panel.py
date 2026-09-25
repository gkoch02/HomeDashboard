"""Wide-native halftone agenda for the 1360x480 panoramic plate.

``halftone_agenda`` cuts an 800x480 plate in two: engraving and weather on the
left, today's events on the right. Stretched or fitted onto the 10.85" strip
it wastes the panel either way. This plate is the same vocabulary drawn for the
strip's own shape, in three panes divided by full-height ordered-Bayer rules:

  * **Art pane** (``ART_W``) — the procedural weather illustration from
    :func:`src.render.skyart.draw_weather_scene`, a horizontal Bayer rule, then
    the typeset weather band ``halftone_agenda`` sets: temperature numeral,
    condition, high/low, sunrise, sunset, date and feels-like. The band is
    imported from that panel rather than copied — the two plates must not
    drift apart in what they read out.
  * **Agenda pane** (``AGENDA_W``) — today's events, drawn by the same
    ``_draw_agenda_pane`` the original uses, at half again its width. Every
    state treatment comes with it: elapsed rows perforated, the event in
    progress inverted into a red bar, the next one up ticked, and the
    after-dark rollover to TOMORROW.
  * **Rail** (the rest) — what the original plate has no room for. Top to
    bottom: an inverted alert bar when the weather service has one; the
    following day's first events (``TOMORROW``, or the day after that once
    the agenda has rolled over — the theme fetches two extra days for it);
    the forecast, one row per day with glyph, high, low and chance of rain;
    the coming birthdays; and a bottom row pairing the air-quality index
    with the moon's phase.

Nothing in the rail reads the clock except through ``agenda_day``, so the
plate keeps the original's property: a tick that crosses no event boundary
renders byte-identically and costs no panel write. Every typeset region is
hardened before the backend dithers; only the illustration diffuses.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import AirQualityData, Birthday, DashboardData, WeatherData
from src.render.artkit import accent_red as _accent_red
from src.render.artkit import ink as _ink
from src.render.artkit import to_local_naive
from src.render.components.day_arc_panel import agenda_day
from src.render.components.halftone_agenda_panel import _clock as _clock_text
from src.render.components.halftone_agenda_panel import (
    _draw_agenda_pane,
    _draw_weather_band,
    _sun_times,
    event_times,
)
from src.render.fonts import weather_icon
from src.render.icons import FALLBACK_ICON, OWM_ICON_MAP
from src.render.moon import moon_illumination, moon_phase_glyph, moon_phase_name
from src.render.primitives import (
    content_time,
    draw_text_truncated,
    events_for_day,
    text_height,
    text_width,
)
from src.render.skyart import draw_bayer_rule, draw_weather_scene, harden_typeset
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Region geometry
# ---------------------------------------------------------------------------

ART_W = 420  # illustration + weather band
DIVIDER_W = 6  # each full-height vertical Bayer rule
AGENDA_W = 560  # today's events
RAIL_X = ART_W + DIVIDER_W + AGENDA_W + DIVIDER_W  # 992
HERO_H = 292
RULE_H = 6
BAND_Y = HERO_H + RULE_H

AGENDA_PAD_X = 20
RAIL_PAD_X = 18
FOOTER_H = 22

# The pane is 52% of halftone's hero width and 99% of its height; 0.8 fills it
# the way 0.72 fills halftone_agenda's narrower pane.
SCENE_SCALE = 0.8

# Rail cells, top to bottom. Each is a labelled block; a block that does not
# fit in what is left of the rail is dropped whole rather than clipped.
TOMORROW_MAX = 3
FORECAST_MAX = 4
BIRTHDAY_MAX = 3
BIRTHDAY_LOOKAHEAD_DAYS = 14

# How many days past today the agenda and the rail can reach: the agenda rolls
# to tomorrow after dark, and the rail then shows the day after. The theme's
# event window is widened by this in ``src.app``.
EXTRA_EVENT_DAYS = 2

_LABEL_PT = 14
_CELL_GAP = 8
# The air-and-moon foot, anchored to the rail bottom.
FOOT_H = 52


def art_rect(region: ComponentRegion) -> tuple[int, int, int, int]:
    """The illustration's rectangle — the part of the plate that may dither in colour."""
    art_w = min(ART_W, max(1, region.w - DIVIDER_W))
    return (region.x, region.y, region.x + art_w, region.y + min(HERO_H, region.h))


def draw_halftone_agenda_wide(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    image: Image.Image | None = None,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the full ``halftone_agenda_wide`` plate into *region* of *image*."""
    if region is None:
        region = ComponentRegion(0, 0, 1360, 480)
    if style is None:
        style = ThemeStyle(fg=0, bg=255)
    if image is None:
        image = draw._image  # type: ignore[attr-defined]

    mode = image.mode
    x0, y0, w, h = region.x, region.y, region.w, region.h
    tz = now.tzinfo
    now_naive = to_local_naive(now, tz)
    sunrise, sunset = _sun_times(data.weather, tz)

    art_w = min(ART_W, max(1, w - DIVIDER_W))
    hero_h = min(HERO_H, h)
    band_h = max(0, h - BAND_Y)

    # --- Art pane.
    icon = data.weather.current_icon if data.weather is not None else None
    draw_weather_scene(image, (x0, y0, x0 + art_w, y0 + hero_h), icon, today, scale=SCENE_SCALE)
    draw_bayer_rule(image, x0, y0 + HERO_H, art_w, RULE_H, mode)
    if band_h > 0:
        _draw_weather_band(
            draw,
            image,
            data.weather,
            today,
            style,
            x0=x0,
            y0=y0 + BAND_Y,
            w=art_w,
            h=band_h,
            sunrise=sunrise,
            sunset=sunset,
        )
    draw_bayer_rule(image, x0 + art_w, y0, DIVIDER_W, h, mode, orientation="vertical")

    # --- Agenda pane on clean paper.
    pane_x = x0 + art_w + DIVIDER_W
    pane_w = min(AGENDA_W, max(0, w - art_w - DIVIDER_W))
    if pane_w <= 0:
        return
    _paper(image, pane_x, y0, pane_w, h)
    day, is_tomorrow = agenda_day(data.events, today, now_naive, sunset)
    _draw_agenda_pane(
        image,
        draw,
        data.events,
        day,
        is_tomorrow,
        now_naive,
        style,
        x0=pane_x + AGENDA_PAD_X,
        y0=y0 + 14,
        w=pane_w - AGENDA_PAD_X * 2,
        h=h - 14 - FOOTER_H,
    )
    ink = _ink(mode)
    footer_font = style.font_medium(16)
    stamp = f"updated {_clock_text(to_local_naive(content_time(data, now), tz)).lower()}"
    sw = text_width(draw, stamp, footer_font)
    draw.text(
        (
            pane_x + pane_w - AGENDA_PAD_X - sw,
            y0 + h - FOOTER_H + (FOOTER_H - text_height(footer_font)) // 2,
        ),
        stamp,
        font=footer_font,
        fill=ink,
    )

    # --- Rail.
    rail_x = pane_x + pane_w
    rail_w = max(0, x0 + w - rail_x)
    if rail_w > DIVIDER_W:
        draw_bayer_rule(image, rail_x, y0, DIVIDER_W, h, mode, orientation="vertical")
        rail_x += DIVIDER_W
        rail_w -= DIVIDER_W
        _paper(image, rail_x, y0, rail_w, h)
        _draw_rail(
            image,
            draw,
            data,
            today,
            day + timedelta(days=1),
            is_tomorrow,
            style,
            x0=rail_x + RAIL_PAD_X,
            y0=y0 + 14,
            w=rail_w - 2 * RAIL_PAD_X,
            h=h - 14 - 10,
        )

    if band_h > 0:
        harden_typeset(image, (x0, y0 + BAND_Y, art_w, band_h))
    harden_typeset(image, (pane_x, y0, pane_w, h))
    if rail_w > 0:
        harden_typeset(image, (rail_x, y0, rail_w, h))


def _paper(image: Image.Image, x: int, y: int, w: int, h: int) -> None:
    paper = Image.new("L", (w, h), 255)
    if image.mode == "RGB":
        paper = paper.convert("RGB")
    image.paste(paper, (x, y))


# ---------------------------------------------------------------------------
# Rail
# ---------------------------------------------------------------------------


class _Cursor:
    """A top-down flow down the rail; each cell asks for room before drawing."""

    def __init__(self, y: int, bottom: int):
        self.y = y
        self.bottom = bottom

    def take(self, needed: int) -> bool:
        return self.y + needed <= self.bottom

    def advance(self, used: int) -> None:
        self.y += used + _CELL_GAP


def _label(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    style: ThemeStyle,
    x: int,
    y: int,
    w: int,
) -> int:
    """Section label in the display face over a 3-px Bayer rule; returns height used."""
    font = (style.font_section_label or style.font_bold)(_LABEL_PT)
    draw.text((x, y), text, font=font, fill=_ink(image.mode))
    rule_y = y + text_height(font) + 6
    draw_bayer_rule(image, x, rule_y, w, 3, image.mode)
    return rule_y + 3 - y + 8


def forecast_rows(weather: WeatherData | None, today: date, limit: int) -> list:
    """The forecast days after *today*, soonest first, at most *limit*."""
    if weather is None:
        return []
    days = [fc for fc in weather.forecast if fc.date > today]
    return sorted(days, key=lambda fc: fc.date)[:limit]


def birthday_countdown(bday: Birthday, today: date) -> tuple[int, str]:
    """``(days_until, label)`` using the birthday bar's convention (Feb 29 → Feb 28)."""
    for year in (today.year, today.year + 1):
        try:
            when = bday.date.replace(year=year)
        except ValueError:
            when = date(year, 2, 28)
        if when >= today:
            break
    days_until = (when - today).days
    if days_until == 0:
        label = "Today!"
    elif days_until == 1:
        label = "Tomorrow"
    else:
        label = f"in {days_until}d"
    return days_until, label


def upcoming_birthdays(birthdays: list[Birthday], today: date, *, days: int, limit: int) -> list:
    """``(days_until, label, birthday)`` rows within *days*, soonest first."""
    rows = [(*birthday_countdown(b, today), b) for b in birthdays]
    rows = [r for r in rows if r[0] <= days]
    rows.sort(key=lambda r: (r[0], r[2].name))
    return rows[:limit]


def _draw_rail(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    next_day: date,
    rolled_over: bool,
    style: ThemeStyle,
    *,
    x0: int,
    y0: int,
    w: int,
    h: int,
) -> None:
    mode = image.mode
    ink = _ink(mode)
    cur = _Cursor(y0, y0 + h)
    weather = data.weather

    # --- Alerts: an inverted bar per alert, in the accent.
    alerts = weather.alerts if weather is not None else []
    if alerts:
        bar_font = style.font_bold(15)
        bar_h = text_height(bar_font) + 10
        for alert in alerts[:2]:
            if not cur.take(bar_h):
                break
            draw.rectangle((x0 - 6, cur.y, x0 + w, cur.y + bar_h), fill=_accent_red(mode))
            draw_text_truncated(
                draw,
                (x0 + 4, cur.y + 5),
                f"! {alert.event.upper()}",
                bar_font,
                w - 10,
                fill=style.bg,
            )
            cur.y += bar_h + 4
        cur.y += _CELL_GAP - 4

    # --- The next day's events.
    time_font = style.font_semibold(14)
    title_font = style.font_bold(16)
    row_h = 24
    label = "TOMORROW" if not rolled_over else next_day.strftime("%A").upper()
    if cur.take(24 + row_h):
        used = _label(image, draw, label, style, x0, cur.y, w)
        y = cur.y + used
        events = events_for_day(data.events, next_day)
        shown = events[:TOMORROW_MAX]
        if not shown:
            draw.text((x0, y), "Nothing scheduled", font=style.font_medium(15), fill=ink)
            y += row_h
        for evt in shown:
            start, _ = event_times(evt)
            draw.text((x0, y + 2), start, font=time_font, fill=ink)
            draw_text_truncated(draw, (x0 + 66, y), evt.summary, title_font, w - 66, fill=ink)
            y += row_h
        if len(events) > len(shown):
            draw.text((x0 + 66, y), f"+{len(events) - len(shown)} more", font=title_font, fill=ink)
            y += row_h
        cur.advance(y - cur.y)

    # --- Forecast.
    days = forecast_rows(weather, today, FORECAST_MAX)
    frow_h = 24
    if days and cur.take(24 + frow_h):
        used = _label(image, draw, "FORECAST", style, x0, cur.y, w)
        y = cur.y + used
        day_font = style.font_bold(15)
        temp_font = style.font_semibold(15)
        pct_font = style.font_medium(13)
        glyph_font = weather_icon(20)
        for fc in days:
            if not cur.take((y - cur.y) + frow_h):
                break
            draw.text((x0, y + 3), fc.date.strftime("%a").upper(), font=day_font, fill=ink)
            glyph = OWM_ICON_MAP.get(fc.icon, FALLBACK_ICON)
            gb = draw.textbbox((0, 0), glyph, font=glyph_font)
            draw.text(
                (x0 + 48 - gb[0], y + 13 - (gb[1] + gb[3]) // 2), glyph, font=glyph_font, fill=ink
            )
            temps = f"{fc.high:.0f}° / {fc.low:.0f}°"
            draw.text((x0 + 84, y + 3), temps, font=temp_font, fill=ink)
            if fc.precip_chance is not None:
                pct = f"{max(0.0, min(1.0, fc.precip_chance)) * 100:.0f}%"
                draw.text(
                    (x0 + w - text_width(draw, pct, pct_font), y + 5), pct, font=pct_font, fill=ink
                )
            y += frow_h
        cur.advance(y - cur.y)

    # --- Birthdays take what is left above the foot.
    rows = upcoming_birthdays(
        data.birthdays, today, days=BIRTHDAY_LOOKAHEAD_DAYS, limit=BIRTHDAY_MAX
    )
    brow_h = 22
    foot_top = y0 + h - FOOT_H
    room = foot_top - _CELL_GAP - cur.y
    if rows and room >= 34 + brow_h:
        used = _label(image, draw, "BIRTHDAYS", style, x0, cur.y, w)
        y = cur.y + used
        fits = max(1, (foot_top - _CELL_GAP - y) // brow_h)
        name_font = style.font_medium(15)
        soon_font = style.font_bold(15)
        for days_until, when, bday in rows[:fits]:
            text = f"{when} — {bday.name}"
            if bday.age is not None:
                text += f" ({bday.age})"
            font = soon_font if days_until <= 1 else name_font
            if days_until == 0:
                draw.rectangle((x0 - 6, y, x0 + w, y + brow_h - 2), fill=_accent_red(mode))
                draw_text_truncated(draw, (x0, y + 2), text, font, w, fill=style.bg)
            else:
                draw_text_truncated(draw, (x0, y + 2), text, font, w, fill=ink)
            y += brow_h

    # --- Foot: air quality beside the moon, anchored to the rail bottom.
    draw_bayer_rule(image, x0, foot_top, w, 3, mode)
    half = w // 2
    _draw_air_cell(image, draw, data.air_quality, style, x0, foot_top + 9, half - 8)
    _draw_moon_cell(image, draw, today, style, x0 + half + 8, foot_top + 9, w - half - 8)


def _draw_air_cell(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    air: AirQualityData | None,
    style: ThemeStyle,
    x: int,
    y: int,
    w: int,
) -> None:
    """``AIR`` caption, then the index numeral with its category beside it."""
    ink = _ink(image.mode)
    cap_font = (style.font_section_label or style.font_bold)(11)
    draw.text((x, y), "AIR", font=cap_font, fill=ink)
    y += text_height(cap_font) + 2
    if air is None:
        draw.text((x, y + 4), "No sensor", font=style.font_medium(13), fill=ink)
        return
    aqi_font = (style.font_title or style.font_bold)(26)
    aqi = str(air.aqi)
    ab = draw.textbbox((0, 0), aqi, font=aqi_font)
    fill = _accent_red(image.mode) if air.aqi >= 101 else ink
    draw.text((x - ab[0], y - ab[1]), aqi, font=aqi_font, fill=fill)
    tx = x + (ab[2] - ab[0]) + 8
    cat_font = style.font_semibold(12)
    draw_text_truncated(draw, (tx, y), air.category.upper(), cat_font, w - (tx - x), fill=ink)
    draw.text(
        (tx, y + text_height(cat_font) + 1),
        f"PM2.5 {air.pm25:.1f}",
        font=style.font_regular(11),
        fill=ink,
    )


def _draw_moon_cell(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    today: date,
    style: ThemeStyle,
    x: int,
    y: int,
    w: int,
) -> None:
    """``MOON`` caption, then the phase glyph with its name and illumination."""
    ink = _ink(image.mode)
    cap_font = (style.font_section_label or style.font_bold)(11)
    draw.text((x, y), "MOON", font=cap_font, fill=ink)
    y += text_height(cap_font) + 2
    glyph_font = weather_icon(26)
    glyph = moon_phase_glyph(today)
    gb = draw.textbbox((0, 0), glyph, font=glyph_font)
    draw.text((x - gb[0], y - gb[1]), glyph, font=glyph_font, fill=ink)
    tx = x + (gb[2] - gb[0]) + 8
    name_font = style.font_semibold(12)
    draw_text_truncated(
        draw, (tx, y), moon_phase_name(today).upper(), name_font, w - (tx - x), fill=ink
    )
    draw.text(
        (tx, y + text_height(name_font) + 1),
        f"{moon_illumination(today):.0f}% lit",
        font=style.font_regular(11),
        fill=ink,
    )
