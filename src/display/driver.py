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
# Maps model name → (waveshare_epd module path, native width px, native height px)
WAVESHARE_MODELS: dict[str, tuple[str, int, int]] = {
    "epd7in5": ("waveshare_epd.epd7in5", 640, 384),
    "epd7in5_V2": ("waveshare_epd.epd7in5_V2", 800, 480),
    "epd7in5_V3": ("waveshare_epd.epd7in5_V3", 800, 480),
    "epd7in5b_V2": ("waveshare_epd.epd7in5b_V2", 800, 480),
    "epd7in5_HD": ("waveshare_epd.epd7in5_HD", 880, 528),
    "epd9in7": ("waveshare_epd.epd9in7", 1200, 825),
    "epd13in3k": ("waveshare_epd.epd13in3k", 1600, 1200),
}

INKY_MODELS: dict[str, tuple[int, int]] = {
    "impression_7_3_2025": (800, 480),
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


def _build_display_specs() -> dict[tuple[str, str], DisplaySpec]:
    specs: dict[tuple[str, str], DisplaySpec] = {}
    for model, (_, width, height) in WAVESHARE_MODELS.items():
        specs[("waveshare", model)] = DisplaySpec(
            provider="waveshare",
            model=model,
            width=width,
            height=height,
            render_mode="1",
            supports_partial_refresh=True,
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
    """Return True if the image differs from the last rendered image.

    Compares SHA-256 hashes of the raw pixel bytes.  The previous hash is
    persisted to ``<output_dir>/last_image_hash.txt`` so comparisons work
    across process invocations.
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

    # Persist the new hash for next comparison
    try:
        hash_path.parent.mkdir(parents=True, exist_ok=True)
        hash_path.write_text(new_hash + "\n")
    except Exception as exc:
        logger.warning("Could not write image hash: %s", exc)

    return True


class DisplayDriver(ABC):
    @abstractmethod
    def show(self, image: Image.Image, force_full: bool = False) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...


class DryRunDisplay(DisplayDriver):
    """Saves rendered image to PNG. No hardware dependency."""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def show(self, image: Image.Image, force_full: bool = False) -> None:
        del force_full
        # Save timestamped version
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"dashboard_{ts}.png"
        image.save(path)

        # Also overwrite latest.png for quick preview
        latest = self.output_dir / "latest.png"
        image.save(latest)

        print(f"Dry run: saved {path}")
        print(f"Dry run: updated {latest}")

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
        self.enable_partial = enable_partial
        self.max_partials = max_partials
        self.state_dir = state_dir
        self._epd = None

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
            if force_full or not self.enable_partial or tracker.needs_full_refresh():
                epd.init()
                epd.display(epd.getbuffer(image))
                tracker.record_full()
            else:
                epd.init_fast()
                epd.display(epd.getbuffer(image))
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
            module = importlib.import_module("inky.auto")
            auto = getattr(module, "auto")
            self._device = auto(ask_user=False, verbose=False)
        return self._device

    def show(self, image: Image.Image, force_full: bool = False) -> None:
        del force_full  # Inky does not expose partial/full refresh control here.
        device = self._get_device()
        device.set_image(image.convert("RGB"))
        device.show()

    def clear(self) -> None:
        device = self._get_device()
        blank = Image.new("RGB", (self.native_width, self.native_height), (255, 255, 255))
        device.set_image(blank)
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
