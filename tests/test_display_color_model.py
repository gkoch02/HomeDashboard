"""The Waveshare 10.85" (G) panel: a colour model in the Waveshare registry.

Covers the registry entry and its spec, the driver's refusal to take the fast
waveform on a colour model, and ``build_display_backend`` routing the model to
the colour pipeline.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PIL import Image

from src.config import DisplayConfig
from src.display.backend import (
    WaveshareBackend,
    WaveshareColorBackend,
    build_display_backend,
)
from src.display.driver import (
    WAVESHARE_COLOR_MODELS,
    WAVESHARE_G_PALETTE,
    WAVESHARE_MODELS,
    WaveshareDisplay,
    get_display_spec,
    supported_display_models,
)

MODEL = "epd10in85g"


class TestRegistry:
    def test_model_is_registered_at_native_size(self):
        module_path, w, h = WAVESHARE_MODELS[MODEL]
        assert module_path == "waveshare_epd.epd10in85g"
        assert (w, h) == (1360, 480)

    def test_model_is_a_colour_model(self):
        assert WAVESHARE_COLOR_MODELS[MODEL] == WAVESHARE_G_PALETTE
        assert set(WAVESHARE_G_PALETTE) == {
            (0, 0, 0),
            (255, 255, 255),
            (255, 255, 0),
            (255, 0, 0),
        }

    def test_spec_is_colour_and_full_refresh_only(self):
        spec = get_display_spec("waveshare", MODEL)
        assert spec is not None
        assert spec.is_color
        assert spec.render_mode == "RGB"
        assert spec.palette == WAVESHARE_G_PALETTE
        assert spec.supports_partial_refresh is False

    def test_mono_models_are_unchanged(self):
        spec = get_display_spec("waveshare", "epd7in5_V2")
        assert spec is not None
        assert not spec.is_color
        assert spec.render_mode == "1"
        assert spec.palette is None
        assert spec.supports_partial_refresh is True

    def test_listed_under_waveshare(self):
        assert MODEL in supported_display_models("waveshare")
        assert MODEL not in supported_display_models("inky")

    def test_config_derives_native_dimensions(self, tmp_path):
        from src.config import load_config

        p = tmp_path / "config.yaml"
        p.write_text(f'display:\n  provider: "waveshare"\n  model: "{MODEL}"\n')
        cfg = load_config(str(p))
        assert (cfg.display.width, cfg.display.height) == (1360, 480)


class TestDriver:
    def _epd(self):
        epd = MagicMock()
        epd.getbuffer = MagicMock(return_value=b"buf")
        return epd

    def test_colour_model_never_enables_partial(self):
        d = WaveshareDisplay(model=MODEL, enable_partial=True)
        assert d.is_color
        assert d.enable_partial is False

    def test_show_uses_full_waveform_even_when_partial_requested(self):
        """The G drivers have no init_fast(); the tracker's opinion is moot."""
        epd = self._epd()
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = False
        d = WaveshareDisplay(model=MODEL, enable_partial=True)
        image = Image.new("RGB", (1360, 480), (255, 255, 255))
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            d.show(image)
        epd.init.assert_called_once()
        epd.init_fast.assert_not_called()
        epd.getbuffer.assert_called_once_with(image)
        epd.display.assert_called_once_with(b"buf")
        tracker.record_full.assert_called_once()
        epd.sleep.assert_called_once()

    def test_mono_model_still_takes_partial(self):
        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=True)
        assert not d.is_color
        assert d.enable_partial is True


class TestBackendRouting:
    def test_colour_model_gets_colour_backend(self):
        backend = build_display_backend(DisplayConfig(model=MODEL, width=1360, height=480))
        assert isinstance(backend, WaveshareColorBackend)

    def test_mono_model_gets_mono_backend(self):
        assert isinstance(build_display_backend(DisplayConfig()), WaveshareBackend)

    def test_unknown_waveshare_model_falls_back_to_mono(self):
        assert isinstance(build_display_backend(DisplayConfig(model="epd_fake")), WaveshareBackend)
