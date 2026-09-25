from __future__ import annotations

import hashlib
import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# Registry of supported Waveshare eInk display models.
# Maps model name → (waveshare_epd module path, native width px, native height px).
# Every entry names a module that exists in waveshare/e-Paper's
# ``RaspberryPi_JetsonNano/python/lib/waveshare_epd`` (except ``epd10in85g``,
# see below), and its dimensions are the driver's own ``EPD_WIDTH`` /
# ``EPD_HEIGHT``. They have to be: a driver's ``getbuffer()`` compares the
# image against those constants and returns a blank buffer on a mismatch, so a
# wrong size here is a white panel with no error (#266). ``epd9in7`` and
# ``epd7in5_V3`` used to be listed; neither module exists upstream (the 9.7"
# panel is IT8951-driven), so selecting them failed at import on the first
# hardware write.
WAVESHARE_MODELS: dict[str, tuple[str, int, int]] = {
    "epd7in5": ("waveshare_epd.epd7in5", 640, 384),
    "epd7in5_V2": ("waveshare_epd.epd7in5_V2", 800, 480),
    "epd7in5b_V2": ("waveshare_epd.epd7in5b_V2", 800, 480),
    "epd7in5_HD": ("waveshare_epd.epd7in5_HD", 880, 528),
    "epd13in3k": ("waveshare_epd.epd13in3k", 960, 680),
    # 10.85" e-Paper (G): a 1360x480 panoramic strip with four inks. Module
    # name follows Waveshare's convention for the "G" family (epd7in3g,
    # epd4in37g): the demo code that ships with the panel installs it as
    # ``waveshare_epd.epd10in85g``.
    "epd10in85g": ("waveshare_epd.epd10in85g", 1360, 480),
}

# The name of the fast full-frame waveform each vendor driver exposes, for the
# models that have one. This is the method ``WaveshareDisplay.show()`` calls
# on a partial refresh, and a model absent from this dict does not support
# partial refresh: ``epd7in5`` and ``epd7in5_HD`` ship only ``init()``, the
# 13.3" K has an ``init_Part`` LUT meant for its windowed ``display_Partial``
# rather than a full-frame repaint, and the G drivers repaint all four inks
# every time. Until this was a per-model fact, every mono model claimed the
# fast path and all but ``epd7in5_V2`` raised ``AttributeError`` on the first
# partial refresh — and kept raising every tick, because the failed run never
# recorded a partial and so never reached the next full one (#268).
WAVESHARE_FAST_INIT: dict[str, str] = {
    "epd7in5_V2": "init_fast",
    "epd7in5b_V2": "init_Fast",
}

# Tri-colour (black/white/red) drivers whose ``display()`` takes two planes,
# ``(imageblack, imagered)``. The dashboard renders monochrome, so the red
# plane it sends is empty; see ``WaveshareDisplay._blank_red_plane`` for why
# "empty" is all-zero bytes and not 0xFF (#267).
WAVESHARE_TRICOLOR_MODELS: frozenset[str] = frozenset({"epd7in5b_V2"})

# The physical inks of a Waveshare "G" panel, in the order the driver's
# ``getbuffer()`` packs them (black=00, white=01, yellow=10, red=11). A model
# listed here is a colour model: the backend snaps the rendered image to these
# exact values before it reaches the driver, and ``WaveshareDisplay.show()``
# always drives it with the full waveform — the G drivers expose no
# ``init_fast()``, and a 4-ink refresh is a full repaint by nature.
WAVESHARE_G_PALETTE: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),
    (255, 255, 255),
    (255, 255, 0),
    (255, 0, 0),
)

WAVESHARE_COLOR_MODELS: dict[str, tuple[tuple[int, int, int], ...]] = {
    "epd10in85g": WAVESHARE_G_PALETTE,
}

INKY_MODELS: dict[str, tuple[int, int]] = {
    "impression_7_3_2025": (800, 480),
}

# Maps Inky model name → (module_path, class_name, init_kwargs).
# Direct instantiation is used instead of inky.auto.auto() because some hardware
# revisions (e.g. impression_7_3_2025) do not expose EEPROM data for auto-detection.
# The 2025 Spectra 6 7.3" panel uses InkyE673 (inky_e673.py), NOT Inky_Impressions_7
# (inky_ac073tc1a.py) which is the older 7-color/orange driver for a different panel.
INKY_MODEL_INIT: dict[str, tuple[str, str, dict]] = {
    "impression_7_3_2025": ("inky", "InkyE673", {}),
}

_HASH_FILENAME = "last_image_hash.txt"


