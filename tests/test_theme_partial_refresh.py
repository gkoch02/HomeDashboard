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

# Themes whose image depends on ink the fast waveform will not lay down —
# either dithered greyscale or a plate whose ground is solid ink.
DECLINES_PARTIAL = {
    "constellation_map",
    "day_arc",
    "fantasy",
    "halftone",
    "halftone_agenda",
    "moonphase",
    "moonphase_invert",
    "moonphase_photo",
    "naturalist",
    "photo",
    "postcard",
    "qotd_invert",
    "terminal",
    "trends",
    "weatherglass",
}

# The one dark-canvas theme that keeps partial refresh, by choice rather than by
# oversight. Its phrase changes every five minutes, so declining would mean ~200
# full-waveform refreshes a day — the panel flashing on every tick — to avoid ink
# that reads charcoal. For a clock face that trade goes the other way, and the
# light `fuzzyclock` covers anyone who wants the cadence with true black.
SOLID_INK_BY_CHOICE = {"fuzzyclock_invert"}


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

    def test_dark_canvas_themes_decline_unless_exempted_on_purpose(self):
        """``bg`` set to ink means the whole plate is one solid fill.

        That is the other half of what the fast waveform cannot hold, and it is
        easy to miss because such a theme can still be ``canvas_mode="1"``. A new
        dark-canvas theme must either decline partial refresh or be added to
        SOLID_INK_BY_CHOICE with a reason — silence is the bug this catches.
        """
        for name in CONCRETE_THEMES:
            theme = load_theme(name)
            if theme.style.bg != 0:
                continue
            if name in SOLID_INK_BY_CHOICE:
                assert theme.layout.supports_partial_refresh is True, (
                    f"{name} is listed as keeping partials by choice but declines them"
                )
                continue
            assert theme.layout.supports_partial_refresh is False, name

    def test_the_exemption_list_names_only_dark_canvas_themes(self):
        """A theme that lightens its canvas should leave the list, not linger."""
        for name in SOLID_INK_BY_CHOICE:
            assert load_theme(name).style.bg == 0, (
                f"{name} is no longer a dark-canvas theme — drop it from SOLID_INK_BY_CHOICE"
            )


class TestPredicate:
    def test_reads_the_layout_flag(self):
        assert theme_supports_partial_refresh("default") is True
        assert theme_supports_partial_refresh("halftone_agenda") is False

    def test_unknown_theme_is_not_a_second_complaint(self):
        """Callers already report the unknown name; don't pile on."""
        assert theme_supports_partial_refresh("no_such_theme") is True
