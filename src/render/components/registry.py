"""Component plugin registry.

Each renderable component (week_view, weather, header, qotd, …) registers
a small adapter under a stable name. ``src.render.canvas.render_dashboard``
iterates the registry instead of carrying a giant ``component_drawers``
dispatch dict.

Adapters take a single :class:`RenderContext` and pull the inputs they
need from it. The context bundles every piece of render-time state that
canvas previously passed via a positional + many-kwarg signature, so a
new component is registered with::

    from src.render.components.registry import register_component

    @register_component("my_panel")
    def _draw(ctx: RenderContext) -> None:
        my_panel.draw_my_panel(
            ctx.draw, ctx.data, ctx.today, region=ctx.layout.my_panel,
            style=ctx.style,
        )

Adding a new component is then: define ``draw_my_panel``, decorate a
single-line adapter, add the region to ``ThemeLayout``, and add the name
to the theme's ``draw_order``. No edits to ``canvas.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from PIL import Image, ImageDraw

from src.data.models import DashboardData


@dataclass(frozen=True)
class RenderContext:
    """Inputs handed to every component adapter on each render."""

    draw: ImageDraw.ImageDraw
    data: DashboardData
    today: date
    now: datetime
    layout: Any  # ThemeLayout — kept Any to avoid a circular import.
    style: Any  # ThemeStyle
    title: str = "Home Dashboard"
    quote_refresh: str = "daily"
    # Override for the daily-quote store (``quotes.path`` in config). ``None``
    # uses the bundled ``config/quotes.json``.
    quotes_path: str | None = None
    message_text: str | None = None
    countdown_events: list | None = None
    latitude: float | None = None
    longitude: float | None = None
    # State directory for components that need to persist tiny rolling state
    # files (e.g. weatherglass pressure history for the barometer trend needle).
    # ``None`` means the component should degrade gracefully without persistence.
    state_dir: str | None = None
    # Raw PIL Image backing ``draw``. Components that need pixel-level access
    # (radial gradients, paste of L-mode sub-images) use this; the rest can
    # ignore it.
    image: Image.Image | None = None
    # Canvas-coordinate rectangles ``(x0, y0, x1, y1)`` a panel declares as
    # artwork. A colour backend error-diffuses these onto the panel's inks
    # instead of snapping them, so a gradient keeps its halftone and a tone
    # the panel has no ink for becomes a mixture of the inks it has; type and
    # rules outside them stay solid. Adapters append here — see
    # ``_builtins`` — using the panel's own pure ``art_rect()`` so the panel
    # itself stays a pure function of its inputs.
    dither_regions: list[tuple[int, int, int, int]] = field(default_factory=list)


ComponentAdapter = Callable[[RenderContext], None]

_REGISTRY: dict[str, ComponentAdapter] = {}


def register_component(name: str) -> Callable[[ComponentAdapter], ComponentAdapter]:
    """Decorator that registers *name* → the decorated adapter.

    Re-registration with the same name is a silent no-op so module
    reloads in tests don't raise. Use :func:`unregister_component` to
    genuinely replace.
    """

    def _decorate(adapter: ComponentAdapter) -> ComponentAdapter:
        if name not in _REGISTRY:
            _REGISTRY[name] = adapter
        return adapter

    return _decorate


def unregister_component(name: str) -> None:
    """Remove *name* from the registry. Used by tests."""
    _REGISTRY.pop(name, None)


def get_component(name: str) -> ComponentAdapter | None:
    """Return the adapter registered under *name*, or ``None``."""
    return _REGISTRY.get(name)


def all_component_names() -> list[str]:
    """Return all registered component names in registration order."""
    return list(_REGISTRY.keys())