@dataclass(frozen=True)
class DisplaySpec:
    provider: str
    model: str
    width: int
    height: int
    render_mode: str
    supports_partial_refresh: bool
    # The panel's inks, for a colour model whose driver takes an image it maps
    # onto a fixed palette (the Waveshare "G" family). ``None`` for 1-bit
    # panels and for Inky, whose palette lives with its quantizer.
    palette: tuple[tuple[int, int, int], ...] | None = None

    @property
    def is_color(self) -> bool:
        """Whether the panel shows more than black and white."""
        return self.render_mode == "RGB"


def _build_display_specs() -> dict[tuple[str, str], DisplaySpec]:
    specs: dict[tuple[str, str], DisplaySpec] = {}
    for model, (_, width, height) in WAVESHARE_MODELS.items():
        palette = WAVESHARE_COLOR_MODELS.get(model)
        specs[("waveshare", model)] = DisplaySpec(
            provider="waveshare",
            model=model,
            width=width,
            height=height,
            render_mode="RGB" if palette is not None else "1",
            supports_partial_refresh=model in WAVESHARE_FAST_INIT,
            palette=palette,
        )
    for model, (width, height) in INKY_MODELS.items():
        specs[("inky", model)] = DisplaySpec(
            provider="inky",
            model=model,
            width=width,
            height=height,
            render_mode="RGB",
            supports_partial_refresh=False,
        )
    return specs


DISPLAY_SPECS: dict[tuple[str, str], DisplaySpec] = _build_display_specs()


def get_display_spec(provider: str, model: str) -> DisplaySpec | None:
    return DISPLAY_SPECS.get((provider, model))


def supported_display_models(provider: str | None = None) -> list[str]:
    if provider is None:
        return sorted(model for _, model in DISPLAY_SPECS)
    return sorted(model for spec_provider, model in DISPLAY_SPECS if spec_provider == provider)


def image_hash(image: Image.Image) -> str:
    """Compute a fast SHA-256 hash of the raw pixel data."""
    return hashlib.sha256(image.tobytes()).hexdigest()


def image_changed(new_image: Image.Image, output_dir: str) -> bool:
    """Return True if the image differs from the last *displayed* image.

    Compares SHA-256 hashes of the raw pixel bytes against
    ``<output_dir>/last_image_hash.txt``. Pure comparison — the hash is
    persisted separately via :func:`persist_image_hash`, only after the
    hardware write succeeds. Persisting here recorded frames the panel never
    actually showed, so one transient display failure pinned the panel on
    stale content until the data changed again (issue #207).
    """
    hash_path = Path(output_dir) / _HASH_FILENAME
    new_hash = image_hash(new_image)

    if hash_path.exists():
        try:
            old_hash = hash_path.read_text().strip()
            if old_hash == new_hash:
                return False
        except Exception:
            pass  # treat read failure as "changed"

    return True


def persist_image_hash(image: Image.Image, output_dir: str) -> None:
    """Record *image* as the currently-displayed frame for future comparisons.

    Call only after a successful hardware write — see :func:`image_changed`.
    """
    hash_path = Path(output_dir) / _HASH_FILENAME
    try:
        hash_path.parent.mkdir(parents=True, exist_ok=True)
        hash_path.write_text(image_hash(image) + "\n")
    except Exception as exc:
        logger.warning("Could not write image hash: %s", exc)


class DisplayDriver(ABC):
    @abstractmethod
    def show(self, image: Image.Image, force_full: bool = False) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...


#: How many timestamped dry-run PNGs to keep. Nothing used to remove them and
#: nothing capped the count: they are gitignored (``output/*.png`` with a
#: ``!output/latest.png`` exception), so they never showed up in ``git status``
#: while quietly filling the card at ~50-100 KB each — and ``make dry`` and
#: preview loops produce them in bulk. The log file next door gets a logrotate
#: config; these got nothing (#245).
DRY_RUN_HISTORY = 20


class DryRunDisplay(DisplayDriver):
    """Saves rendered image to PNG. No hardware dependency."""

    def __init__(self, output_dir: str = "output", keep: int = DRY_RUN_HISTORY):
        self.output_dir = Path(output_dir)
        self.keep = keep
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def show(self, image: Image.Image, force_full: bool = False) -> None:
        del force_full
        # Save timestamped version
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # allow-naive-datetime — file-name timestamp
        path = self.output_dir / f"dashboard_{ts}.png"
        image.save(path)

        # Also overwrite latest.png for quick preview
        latest = self.output_dir / "latest.png"
        image.save(latest)

        self._prune_history()

        print(f"Dry run: saved {path}")
        print(f"Dry run: updated {latest}")

    def _prune_history(self) -> None:
        """Keep only the newest ``self.keep`` timestamped dry-run PNGs.

        Sorted by name, which for ``dashboard_YYYYmmdd_HHMMSS.png`` is
        chronological order and does not depend on filesystem mtimes.
        ``latest.png`` never matches the glob, so it is never a candidate.
        """
        if self.keep is None or self.keep < 0:
            return
        try:
            history = sorted(self.output_dir.glob("dashboard_*.png"))
            for stale in history[: max(0, len(history) - self.keep)]:
                stale.unlink()
        except OSError as exc:
            # Housekeeping must never be what fails a preview.
            logger.debug("Could not prune dry-run PNGs: %s", exc)

    def clear(self) -> None:
        print("Dry run: clear (no-op)")


