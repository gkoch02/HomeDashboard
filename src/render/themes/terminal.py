"""Terminal theme: white-on-black, dense, technical.

Inverted color scheme (white on black) with a compact header and wider
weather panel for a data-heavy, information-dense terminal aesthetic.
Uses Share Tech Mono for an authentic monospace terminal feel.
"""
from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle
from src.render.fonts import cyber_mono, maratype, synthetic_genesis, uesc_display


def terminal_theme() -> Theme:
    header_h = 34
    week_h = 326
    bottom_y = header_h + week_h  # 360
    bottom_h = 480 - bottom_y     # 120

    return Theme(
        name="terminal",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            header=ComponentRegion(0, 0, 800, header_h),
            week_view=ComponentRegion(0, header_h, 800, week_h),
            weather=ComponentRegion(0, bottom_y, 340, bottom_h),
            birthdays=ComponentRegion(340, bottom_y, 200, bottom_h),
            info=ComponentRegion(540, bottom_y, 260, bottom_h),
        ),
        style=ThemeStyle(
            fg=1,                     # white text / lines on black canvas
            bg=0,                     # black background
            invert_header=False,      # dark canvas already; bottom border line only
            invert_today_col=True,    # today column: white fill + black text
            invert_allday_bars=True,  # all-day bars: white fill + black text
            spacing_scale=0.85,       # tight — denser, more information visible
            label_font_size=11,
            label_font_weight="bold",
            # Share Tech Mono: monospace terminal font across all weights for
            # a consistent hacker/data-terminal aesthetic.
            font_regular=cyber_mono,
            font_medium=cyber_mono,
            font_semibold=cyber_mono,
            font_bold=cyber_mono,
            font_date_number=synthetic_genesis,
            font_month_title=uesc_display,
            font_title=maratype,
            font_section_label=uesc_display,
            font_quote=maratype,
            font_quote_author=uesc_display,
        ),
    )
