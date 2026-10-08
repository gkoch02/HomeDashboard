"""Old Fashioned theme: Victorian/Edwardian newspaper front page layout.

A newspaper nameplate (``broadsheet_masthead``: inverted band, boxed ears,
ruled dateline), Cinzel Roman caps for section labels, Playfair Display at
display sizes and Literata for running text, a double column rule separating
today's schedule from the right-hand sidebar, and a double-rule bottom border.

Layout (800 × 480):
  ┌────────────────────────────────────────────────────────────────────────┐
  │ [VOL.]           Home Dashboard (Playfair Bold 34)            [FINAL] │
  ├════════════════════════════════════════════════════════════════════════┤
  │ MONDAY, APRIL 6, 2026            ─◆─              UPDATED APR 6 · 10:30A│
  ├─────────────────────────────────────┬──────────────────────────────────┤
  │  [today_view  490 × 400 px]         ║  THE WEATHER        170 px       │
  │   inverted date panel + event list  ║  SOCIAL NOTICES     110 px       │
  │                                     ║  WORDS OF WISDOM    120 px       │
  ├─────────────────── double-rule bottom border ──────────────────────────┤
"""

from src.render.fonts import (
    cinzel_black,
    literata_bold,
    literata_semibold,
    playfair_bold,
    playfair_semibold,
)
from src.render.primitives import vline
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

# Playfair's hairlines vanish below ~15 px on a 1-bit plate, so text under that
# size is set in Literata, a screen serif with lining figures; Playfair keeps
# the display sizes. Cinzel is caps-only and is reserved for section labels.
_DISPLAY_MIN_PX = 17


def _text(size: int):
    return literata_semibold(size) if size < _DISPLAY_MIN_PX else playfair_semibold(size)


def _bold(size: int):
    return literata_bold(size) if size < _DISPLAY_MIN_PX else playfair_bold(size)


def _newspaper_overlay(draw, layout, style):
    """Column rule, junction dingbats and the bottom rule, drawn over the components."""
    W = layout.canvas_w
    H = layout.canvas_h
    fg = style.fg
    body_y = layout.today_view.y
    sep_x = layout.today_view.x + layout.today_view.w

    # Double vertical column rule — the traditional broadsheet gutter rule.
    vline(draw, sep_x, body_y, H - 7, fill=fg)
    vline(draw, sep_x + 3, body_y, H - 7, fill=fg)
    for junc_y in (layout.birthdays.y, layout.info.y):
        draw.rectangle([sep_x - 1, junc_y, sep_x + 4, junc_y + 1], fill=fg)

    # Thick pair over a thin rule closes the page.
    draw.rectangle([0, H - 6, W - 1, H - 5], fill=fg)
    draw.line([(0, H - 2), (W - 1, H - 2)], fill=fg)


def old_fashioned_theme() -> Theme:
    """Return the revamped Old Fashioned / Victorian broadsheet theme."""
    header_h = 80  # nameplate band + ruled dateline strip
    body_y = header_h
    body_h = 480 - body_y  # 400 px body area

    main_w = 490  # left column: today's schedule
    side_x = main_w
    side_w = 800 - main_w  # 310 px right sidebar

    # Right sidebar: three stacked panels filling body_h (400 px)
    weather_h = 170
    birthday_h = 110
    info_h = body_h - weather_h - birthday_h  # 120 px

    return Theme(
        name="old_fashioned",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            header=ComponentRegion(0, 0, 800, header_h),
            # Week view hidden — today_view replaces it for the broadsheet column
            week_view=ComponentRegion(0, body_y, main_w, body_h, visible=False),
            today_view=ComponentRegion(0, body_y, main_w, body_h),
            weather=ComponentRegion(side_x, body_y, side_w, weather_h),
            birthdays=ComponentRegion(
                side_x,
                body_y + weather_h,
                side_w,
                birthday_h,
            ),
            info=ComponentRegion(
                side_x,
                body_y + weather_h + birthday_h,
                side_w,
                info_h,
            ),
            draw_order=[
                "broadsheet_masthead",
                "today_view",
                "weather",
                "birthdays",
                "info",
            ],
            overlay_fn=_newspaper_overlay,
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=True,
            invert_today_col=True,
            invert_allday_bars=True,
            spacing_scale=1.0,
            label_font_size=12,
            label_font_weight="bold",
            font_regular=_text,
            font_medium=_text,
            font_semibold=_text,
            font_bold=_bold,
            font_title=playfair_bold,
            font_section_label=cinzel_black,
            font_quote=literata_semibold,
            font_quote_author=literata_semibold,
            component_labels={
                "weather": "THE WEATHER",
                "birthdays": "SOCIAL NOTICES",
                "info": "WORDS OF WISDOM",
            },
        ),
    )


def _register() -> None:
    from src.render.theme import INKY_BLACK, INKY_RED
    from src.render.themes.registry import register_theme

    register_theme("old_fashioned", old_fashioned_theme, inky_palette=(INKY_RED, INKY_BLACK))


_register()
