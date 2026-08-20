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
# either an actual dither or a plate whose ground is solid ink.
DECLINES_PARTIAL = {
    "constellation_map",
    "day_arc",
    "fantasy",
    "halftone",
    "halftone_agenda",
    "naturalist",
    "photo",
    "postcard",
    "qotd_invert",
    "terminal",
    "trends",
}

# Dark-canvas themes that keep partial refresh by choice rather than by
# oversight. Each would decline under the rule below, and each has a reason
# recorded at the theme:
#
#   fuzzyclock_invert — its phrase changes every five minutes, so declining
#     would mean ~200 full-waveform refreshes a day to avoid ink that reads
#     charcoal; the light `fuzzyclock` covers anyone wanting cadence and tone.
#   moonphase / moonphase_photo — field evidence: no fade observed on real
#     hardware. The plate has no fine detail to band and an evenly greying black
#     ground gives the eye nothing to read the drift against, while a
#     full-waveform flash is at its most intrusive on a theme left up at night.
SOLID_INK_BY_CHOICE = {"fuzzyclock_invert", "moonphase", "moonphase_photo"}

# Quantizers that actually diffuse ink across the plate. `threshold` is a hard
# cut and produces none, which is why an `"L"` canvas is not by itself a reason
# to decline — `moonphase_invert` and `weatherglass` are both L-mode, both
# threshold-quantized, and both lighter than `default`.
DITHERING_QUANTIZERS = {"floyd_steinberg", "ordered"}


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

    def test_dithered_themes_never_claim_partial_support(self):
        """A declared dither is ink spread thin across the plate, which is what
        the fast waveform fails to lay down. Any theme choosing a diffusing
        quantizer must decline; this is the guard that says so.

        Note this keys off the quantizer, not ``canvas_mode``. An ``"L"`` canvas
        quantized with ``threshold`` is a hard cut with no dither in it at all.
        """
        for name in CONCRETE_THEMES:
            layout = load_theme(name).layout
            if layout.preferred_quantization_mode in DITHERING_QUANTIZERS:
                assert layout.supports_partial_refresh is False, name

    def test_a_dithered_background_also_declines(self):
        """``photo`` dithers a photograph across the whole canvas via
        ``background_fn`` rather than through the quantizer, so the rule above
        cannot see it."""
        for name in CONCRETE_THEMES:
            layout = load_theme(name).layout
            if layout.background_fn is not None:
                assert layout.supports_partial_refresh is False, name

    def test_threshold_quantized_light_themes_keep_partials(self):
        """The counterpart to the dither rule, pinned so the L-mode proxy does
        not creep back: a light plate that snaps to a hard cut has nothing to
        fade, and should keep the fast path."""
        for name in ("moonphase_invert", "weatherglass"):
            theme = load_theme(name)
            assert theme.layout.canvas_mode == "L", name
            assert theme.layout.preferred_quantization_mode == "threshold", name
            assert theme.style.bg != 0, name
            assert theme.layout.supports_partial_refresh is True, name

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
