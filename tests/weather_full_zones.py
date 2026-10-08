"""Zone geometry of ``draw_weather_full`` on an 800×480 plate, for ink measurement.

Mirrored from the component's own proportions, so a band follows the component
if its layout moves rather than pointing at blank plate.
"""

from __future__ import annotations

CANVAS_W, CANVAS_H = 800, 480

HERO_H = int(CANVAS_H * 0.44)
CARDS_H = int(CANVAS_H * 0.155)
DETAIL_H = int(CANVAS_H * 0.06)
ALERT_H = int(CANVAS_H * 0.055)

HERO = (0, 0, CANVAS_W, HERO_H)
CARDS = (0, HERO_H, CANVAS_W, HERO_H + CARDS_H)
# The thin rule above the forecast lands on the detail zone's last row, and it
# is drawn whether or not the strip has any content, so it is excluded here.
DETAIL = (0, HERO_H + CARDS_H, CANVAS_W, HERO_H + CARDS_H + DETAIL_H - 1)
ALERT = (0, HERO_H + CARDS_H + DETAIL_H, CANVAS_W, HERO_H + CARDS_H + DETAIL_H + ALERT_H)


def forecast_band(has_alerts: bool = False) -> tuple[int, int, int, int]:
    top = HERO_H + CARDS_H + DETAIL_H + (ALERT_H if has_alerts else 0)
    return (0, top, CANVAS_W, CANVAS_H)
