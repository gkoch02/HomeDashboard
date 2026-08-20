"""Partial-refresh capability, derived from the plate (#222).

Waveshare's fast waveform does not drive black as deeply as a full init. A
plate built out of dithered ink or large solid fills fades under it — on
``halftone_agenda`` the fade tracked the artwork's rows across the whole width,
which is what made that theme's partial-refresh-friendly redesign pointless.

``Theme.allows_partial_refresh`` answers the question at runtime, deriving it
from the plate unless the theme overrules the derivation. That is the change
these tests are built around: the rule is no longer something a theme author
has to remember, so a new theme that dithers and declares nothing gets the
right answer rather than failing open onto a panel that cannot hold its ink.

What is left for tests to hold is narrower and more useful:

* the derivation is right for each of the three things that trigger it;
* the concrete themes resolve to the set we expect;
* an override is a judgement call, so every one of them is named here with a
  reason, and no theme redundantly declares what the derivation already says.
"""

from __future__ import annotations

import pytest

from src.render.theme import (
    AVAILABLE_THEMES,
    DITHERING_QUANTIZERS,
    Theme,
    ThemeLayout,
    ThemeStyle,
    load_theme,
    plate_needs_full_waveform,
    theme_supports_partial_refresh,
)

# ``AVAILABLE_THEMES`` carries the rotation pseudo-names alongside the real
# ones; they resolve to a concrete theme before a layout ever exists.
PSEUDO = {"random", "random_daily", "random_hourly"}
CONCRETE_THEMES = sorted(set(AVAILABLE_THEMES) - PSEUDO)

# Themes whose image depends on ink the fast waveform will not lay down —
# either an actual dither or a plate whose ground is solid ink. Every one of
# these is *derived*, not declared: the list is the expected outcome of the
# rule, which is what makes it worth writing down separately.
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

# Themes that overrule the derivation, with the reason each one does. The
# derivation would decline all three — they are dark-canvas plates — and each
# keeps partial refresh on purpose:
#
#   fuzzyclock_invert — its phrase changes every five minutes, so declining
#     would mean ~200 full-waveform refreshes a day to avoid ink that reads
#     charcoal; the light `fuzzyclock` covers anyone wanting cadence and tone.
#   moonphase / moonphase_photo — field evidence: no fade observed on real
#     hardware. The plate has no fine detail to band and an evenly greying black
#     ground gives the eye nothing to read the drift against, while a
#     full-waveform flash is at its most intrusive on a theme left up at night.
#
# `moonphase_photo` inherits `moonphase`'s layout via ``dataclasses.replace``,
# so the two share one declaration.
OVERRIDES = {"fuzzyclock_invert", "moonphase", "moonphase_photo"}


def _theme(**layout_kw) -> Theme:
    """A minimal theme, for exercising the derivation without a real plate."""
    style_kw = {"fg": layout_kw.pop("fg", 0), "bg": layout_kw.pop("bg", 1)}
    return Theme(
        name="probe",
        style=ThemeStyle(**style_kw),
        layout=ThemeLayout(**layout_kw),
    )


