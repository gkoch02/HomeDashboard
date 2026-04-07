"""Graphite theme: the default weekly layout rendered in native 8-bit greyscale.

The layout is identical to the default (800×480, 40px header, 320px week view,
120px three-zone bottom bar) but the canvas uses ``canvas_mode="L"`` so every
pixel carries a full 0-255 luminance value before the final 1-bit quantization.

Three greyscale-exclusive techniques are layered on top of the standard layout:

**Date cell wash (background_fn)**
  The combined Sat/Sun date cell (the large "APRIL / 7" zone in the lower-right
  corner of the week view) receives a medium-grey fill (155) before the week
  component renders.  The component draws the inverted APRIL band and the big
  day-number on top; the grey shows through in the open space around and below
  the numerals, framing the date in a tonal field that is impossible in 1-bit.
  After floyd_steinberg or ordered dithering this produces a clearly visible
  ~37 % black-pixel halftone; after threshold it collapses to white (graceful
  degradation, no visual difference from default).

**Tonal panel washes (background_fn)**
  The three bottom panels each receive a distinct grey fill — weather at 160
  (~37 %), birthdays at 175 (~31 %), info at 190 (~25 %) — before any component
  renders.  Because the components draw only text and borders, not background
  fills, the grey persists in all the open whitespace around labels, between
  event rows, and beside the weather icon.  The result is three tonal zones that
  are visually distinct from each other and from the clean white calendar above.

**Soft structural borders (overlay_fn)**
  After all components have drawn their solid-black (0) structural lines, the
  overlay repaints those dividers with graduated grey values — a two-tone shadow
  (dark 80 / light 150) at the horizontal week-view / bottom-bar boundary, and a
  mid-grey (115) for the two vertical panel separators — so dividers read as
  shadows rather than hard black rules.

**Quantization guide**
  ``threshold``       → date cell and panel washes collapse to white (>128);
                        the dark row of the two-tone border (80) survives as
                        a single thin line.  Appearance matches the default.
  ``floyd_steinberg`` → recommended; all three grey zones show as clearly
                        visible, softly-grained tonal fields.
  ``ordered``         → Bayer dot-matrix texture on each grey zone; regular,
                        mechanical, and distinctly greyscale in character.

Set ``display.quantization_mode: floyd_steinberg`` (or ``ordered``) in
``config/config.yaml`` to unlock the full visual effect.

Fonts: DM Sans — a crisp geometric variable sans that differentiates this theme
from the Plus Jakarta Sans default.
"""

from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

# ---------------------------------------------------------------------------
# Grey tones used throughout — collected here so they're easy to tune.
# ---------------------------------------------------------------------------

# Date cell: the APRIL/7 area in the lower-right of the week view.
# 155 → ~37 % black pixels after floyd_steinberg.
_GREY_DATE_CELL = 155

# Bottom panel backgrounds — three distinct, clearly-separable tones.
_GREY_WEATHER = 160  # darkest (~37 % density)
_GREY_BIRTHDAY = 175  # mid     (~31 % density)
_GREY_INFO = 190  # lightest (~25 % density)

# Overlay border values.
_BORDER_DARK = 80  # darker row of the two-tone horizontal shadow
_BORDER_LIGHT = 150  # lighter row — fades toward panel background
_BORDER_VSEP = 115  # vertical panel separator grey


# ---------------------------------------------------------------------------
# Background function — tonal washes painted BEFORE components render
# ---------------------------------------------------------------------------


