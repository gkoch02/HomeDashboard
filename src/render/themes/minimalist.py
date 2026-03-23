"""Minimalist theme: Bauhaus — form follows function, the grid is the content.

Ultra-slim 22px header (no fill, no border). The week grid dominates
at 374px — 54px more than the default. Today's column is marked with a full
inverted black header block (not a soft double-underline) — the NOW is declared.
All-day event bars are filled black. Events pack to a 1.0× grid.

A 100px bottom strip splits asymmetrically: weather at 500px (wider,
proportioned ~5:3) and quote at 300px. Section labels are 8pt regular —
functional, recessive. The quote label collapses to a single em dash.

No structural borders or separator lines — pure whitespace defines the regions.

Font: DM Sans — geometric, screen-optimized variable sans. Each weight is used
at its optical sweet spot.
"""
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle
from src.render.fonts import dm_regular, dm_medium, dm_semibold, dm_bold


def minimalist_theme() -> Theme:
    header_h = 22
    bottom_h = 100
    week_h = 480 - header_h - bottom_h     # 358px
    bottom_y = header_h + week_h            # 396

    return Theme(
        name="minimalist",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            header=ComponentRegion(0, 0, 800, header_h),
            week_view=ComponentRegion(0, header_h, 800, week_h),
            weather=ComponentRegion(0, bottom_y, 500, bottom_h),
            birthdays=ComponentRegion(0, 0, 0, 0, visible=False),
            info=ComponentRegion(500, bottom_y, 300, bottom_h),
            draw_order=["header", "week_view", "weather", "info"],
        ),
        style=ThemeStyle(
            fg=0,
            bg=1,
            invert_header=False,          # no filled bar, no border line
            invert_today_col=False,       # subtle border around today's column header
            invert_allday_bars=False,     # outlined all-day bars, no fill
            show_borders=False,           # no structural borders or separator lines
            spacing_scale=1.0,            # tight, grid-precise event packing
            label_font_size=8,            # labels recede; data leads
            label_font_weight="regular",
            component_labels={"info": "—"},   # strip verbose "QUOTE OF THE DAY"
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
        ),
    )
