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

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from PIL import ImageDraw

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
    message_text: str | None = None
    countdown_events: list | None = None
    latitude: float | None = None
    longitude: float | None = None


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
