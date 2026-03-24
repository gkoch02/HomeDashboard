from datetime import datetime
from PIL import Image, ImageDraw

from src.data.models import DashboardData
from src.config import DisplayConfig
from src.render.components import (
    header, week_view, weather_panel, birthday_bar, info_panel, today_view, qotd_panel,
    weather_full as weather_full_comp, fuzzyclock_panel,
)
from src.render.theme import Theme, default_theme

# Base resolution used when no theme is provided (legacy path).
_BASE_W = 800
_BASE_H = 480


def render_dashboard(
    data: DashboardData,
    config: DisplayConfig,
    title: str = "Home Dashboard",
    theme: Theme | None = None,
) -> Image.Image:
    """Compose all components onto a 1-bit image at the configured display resolution.

    Components are drawn at the theme's base canvas size (default: 800×480).
    If the configured display differs, the image is scaled to native resolution
    via LANCZOS resampling before being returned.

    When *theme* is ``None``, the default theme is used, producing output
    identical to the pre-theme rendering.
    """
    if theme is None:
        theme = default_theme()

    layout = theme.layout
    style = theme.style

    image = Image.new("1", (layout.canvas_w, layout.canvas_h), style.bg)
    draw = ImageDraw.Draw(image)

    now = data.fetched_at
    today = now.date() if isinstance(now, datetime) else now

    week_forecast = data.weather.forecast if data.weather else None

    # Build the dispatcher: component name → lambda that draws it
    component_drawers = {
        "header": lambda: header.draw_header(
            draw, now,
            is_stale=data.is_stale,
            title=title,
            source_staleness=data.source_staleness,
            region=layout.header,
            style=style,
        ),
        "week_view": lambda: week_view.draw_week(
            draw, data.events, today,
            forecast=week_forecast,
            region=layout.week_view,
            style=style,
        ),
        "weather": lambda: weather_panel.draw_weather(
            draw, data.weather, today=today,
            air_quality=data.air_quality,
            region=layout.weather,
            style=style,
        ),
        "birthdays": lambda: birthday_bar.draw_birthdays(
            draw, data.birthdays, today,
            region=layout.birthdays,
            style=style,
        ),
        "info": lambda: info_panel.draw_info(
            draw, today,
            region=layout.info,
            style=style,
        ),
        "today_view": lambda: today_view.draw_today(
            draw, data.events, today,
            forecast=week_forecast,
            region=layout.today_view,
            style=style,
        ),
        "qotd": lambda: qotd_panel.draw_qotd(
            draw, today,
            region=layout.qotd,
            style=style,
        ),
        "qotd_weather": lambda: qotd_panel.draw_qotd_weather(
            draw, data.weather, today,
            region=layout.weather,
            style=style,
        ),
        "weather_full": lambda: weather_full_comp.draw_weather_full(
            draw, data.weather, today,
            air_quality=data.air_quality,
            region=layout.weather_full,
            style=style,
        ),
        "fuzzyclock": lambda: fuzzyclock_panel.draw_fuzzyclock(
            draw, now,
            region=layout.fuzzyclock,
            style=style,
        ),
        "fuzzyclock_weather": lambda: qotd_panel.draw_qotd_weather(
            draw, data.weather, today,
            region=layout.weather,
            style=style,
        ),
    }

    # Config visibility overrides (show_weather etc.) respected regardless of draw_order
    visibility = {
        "weather": config.show_weather,
        "birthdays": config.show_birthdays,
        "info": config.show_info_panel,
    }

    for name in layout.draw_order:
        region = getattr(layout, name, None)
        # Skip if the region itself is marked not visible
        if region is not None and not region.visible:
            continue
        # Skip if the DisplayConfig visibility flag is False
        if not visibility.get(name, True):
            continue
        drawer = component_drawers.get(name)
        if drawer is not None:
            drawer()

    # Optional theme overlay (e.g. decorative borders drawn on top of all components)
    if layout.overlay_fn is not None:
        layout.overlay_fn(draw, layout, style)

    # Scale to native display resolution when it differs from the base canvas size
    if (config.width, config.height) != (layout.canvas_w, layout.canvas_h):
        image = (
            image.convert("L")
            .resize((config.width, config.height), Image.LANCZOS)
            .convert("1")
        )

    return image
