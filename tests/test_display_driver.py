"""Tests for src/display/driver.py — display registries and drivers."""

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.display.driver import (
    INKY_MODELS,
    WAVESHARE_MODELS,
    DryRunDisplay,
    InkyDisplay,
    WaveshareDisplay,
    build_display_driver,
    get_display_spec,
    image_changed,
)


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "output"


@pytest.fixture
def display(output_dir):
    return DryRunDisplay(output_dir=str(output_dir))


def _make_image() -> Image.Image:
    return Image.new("1", (800, 480), 1)


class TestDryRunDisplayInit:
    def test_creates_output_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        DryRunDisplay(output_dir=str(nested))
        assert nested.is_dir()

    def test_existing_directory_ok(self, output_dir):
        output_dir.mkdir(parents=True)
        DryRunDisplay(output_dir=str(output_dir))  # no exception


class TestDryRunDisplayShow:
    def test_creates_latest_png(self, display, output_dir):
        display.show(_make_image())
        assert (output_dir / "latest.png").exists()

    def test_creates_timestamped_png(self, display, output_dir):
        display.show(_make_image())
        pngs = list(output_dir.glob("dashboard_*.png"))
        assert len(pngs) == 1

    def test_latest_png_is_valid_image(self, display, output_dir):
        display.show(_make_image())
        loaded = Image.open(output_dir / "latest.png")
        assert loaded.size == (800, 480)

    def test_multiple_shows_create_multiple_timestamped(self, display, output_dir):
        import time

        display.show(_make_image())
        time.sleep(1.1)  # ensure different second → different filename
        display.show(_make_image())
        pngs = list(output_dir.glob("dashboard_*.png"))
        assert len(pngs) == 2

    def test_latest_png_overwritten_each_call(self, display, output_dir):
        img1 = Image.new("1", (800, 480), 0)  # all black
        img2 = Image.new("1", (800, 480), 1)  # all white

        display.show(img1)
        display.show(img2)

        # File was rewritten (sizes may differ between all-black and all-white PNGs)
        loaded = Image.open(output_dir / "latest.png")
        assert loaded.size == (800, 480)


class TestDryRunDisplayClear:
    def test_clear_does_not_raise(self, display):
        display.clear()  # should be a no-op, no exception


class TestWaveshareModels:
    def test_registry_contains_default_model(self):
        assert "epd7in5_V2" in WAVESHARE_MODELS

    def test_registry_contains_larger_models(self):
        assert "epd9in7" in WAVESHARE_MODELS
        assert "epd13in3k" in WAVESHARE_MODELS

    def test_default_model_dimensions(self):
        _, w, h = WAVESHARE_MODELS["epd7in5_V2"]
        assert w == 800
        assert h == 480

    def test_epd9in7_dimensions(self):
        _, w, h = WAVESHARE_MODELS["epd9in7"]
        assert w == 1200
        assert h == 825

    def test_epd13in3k_dimensions(self):
        _, w, h = WAVESHARE_MODELS["epd13in3k"]
        assert w == 1600
        assert h == 1200

    def test_all_entries_have_module_path(self):
        for name, (module_path, w, h) in WAVESHARE_MODELS.items():
            assert module_path.startswith("waveshare_epd."), name
            assert w > 0 and h > 0, name


class TestInkyModels:
    def test_registry_contains_2025_model(self):
        assert "impression_7_3_2025" in INKY_MODELS

    def test_2025_model_dimensions(self):
        w, h = INKY_MODELS["impression_7_3_2025"]
        assert w == 800
        assert h == 480

    def test_display_spec_for_inky(self):
        spec = get_display_spec("inky", "impression_7_3_2025")
        assert spec is not None
        assert spec.render_mode == "RGB"
        assert spec.supports_partial_refresh is False


class TestWaveshareDisplayInit:
    def test_valid_model_accepted(self):
        d = WaveshareDisplay(model="epd7in5_V2")
        assert d.model == "epd7in5_V2"

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="Unknown Waveshare model"):
            WaveshareDisplay(model="epd_does_not_exist")

    def test_native_dimensions_from_model(self):
        d = WaveshareDisplay(model="epd9in7")
        assert d.native_width == 1200
        assert d.native_height == 825

    def test_native_dimensions_default_model(self):
        d = WaveshareDisplay(model="epd7in5_V2")
        assert d.native_width == 800
        assert d.native_height == 480


