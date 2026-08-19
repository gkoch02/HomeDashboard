"""Theme-declared partial-refresh capability (#222).

Waveshare's fast waveform does not drive black as deeply as a full init. A
plate built out of dithered greyscale or large solid ink fades under it — on
``halftone_agenda`` the fade tracked the artwork's rows across the whole
width, which is what made the theme's partial-refresh-friendly redesign
pointless. Themes now declare the requirement and the output service honours
it; these tests pin the declaration and the invariant behind it.
"""

from __future__ import annotations

import pytest

from src.render.theme import (
    AVAILABLE_THEMES,
    ThemeLayout,
    load_theme,
    theme_supports_partial_refresh,
)

# ``AVAILABLE_THEMES`` carries the rotation pseudo-names alongside the real
# ones; they resolve to a concrete theme before a layout ever exists.
PSEUDO = {"random", "random_daily", "random_hourly"}
CONCRETE_THEMES = sorted(set(AVAILABLE_THEMES) - PSEUDO)

# Themes whose image depends on ink the fast waveform will not lay down.
DECLINES_PARTIAL = {
    "constellation_map",
    "day_arc",
    "halftone",
    "halftone_agenda",
    "moonphase",
    "moonphase_invert",
    "moonphase_photo",
    "naturalist",
    "photo",
    "postcard",
    "trends",
    "weatherglass",
}


class TestDeclaration:
    def test_default_is_partial_capable(self):
        """Crisp 1-bit themes keep the speed — the flag is opt-out, not opt-in."""
        assert ThemeLayout().supports_partial_refresh is True

    def test_halftone_agenda_declines(self):
        assert load_theme("halftone_agenda").layout.supports_partial_refresh is False

    @pytest.mark.parametrize("name", sorted(DECLINES_PARTIAL))
    def test_dithered_themes_decline(self, name):
        assert load_theme(name).layout.supports_partial_refresh is False

    def test_every_other_theme_still_allows_partials(self):
        allowed = {
            name for name in CONCRETE_THEMES if load_theme(name).layout.supports_partial_refresh
        }
        assert allowed == set(CONCRETE_THEMES) - DECLINES_PARTIAL

    def test_greyscale_themes_never_claim_partial_support(self):
        """An ``L``-mode canvas is greyscale by definition, and greyscale is
        exactly what the fast waveform washes out. New L-mode themes must
        declare the opt-out; this is the guard that says so."""
        for name in CONCRETE_THEMES:
            layout = load_theme(name).layout
            if layout.canvas_mode == "L":
                assert layout.supports_partial_refresh is False, name


class TestPredicate:
    def test_reads_the_layout_flag(self):
        assert theme_supports_partial_refresh("default") is True
        assert theme_supports_partial_refresh("halftone_agenda") is False

    def test_unknown_theme_is_not_a_second_complaint(self):
        """Callers already report the unknown name; don't pile on."""
        assert theme_supports_partial_refresh("no_such_theme") is True