class WaveshareDisplay(DisplayDriver):
    """Drives a Waveshare eInk display. Supports multiple models via WAVESHARE_MODELS."""

    def __init__(
        self,
        model: str = "epd7in5_V2",
        enable_partial: bool = False,
        max_partials: int = 6,
        state_dir: str | None = None,
    ):
        if model not in WAVESHARE_MODELS:
            raise ValueError(
                f"Unknown Waveshare model '{model}'. Supported models: {sorted(WAVESHARE_MODELS)}"
            )
        self.model = model
        # Only a model with a fast full-frame waveform can honour the option;
        # the colour ("G") panels and the mono models that ship only ``init()``
        # take the full waveform on every write whatever the config says.
        self.enable_partial = enable_partial and model in WAVESHARE_FAST_INIT
        if enable_partial and not self.enable_partial:
            logger.warning(
                "Partial refresh is not supported on Waveshare model %s (its driver has "
                "no fast waveform); every write uses the full refresh.",
                model,
            )
        self.max_partials = max_partials
        self.state_dir = state_dir
        self._epd = None

    @property
    def is_color(self) -> bool:
        return self.model in WAVESHARE_COLOR_MODELS

    @property
    def is_tricolor(self) -> bool:
        return self.model in WAVESHARE_TRICOLOR_MODELS

    @staticmethod
    def _blank_red_plane(black: bytes | bytearray | list) -> bytearray:
        """An all-white red plane the same size as *black*.

        The tri-colour driver's ``getbuffer()`` XORs every byte with 0xFF, so
        a white image comes out of it as 0x00 bytes; ``display()`` XORs the
        black plane back before writing it but sends the red plane as given.
        Waveshare's own demo builds the red plane by running a white image
        through ``getbuffer()``, so "no red" is all-zero bytes. An all-0xFF
        plane would paint the whole panel red.
        """
        return bytearray(len(black))

    def _write_frame(self, epd, image: Image.Image) -> None:
        """Push one frame through the vendor driver's ``display()``."""
        # A "G" driver's getbuffer() maps RGB onto the panel's four inks
        # itself; the backend has already snapped every pixel to one of them,
        # so that mapping is exact. A 1-bit driver wants the "1" image the
        # mono backend produced.
        black = epd.getbuffer(image)
        if self.is_tricolor:
            # display(imageblack, imagered): the dashboard is monochrome, so
            # the red plane is blank. Calling display() with one buffer, as
            # every other model takes, raised TypeError on every write (#267).
            epd.display(black, self._blank_red_plane(black))
        else:
            epd.display(black)

    def _fast_init(self, epd):
        """Return the driver's fast full-frame init, or ``None`` if it has none.

        Looked up by the name the registry records for the model, then by the
        two spellings the vendor library uses (``init_fast`` on the 7.5" V2,
        ``init_Fast`` on the tri-colour 7.5"), so a driver whose author picked
        the other case still gets its fast path.
        """
        names = [WAVESHARE_FAST_INIT.get(self.model), "init_fast", "init_Fast"]
        for name in names:
            if name and callable(getattr(epd, name, None)):
                return getattr(epd, name)
        return None

    @property
    def native_width(self) -> int:
        return WAVESHARE_MODELS[self.model][1]

    @property
    def native_height(self) -> int:
        return WAVESHARE_MODELS[self.model][2]

    def _get_epd(self):
        if self._epd is None:
            module_path = WAVESHARE_MODELS[self.model][0]
            module = importlib.import_module(module_path)
            self._epd = module.EPD()
        return self._epd

    def show(self, image: Image.Image, force_full: bool = False) -> None:
        from pathlib import Path

        from src.display.refresh_tracker import RefreshTracker

        state_path = (
            Path(self.state_dir) / "dashboard_refresh_state.json"
            if self.state_dir is not None
            else None
        )
        epd = self._get_epd()
        tracker = RefreshTracker.load(max_partials=self.max_partials, state_path=state_path)

        try:
            fast_init = self._fast_init(epd) if self.enable_partial else None
            if self.enable_partial and fast_init is None:
                # The registry said this model has a fast waveform but the
                # installed driver does not expose one (an older or renamed
                # vendor library). Fall back rather than fail every tick.
                logger.warning(
                    "Waveshare driver for %s has no fast waveform method; using a full "
                    "refresh instead of the requested partial refresh.",
                    self.model,
                )
            if (
                force_full
                or not self.enable_partial
                or fast_init is None
                or tracker.needs_full_refresh()
            ):
                epd.init()
                self._write_frame(epd, image)
                tracker.record_full()
            else:
                # Fast waveform: quicker, but it does not drive black as
                # deeply as a full init, so solid fills read closer to
                # charcoal than to ink and ghosting accumulates. Reached only
                # when the user opts into partial refresh.
                fast_init()
                self._write_frame(epd, image)
                tracker.record_partial()
        finally:
            try:
                tracker.save()
            except Exception as exc:
                logger.warning("Could not save refresh state: %s", exc)
            try:
                epd.sleep()
            except Exception as exc:
                logger.warning("EPD sleep failed: %s", exc)

    def clear(self) -> None:
        epd = self._get_epd()
        epd.init()
        epd.Clear()
        epd.sleep()