class TestWaveshareDisplayHardware:
    """Tests for WaveshareDisplay methods that require mocked hardware."""

    def _make_mock_epd(self):
        epd = MagicMock()
        epd.init = MagicMock()
        epd.init_fast = MagicMock()
        epd.display = MagicMock()
        epd.getbuffer = MagicMock(return_value=b"buf")
        epd.sleep = MagicMock()
        epd.Clear = MagicMock()
        return epd

    def _make_mock_module(self, epd):
        mod = MagicMock()
        mod.EPD.return_value = epd
        return mod

    def test_get_epd_imports_module(self):
        epd = self._make_mock_epd()
        mod = self._make_mock_module(epd)
        d = WaveshareDisplay(model="epd7in5_V2")
        with patch("importlib.import_module", return_value=mod):
            result = d._get_epd()
        assert result is epd

    def test_get_epd_caches_instance(self):
        epd = self._make_mock_epd()
        mod = self._make_mock_module(epd)
        d = WaveshareDisplay(model="epd7in5_V2")
        with patch("importlib.import_module", return_value=mod) as mock_import:
            d._get_epd()
            d._get_epd()
        # importlib.import_module should only be called once (result is cached)
        assert mock_import.call_count == 1

    def test_show_full_refresh(self):
        epd = self._make_mock_epd()
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = True

        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=False)
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            d.show(image)

        epd.init.assert_called_once()
        epd.display.assert_called_once()
        epd.sleep.assert_called_once()
        tracker.record_full.assert_called_once()
        tracker.save.assert_called_once()

    def test_show_partial_refresh(self):
        epd = self._make_mock_epd()
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = False

        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=True)
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            d.show(image)

        epd.init_fast.assert_called_once()
        epd.display.assert_called_once()
        tracker.record_partial.assert_called_once()

    def test_show_force_full_overrides_partial(self):
        epd = self._make_mock_epd()
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = False

        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=True)
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            d.show(image, force_full=True)

        epd.init.assert_called_once()
        tracker.record_full.assert_called_once()

    def test_show_sleeps_even_on_display_error(self):
        """epd.sleep() must be called even if display() raises."""
        epd = self._make_mock_epd()
        epd.display.side_effect = RuntimeError("display failed")
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = True

        d = WaveshareDisplay(model="epd7in5_V2")
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            with pytest.raises(RuntimeError):
                d.show(image)
        epd.sleep.assert_called_once()

    def test_clear(self):
        epd = self._make_mock_epd()
        d = WaveshareDisplay(model="epd7in5_V2")
        with patch.object(d, "_get_epd", return_value=epd):
            d.clear()
        epd.init.assert_called_once()
        epd.Clear.assert_called_once()
        epd.sleep.assert_called_once()


class TestInkyDisplayInit:
    def test_valid_model_accepted(self):
        d = InkyDisplay(model="impression_7_3_2025")
        assert d.model == "impression_7_3_2025"

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="Unknown Inky model"):
            InkyDisplay(model="inky_does_not_exist")

    def test_native_dimensions(self):
        d = InkyDisplay(model="impression_7_3_2025")
        assert d.native_width == 800
        assert d.native_height == 480


class TestInkyDisplayHardware:
    def _make_mock_device(self):
        device = MagicMock()
        device.set_image = MagicMock()
        device.show = MagicMock()
        return device

    def test_get_device_imports_inky_auto(self):
        device = self._make_mock_device()
        mod = MagicMock()
        mod.auto.return_value = device
        d = InkyDisplay(model="impression_7_3_2025")
        with patch("importlib.import_module", return_value=mod):
            result = d._get_device()
        assert result is device

    def test_show_converts_to_rgb(self):
        device = self._make_mock_device()
        d = InkyDisplay(model="impression_7_3_2025")
        image = Image.new("1", (800, 480), 1)
        with patch.object(d, "_get_device", return_value=device):
            d.show(image)
        shown = device.set_image.call_args.args[0]
        assert shown.mode == "RGB"
        device.show.assert_called_once()

    def test_clear_displays_blank_rgb_image(self):
        device = self._make_mock_device()
        d = InkyDisplay(model="impression_7_3_2025")
        with patch.object(d, "_get_device", return_value=device):
            d.clear()
        shown = device.set_image.call_args.args[0]
        assert shown.mode == "RGB"
        assert shown.size == (800, 480)
        device.show.assert_called_once()


class TestBuildDisplayDriver:
    def test_builds_waveshare_driver(self):
        driver = build_display_driver(provider="waveshare", model="epd7in5_V2")
        assert isinstance(driver, WaveshareDisplay)

    def test_builds_inky_driver(self):
        driver = build_display_driver(provider="inky", model="impression_7_3_2025")
        assert isinstance(driver, InkyDisplay)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown display provider"):
            build_display_driver(provider="future", model="x")


class TestImageChanged:
    def test_returns_true_when_no_hash_file(self, tmp_path):
        image = Image.new("1", (100, 100), 1)
        assert image_changed(image, str(tmp_path)) is True

    def test_returns_false_when_image_unchanged(self, tmp_path):
        image = Image.new("1", (100, 100), 1)
        image_changed(image, str(tmp_path))  # write hash
        assert image_changed(image, str(tmp_path)) is False

    def test_returns_true_when_image_differs(self, tmp_path):
        img1 = Image.new("1", (100, 100), 1)
        img2 = Image.new("1", (100, 100), 0)
        image_changed(img1, str(tmp_path))  # write hash for img1
        assert image_changed(img2, str(tmp_path)) is True

    def test_hash_file_written_after_change(self, tmp_path):
        image = Image.new("1", (100, 100), 1)
        image_changed(image, str(tmp_path))
        hash_file = tmp_path / "last_image_hash.txt"
        assert hash_file.exists()
        assert len(hash_file.read_text().strip()) == 64  # SHA-256 hex digest

    def test_treats_corrupt_hash_file_as_changed(self, tmp_path):
        image = Image.new("1", (100, 100), 1)
        hash_file = tmp_path / "last_image_hash.txt"
        hash_file.write_text("not-a-valid-hash\n")
        # Different hash → treated as changed
        assert image_changed(image, str(tmp_path)) is True

    def test_handles_unreadable_hash_file(self, tmp_path):
        """If the hash file can't be read, treat the image as changed."""
        image = Image.new("1", (100, 100), 1)
        hash_file = tmp_path / "last_image_hash.txt"
        hash_file.write_text("anything")
        with patch("pathlib.Path.read_text", side_effect=OSError("no perm")):
            result = image_changed(image, str(tmp_path))
        assert result is True

    def test_continues_when_hash_write_fails(self, tmp_path):
        """Even if the hash can't be written, image_changed should return True."""
        image = Image.new("1", (100, 100), 1)
        with patch("pathlib.Path.write_text", side_effect=OSError("read-only")):
            result = image_changed(image, str(tmp_path))
        assert result is True
