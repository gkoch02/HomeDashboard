from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import DashboardData
from src.display.driver import get_display_spec
from src.render.components import (
    air_quality_panel,
    birthday_bar,
    diags_panel,
    fuzzyclock_panel,
    header,
    info_panel,
    message_panel,
    moonphase_panel,
    qotd_panel,
    scorecard_panel,
    sunrise_panel,
    tides_panel,
    timeline_panel,
    today_view,
    weather_panel,
    week_view,
    year_pulse_panel,
)
from src.render.components import (
    weather_full as weather_full_comp,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE, quantize_for_display, quantize_to_palette
from src.render.theme import Theme, default_theme

# Base resolution used when no theme is provided (legacy path).
_BASE_W = 800
_BASE_H = 480

_INKY_BLACK = 0
_INKY_WHITE = 1
_INKY_RED = 2
_INKY_BLUE = 3
_INKY_YELLOW = 4
_INKY_GREEN = 5

_INKY_THEME_KEY_COLORS: dict[str, tuple[int, int]] = {
    "default": (_INKY_BLUE, _INKY_RED),
    "terminal": (_INKY_GREEN, _INKY_YELLOW),
    "minimalist": (_INKY_BLUE, _INKY_RED),
    "old_fashioned": (_INKY_RED, _INKY_YELLOW),
    "today": (_INKY_BLUE, _INKY_RED),
    "fantasy": (_INKY_RED, _INKY_YELLOW),
    "qotd": (_INKY_BLUE, _INKY_RED),
    "qotd_invert": (_INKY_YELLOW, _INKY_RED),
    "weather": (_INKY_BLUE, _INKY_YELLOW),
    "fuzzyclock": (_INKY_YELLOW, _INKY_BLUE),
    "fuzzyclock_invert": (_INKY_YELLOW, _INKY_BLUE),
    "diags": (_INKY_GREEN, _INKY_BLUE),
    "air_quality": (_INKY_BLUE, _INKY_GREEN),
    "moonphase": (_INKY_BLUE, _INKY_YELLOW),
    "moonphase_invert": (_INKY_YELLOW, _INKY_BLUE),
    "message": (_INKY_RED, _INKY_BLUE),
    "timeline": (_INKY_BLUE, _INKY_RED),
    "year_pulse": (_INKY_GREEN, _INKY_BLUE),
    "sunrise": (_INKY_YELLOW, _INKY_RED),
    "scorecard": (_INKY_RED, _INKY_BLUE),
    "tides": (_INKY_BLUE, _INKY_YELLOW),
    "photo": (_INKY_BLUE, _INKY_RED),
}


def _resolve_render_mode(layout_mode: str, config: DisplayConfig) -> str:
    spec = get_display_spec(config.provider, config.model)
    if spec is None:
        return layout_mode
    if spec.render_mode != "RGB":
        return layout_mode
    if layout_mode == "L":
        return "L"
    return "P"


def _resolve_style(theme: Theme, render_mode: str, config: DisplayConfig):
    style = theme.style
    if config.provider != "inky":
        return replace(
            style,
            accent_info=style.fg if style.accent_info is None else style.accent_info,
            accent_warn=style.fg if style.accent_warn is None else style.accent_warn,
            accent_alert=style.fg if style.accent_alert is None else style.accent_alert,
            accent_good=style.fg if style.accent_good is None else style.accent_good,
            accent_primary=style.fg if style.accent_primary is None else style.accent_primary,
            accent_secondary=(
                style.fg if style.accent_secondary is None else style.accent_secondary
            ),
        )
    if render_mode == "P":
        primary, secondary = _INKY_THEME_KEY_COLORS.get(theme.name, (_INKY_BLUE, _INKY_RED))
        return replace(
            style,
            fg=_INKY_BLACK if style.fg == 0 else _INKY_WHITE,
            bg=_INKY_BLACK if style.bg == 0 else _INKY_WHITE,
            accent_info=_INKY_BLUE if style.accent_info is None else style.accent_info,
            accent_warn=_INKY_YELLOW if style.accent_warn is None else style.accent_warn,
            accent_alert=_INKY_RED if style.accent_alert is None else style.accent_alert,
            accent_good=_INKY_GREEN if style.accent_good is None else style.accent_good,
            accent_primary=primary if style.accent_primary is None else style.accent_primary,
            accent_secondary=(
                secondary if style.accent_secondary is None else style.accent_secondary
            ),
        )
    return replace(
        style,
        accent_info=style.fg if style.accent_info is None else style.accent_info,
        accent_warn=style.fg if style.accent_warn is None else style.accent_warn,
        accent_alert=style.fg if style.accent_alert is None else style.accent_alert,
        accent_good=style.fg if style.accent_good is None else style.accent_good,
        accent_primary=style.fg if style.accent_primary is None else style.accent_primary,
        accent_secondary=style.fg if style.accent_secondary is None else style.accent_secondary,
    )


def _inky_palette_image() -> Image.Image:
    palette = Image.new("P", (1, 1))
    flat: list[int] = []
    for r, g, b in INKY_SPECTRA6_PALETTE:
        flat.extend([r, g, b])
    flat.extend([0] * (768 - len(flat)))
    palette.putpalette(flat)
    return palette


def render_dashboard(
    data: DashboardData,
    config: DisplayConfig,
    title: str = "Home Dashboard",
    theme: Theme | None = None,
    quote_refresh: str = "daily",
    message_text: str | None = None,
) -> Image.Image:
    """Compose all components onto a 1-bit image at the configured display resolution.

    Components are drawn at the theme's base canvas size (default: 800×480) using the
    canvas mode declared by the theme (``layout.canvas_mode``; ``"1"`` for all existing
    themes, ``"L"`` for new greyscale themes that opt in).

    If the configured display differs from the canvas size, the image is scaled to native
    resolution via LANCZOS resampling.  The final quantization step (``"L"`` → ``"1"``)
    is applied whenever a resize occurred OR the canvas mode is ``"L"``.  The algorithm
    used is controlled by ``config.quantization_mode`` (default: ``"threshold"``).

    When *theme* is ``None``, the default theme is used, producing output
    identical to the pre-theme rendering.
    """
    if theme is None:
        theme = default_theme()

    layout = theme.layout
    render_mode = _resolve_render_mode(layout.canvas_mode, config)
    style = _resolve_style(theme, render_mode, config)

    image = Image.new(render_mode, (layout.canvas_w, layout.canvas_h), style.bg)
    if render_mode == "P":
        palette = _inky_palette_image().getpalette()
        if palette is None:
            raise RuntimeError("Inky palette image is missing a palette")
        image.putpalette(palette)
    if layout.background_fn is not None:
        layout.background_fn(image, layout, style)
    draw = ImageDraw.Draw(image)

    now = data.fetched_at
    today = now.date() if isinstance(now, datetime) else now

    week_forecast = data.weather.forecast if data.weather else None

    # Build the dispatcher: component name → lambda that draws it
    component_drawers = {
        "header": lambda: header.draw_header(
            draw,
            now,
            is_stale=data.is_stale,
            title=title,
            source_staleness=data.source_staleness,
            region=layout.header,
            style=style,
        ),
        "week_view": lambda: week_view.draw_week(
            draw,
            data.events,
            today,
            forecast=week_forecast,
            region=layout.week_view,
            style=style,
        ),
        "weather": lambda: weather_panel.draw_weather(
            draw,
            data.weather,
            today=today,
            air_quality=data.air_quality,
            region=layout.weather,
            style=style,
            staleness=data.source_staleness.get("weather"),
        ),
        "birthdays": lambda: birthday_bar.draw_birthdays(
            draw,
            data.birthdays,
            today,
            region=layout.birthdays,
            style=style,
            staleness=data.source_staleness.get("birthdays"),
        ),
        "info": lambda: info_panel.draw_info(
            draw,
            today,
            region=layout.info,
            style=style,
            quote_refresh=quote_refresh,
        ),
        "today_view": lambda: today_view.draw_today(
            draw,
            data.events,
            today,
            forecast=week_forecast,
            region=layout.today_view,
            style=style,
        ),
        "qotd": lambda: qotd_panel.draw_qotd(
            draw,
            today,
            region=layout.qotd,
            style=style,
            quote_refresh=quote_refresh,
        ),
        "qotd_weather": lambda: qotd_panel.draw_qotd_weather(
            draw,
            data.weather,
            today,
            region=layout.weather,
            style=style,
        ),
        "weather_full": lambda: weather_full_comp.draw_weather_full(
            draw,
            data.weather,
            today,
            air_quality=data.air_quality,
            region=layout.weather_full,
            style=style,
        ),
        "fuzzyclock": lambda: fuzzyclock_panel.draw_fuzzyclock(
            draw,
            now,
            region=layout.fuzzyclock,
            style=style,
        ),
        "fuzzyclock_weather": lambda: qotd_panel.draw_qotd_weather(
            draw,
            data.weather,
            today,
            region=layout.weather,
            style=style,
        ),
        "diags": lambda: diags_panel.draw_diags(
            draw,
            data,
            today,
            region=layout.diags,
            style=style,
        ),
        "air_quality_full": lambda: air_quality_panel.draw_air_quality_full(
            draw,
            data,
            today,
            region=layout.air_quality_full,
            style=style,
        ),
        "moonphase_full": lambda: moonphase_panel.draw_moonphase(
            draw,
            data,
            today,
            region=layout.moonphase_full,
            style=style,
            quote_refresh=quote_refresh,
        ),
        "message": lambda: message_panel.draw_message(
            draw,
            message_text or "",
            region=layout.message,
            style=style,
        ),
        "message_weather": lambda: qotd_panel.draw_qotd_weather(
            draw,
            data.weather,
            today,
            region=layout.weather,
            style=style,
        ),
        "timeline": lambda: timeline_panel.draw_timeline(
            draw,
            data.events,
            today,
            now,
            region=layout.timeline,
            style=style,
        ),
        "year_pulse": lambda: year_pulse_panel.draw_year_pulse(
            draw,
            data,
            today,
            region=layout.year_pulse,
            style=style,
        ),
        "sunrise": lambda: sunrise_panel.draw_sunrise(
            draw,
            data,
            today,
            now,
            region=layout.sunrise,
            style=style,
        ),
        "scorecard": lambda: scorecard_panel.draw_scorecard(
            draw,
            data,
            today,
            now,
            region=layout.scorecard,
            style=style,
            quote_refresh=quote_refresh,
        ),
        "tides": lambda: tides_panel.draw_tides(
            draw,
            data,
            today,
            now,
            region=layout.tides,
            style=style,
            quote_refresh=quote_refresh,
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

    # Scale to native display resolution and/or quantize to 1-bit.
    # Quantization is needed whenever a resize occurred (LANCZOS produces grey pixels)
    # or the theme rendered onto a greyscale canvas (canvas_mode == "L").
    needs_resize = (config.width, config.height) != (layout.canvas_w, layout.canvas_h)
    target_is_color = config.provider == "inky"
    needs_quantize = (needs_resize or layout.canvas_mode == "L") and not target_is_color

    if needs_resize:
        if target_is_color:
            image = image.convert("RGB").resize(
                (config.width, config.height), Image.Resampling.LANCZOS
            )
        else:
            l_image = image if layout.canvas_mode == "L" else image.convert("L")
            image = l_image.resize((config.width, config.height), Image.Resampling.LANCZOS)

    if needs_quantize:
        image = quantize_for_display(image, config.quantization_mode)
    elif target_is_color:
        image = quantize_to_palette(image, INKY_SPECTRA6_PALETTE)

    return image
