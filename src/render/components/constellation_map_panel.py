"""constellation_map_panel.py — full-canvas star-chart theme.

Projects the visible northern-hemisphere bright sky onto a circular disc
centered on the canvas: zenith at the centre, horizon at the rim, with the
conventional "looking up" orientation (N at top, E to the **left**, S at
bottom, W to the right).  Stars are sized by visual magnitude, the named
ones receive Cinzel labels, and the registered constellations are joined
by thin polylines.  The moon is plotted at its computed altitude/azimuth
when above the horizon.

Around the disc, a margin band carries the date, observation time + zone,
location, current sky condition (e.g. "Sky open at twilight"), and a
short tonight-line about the moon and the next meteor shower.

  ┌──────────────────────────────────────────────────────────────┐
  │  ✦ TONIGHT'S SKY                            APRIL 23 · 22:00 │
  │                                                              │
  │                          •  Polaris                          │
  │                       •     ·                                │
  │                   ·      ·  ·   *Capella                     │
  │             *Vega                                           │
  │             ◇  ─── Orion ───                                │
  │           •  ·  •─•─•  ·                                    │
  │                · ·  ·                                       │
  │                                                              │
  │  NYC 40.7°N · 74.0°W      ☽ Waxing Crescent · Eta Aquariids │
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone, tzinfo

from PIL import ImageDraw

from src.astronomy import (
    SUNRISE_ALTITUDE,
    equatorial_to_horizontal,
    local_sidereal_time,
    moon_equatorial,
    next_meteor_shower,
    sun_times,
)
from src.data.models import DashboardData
from src.render.fonts import cinzel_regular, dm_medium, dm_regular, weather_icon
from src.render.moon import moon_phase_glyph, moon_phase_name
from src.render.primitives import text_height, text_width
from src.render.star_catalog import (
    CONSTELLATIONS,
    LABELED_STARS,
    STARS,
    STARS_BY_NAME,
    Star,
)
from src.render.theme import ComponentRegion, ThemeStyle

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

_HEADER_H = 36
_FOOTER_H = 40
_DISC_CENTER_X = 400
_DISC_CENTER_Y = 246
_DISC_RADIUS = 196
_PAD_X = 18


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def _alt_az_to_chart_xy(alt_deg: float, az_deg: float, radius: int) -> tuple[int, int] | None:
    """Project (alt, az) onto a 2-D chart disc using equidistant azimuthal.

    Returns ``None`` for objects below the horizon.  The chart is drawn in
    the conventional "looking up" orientation: North at the top, East to the
    left, South at the bottom, West at the right.
    """
    if alt_deg < 0.0:
        return None
    # Equidistant azimuthal: r linear in (90° − alt), so zenith at centre,
    # horizon at radius ``R``.  Stereographic skews edges; equidistant keeps
    # the constellations evenly spaced and avoids exaggerating low stars.
    r = radius * (90.0 - alt_deg) / 90.0
    az_rad = math.radians(az_deg)
    # In looking-up orientation, East azimuth (90°) lands at the LEFT and
    # West (270°) lands at the RIGHT — flip the sin-component.
    dx = -r * math.sin(az_rad)
    dy = -r * math.cos(az_rad)  # North is up, but image y grows down → flip cos
    return (
        _DISC_CENTER_X + int(round(dx)),
        _DISC_CENTER_Y + int(round(dy)),
    )


# ---------------------------------------------------------------------------
# Time + observation helpers
# ---------------------------------------------------------------------------


def _utc(dt: datetime) -> datetime:
    """Return *dt* expressed in UTC (naive datetimes are treated as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_observation_time(
    now: datetime,
    today: date,
    latitude: float | None,
    longitude: float | None,
) -> datetime:
    """Return the time the chart should be projected for.

    During darkness we use *now* directly.  Daylight (or twilight) renders
    are projected for tonight's solar midnight so the chart shows what the
    user will actually see tonight rather than an empty daytime sky.
    """
    if latitude is None or longitude is None or (latitude, longitude) == (0.0, 0.0):
        return _utc(now)

    st = sun_times(today, latitude, longitude)
    now_utc = _utc(now)
    sunrise = st.sunrise
    sunset = st.sunset
    if sunrise is None or sunset is None:
        return now_utc

    # If now is between sunrise and sunset (broadly daytime) project for
    # tonight's solar midnight so the chart is informative.
    if sunrise <= now_utc <= sunset:
        # Solar midnight is roughly 12 hours after the day's solar noon.
        if st.solar_noon is not None:
            return st.solar_noon + timedelta(hours=12)
    return now_utc


def _is_dark_sky(
    now: datetime,
    today: date,
    latitude: float | None,
    longitude: float | None,
) -> bool:
    """True when the sun is below the (refraction-corrected) horizon at *now*."""
    if latitude is None or longitude is None or (latitude, longitude) == (0.0, 0.0):
        return True  # No location data → assume the chart is meaningful

    lst = local_sidereal_time(_utc(now), longitude)
    # Compute sun's RA/Dec at *now* via the existing solar-declination helper —
    # the equation-of-time gives the apparent solar noon offset, which drives RA.
    from src.astronomy import _julian_day_full, _solar_declination_and_eot

    jd = _julian_day_full(_utc(now))
    decl_deg, eot_min = _solar_declination_and_eot(jd)
    # RA(sun) ≈ LST_at_solar_noon - 12h; equivalently RA(sun) hours = (mean
    # solar time hour at Greenwich + offset) — but we only need alt sign so
    # use the direct hour-angle formulation instead.
    # Hour angle of the sun ≈ LST - RA(sun); we recover RA via equation of time.
    sun_ra_deg = (lst - 15.0 * (-eot_min / 60.0 + 12.0)) % 360.0  # crude — see below
    sun_ra_hours = sun_ra_deg / 15.0
    alt, _ = equatorial_to_horizontal(sun_ra_hours, decl_deg, lst, latitude)
    return alt < SUNRISE_ALTITUDE


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------


def _star_radius(mag: float) -> int:
    """Pixel radius for a star plotted by visual magnitude (brighter = bigger)."""
    if mag < 0.0:
        return 4
    if mag < 1.0:
        return 3
    if mag < 2.0:
        return 2
    if mag < 3.0:
        return 2
    return 1


def _draw_chart_chrome(
    draw: ImageDraw.ImageDraw,
    fg,
    bg,
    accent_primary,
    accent_secondary,
    style: ThemeStyle,
) -> None:
    """Outer disc + cardinal-direction labels (N / E / S / W)."""
    # Horizon ring
    draw.ellipse(
        (
            _DISC_CENTER_X - _DISC_RADIUS,
            _DISC_CENTER_Y - _DISC_RADIUS,
            _DISC_CENTER_X + _DISC_RADIUS,
            _DISC_CENTER_Y + _DISC_RADIUS,
        ),
        outline=accent_primary,
        width=1,
    )
    # Inner reference rings at altitude 30° and 60° (very faint guides)
    for alt in (30.0, 60.0):
        r = int(_DISC_RADIUS * (90.0 - alt) / 90.0)
        # Dotted: short arc segments around the circle
        for deg_start in range(0, 360, 12):
            draw.arc(
                (
                    _DISC_CENTER_X - r,
                    _DISC_CENTER_Y - r,
                    _DISC_CENTER_X + r,
                    _DISC_CENTER_Y + r,
                ),
                deg_start,
                deg_start + 4,
                fill=accent_secondary,
                width=1,
            )

    # Cardinal direction labels just outside the rim
    label_font = (style.font_section_label or style.font_bold)(15)
    label_pad = 8
    cardinals = [
        ("N", _DISC_CENTER_X, _DISC_CENTER_Y - _DISC_RADIUS - label_pad - 8),
        ("S", _DISC_CENTER_X, _DISC_CENTER_Y + _DISC_RADIUS + label_pad),
        ("E", _DISC_CENTER_X - _DISC_RADIUS - label_pad - 6, _DISC_CENTER_Y - 6),
        ("W", _DISC_CENTER_X + _DISC_RADIUS + label_pad - 4, _DISC_CENTER_Y - 6),
    ]
    for letter, lx, ly in cardinals:
        lw = text_width(draw, letter, label_font)
        draw.text((lx - lw // 2, ly), letter, font=label_font, fill=fg)

    # bg used implicitly via canvas fill; reference it so linters don't flag.
    _ = bg


def _draw_constellation_lines(
    draw: ImageDraw.ImageDraw,
    star_xy: dict[str, tuple[int, int]],
    accent,
) -> set[str]:
    """Draw constellation outline polylines for stars currently above horizon.

    Returns the set of constellation names that had at least one segment
    drawn — caller may want to label them separately.
    """
    drawn: set[str] = set()
    for name, segments in CONSTELLATIONS.items():
        for a_name, b_name in segments:
            a = star_xy.get(a_name)
            b = star_xy.get(b_name)
            if a is None or b is None:
                continue
            draw.line([a, b], fill=accent, width=1)
            drawn.add(name)
    return drawn


def _draw_star(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    mag: float,
    fg,
    bg,
) -> None:
    """Plot one star as a filled disc with a 1px halo against the background."""
    r = _star_radius(mag)
    cx, cy = xy
    # Halo (one pixel of bg around the dot) so stars sitting on a
    # constellation line still read distinctly.
    draw.ellipse((cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1), fill=bg)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fg)


def _draw_star_label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    name: str,
    mag: float,
    style: ThemeStyle,
    fg,
) -> None:
    """Display-font label placed up-right of a labeled star."""
    label_font = (style.font_section_label or style.font_bold)(11)
    cx, cy = xy
    r = _star_radius(mag)
    # Offset: a few pixels up and to the right of the star.
    draw.text(
        (cx + r + 4, cy - r - text_height(label_font) // 2),
        name,
        font=label_font,
        fill=fg,
    )


def _draw_moon(
    draw: ImageDraw.ImageDraw,
    today: date,
    obs_time: datetime,
    latitude: float,
    longitude: float,
    style: ThemeStyle,
    fg,
    bg,
) -> bool:
    """Plot the moon at its current alt/az.  Returns True when drawn."""
    ra, dec = moon_equatorial(obs_time)
    lst = local_sidereal_time(obs_time, longitude)
    alt, az = equatorial_to_horizontal(ra, dec, lst, latitude)
    xy = _alt_az_to_chart_xy(alt, az, _DISC_RADIUS)
    if xy is None:
        return False
    cx, cy = xy
    # Halo behind the moon so the stars/lines underneath don't intersect it
    halo_r = 12
    draw.ellipse((cx - halo_r, cy - halo_r, cx + halo_r, cy + halo_r), fill=bg, outline=fg)
    # Render the actual phase glyph in the Weather Icons font
    glyph = moon_phase_glyph(today)
    glyph_font = weather_icon(20)
    bbox = draw.textbbox((0, 0), glyph, font=glyph_font)
    gw, gh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (cx - gw // 2 - bbox[0], cy - gh // 2 - bbox[1]),
        glyph,
        font=glyph_font,
        fill=fg,
    )
    return True


def _draw_constellation_label(
    draw: ImageDraw.ImageDraw,
    name: str,
    star_xy: dict[str, tuple[int, int]],
    constellation_segments: list[tuple[str, str]],
    style: ThemeStyle,
    accent,
) -> None:
    """Place a Cinzel italic constellation name above its asterism centroid."""
    points: list[tuple[int, int]] = []
    for a, b in constellation_segments:
        if a in star_xy:
            points.append(star_xy[a])
        if b in star_xy:
            points.append(star_xy[b])
    if not points:
        return
    cx = sum(p[0] for p in points) // len(points)
    cy = sum(p[1] for p in points) // len(points)
    label_font = (style.font_section_label or style.font_bold)(13)
    upper = name.upper()
    lw = text_width(draw, upper, label_font)
    draw.text((cx - lw // 2, cy - 30), upper, font=label_font, fill=accent)


# ---------------------------------------------------------------------------
# Header + footer bands
# ---------------------------------------------------------------------------


def _fmt_local_time(dt: datetime, tz: tzinfo | None) -> str:
    if dt.tzinfo is None:
        local = dt
    else:
        local = dt.astimezone(tz) if tz is not None else dt.astimezone()
    return local.strftime("%-H:%M")


def _draw_header(
    draw: ImageDraw.ImageDraw,
    region: ComponentRegion,
    obs_time: datetime,
    tz: tzinfo | None,
    style: ThemeStyle,
    fg,
) -> None:
    title_font = (style.font_section_label or style.font_bold)(16)
    info_font = style.font_medium(14)
    title = "TONIGHT'S SKY"
    draw.text((region.x + _PAD_X, region.y + 12), title, font=title_font, fill=fg)
    when = obs_time.astimezone(tz) if tz is not None and obs_time.tzinfo else obs_time
    info = when.strftime("%B %-d  ·  %-H:%M").upper()
    iw = text_width(draw, info, info_font)
    draw.text(
        (region.x + region.w - iw - _PAD_X, region.y + 13),
        info,
        font=info_font,
        fill=fg,
    )


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    region: ComponentRegion,
    today: date,
    obs_time: datetime,
    weather,
    latitude: float | None,
    longitude: float | None,
    style: ThemeStyle,
    fg,
    accent,
) -> None:
    body_font = style.font_regular(13)
    bold_font = style.font_medium(13)
    fy = region.y + region.h - _FOOTER_H + 14

    # Left side: location
    loc_parts: list[str] = []
    if weather is not None and weather.location_name:
        loc_parts.append(weather.location_name.upper())
    if latitude is not None and longitude is not None and (latitude, longitude) != (0.0, 0.0):
        ns = "N" if latitude >= 0 else "S"
        ew = "E" if longitude >= 0 else "W"
        loc_parts.append(f"{abs(latitude):.1f}°{ns}  {abs(longitude):.1f}°{ew}")
    loc = "  ·  ".join(loc_parts) if loc_parts else "OBSERVER UNSET"
    draw.text((region.x + _PAD_X, fy), loc, font=bold_font, fill=fg)

    # Right side: tonight's moon + next meteor shower
    parts: list[str] = []
    parts.append(f"Moon · {moon_phase_name(today)}")
    shower, days = next_meteor_shower(today)
    if days == 0:
        parts.append(f"{shower.name} tonight")
    elif days == 1:
        parts.append(f"{shower.name} tomorrow")
    else:
        parts.append(f"{shower.name} in {days}d")
    right = "   ·   ".join(parts)
    rw = text_width(draw, right, body_font)
    draw.text(
        (region.x + region.w - rw - _PAD_X, fy + 1),
        right,
        font=body_font,
        fill=accent,
    )

    # Reference unused obs_time intentionally — present in the signature so
    # future enhancements (e.g. tonight's astronomical-midnight LST) have it.
    _ = obs_time


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def draw_constellation_map(
    draw: ImageDraw.ImageDraw,
    data: DashboardData,
    today: date,
    now: datetime,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """Render the full-canvas constellation map inside *region*."""
    if region is None:
        region = ComponentRegion(0, 0, 800, 480)
    if style is None:
        style = ThemeStyle()

    fg = style.fg
    bg = style.bg
    accent_primary = style.primary_accent_fill()
    accent_secondary = style.secondary_accent_fill()

    weather = data.weather
    tz = now.tzinfo

    # Decide which moment to project for.  During daylight at a known location
    # we project for tonight's solar midnight; otherwise we use *now*.
    obs_time = _resolve_observation_time(now, today, latitude, longitude)

    # Header
    _draw_header(draw, region, obs_time, tz, style, fg)

    # Disc chrome (horizon, altitude rings, cardinal labels)
    _draw_chart_chrome(draw, fg, bg, accent_primary, accent_secondary, style)

    # Project every catalogue star to chart coordinates (skipping ones below
    # the horizon).
    if latitude is not None and longitude is not None and (latitude, longitude) != (0.0, 0.0):
        lst = local_sidereal_time(obs_time, longitude)
        star_xy: dict[str, tuple[int, int]] = {}
        for star in STARS:
            alt, az = equatorial_to_horizontal(star.ra, star.dec, lst, latitude)
            xy = _alt_az_to_chart_xy(alt, az, _DISC_RADIUS)
            if xy is not None:
                star_xy[star.name] = xy

        # Constellation lines first so star halos sit on top of them.
        drawn_constellations = _draw_constellation_lines(draw, star_xy, accent_secondary)

        # Stars
        for star in STARS:
            xy = star_xy.get(star.name)
            if xy is None:
                continue
            _draw_star(draw, xy, star.mag, fg, bg)

        # Star labels (only the marquee ones)
        for star_name in LABELED_STARS:
            xy = star_xy.get(star_name)
            if xy is None:
                continue
            star = STARS_BY_NAME[star_name]
            _draw_star_label(draw, xy, star.name, star.mag, style, fg)

        # Constellation labels (centred on each visible asterism)
        for cname in drawn_constellations:
            _draw_constellation_label(
                draw, cname, star_xy, CONSTELLATIONS[cname], style, accent_primary
            )

        # Moon
        _draw_moon(draw, today, obs_time, latitude, longitude, style, fg, bg)
    else:
        # No coordinates → render an explanatory message inside the disc.
        msg_font = style.font_medium(13)
        msg = "Set weather.latitude / longitude to plot the sky"
        mw = text_width(draw, msg, msg_font)
        draw.text(
            (_DISC_CENTER_X - mw // 2, _DISC_CENTER_Y - text_height(msg_font) // 2),
            msg,
            font=msg_font,
            fill=fg,
        )

    # Footer
    _draw_footer(
        draw,
        region,
        today,
        obs_time,
        weather,
        latitude,
        longitude,
        style,
        fg,
        accent_primary,
    )

    # Type-pin the lazy imports so static-analysis sees them as referenced.
    _ = (Star, dm_regular, dm_medium, cinzel_regular)
