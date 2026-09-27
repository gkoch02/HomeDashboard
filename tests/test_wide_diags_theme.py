"""wide_diags: the diags readout beside an ink and dither swatch plate.

The tests pin what the swatch plate is for: it shows exactly the inks the
panel has (four on the G panel, six on Inky, two on monochrome), everything
but the DIFFUSED row reaches the panel as exact inks, the DIFFUSED row is the
one place the backend dithers, and the left 800 px are the ``diags`` theme
unchanged.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.dummy_data import generate_dummy_data
from src.render.canvas import _resolve_style, render_dashboard
from src.render.components import wide_diags_panel as wd
from src.render.components.registry import get_component
from src.render.quantize import INKY_SPECTRA6_PALETTE, WAVESHARE_G_STYLE_PALETTE
from src.render.random_theme import _EXCLUDED_FROM_POOL
from src.render.theme import ComponentRegion, ThemeStyle, load_theme
from src.render.themes.wide_diags import wide_diags_theme

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
G_PANEL = DisplayConfig(model="epd10in85g", width=1360, height=480)
INKY = DisplayConfig(provider="inky", model="impression_7_3_2025", width=1360, height=480)
MONO = DisplayConfig(model="epd7in5_V2", width=1360, height=480)
REGION = ComponentRegion(800, 0, 560, 480)
G_INKS = {(0, 0, 0), (255, 255, 255), (255, 255, 0), (255, 0, 0)}


def _render(config: DisplayConfig, theme: str = "wide_diags") -> Image.Image:
    return render_dashboard(generate_dummy_data(now=FIXED_NOW), config, theme=load_theme(theme))


def _colours(img: Image.Image) -> set:
    return {c for _, c in img.getcolors(maxcolors=1 << 20)}


def _style(palette) -> ThemeStyle:
    """A style resolved the way ``canvas._resolve_style`` does for a colour panel."""
    return ThemeStyle(
        fg=palette[0],
        bg=palette[1],
        accent_warn=palette[2],
        accent_alert=palette[3],
        accent_info=palette[4],
        accent_good=palette[5],
    )


class TestInks:
    def test_g_panel_has_its_four_inks(self):
        inks = wd.panel_inks(_style(WAVESHARE_G_STYLE_PALETTE))
        assert [i.name for i in inks] == ["BLACK", "WHITE", "YELLOW", "RED"]
        assert {i.value for i in inks} == G_INKS

    def test_inky_has_six(self):
        inks = wd.panel_inks(_style(INKY_SPECTRA6_PALETTE))
        assert [i.value for i in inks] == INKY_SPECTRA6_PALETTE

    def test_mono_collapses_to_ink_and_paper(self):
        style = ThemeStyle(fg=0, bg=1, accent_warn=0, accent_alert=0, accent_info=0, accent_good=0)
        assert [(i.name, i.value) for i in wd.panel_inks(style)] == [("BLACK", 0), ("WHITE", 1)]

    def test_every_pair_once(self):
        inks = wd.panel_inks(_style(INKY_SPECTRA6_PALETTE))
        assert len(wd.ink_pairs(inks)) == 15


class TestScreens:
    @pytest.mark.parametrize("level", range(wd.RAMP_LEVELS))
    def test_ramp_step_covers_its_fraction_exactly(self, level):
        # Over whole 8x8 tiles the Bayer screen puts down exactly level/8.
        img = Image.new("1", (16, 16), 1)
        wd._screen(img, (0, 0, 16, 16), 1, 0, wd.ramp_cover(level))
        assert img.histogram()[0] == level * 256 // 8

    def test_continuous_ramp_darkens_left_to_right(self):
        img = Image.new("L", (256, 8), 255)
        wd._screen_ramp(img, (0, 0, 256, 8), 255, 0)
        ink = (np.asarray(img) == 0).sum(axis=0)
        halves = ink[:128].sum(), ink[128:].sum()
        assert halves[0] < halves[1]
        assert ink[:8].sum() <= 2 and ink[-8:].sum() >= 62

    def test_few_pairs_get_a_continuous_row_each(self):
        inks = wd.panel_inks(ThemeStyle(fg=0, bg=1))
        rows = wd.ramp_rows(wd.ink_pairs(inks), 0, 0, 500, 200)
        assert [fine for *_, fine in rows] == [False, True]

    def test_many_pairs_split_into_two_columns(self):
        inks = wd.panel_inks(_style(INKY_SPECTRA6_PALETTE))
        rows = wd.ramp_rows(wd.ink_pairs(inks), 0, 0, 500, 200)
        assert len(rows) == 15
        assert not any(fine for *_, fine in rows)
        assert len({box[0] for box, *_ in rows}) == 2


class TestPlate:
    def test_g_swatches_reach_the_panel_as_drawn(self):
        # Everything but the DIFFUSED row is drawn in exact inks with bilevel
        # type, so the backend's nearest-ink snap must be the identity there.
        theme = load_theme("wide_diags")
        style = _resolve_style(theme, "RGB", G_PANEL)
        drawn = Image.new("RGB", (1360, 480), style.bg)
        wd.draw_wide_diags(drawn, ImageDraw.Draw(drawn), region=REGION, style=style)
        y0 = wd.diffused_rect(REGION)[1]
        box = (REGION.x, 0, REGION.x + REGION.w, y0 - 1)
        panel = _render(G_PANEL).crop(box)
        assert np.array_equal(np.asarray(panel), np.asarray(drawn.crop(box)))
        assert _colours(panel) == G_INKS

    def test_diffused_row_is_dithered_by_the_backend(self):
        # The grey half of the DIFFUSED row: a nearest-ink snap would cut it
        # into a solid black block and a solid white one; declared as an art
        # region it is error-diffused, so its middle mixes both.
        img = np.asarray(_render(G_PANEL))
        x0, y0, x1, y1 = wd.diffused_rect(REGION)
        grey = img[(y0 + y1) // 2 + 4 : y1 - 1, x0 + 1 : x1 - 1]
        w = grey.shape[1]
        dark = grey[:, w // 4 : w * 2 // 5]  # a snap makes this solid black
        light = grey[:, w * 3 // 5 : w * 3 // 4]  # ... and this solid white
        assert np.all(dark == 255, axis=-1).mean() > 0.1
        assert np.all(light == 0, axis=-1).mean() > 0.1

    def test_inky_shows_six_swatches(self):
        img = np.asarray(_render(INKY))
        x0, _, x1, _ = wd.diffused_rect(REGION)
        # The swatch row sits under the INKS label; sample each swatch centre.
        y = wd.INK_TOP + 14 + wd.INK_H // 2
        n = 6
        sw = ((x1 - x0) - (n - 1) * wd.INK_GAP) // n
        centres = [tuple(img[y, x0 + i * (sw + wd.INK_GAP) + sw // 2]) for i in range(n)]
        assert centres == [tuple(c) for c in INKY_SPECTRA6_PALETTE]

    def test_mono_is_one_bit(self):
        img = _render(MONO)
        assert img.size == (1360, 480)
        assert set(np.unique(np.asarray(img.convert("L")))) <= {0, 255}

    @pytest.mark.parametrize("config", [MONO, G_PANEL], ids=["mono", "g"])
    def test_left_half_is_the_diags_theme(self, config):
        wide = _render(config).crop((0, 0, 800, 480))
        narrow_cfg = DisplayConfig(model=config.model, width=800, height=480)
        diags = _render(narrow_cfg, theme="diags")
        if config is G_PANEL:
            # Same readout, but diags names its own accent pair; compare shape.
            wide, diags = wide.convert("L").point(_ink), diags.convert("L").point(_ink)
        assert np.array_equal(np.asarray(wide), np.asarray(diags))


def _ink(v: int) -> int:
    return 0 if v < 250 else 255


class TestTheme:
    def test_layout(self):
        layout = wide_diags_theme().layout
        assert (layout.canvas_w, layout.canvas_h) == (1360, 480)
        assert layout.draw_order == ["diags", "wide_diags"]
        assert layout.diags.w + layout.wide_diags.w == 1360
        assert layout.wide_diags.x == layout.diags.w

    def test_declines_partial_refresh(self):
        assert not wide_diags_theme().allows_partial_refresh

    def test_excluded_from_rotation(self):
        assert "wide_diags" in _EXCLUDED_FROM_POOL

    def test_adapter_declares_the_diffused_row(self):
        from src.render.components.registry import RenderContext

        img = Image.new("RGB", (1360, 480), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        ctx = RenderContext(
            draw=draw,
            data=generate_dummy_data(now=FIXED_NOW),
            today=FIXED_NOW.date(),
            now=FIXED_NOW,
            layout=wide_diags_theme().layout,
            style=_style(WAVESHARE_G_STYLE_PALETTE),
            image=img,
        )
        get_component("wide_diags")(ctx)
        assert ctx.dither_regions == [wd.diffused_rect(REGION)]

    def test_default_region_and_style(self):
        img = Image.new("1", (1360, 480), 1)
        wd.draw_wide_diags(img, ImageDraw.Draw(img))
        assert img.crop((800, 0, 1360, 480)).histogram()[0] > 0
