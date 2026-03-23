"""Old Fashioned theme: Victorian/Edwardian newspaper front page layout.

A bold inverted masthead with white corner-bracket ornaments, a triple-rule
divider band, Cinzel Roman caps for section labels, Playfair Display for body
text, a double column rule separating today's schedule from the right-hand
news sidebar, and a double-rule bottom border — the complete broadsheet
experience.

Layout (800 × 480):
  ┌────────────────────────────────────────────────────────────────────────┐
  │  [INVERTED MASTHEAD  70 px]                               ┘    White   │
  │    Title (Playfair Bold 20)              timestamp (Playfair Semi 13)  │
  │  └  corner-bracket ornaments    thin inner rule  ┘                     │
  ├──────────────────── triple-rule band (10 px) ──────────────────────────┤
  │                                     ║  ┌─────────────────────────────┐ │
  │  [today_view  490 × 400 px]         ║  │  THE WEATHER   175 px       │ │
  │   ┌────────┐                        ║  ├─────────────────────────────┤ │
  │   │ inverted│  Event list           ║  │  SOCIAL NOTICES  125 px     │ │
  │   │ date   │  (Playfair body)       ║  ├─────────────────────────────┤ │
  │   │ panel  │                        ║  │  WORDS OF WISDOM  100 px    │ │
  │   └────────┘                        ║  └─────────────────────────────┘ │
  ├─────────────────── double-rule bottom border ──────────────────────────┤
"""
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle
from src.render.fonts import (
    playfair_regular, playfair_medium, playfair_semibold, playfair_bold,
    cinzel_black,
)
from src.render.primitives import hline, vline


# ---------------------------------------------------------------------------
# Hybrid font callable: Cinzel Black for small label sizes, Playfair for body
# ---------------------------------------------------------------------------

def _press_bold(size: int):
    """Cinzel Black for small text (≤14 px — section labels, milestone tags).

    Playfair Display Bold for larger body content (temperatures, date numerals,
    event titles at 16 px+, header title at 20 px …).
    """
    if size <= 14:
        return cinzel_black(size)
    return playfair_bold(size)


# ---------------------------------------------------------------------------
# Newspaper overlay — ornamental rules, column separator, masthead ornaments
# ---------------------------------------------------------------------------