def _graphite_background(image, layout, style) -> None:
    """Paint grey fills on the date cell and the three bottom panels."""
    from PIL import ImageDraw as _ID

    draw = _ID.Draw(image)

    wv = layout.week_view
    W = wv.w
    H_wv = wv.h

    # ------------------------------------------------------------------
    # Combined date cell (Sat + Sun lower half): the big "APRIL / 7" zone.
    # Mirrors the geometry calculated inside draw_week():
    #   header_h = max(24, H_wv * 32 // 320)
    #   body_h = H_wv - header_h
    #   date_section_h = body_h // 2
    #   date_y = wv.y + header_h + body_h - date_section_h
    #   sat_cx = wv.x + 5 * (W // 7)
    # ------------------------------------------------------------------
    col_w = W // 7
    header_h = max(24, H_wv * 32 // 320)
    body_h = H_wv - header_h
    date_section_h = body_h // 2
    date_y = wv.y + header_h + body_h - date_section_h
    sat_cx = wv.x + 5 * col_w

    draw.rectangle(
        [sat_cx, date_y, wv.x + W - 1, wv.y + H_wv - 1],
        fill=_GREY_DATE_CELL,
    )

    # ------------------------------------------------------------------
    # Bottom bar panels — three tonal zones.
    # ------------------------------------------------------------------
    by = layout.weather.y
    bh = layout.weather.h

    draw.rectangle(
        [layout.weather.x, by, layout.weather.x + layout.weather.w - 1, by + bh - 1],
        fill=_GREY_WEATHER,
    )
    draw.rectangle(
        [layout.birthdays.x, by, layout.birthdays.x + layout.birthdays.w - 1, by + bh - 1],
        fill=_GREY_BIRTHDAY,
    )
    draw.rectangle(
        [layout.info.x, by, layout.info.x + layout.info.w - 1, by + bh - 1],
        fill=_GREY_INFO,
    )


# ---------------------------------------------------------------------------
# Overlay function — soft border repainting AFTER all components render
# ---------------------------------------------------------------------------


def _graphite_overlay(draw, layout, style) -> None:
    """Repaint structural dividers with graduated grey values."""
    W = layout.canvas_w
    H = layout.canvas_h
    by = layout.weather.y  # top of bottom bar (360 in default layout)

    # ------------------------------------------------------------------
    # Horizontal divider above the bottom bar — two-tone shadow.
    # ------------------------------------------------------------------
    draw.line([(0, by), (W - 1, by)], fill=_BORDER_DARK)
    draw.line([(0, by + 1), (W - 1, by + 1)], fill=_BORDER_LIGHT)

    # ------------------------------------------------------------------
    # Vertical separators between the three bottom panels.
    # ------------------------------------------------------------------
    sep_wx = layout.birthdays.x  # weather | birthdays  (x=300)
    sep_bx = layout.info.x - 1  # birthdays | info     (x=549)

    for sx in (sep_wx, sep_bx):
        draw.line([(sx, by + 2), (sx, H - 1)], fill=_BORDER_VSEP)


# ---------------------------------------------------------------------------
# Theme factory
# ---------------------------------------------------------------------------


def graphite_theme() -> Theme:
    """Return the Graphite theme: default layout with L-mode greyscale depth."""
    from src.render import layout as L
    from src.render.fonts import dm_bold, dm_medium, dm_regular, dm_semibold

    return Theme(
        name="graphite",
        layout=ThemeLayout(
            canvas_w=L.WIDTH,
            canvas_h=L.HEIGHT,
            canvas_mode="L",
            header=ComponentRegion(0, L.HEADER_Y, L.WIDTH, L.HEADER_H),
            week_view=ComponentRegion(L.WEEK_X, L.WEEK_Y, L.WEEK_W, L.WEEK_H),
            weather=ComponentRegion(L.WEATHER_X, L.WEATHER_Y, L.WEATHER_W, L.WEATHER_H),
            birthdays=ComponentRegion(L.BIRTHDAY_X, L.BIRTHDAY_Y, L.BIRTHDAY_W, L.BIRTHDAY_H),
            info=ComponentRegion(L.INFO_X, L.INFO_Y, L.INFO_W, L.INFO_H),
            draw_order=["header", "week_view", "weather", "birthdays", "info"],
            background_fn=_graphite_background,
            overlay_fn=_graphite_overlay,
        ),
        style=ThemeStyle(
            fg=0,
            bg=255,
            invert_header=True,
            invert_today_col=True,
            invert_allday_bars=True,
            show_borders=True,
            show_forecast_strip=True,
            spacing_scale=1.0,
            label_font_size=12,
            label_font_weight="semibold",
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
        ),
    )
