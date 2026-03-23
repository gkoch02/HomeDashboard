"""Full-screen weather theme.

Devotes the entire 800×480 canvas to a rich weather display inspired by
iOS Weather and Foreca Weather.  The upper two-thirds show the current
conditions at a glance — large icon, hero temperature, description, and
a row of metric cards — while the lower third presents a clean five-day
forecast grid.

Layout (800 × 480):
  ┌──────────────────────────────────────────────────────────────────────┐
  │                      [weather icon, 80px]                           │
  │                           72°                                       │
  │                      Partly Cloudy                                  │
  │                     H: 78°  ·  L: 60°                              │
  │                                                                     │
  │   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
  │   │ Feels 70°│  │Wind 5 NW │  │ Hum 45%  │  │  UV 3    │          │
  │   └──────────┘  └──────────┘  └──────────┘  └──────────┘          │
  │                                                                     │
  │   ↑6:24a  ↓7:45p    ·    1013 hPa    ·    🌒 Waxing Crescent      │
  │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
  │   Mon        Tue        Wed        Thu        Fri                   │
  │  [icon]     [icon]     [icon]     [icon]     [icon]                │
  │  58°/42°    62°/48°    55°/40°    60°/44°    57°/41°              │
  │   10%        30%        60%         —          —                    │
  └──────────────────────────────────────────────────────────────────────┘

Font: DM Sans — geometric, modern, excellent legibility on eInk.
"""

from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle
from src.render.fonts import dm_regular, dm_medium, dm_semibold, dm_bold


def weather_theme() -> Theme:
    """Return the full-screen weather theme."""
    return Theme(
        name="weather",
        layout=ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            # Hide all standard components
            header=ComponentRegion(0, 0, 800, 40, visible=False),
            week_view=ComponentRegion(0, 0, 800, 320, visible=False),
            weather=ComponentRegion(0, 0, 300, 120, visible=False),
            birthdays=ComponentRegion(0, 0, 250, 120, visible=False),
            info=ComponentRegion(0, 0, 250, 120, visible=False),
            today_view=ComponentRegion(0, 0, 800, 280, visible=False),
            qotd=ComponentRegion(0, 0, 800, 400, visible=False),
            # Full-screen weather region
            weather_full=ComponentRegion(0, 0, 800, 480),
            draw_order=["weather_full"],
        ),
        style=ThemeStyle(
            fg=0,   # black on white — optimal eInk contrast
            bg=1,
            invert_header=False,
            invert_today_col=False,
            invert_allday_bars=False,
            show_borders=False,   # whitespace-defined layout
            font_regular=dm_regular,
            font_medium=dm_medium,
            font_semibold=dm_semibold,
            font_bold=dm_bold,
            label_font_size=10,
            label_font_weight="semibold",
        ),
    )