class TestDerivation:
    """The three things that put a plate beyond the fast waveform."""

    def test_a_plain_plate_keeps_partials(self):
        assert _theme().allows_partial_refresh is True

    @pytest.mark.parametrize("mode", sorted(DITHERING_QUANTIZERS))
    def test_a_diffusing_quantizer_declines(self, mode):
        assert _theme(canvas_mode="L", preferred_quantization_mode=mode).allows_partial_refresh is (
            False
        )

    def test_threshold_is_not_a_dither(self):
        """A hard cut spreads no ink, so an ``L`` canvas alone is not a reason.

        This is the proxy that got it wrong the first time round: keying on
        ``canvas_mode`` swept up `moonphase_invert` and `weatherglass`, which
        are lighter than `default` and have nothing to fade.
        """
        theme = _theme(canvas_mode="L", preferred_quantization_mode="threshold", fg=0, bg=255)
        assert theme.allows_partial_refresh is True

    def test_a_dithered_background_declines(self):
        """``photo`` dithers its image through ``background_fn``, not the
        quantizer, so the rule has to look there too."""
        assert _theme(background_fn=lambda *a: None).allows_partial_refresh is False

    def test_an_ink_ground_declines(self):
        """``bg`` of 0 is black in both ``"1"`` and ``"L"`` mode — the whole
        plate is one solid fill either way."""
        assert _theme(fg=1, bg=0).allows_partial_refresh is False

    def test_an_rgb_ink_ground_declines_too(self):
        """``ThemeStyle`` allows a triple for the colour-canvas themes, and a
        black triple is the same solid plate as a black int."""
        assert _theme(fg=(255, 255, 255), bg=(0, 0, 0)).allows_partial_refresh is False

    def test_a_light_rgb_ground_is_not_ink(self):
        assert _theme(fg=(0, 0, 0), bg=(255, 255, 255)).allows_partial_refresh is True

    def test_the_predicate_agrees_with_the_property(self):
        for name in CONCRETE_THEMES:
            theme = load_theme(name)
            if theme.layout.supports_partial_refresh is not None:
                continue
            assert theme.allows_partial_refresh is not plate_needs_full_waveform(
                theme.layout, theme.style
            ), name


class TestOverrides:
    def test_an_override_wins_over_the_plate(self):
        declined = _theme(fg=1, bg=0)
        assert declined.allows_partial_refresh is False
        declined.layout.supports_partial_refresh = True
        assert declined.allows_partial_refresh is True

    def test_an_override_can_also_decline_a_plain_plate(self):
        """The escape hatch runs both ways — a theme knowing something the
        derivation cannot see may decline on its own account."""
        theme = _theme()
        theme.layout.supports_partial_refresh = False
        assert theme.allows_partial_refresh is False

    def test_only_the_named_themes_override(self):
        """An override is a judgement call and belongs in ``OVERRIDES`` with a
        reason. A theme redundantly declaring what the derivation already says
        is the thing this catches: it reads as a decision when it is noise, and
        it goes stale silently when the plate changes underneath it.
        """
        declared = {
            name
            for name in CONCRETE_THEMES
            if load_theme(name).layout.supports_partial_refresh is not None
        }
        assert declared == OVERRIDES

    def test_every_override_contradicts_its_plate(self):
        """If an override agrees with the derivation it is doing nothing, and
        should be deleted rather than left to rot."""
        for name in sorted(OVERRIDES):
            theme = load_theme(name)
            declared = theme.layout.supports_partial_refresh
            derived = not plate_needs_full_waveform(theme.layout, theme.style)
            assert declared != derived, (
                f"{name} declares {declared}, which is what the plate derives anyway — "
                "drop the declaration"
            )


class TestResolvedThemes:
    def test_halftone_agenda_declines(self):
        assert load_theme("halftone_agenda").allows_partial_refresh is False

    @pytest.mark.parametrize("name", sorted(DECLINES_PARTIAL))
    def test_the_at_risk_themes_decline(self, name):
        assert load_theme(name).allows_partial_refresh is False

    def test_every_other_theme_keeps_partials(self):
        allowed = {name for name in CONCRETE_THEMES if load_theme(name).allows_partial_refresh}
        assert allowed == set(CONCRETE_THEMES) - DECLINES_PARTIAL

    def test_threshold_quantized_light_themes_keep_partials(self):
        """Pinned by name so the ``canvas_mode == "L"`` proxy cannot creep back:
        a light plate that snaps to a hard cut has nothing to fade."""
        for name in ("moonphase_invert", "weatherglass"):
            theme = load_theme(name)
            assert theme.layout.canvas_mode == "L", name
            assert theme.layout.preferred_quantization_mode == "threshold", name
            assert theme.style.bg != 0, name
            assert theme.allows_partial_refresh is True, name


class TestPredicate:
    def test_resolves_by_name(self):
        assert theme_supports_partial_refresh("default") is True
        assert theme_supports_partial_refresh("halftone_agenda") is False

    def test_unknown_theme_is_not_a_second_complaint(self):
        """Callers already report the unknown name; don't pile on."""
        assert theme_supports_partial_refresh("no_such_theme") is True
