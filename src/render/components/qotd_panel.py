"""Quote-of-the-Day panel and companion weather banner for the ``qotd`` theme.

Two independent draw functions:

    draw_qotd()         — Fills the main region with the day's quote, large and
                          centered, using the theme's decorative bold font.
    draw_qotd_weather() — Fills the banner region with a compact horizontal
                          weather summary (icon, temperature, conditions, forecast).
"""

from __future__ import annotations

from datetime import date

from PIL import ImageDraw

from src.data.models import WeatherData
from src.render.components.info_panel import _quote_for_today
from src.render.fonts import (
    weather_icon as weather_icon_font,
    regular as jakarta_regular,
    semibold as jakarta_semibold,
    bold as jakarta_bold,
)
from src.render.icons import draw_weather_icon, OWM_ICON_MAP, FALLBACK_ICON
from src.render.moon import moon_phase_glyph
from src.render.primitives import text_height, wrap_lines as _wrap_lines
from src.render.theme import ComponentRegion, ThemeStyle


def _icon_width(draw, owm_code: str, size: int) -> int:
    """Return the actual rendered pixel width of a weather icon glyph."""
    font = weather_icon_font(size)
    glyph = OWM_ICON_MAP.get(owm_code, FALLBACK_ICON)
    bbox = draw.textbbox((0, 0), glyph, font=font)
    return bbox[2]  # right edge from origin = true rendered width


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Main quote panel
# ---------------------------------------------------------------------------

