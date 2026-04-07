"""Graphite theme: the default weekly layout rendered in native 8-bit greyscale.

The layout is identical to the default (800×480, 40px header, 320px week view,
120px three-zone bottom bar) but the canvas uses ``canvas_mode="L"`` so every
pixel carries a full 0-255 luminance value before the final 1-bit quantization.

Two greyscale-exclusive techniques are layered on top of the standard layout:

**Tonal panel washes (background_fn)**
  The three bottom panels receive distinct light-grey fills (weather: 220,
  birthdays: 228, info: 236) before any component renders.  Where components
  leave whitespace — around labels, between quote lines, between weather rows —
  the underlying grey tint shows through, visually separating each zone from
  the clean white calendar above in a way that is impossible in 1-bit mode.

**Soft structural borders (overlay_fn)**
  After all components have drawn their solid-black structural lines, the
  overlay repaints those same borders with graduated grey values (two-tone
  shadow: dark-grey / mid-grey) so separators read as shadows rather than hard
  edges.  The week-view / bottom-bar divider gets the same treatment, giving
  the layout a subtle sense of depth.

**Quantization behaviour**
  ``threshold``       → panel washes disappear (>128 = white); grey separators
                        survive as a single mid-grey pixel row.
  ``floyd_steinberg`` → beautiful error-diffusion grain on each bottom panel;
                        the tonal differences between weather / birthdays / info
                        become clearly visible.
  ``ordered``         → Bayer dot-matrix texture on the panels; regular,
                        mechanical and distinctly greyscale in character.

Set ``display.quantization_mode: floyd_steinberg`` (or ``ordered``) in
``config/config.yaml`` to unlock the full visual effect.

Fonts: DM Sans — a crisp geometric variable sans that reads cleanly at every
size and differentiates this theme from the Plus Jakarta Sans default.
"""

from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

# ---------------------------------------------------------------------------
# Grey tones used throughout — collected here so they're easy to tune.
# ---------------------------------------------------------------------------
_GREY_WEATHER = 220   # darkest panel tint — weather has the most visual density
_GREY_BIRTHDAY = 228  # mid tint
_GREY_INFO = 236      # lightest tint — quote panel is the quietest zone

_BORDER_DARK = 80     # first (darker) row of the two-tone separator shadow
_BORDER_MID = 145     # second (lighter) row — fades toward the panel background
_BORDER_VSEP = 110    # vertical panel separator grey


# ---------------------------------------------------------------------------
# Background function — tonal washes painted BEFORE components render
# ---------------------------------------------------------------------------


def _graphite_background(image, layout, style) -> None:
    """Paint distinct grey fills on the three bottom panels."""
    from PIL import ImageDraw as _ID

    draw = _ID.Draw(image)

    by = layout.weather.y   # top of bottom bar (360 in default layout)
    bh = layout.weather.h   # height of bottom bar (120 in default layout)

    # Weather panel — darkest tint
    wx, ww = layout.weather.x, layout.weather.w
    draw.rectangle([wx, by, wx + ww - 1, by + bh - 1], fill=_GREY_WEATHER)

    # Birthdays panel — mid tint
    bx, bbw = layout.birthdays.x, layout.birthdays.w
    draw.rectangle([bx, by, bx + bbw - 1, by + bh - 1], fill=_GREY_BIRTHDAY)

    # Info / quote panel — lightest tint
    ix, iw = layout.info.x, layout.info.w
    draw.rectangle([ix, by, ix + iw - 1, by + bh - 1], fill=_GREY_INFO)


# ---------------------------------------------------------------------------
# Overlay function — soft border repainting AFTER all components render
# ---------------------------------------------------------------------------


def _graphite_overlay(draw, layout, style) -> None:
    """Repaint structural dividers with graduated grey values."""
    W = layout.canvas_w
    H = layout.canvas_h
    by = layout.weather.y   # top of bottom bar

    # ------------------------------------------------------------------
    # Horizontal divider between week view and bottom bar.
    # Two-tone shadow: a darker grey pixel sits just above a lighter one.
    # Components drew solid-black (0) here; we replace with softer values.
    # ------------------------------------------------------------------
    draw.line([(0, by), (W - 1, by)], fill=_BORDER_DARK)
    draw.line([(0, by + 1), (W - 1, by + 1)], fill=_BORDER_MID)

    # ------------------------------------------------------------------
    # Vertical separators between the three bottom panels.
    # birthday_bar draws its right-edge vline at x0+w-1; weather draws none.
    # We paint both separators in a mid-grey to unify the visual language.
    # ------------------------------------------------------------------
    sep_wx = layout.birthdays.x          # weather | birthdays  (x=300)
    sep_bx = layout.info.x - 1          # birthdays | info     (x=549)

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
            birthdays=ComponentRegion(
                L.BIRTHDAY_X, L.BIRTHDAY_Y, L.BIRTHDAY_W, L.BIRTHDAY_H
            ),
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