class InkyDisplay(DisplayDriver):
    """Drive a Pimoroni Inky display via the `inky` library."""

    def __init__(self, model: str = "impression_7_3_2025"):
        if model not in INKY_MODELS:
            raise ValueError(
                f"Unknown Inky model '{model}'. Supported models: {sorted(INKY_MODELS)}"
            )
        self.model = model
        self._device = None

    @property
    def native_width(self) -> int:
        return INKY_MODELS[self.model][0]

    @property
    def native_height(self) -> int:
        return INKY_MODELS[self.model][1]

    def _get_device(self):
        if self._device is None:
            module_path, class_name, kwargs = INKY_MODEL_INIT[self.model]
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            self._device = cls(**kwargs)
        return self._device

    def show(self, image: Image.Image, force_full: bool = False) -> None:
        del force_full  # Inky does not expose partial/full refresh control here.
        import numpy as np

        device = self._get_device()
        # inky_ac073tc1a.py's set_image() uses the deprecated image.im.convert("P", ...)
        # internal Pillow API which assigns wrong palette indices with Pillow 10+.
        # Pillow's .quantize(palette=...) also calls this broken path internally.
        # Bypass set_image() entirely — it uses broken PIL internal APIs with Pillow 10+.
        # Compute nearest SATURATED_PALETTE index per pixel via numpy, then apply the
        # InkyE673 controller remap [0,1,2,3,5,6] that skips controller position 4
        # (matching inky_e673.py's set_image() remap step).  Write a 2-D (H×W) array
        # to device.buf so show()'s flip/rotation transforms work on correctly-shaped data.
        _REMAP = np.array([0, 1, 2, 3, 5, 6], dtype=np.uint8)
        rgb = np.array(image.convert("RGB"), dtype=np.int32)  # (H, W, 3)
        # Use only the 6 ink colours — SATURATED_PALETTE may include Clear at index 6.
        palette = np.array(device.SATURATED_PALETTE[: len(_REMAP)], dtype=np.int32)  # (6, 3)
        diff = rgb[:, :, np.newaxis, :] - palette[np.newaxis, np.newaxis, :, :]
        logical_idx = np.argmin(np.sum(diff**2, axis=3), axis=2).astype(np.uint8)  # (H, W)
        device.buf = _REMAP[logical_idx]  # (H, W), controller positions
        device.show()

    def clear(self) -> None:
        import numpy as np

        device = self._get_device()
        # White ink is always palette index 1 in Inky Spectra 6 displays.
        # Write a 2-D (height × width) array directly to device.buf, matching the
        # shape that set_image() would produce, so show()'s flip/rotation logic works.
        device.buf = np.ones((self.native_height, self.native_width), dtype=np.uint8)
        device.show()


def build_display_driver(
    *,
    provider: str,
    model: str,
    enable_partial: bool = False,
    max_partials: int = 6,
    state_dir: str | None = None,
) -> DisplayDriver:
    if provider == "waveshare":
        return WaveshareDisplay(
            model=model,
            enable_partial=enable_partial,
            max_partials=max_partials,
            state_dir=state_dir,
        )
    if provider == "inky":
        return InkyDisplay(model=model)
    raise ValueError(f"Unknown display provider '{provider}'. Supported providers: inky, waveshare")
