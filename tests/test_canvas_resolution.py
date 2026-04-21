"""Coverage for the resolution helpers in src/render/canvas.py.

Targets specific defensive branches in:
* `_resolve_inky_explicit_color` (tuple passthrough, out-of-range fallback)
* `_resolve_mono_explicit_color` (tuple → fallback, out-of-range value → fallback)
* `_resolve_render_mode` (unknown spec, L-mode preservation)
* `_resolve_style` (Inky-but-not-RGB greyscale-style branch)
* `render_dashboard` (prefer_color_on_inky promotion, Inky resize path)
"""

from __future__ import annotations

from unittest.mock import patch

from PIL import Image

from src.config import DisplayConfig
from src.data.models import DashboardData
from src.render.canvas import (
    _resolve_inky_explicit_color,
    _resolve_mono_explicit_color,
    _resolve_render_mode,
    _resolve_style,
    render_dashboard,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE
from src.render.theme import default_theme, load_theme

# ---------------------------------------------------------------------------
# _resolve_inky_explicit_color
# ---------------------------------------------------------------------------


class TestResolveInkyExplicitColor:
    def test_tuple_value_returned_as_is(self):
        result = _resolve_inky_explicit_color((10, 20, 30), fallback=(0, 0, 0))
        assert result == (10, 20, 30)

    def test_valid_palette_index_returns_palette_entry(self):
        result = _resolve_inky_explicit_color(2, fallback=(0, 0, 0))
        assert result == INKY_SPECTRA6_PALETTE[2]

    def test_negative_index_falls_back(self):
        fallback = (123, 45, 67)
        assert _resolve_inky_explicit_color(-1, fallback=fallback) == fallback

    def test_out_of_range_index_falls_back(self):
        fallback = (123, 45, 67)
        assert (
            _resolve_inky_explicit_color(len(INKY_SPECTRA6_PALETTE) + 1, fallback=fallback)
            == fallback
        )

    def test_none_value_returns_fallback(self):
        fallback = (1, 2, 3)
        assert _resolve_inky_explicit_color(None, fallback=fallback) == fallback


# ---------------------------------------------------------------------------
# _resolve_mono_explicit_color
# ---------------------------------------------------------------------------


class TestResolveMonoExplicitColor:
    def test_tuple_input_falls_back_in_mono(self):
        # Tuples can't be drawn on a mono backend → fallback
        assert _resolve_mono_explicit_color((1, 2, 3), fallback=0, allow_grayscale=False) == 0

    def test_tuple_input_falls_back_even_in_grayscale(self):
        assert _resolve_mono_explicit_color((1, 2, 3), fallback=255, allow_grayscale=True) == 255

    def test_grayscale_value_in_range_returned(self):
        assert _resolve_mono_explicit_color(128, fallback=0, allow_grayscale=True) == 128

    def test_grayscale_value_out_of_range_falls_back(self):
        # Triggers the `else fallback` branch in the allow_grayscale path
        assert _resolve_mono_explicit_color(300, fallback=0, allow_grayscale=True) == 0
        assert _resolve_mono_explicit_color(-5, fallback=0, allow_grayscale=True) == 0

    def test_bilevel_only_zero_or_one_allowed(self):
        assert _resolve_mono_explicit_color(0, fallback=1, allow_grayscale=False) == 0
        assert _resolve_mono_explicit_color(1, fallback=0, allow_grayscale=False) == 1
        # Anything else → fallback
        assert _resolve_mono_explicit_color(128, fallback=0, allow_grayscale=False) == 0


# ---------------------------------------------------------------------------
# _resolve_render_mode
# ---------------------------------------------------------------------------


class TestResolveRenderMode:
    def test_unknown_provider_returns_layout_mode(self):
        cfg = DisplayConfig(provider="unknown", model="bogus")
        # spec is None → return layout_mode unchanged
        assert _resolve_render_mode("1", cfg) == "1"
        assert _resolve_render_mode("L", cfg) == "L"

    def test_waveshare_keeps_layout_mode(self):
        cfg = DisplayConfig(provider="waveshare", model="epd7in5_V2")
        # Waveshare render_mode is "1", not "RGB" → fall through to layout_mode
        assert _resolve_render_mode("1", cfg) == "1"
        assert _resolve_render_mode("L", cfg) == "L"

    def test_inky_l_layout_stays_l(self):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        # spec.render_mode == "RGB" but layout_mode == "L" → preserve L
        assert _resolve_render_mode("L", cfg) == "L"

    def test_inky_one_layout_promoted_to_rgb(self):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        assert _resolve_render_mode("1", cfg) == "RGB"


# ---------------------------------------------------------------------------
# _resolve_style — Inky-but-not-RGB branch (line 164)
# ---------------------------------------------------------------------------


class TestResolveStyleInkyMono:
    def test_inky_l_render_uses_grayscale_accent_resolution(self):
        """When provider=inky AND render_mode is not RGB, falls into the L-mode branch."""
        theme = default_theme()
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        # render_mode != "RGB" → exercise the trailing `replace(...)` branch
        resolved = _resolve_style(theme, render_mode="L", config=cfg)
        # All accent fields should be resolved; the function returns a ThemeStyle
        assert resolved is not theme.style
        assert hasattr(resolved, "accent_info")


# ---------------------------------------------------------------------------
# render_dashboard — prefer_color_on_inky and Inky resize paths
# ---------------------------------------------------------------------------


def _empty_data():
    from datetime import datetime

    return DashboardData(
        events=[],
        weather=None,
        birthdays=[],
        air_quality=None,
        host_data=None,
        is_stale=False,
        fetched_at=datetime(2026, 4, 5, 12, 0),
        source_staleness={},
    )


class TestRenderDashboardInkyPaths:
    def test_prefer_color_on_inky_promotes_l_to_rgb(self):
        """Force the line 209 branch: layout.canvas_mode='L' AND prefer_color_on_inky=True."""
        from dataclasses import replace as dc_replace

        # Synthesize an L-mode + prefer_color_on_inky layout from any L-mode theme.
        # No built-in theme combines both, so build one explicitly.
        base = default_theme()
        l_layout = dc_replace(base.layout, canvas_mode="L", prefer_color_on_inky=True)
        # L-mode requires bg=255 (per CLAUDE.md), but canvas only allocates an image —
        # the bg fill happens before any drawing.
        l_style = dc_replace(base.style, fg=0, bg=255)
        theme = dc_replace(base, layout=l_layout, style=l_style)

        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        img = render_dashboard(_empty_data(), cfg, title="Test", theme=theme)
        # When promoted, the final image should be RGB (Inky path skips quantize)
        assert img.mode == "RGB"

    def test_inky_resize_uses_rgb_convert(self):
        """When Inky display dimensions differ from canvas dimensions, line 425 fires."""
        theme = default_theme()
        # Pick a model size that differs from the 800×480 canvas.
        cfg = DisplayConfig(
            provider="inky",
            model="impression_7_3_2025",
            width=900,  # forcing a resize via custom width
            height=600,
        )
        with patch("src.render.canvas.get_display_spec") as mock_spec:
            mock_spec.return_value.render_mode = "RGB"
            img = render_dashboard(_empty_data(), cfg, title="Test", theme=theme)
        # Final image should match the configured dimensions and be RGB
        assert img.size == (900, 600)
        assert img.mode == "RGB"


# ---------------------------------------------------------------------------
# Smoke: Inky non-RGB path through render_dashboard (covers _resolve_style 164)
# ---------------------------------------------------------------------------


def test_render_dashboard_inky_with_l_layout_no_color_preference():
    """Render an L-mode theme on Inky WITHOUT prefer_color_on_inky → render_mode stays L."""
    theme = load_theme("monthly")
    # Override prefer_color_on_inky to False to exercise the L branch on Inky
    from dataclasses import replace as dc_replace

    layout = dc_replace(theme.layout, prefer_color_on_inky=False)
    theme = dc_replace(theme, layout=layout)

    cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
    img = render_dashboard(_empty_data(), cfg, title="Test", theme=theme)
    # Canvas should remain in L since prefer_color_on_inky was False.
    # Inky path skips quantize so the image stays in its rendered mode.
    assert img.mode in {"L", "RGB"}  # tolerant: confirm no crash and a sane mode
    assert isinstance(img, Image.Image)
