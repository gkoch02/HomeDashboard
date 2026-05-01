"""Theme plugin registry.

Each theme module registers a name → factory pair (and an optional Inky
Spectra-6 ``(primary, secondary)`` palette pair) via :func:`register_theme`.
``src.render.theme.load_theme`` iterates this registry to resolve a name to
a concrete ``Theme`` instance, and ``AVAILABLE_THEMES`` is derived from the
registered names.

Adding a new theme is a single registration call at the bottom of the
theme's module::

    from src.render.theme import INKY_BLUE, INKY_RED
    from src.render.themes.registry import register_theme

    def my_theme() -> Theme:
        return Theme(...)

    register_theme("my_theme", my_theme, inky_palette=(INKY_BLUE, INKY_RED))

The package's ``__init__`` imports every built-in theme module so any
caller of :func:`available_themes` sees a fully-populated registry.
"""

from __future__ import annotations

from typing import Any, Callable

ThemeFactory = Callable[[], Any]

# Pseudo-theme names that are not registered as concrete factories but
# are still accepted by CLI / config (resolved at run-time to a real theme).
PSEUDO_THEME_NAMES: frozenset[str] = frozenset(
    {"default", "random", "random_daily", "random_hourly"}
)

# (primary, secondary) Spectra-6 palette index pair for each registered theme.
# When unset, the canvas falls back to ``(INKY_BLUE, INKY_RED)``.
_REGISTRY: dict[str, ThemeFactory] = {}
_INKY_PALETTES: dict[str, tuple[int, int]] = {}


def register_theme(
    name: str,
    factory: ThemeFactory,
    *,
    inky_palette: tuple[int, int] | None = None,
) -> ThemeFactory:
    """Register *factory* under *name*. Duplicate registrations are a no-op.

    Re-registration is silent so module reloads in tests don't raise. Use
    :func:`unregister_theme` first to genuinely replace.
    """
    if name in _REGISTRY:
        return _REGISTRY[name]
    _REGISTRY[name] = factory
    if inky_palette is not None:
        _INKY_PALETTES[name] = inky_palette
    return factory


def unregister_theme(name: str) -> None:
    """Remove *name* from the registry. Used by tests."""
    _REGISTRY.pop(name, None)
    _INKY_PALETTES.pop(name, None)


def get_theme_factory(name: str) -> ThemeFactory | None:
    """Return the registered factory for *name*, or ``None``."""
    return _REGISTRY.get(name)


def get_inky_palette(name: str) -> tuple[int, int] | None:
    """Return the registered Inky Spectra-6 ``(primary, secondary)`` pair, or ``None``."""
    return _INKY_PALETTES.get(name)


def all_theme_names() -> list[str]:
    """Return all registered concrete theme names in registration order."""
    return list(_REGISTRY.keys())


def available_themes() -> frozenset[str]:
    """Return concrete + pseudo theme names accepted by the CLI / config."""
    return frozenset(_REGISTRY.keys()) | PSEUDO_THEME_NAMES
