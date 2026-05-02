from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import DashboardData
from src.display.backend import build_display_backend
from src.display.driver import get_display_spec
from src.render.components import (
    _builtins as _component_builtins,  # noqa: F401  registers components
)
from src.render.components.registry import RenderContext, get_component
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import (
    INKY_BLACK as _INKY_BLACK,
)
from src.render.theme import (
    INKY_BLUE as _INKY_BLUE,
)
from src.render.theme import (
    INKY_GREEN as _INKY_GREEN,
)
from src.render.theme import (
    INKY_RED as _INKY_RED,
)
from src.render.theme import (
    INKY_WHITE as _INKY_WHITE,
)
from src.render.theme import (
    INKY_YELLOW as _INKY_YELLOW,
)
from src.render.theme import Theme, default_theme

# Base resolution used when no theme is provided (legacy path).
_BASE_W = 800
_BASE_H = 480


def _resolve_inky_palette(theme: Theme) -> tuple[int, int]:
    """Return the (primary, secondary) Spectra-6 indices for *theme*.

    Priority: explicit ``ThemeStyle.inky_palette`` > registry mapping
    populated by each theme's ``register_theme`` call > default ``(BLUE, RED)``.
    """
    if theme.style.inky_palette is not None:
        return theme.style.inky_palette
    from src.render.themes.registry import get_inky_palette

    pair = get_inky_palette(theme.name)
    if pair is not None:
        return pair
    return (_INKY_BLUE, _INKY_RED)


def _resolve_inky_explicit_color(
    value: int | tuple[int, int, int] | None,
    fallback: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Resolve an explicit theme color for Inky RGB output.

    Themes may specify an RGB tuple directly or use a Spectra 6 palette index
    to override an accent role without baking backend-specific RGB values into
    the theme module.
    """
    if value is None:
        return fallback
    if isinstance(value, tuple):
        return value
    if 0 <= value < len(INKY_SPECTRA6_PALETTE):
        return INKY_SPECTRA6_PALETTE[value]
    return fallback


def _resolve_mono_explicit_color(
    value: int | tuple[int, int, int] | None,
    fallback: int | tuple[int, int, int],
    *,
    allow_grayscale: bool,
) -> int | tuple[int, int, int]:
    """Resolve explicit accent colors for monochrome or greyscale backends."""
    if value is None:
        return fallback
    if isinstance(value, tuple):
        return fallback
    if allow_grayscale:
        return value if 0 <= value <= 255 else fallback
    return value if value in (0, 1) else fallback


def _resolve_render_mode(layout_mode: str, config: DisplayConfig) -> str:
    spec = get_display_spec(config.provider, config.model)
    if spec is None:
        return layout_mode
    if spec.render_mode != "RGB":
        return layout_mode
    if layout_mode == "L":
        return "L"
    return "RGB"


def _resolve_style(theme: Theme, render_mode: str, config: DisplayConfig):
    style = theme.style
    if config.provider != "inky":
        allow_grayscale = render_mode == "L"
        return replace(
            style,
            accent_info=_resolve_mono_explicit_color(
                style.accent_info, style.fg, allow_grayscale=allow_grayscale
            ),
            accent_warn=_resolve_mono_explicit_color(
                style.accent_warn, style.fg, allow_grayscale=allow_grayscale
            ),
            accent_alert=_resolve_mono_explicit_color(
                style.accent_alert, style.fg, allow_grayscale=allow_grayscale
            ),
            accent_good=_resolve_mono_explicit_color(
                style.accent_good, style.fg, allow_grayscale=allow_grayscale
            ),
            accent_primary=_resolve_mono_explicit_color(
                style.accent_primary, style.fg, allow_grayscale=allow_grayscale
            ),
            accent_secondary=(
                _resolve_mono_explicit_color(
                    style.accent_secondary, style.fg, allow_grayscale=allow_grayscale
                )
            ),
        )
    if render_mode == "RGB":
        pal = INKY_SPECTRA6_PALETTE
        primary, secondary = _resolve_inky_palette(theme)
        return replace(
            style,
            fg=pal[_INKY_BLACK] if style.fg == 0 else pal[_INKY_WHITE],
            bg=pal[_INKY_BLACK] if style.bg == 0 else pal[_INKY_WHITE],
            accent_info=_resolve_inky_explicit_color(style.accent_info, pal[_INKY_BLUE]),
            accent_warn=_resolve_inky_explicit_color(style.accent_warn, pal[_INKY_YELLOW]),
            accent_alert=_resolve_inky_explicit_color(style.accent_alert, pal[_INKY_RED]),
            accent_good=_resolve_inky_explicit_color(style.accent_good, pal[_INKY_GREEN]),
            accent_primary=_resolve_inky_explicit_color(style.accent_primary, pal[primary]),
            accent_secondary=(_resolve_inky_explicit_color(style.accent_secondary, pal[secondary])),
        )
    return replace(
        style,
        accent_info=_resolve_mono_explicit_color(style.accent_info, style.fg, allow_grayscale=True),
        accent_warn=_resolve_mono_explicit_color(style.accent_warn, style.fg, allow_grayscale=True),
        accent_alert=_resolve_mono_explicit_color(
            style.accent_alert, style.fg, allow_grayscale=True
        ),
        accent_good=_resolve_mono_explicit_color(style.accent_good, style.fg, allow_grayscale=True),
        accent_primary=_resolve_mono_explicit_color(
            style.accent_primary, style.fg, allow_grayscale=True
        ),
        accent_secondary=_resolve_mono_explicit_color(
            style.accent_secondary, style.fg, allow_grayscale=True
        ),
    )


def render_dashboard(
    data: DashboardData,
    config: DisplayConfig,
    title: str = "Home Dashboard",
    theme: Theme | None = None,
    quote_refresh: str = "daily",
    message_text: str | None = None,
    countdown_events: list | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
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
    if config.provider == "inky" and layout.canvas_mode == "L" and layout.prefer_color_on_inky:
        render_mode = "RGB"
    style = _resolve_style(theme, render_mode, config)

    image = Image.new(render_mode, (layout.canvas_w, layout.canvas_h), style.bg)
    if layout.background_fn is not None:
        layout.background_fn(image, layout, style)
    draw = ImageDraw.Draw(image)

    now = data.fetched_at
    today = now.date() if isinstance(now, datetime) else now

    ctx = RenderContext(
        draw=draw,
        data=data,
        today=today,
        now=now,
        layout=layout,
        style=style,
        title=title,
        quote_refresh=quote_refresh,
        message_text=message_text,
        countdown_events=countdown_events,
        latitude=latitude,
        longitude=longitude,
    )

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
        adapter = get_component(name)
        if adapter is not None:
            adapter(ctx)

    # Optional theme overlay (e.g. decorative borders drawn on top of all components)
    if layout.overlay_fn is not None:
        layout.overlay_fn(draw, layout, style)

    # Delegate resize + final quantization to the backend so canvas no longer
    # forks on `config.provider`.
    backend = build_display_backend(config)
    image = backend.resize_and_finalize(
        image,
        canvas_size=(layout.canvas_w, layout.canvas_h),
        layout=layout,
    )

    return image