def _newspaper_overlay(draw, layout, style):
    """Draw Victorian broadsheet ornaments on top of all components.

    Renders:
    - White corner-bracket ornaments (L-shapes) inside the inverted masthead
    - A thin white inner rule inside the lower masthead for a frame effect
    - Triple horizontal rule in the 10-px band between masthead and body
    - Double vertical column rule between today_view and the right sidebar
    - Filled-square dingbats at section-junction rows on the right column
    - Double-rule bottom border across the full canvas width
    """
    W = layout.canvas_w
    H = layout.canvas_h
    fg = style.fg
    bg = style.bg
    hdr_h = layout.header.h          # masthead height  (70 px)
    body_y = layout.today_view.y     # body starts here (80 px)
    sep_x = layout.today_view.x + layout.today_view.w  # column split (490)

    # ------------------------------------------------------------------
    # 1.  Corner-bracket ornaments inside the inverted masthead (white).
    #     Each bracket is a pair of thin white rectangles forming an L-shape.
    # ------------------------------------------------------------------
    pad = 8
    arm = 11   # bracket arm length in px

    # top-left  ┌
    draw.rectangle([pad,               pad,               pad + arm, pad + 2  ], fill=bg)
    draw.rectangle([pad,               pad,               pad + 2,   pad + arm], fill=bg)
    # top-right ┐
    draw.rectangle([W - pad - arm - 1, pad,               W - pad - 1, pad + 2  ], fill=bg)
    draw.rectangle([W - pad - 2 - 1,   pad,               W - pad - 1, pad + arm], fill=bg)
    # bottom-left └
    draw.rectangle([pad,               hdr_h - pad - 2, pad + arm, hdr_h - pad], fill=bg)
    draw.rectangle([pad,               hdr_h - pad - arm, pad + 2, hdr_h - pad], fill=bg)
    # bottom-right ┘
    draw.rectangle([W - pad - arm - 1, hdr_h - pad - 2, W - pad - 1, hdr_h - pad], fill=bg)
    draw.rectangle([W - pad - 2 - 1,   hdr_h - pad - arm, W - pad - 1, hdr_h - pad], fill=bg)

    # Thin white inner rule aligned with the top of the lower bracket arms —
    # creates a subtle "picture-frame" effect inside the masthead.
    inner_x0 = pad + arm + 4
    inner_x1 = W - pad - arm - 4
    hline(draw, hdr_h - pad - 2, inner_x0, inner_x1, fill=bg)

    # ------------------------------------------------------------------
    # 2.  Triple-rule band between masthead and body  (y = hdr_h … body_y).
    #     Classic broadsheet pattern: thick–thick / gap / thin.
    # ------------------------------------------------------------------
    hline(draw, hdr_h + 2, 0, W - 1, fill=fg)
    hline(draw, hdr_h + 3, 0, W - 1, fill=fg)   # thick pair
    hline(draw, hdr_h + 7, 0, W - 1, fill=fg)   # thin accent

    # ------------------------------------------------------------------
    # 3.  Double vertical column rule separating today_view / right sidebar.
    #     Two vlines with a 2-px gap — the traditional broadsheet gutter rule.
    # ------------------------------------------------------------------
    vline(draw, sep_x,     body_y, H - 7, fill=fg)
    vline(draw, sep_x + 3, body_y, H - 7, fill=fg)

    # Small filled-square dingbat bridging the gap at the top of the rule.
    draw.rectangle([sep_x - 1, body_y - 1, sep_x + 4, body_y + 2], fill=fg)

    # ------------------------------------------------------------------
    # 4.  Dingbats where right-column section borders cross the column rule.
    # ------------------------------------------------------------------
    for junc_y in (layout.birthdays.y, layout.info.y):
        draw.rectangle([sep_x - 1, junc_y, sep_x + 4, junc_y + 1], fill=fg)

    # ------------------------------------------------------------------
    # 5.  Double-rule bottom border.
    #     Pattern: thick–thick / gap / thin  (mirrors the top triple-rule).
    # ------------------------------------------------------------------
    hline(draw, H - 6, 0, W - 1, fill=fg)
    hline(draw, H - 5, 0, W - 1, fill=fg)
    hline(draw, H - 2, 0, W - 1, fill=fg)


# ---------------------------------------------------------------------------
# Theme factory
# ---------------------------------------------------------------------------

def old_fashioned_theme() -> Theme:
    """Return the revamped Old Fashioned / Victorian broadsheet theme."""
    header_h = 70                              # tall inverted masthead
    rule_h = 10                                # decorative rule band below masthead
    body_y = header_h + rule_h                 # body components start at y=80
    body_h = 480 - body_y                      # 400 px body area

    main_w = 490                               # left column: today's schedule
    side_x = main_w
    side_w = 800 - main_w                      # 310 px right sidebar

    # Right sidebar: three stacked panels filling body_h (400 px)
    weather_h = 175
    birthday_h = 125
    info_h = body_h - weather_h - birthday_h   # 100 px

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
                side_x, body_y + weather_h, side_w, birthday_h,
            ),
            info=ComponentRegion(
                side_x, body_y + weather_h + birthday_h, side_w, info_h,
            ),
            draw_order=[
                "header", "today_view", "weather", "birthdays", "info",
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
            # Body text: Playfair Display (classic broadsheet serif).
            # Section labels (≤14 px via font_bold): Cinzel Black — Roman
            # inscription caps that evoke Victorian newspaper column headers.
            font_regular=playfair_regular,
            font_medium=playfair_medium,
            font_semibold=playfair_semibold,
            font_bold=_press_bold,
            component_labels={
                "weather":   "THE WEATHER",
                "birthdays": "SOCIAL NOTICES",
                "info":      "WORDS OF WISDOM",
            },
        ),
    )
