"""Tests for the shared render-argument assembly (#240).

The preview endpoint and the renderer must build the same arguments, or the
preview shows something the real render will never produce — which is the one
thing the preview exists to rule out.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from src.config import Config, CountdownEvent
from src.render.canvas import render_dashboard
from src.render.theme import load_theme
from src.services.render_args import build_render_kwargs, coords_or_none


def _cfg(**overrides) -> Config:
    cfg = Config()
    cfg.title = "Test Dashboard"
    for path, value in overrides.items():
        target = cfg
        *parents, leaf = path.split(".")
        for name in parents:
            target = getattr(target, name)
        setattr(target, leaf, value)
    return cfg


class TestCoordsOrNone:
    def test_exact_origin_is_the_unset_sentinel(self):
        assert coords_or_none(0.0, 0.0) == (None, None)

    @pytest.mark.parametrize(
        "lat,lon",
        [
            (0.0, -122.4),  # on the equator, but configured
            (37.8, 0.0),  # on the prime meridian, but configured
            (37.8, -122.4),
            (-33.9, 151.2),
        ],
    )
    def test_any_real_coordinate_passes_through(self, lat, lon):
        assert coords_or_none(lat, lon) == (lat, lon)


class TestBuildRenderKwargs:
    def test_photo_theme_receives_the_configured_path(self):
        theme = load_theme("photo")
        build_render_kwargs(_cfg(**{"photo.path": "/photos/hero.jpg"}), theme, "photo")
        assert theme.style.photo_path == "/photos/hero.jpg"

    def test_other_themes_are_not_given_a_photo_path(self):
        theme = load_theme("agenda")
        build_render_kwargs(_cfg(**{"photo.path": "/photos/hero.jpg"}), theme, "agenda")
        assert theme.style.photo_path == ""

    def test_countdown_events_are_forwarded(self):
        events = [CountdownEvent(name="Trip", date="2026-12-01")]
        kwargs = build_render_kwargs(
            _cfg(**{"countdown.events": events}), load_theme("countdown"), "countdown"
        )
        assert kwargs["countdown_events"] == events

    def test_countdown_events_are_copied_not_aliased(self):
        events = [CountdownEvent(name="Trip", date="2026-12-01")]
        kwargs = build_render_kwargs(
            _cfg(**{"countdown.events": events}), load_theme("countdown"), "countdown"
        )
        kwargs["countdown_events"].clear()
        assert len(events) == 1

    def test_custom_quotes_path_is_forwarded(self):
        kwargs = build_render_kwargs(
            _cfg(**{"quotes.path": "/etc/quotes.json"}), load_theme("qotd"), "qotd"
        )
        assert kwargs["quotes_path"] == "/etc/quotes.json"

    def test_bundled_quote_store_is_none_not_empty_string(self):
        kwargs = build_render_kwargs(_cfg(), load_theme("qotd"), "qotd")
        assert kwargs["quotes_path"] is None

    def test_unset_coordinates_become_none(self):
        kwargs = build_render_kwargs(_cfg(), load_theme("astronomy"), "astronomy")
        assert (kwargs["latitude"], kwargs["longitude"]) == (None, None)

    def test_configured_coordinates_are_passed_through(self):
        cfg = _cfg(**{"weather.latitude": 37.8, "weather.longitude": -122.4})
        kwargs = build_render_kwargs(cfg, load_theme("astronomy"), "astronomy")
        assert (kwargs["latitude"], kwargs["longitude"]) == (37.8, -122.4)

    def test_message_and_state_dir_are_the_callers_to_supply(self):
        kwargs = build_render_kwargs(
            _cfg(), load_theme("message"), "message", message="hello", state_dir="/state"
        )
        assert kwargs["message_text"] == "hello"
        assert kwargs["state_dir"] == "/state"

    def test_state_dir_defaults_to_none(self):
        """Previews and dry runs must not persist weatherglass pressure history."""
        kwargs = build_render_kwargs(_cfg(), load_theme("weatherglass"), "weatherglass")
        assert kwargs["state_dir"] is None

    def test_every_key_is_a_real_render_dashboard_parameter(self):
        """A typo here would be silently swallowed by a **kwargs signature."""
        accepted = set(inspect.signature(render_dashboard).parameters)
        kwargs = build_render_kwargs(_cfg(), load_theme("agenda"), "agenda")
        assert set(kwargs) <= accepted

    def test_it_covers_every_config_driven_render_parameter(self):
        """New render kwargs must be added here, not only at one call site.

        The preview diverging from the renderer is exactly how #240 happened.
        """
        params = inspect.signature(render_dashboard).parameters
        # Both call sites pass these two positionally.
        positional = {"data", "config"}
        expected = set(params) - positional
        assert set(build_render_kwargs(_cfg(), load_theme("agenda"), "agenda")) == expected


class TestConfigWithoutRealFile:
    def test_a_default_config_produces_renderable_kwargs(self):
        kwargs = build_render_kwargs(_cfg(), load_theme("default"), "default")
        assert kwargs["title"] == "Test Dashboard"
        assert kwargs["quote_refresh"] == "daily"


class TestNamespaceCompatibility:
    """The helper reads plain attributes, so a candidate config works too."""

    def test_works_with_a_duck_typed_config(self):
        cfg = SimpleNamespace(
            title="X",
            photo=SimpleNamespace(path=""),
            cache=SimpleNamespace(quote_refresh="hourly"),
            quotes=SimpleNamespace(path=""),
            countdown=SimpleNamespace(events=[]),
            weather=SimpleNamespace(latitude=0.0, longitude=0.0),
        )
        kwargs = build_render_kwargs(cfg, load_theme("agenda"), "agenda")
        assert kwargs["quote_refresh"] == "hourly"
