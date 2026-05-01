"""Contract tests for the v5 render-side registries.

Guards the public shape of:
- ``src.render.themes.registry`` — the theme name → factory map plus its
  per-theme Inky Spectra-6 palette mapping.
- ``src.render.components.registry`` — the component name → adapter map
  iterated by ``render_dashboard``.
"""

from __future__ import annotations

import pytest

from src.render.components.registry import (
    RenderContext,
    all_component_names,
    get_component,
    register_component,
    unregister_component,
)
from src.render.theme import (
    AVAILABLE_THEMES,
    INKY_BLACK,
    INKY_BLUE,
    INKY_GREEN,
    INKY_RED,
    INKY_WHITE,
    INKY_YELLOW,
    Theme,
    ThemeLayout,
    ThemeStyle,
    load_theme,
)
from src.render.themes.registry import (
    PSEUDO_THEME_NAMES,
    all_theme_names,
    available_themes,
    get_inky_palette,
    get_theme_factory,
    register_theme,
    unregister_theme,
)

# ---------------------------------------------------------------------------
# Theme registry
# ---------------------------------------------------------------------------


class TestThemeRegistry:
    def test_builtin_themes_registered(self):
        names = set(all_theme_names())
        assert {"agenda", "terminal", "minimalist", "qotd", "weather", "diags"} <= names

    def test_pseudo_names_in_available_themes(self):
        avail = available_themes()
        assert "default" in avail
        assert "random" in avail
        assert "random_daily" in avail
        assert "random_hourly" in avail
        # Pseudo names are NOT registered as concrete factories.
        assert get_theme_factory("default") is None
        assert get_theme_factory("random") is None

    def test_legacy_AVAILABLE_THEMES_view_iterates(self):
        """The proxy used by `src.cli` for argparse choices must iterate."""
        names = list(AVAILABLE_THEMES)
        assert "agenda" in names
        assert "default" in names
        assert "random" in names

    def test_legacy_AVAILABLE_THEMES_supports_set_ops(self):
        # config.py does AVAILABLE_THEMES - {"random", ...}
        concrete = AVAILABLE_THEMES - PSEUDO_THEME_NAMES
        assert "agenda" in concrete
        assert "default" not in concrete

    def test_load_theme_returns_a_Theme(self):
        t = load_theme("agenda")
        assert isinstance(t, Theme)
        assert t.name == "agenda"
        assert isinstance(t.style, ThemeStyle)
        assert isinstance(t.layout, ThemeLayout)

    def test_load_theme_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown theme"):
            load_theme("__never_registered__")


class TestInkyPaletteRegistry:
    def test_every_concrete_theme_has_a_palette(self):
        missing = [n for n in all_theme_names() if get_inky_palette(n) is None]
        assert not missing, f"themes missing inky_palette registration: {missing}"

    def test_palette_indices_are_in_range(self):
        valid = {INKY_BLACK, INKY_WHITE, INKY_YELLOW, INKY_RED, INKY_BLUE, INKY_GREEN}
        for name in all_theme_names():
            primary, secondary = get_inky_palette(name)  # type: ignore[misc]
            assert primary in valid, f"{name} primary {primary} not a Spectra-6 index"
            assert secondary in valid, f"{name} secondary {secondary} not a Spectra-6 index"

    def test_known_palette_values(self):
        # Spot-check a couple of known mappings to lock the legacy values in.
        assert get_inky_palette("agenda") == (INKY_RED, INKY_BLACK)
        assert get_inky_palette("terminal") == (INKY_GREEN, INKY_YELLOW)
        assert get_inky_palette("air_quality") == (INKY_BLUE, INKY_GREEN)


class TestThemeRegistryMutation:
    def test_register_then_lookup(self):
        try:
            register_theme(
                "__test_theme__",
                lambda: Theme(name="__test_theme__", style=ThemeStyle(), layout=ThemeLayout()),
                inky_palette=(INKY_BLUE, INKY_RED),
            )
            assert get_theme_factory("__test_theme__") is not None
            assert get_inky_palette("__test_theme__") == (INKY_BLUE, INKY_RED)
        finally:
            unregister_theme("__test_theme__")

    def test_duplicate_registration_silent(self):
        try:
            f1 = lambda: None  # noqa: E731
            f2 = lambda: None  # noqa: E731
            register_theme("__test_dupe__", f1)
            assert register_theme("__test_dupe__", f2) is f1
        finally:
            unregister_theme("__test_dupe__")


# ---------------------------------------------------------------------------
# Component registry
# ---------------------------------------------------------------------------


class TestComponentRegistry:
    def test_builtin_components_registered(self):
        names = set(all_component_names())
        assert {"header", "week_view", "weather", "birthdays", "info"} <= names
        assert {"qotd", "fuzzyclock", "diags", "moonphase_full", "monthly"} <= names

    def test_get_component_returns_callable(self):
        adapter = get_component("header")
        assert callable(adapter)

    def test_unknown_component_returns_none(self):
        assert get_component("__never_registered__") is None


class TestComponentRegistryMutation:
    def test_register_then_lookup(self):
        @register_component("__test_component__")
        def _adapter(ctx: RenderContext) -> None:
            pass

        try:
            assert get_component("__test_component__") is _adapter
        finally:
            unregister_component("__test_component__")

    def test_duplicate_registration_silent(self):
        @register_component("__test_component_dupe__")
        def _first(ctx: RenderContext) -> None:
            pass

        try:

            @register_component("__test_component_dupe__")
            def _second(ctx: RenderContext) -> None:  # pragma: no cover - replaced
                pass

            assert get_component("__test_component_dupe__") is _first
        finally:
            unregister_component("__test_component_dupe__")