def draw_qotd(
    draw: ImageDraw.ImageDraw,
    today: date,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw the quote of the day, typographically centered in *region*.

    Tries font sizes from large to small, picking the largest size at which
    the full quote fits vertically.  The quote text and attribution are then
    centered both horizontally and vertically within the region.
    """
    if region is None:
        region = ComponentRegion(0, 0, 800, 400)
    if style is None:
        style = ThemeStyle()

    quote = _quote_for_today(today)
    text = quote["text"]                           # marks rendered separately, large
    author = f'\u2014\u2002{quote["author"]}'      # — thin-space author

    h_pad = 52   # horizontal padding from region edges
    v_pad = 28   # vertical padding at top/bottom
    max_w = region.w - h_pad * 2

    quote_font_fn = style.font_bold
    best_size = 20
    best_lines: list[str] = []
    best_quote_font = None
    best_attr_font = None

    for size in (64, 60, 56, 52, 48, 44, 40, 36, 32, 28, 24, 20):
        q_font = quote_font_fn(size)
        a_size = max(13, int(size * 0.52))
        a_font = style.font_semibold(a_size)
        lines = _wrap_lines(text, q_font, max_w)
        lh = text_height(q_font)
        line_gap = max(4, size // 6)
        attr_gap = max(12, size // 3)
        attr_lh = text_height(a_font)
        total_h = (
            len(lines) * lh
            + max(0, len(lines) - 1) * line_gap
            + attr_gap
            + attr_lh
        )
        if total_h <= region.h - v_pad * 2:
            best_size = size
            best_lines = lines
            best_quote_font = q_font
            best_attr_font = a_font
            break

    # Fallback: force size 20, allow up to 8 lines
    if not best_lines:
        best_quote_font = quote_font_fn(20)
        best_attr_font = style.font_semibold(13)
        best_lines = _wrap_lines(text, best_quote_font, max_w)[:8]

    lh = text_height(best_quote_font)
    line_gap = max(4, best_size // 6)
    attr_gap = max(12, best_size // 3)
    attr_lh = text_height(best_attr_font)
    total_h = (
        len(best_lines) * lh
        + max(0, len(best_lines) - 1) * line_gap
        + attr_gap
        + attr_lh
    )

    # Start y for vertical centering
    text_block_top = region.y + (region.h - total_h) // 2
    text_block_bottom = text_block_top + total_h

    # ---- Decorative oversized quotation marks ----
    # Rendered at ~3.5× body size, positioned as large corner accents that
    # frame the centred quote text — opening mark top-left, closing bottom-right.
    mark_size = min(100, max(60, int(best_size * 3.0)))
    mark_font = style.font_bold(mark_size)

    for glyph, side in (('\u201c', 'open'), ('\u201d', 'close')):
        bb = draw.textbbox((0, 0), glyph, font=mark_font)
        ink_w = bb[2] - bb[0]
        ink_h = bb[3] - bb[1]

        if side == 'open':
            # Top-left: ink top sits slightly above the first text line
            px = region.x + h_pad // 4
            py = text_block_top - ink_h // 3
        else:
            # Bottom-right: ink bottom aligns near the end of the text block
            px = region.x + region.w - h_pad // 4 - ink_w
            py = text_block_bottom - ink_h * 2 // 3

        draw.text((px - bb[0], py - bb[1]), glyph, font=mark_font, fill=style.fg)

    # ---- Quote body lines (centered horizontally) ----
    y = text_block_top
    for line in best_lines:
        lw = int(best_quote_font.getlength(line))
        x = region.x + (region.w - lw) // 2
        draw.text((x, y), line, font=best_quote_font, fill=style.fg)
        y += lh + line_gap

    # Attribution — gap after last line, then centered
    y += attr_gap - line_gap
    aw = int(best_attr_font.getlength(author))
    ax = region.x + (region.w - aw) // 2
    draw.text((ax, y), author, font=best_attr_font, fill=style.fg)


# ---------------------------------------------------------------------------
# Weather banner (full-width horizontal strip)
# ---------------------------------------------------------------------------

def draw_qotd_weather(
    draw: ImageDraw.ImageDraw,
    weather: WeatherData | None,
    today: date | None = None,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
) -> None:
    """Draw a compact full-width weather banner.

    The banner is divided into four fixed zones (pixel offsets from x0):

        [ pad ][ icon + temp ][ conditions text ][ forecast cols ][ moon ][ pad ]
               |              |                  |                |
              Z1             Z2                 Z3              Z4

    Fixed zone boundaries prevent overlap regardless of font metrics or
    temperature string width.  Zone 2 text is truncated to its allocated
    width.  Zone 3 columns share whatever space remains.
    """
    if region is None:
        region = ComponentRegion(0, 400, 800, 80)
    if style is None:
        style = ThemeStyle()

    x0 = region.x
    y0 = region.y
    w = region.w
    h = region.h
    center_y = y0 + h // 2

    # Fixed zone boundaries (absolute x, relative to x0)
    PAD = 14
    Z1_X = x0 + PAD          # icon starts here
    Z2_X = x0 + 185          # conditions text starts here
    Z3_X = x0 + 430          # forecast columns start here
    MOON_W = 26               # px reserved for moon glyph on the far right
    Z3_RIGHT = x0 + w - PAD - MOON_W - 4
    Z2_MAX_W = Z3_X - Z2_X - 12   # max width for conditions text (with gap)

    if weather is None:
        msg_font = jakarta_regular(13)
        msg = "Weather unavailable"
        bbox = draw.textbbox((0, 0), msg, font=msg_font)
        mw = bbox[2] - bbox[0]
        mh = bbox[3] - bbox[1]
        draw.text(
            (x0 + (w - mw) // 2, y0 + (h - mh) // 2),
            msg, font=msg_font, fill=style.fg,
        )
        return

    # ---- Zone 1: icon + temperature ----
    icon_size = 40
    icon_y = center_y - icon_size // 2
    draw_weather_icon(draw, (Z1_X, icon_y), weather.current_icon, size=icon_size, fill=style.fg)
    icon_right = Z1_X + _icon_width(draw, weather.current_icon, icon_size)

    temp_font = jakarta_bold(34)
    temp_str = f"{weather.current_temp:.0f}°"
    temp_bbox = draw.textbbox((0, 0), temp_str, font=temp_font)
    temp_h = temp_bbox[3] - temp_bbox[1]
    temp_x = icon_right + 6
    # Compensate for font's internal top bearing so the number sits centered
    temp_y = center_y - temp_h // 2 - temp_bbox[1]
    draw.text((temp_x, temp_y), temp_str, font=temp_font, fill=style.fg)

    # ---- Zone 2: description + hi/lo + detail ----
    row_gap = 4

    desc_font = jakarta_semibold(14)
    hilo_font = jakarta_regular(13)
    detail_font = jakarta_regular(12)

    desc = weather.current_description.title()
    hilo_str = f"H:{weather.high:.0f}°  L:{weather.low:.0f}°"

    detail_parts: list[str] = []
    if weather.feels_like is not None:
        detail_parts.append(f"Feels {weather.feels_like:.0f}°")
    if weather.wind_speed is not None:
        from src.render.primitives import deg_to_compass
        wind_str = f"Wind {weather.wind_speed:.0f}mph"
        if weather.wind_deg is not None:
            wind_str += f" {deg_to_compass(weather.wind_deg)}"
        detail_parts.append(wind_str)
    detail_str = "  ·  ".join(detail_parts) if detail_parts else f"Humidity {weather.humidity}%"

    desc_h = text_height(desc_font)
    hilo_h = text_height(hilo_font)
    detail_h = text_height(detail_font)
    block_h = desc_h + row_gap + hilo_h + row_gap + detail_h
    by = center_y - block_h // 2

    from src.render.primitives import draw_text_truncated
    draw_text_truncated(draw, (Z2_X, by), desc, desc_font, Z2_MAX_W, fill=style.fg)
    by += desc_h + row_gap
    draw_text_truncated(draw, (Z2_X, by), hilo_str, hilo_font, Z2_MAX_W, fill=style.fg)
    by += hilo_h + row_gap
    draw_text_truncated(draw, (Z2_X, by), detail_str, detail_font, Z2_MAX_W, fill=style.fg)

    # ---- Zone 3: forecast columns ----
    forecast_items = weather.forecast or []
    n_cols = min(len(forecast_items), 3)

    if n_cols > 0 and Z3_X < Z3_RIGHT:
        col_w = (Z3_RIGHT - Z3_X) // n_cols
        day_font = jakarta_semibold(12)
        sm_font = jakarta_regular(12)
        fc_icon_size = 16

        for i, fc in enumerate(forecast_items[:n_cols]):
            cx = Z3_X + i * col_w
            row_lh = text_height(day_font)
            # Center the icon+text block vertically
            block_fc_h = fc_icon_size + 3 + row_lh + 3 + row_lh
            fc_y = center_y - block_fc_h // 2

            draw_weather_icon(draw, (cx, fc_y), fc.icon, size=fc_icon_size, fill=style.fg)
            # Use measured glyph width (not font size) to avoid overlap
            tx = cx + _icon_width(draw, fc.icon, fc_icon_size) + 4
            draw.text((tx, fc_y), fc.date.strftime("%a"), font=day_font, fill=style.fg)
            draw.text(
                (tx, fc_y + row_lh + 3),
                f"{fc.high:.0f}°/{fc.low:.0f}°",
                font=sm_font, fill=style.fg,
            )

    # ---- Moon phase glyph (right edge) ----
    if today is not None:
        moon_glyph = moon_phase_glyph(today)
        moon_font = weather_icon_font(22)
        moon_bbox = draw.textbbox((0, 0), moon_glyph, font=moon_font)
        moon_x = x0 + w - PAD - (moon_bbox[2] - moon_bbox[0]) - moon_bbox[0]
        moon_y = center_y - (moon_bbox[3] - moon_bbox[1]) // 2 - moon_bbox[1]
        draw.text((moon_x, moon_y), moon_glyph, font=moon_font, fill=style.fg)
