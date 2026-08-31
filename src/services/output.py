"""OutputService — publish a rendered image to the configured display.

The v4 "Inky hourly throttle" is replaced in v5 with a backend-agnostic
**content-hash + minimum-cooldown** throttle: any rendered image whose
SHA-256 differs from the last persisted hash is allowed to refresh,
subject to ``DisplayConfig.min_refresh_interval_seconds`` (default 60s on
Inky, 0s on Waveshare).

State persists in ``state/refresh_throttle_state.json``. The legacy
``inky_refresh_state.json`` is migrated transparently on read.

Separately, a theme can decline the Waveshare fast waveform outright —
``Theme.allows_partial_refresh``, derived from the plate — and
:meth:`OutputService.publish` then builds the driver with partials off no
matter what the config asked for.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from src._io import atomic_write_json
from src._time import now_local, to_aware
from src.display.driver import (
    DryRunDisplay,
    build_display_driver,
    image_changed,
    persist_image_hash,
)

logger = logging.getLogger(__name__)

_REFRESH_STATE_FILENAME = "refresh_throttle_state.json"
_LEGACY_INKY_STATE_FILENAME = "inky_refresh_state.json"

_DEFAULT_MIN_REFRESH_SECONDS = {"inky": 60, "waveshare": 0}


def _resolve_min_refresh_seconds(provider: str, configured: int | None) -> int:
    """Return the cooldown to enforce, given a provider and a config value."""
    if configured is not None:
        return max(0, int(configured))
    return _DEFAULT_MIN_REFRESH_SECONDS.get(provider, 0)


def _refresh_state_path(state_dir: str) -> Path:
    return Path(state_dir) / _REFRESH_STATE_FILENAME


def _legacy_inky_state_path(state_dir: str) -> Path:
    return Path(state_dir) / _LEGACY_INKY_STATE_FILENAME


def _load_last_refresh(state_dir: str) -> datetime | None:
    """Read the last-refresh timestamp, migrating from the legacy file once."""
    path = _refresh_state_path(state_dir)
    if not path.exists():
        legacy = _legacy_inky_state_path(state_dir)
        if not legacy.exists():
            return None
        # Migrate legacy file: parse to validate shape, then atomically rename
        # under the new name. Both files use the same JSON schema
        # ({"last_refresh_at": "<iso>"}) so a rename preserves the payload
        # bit-for-bit. ``Path.replace`` is atomic on POSIX so a kill mid-rename
        # leaves either the legacy or the new file in place — never both.
        try:
            raw = json.loads(legacy.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        value = raw.get("last_refresh_at") if isinstance(raw, dict) else None
        if not isinstance(value, str):
            return None
        try:
            ts = datetime.fromisoformat(value)
        except ValueError:
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(path)
        except OSError as exc:
            logger.debug("Could not migrate legacy inky refresh state: %s", exc)
        # Legacy v4 files were written via datetime.utcnow().isoformat() —
        # naive. Readers treat naive ISO timestamps as UTC (repo convention);
        # returning them raw made the aware-now subtraction in
        # should_throttle_display_refresh raise TypeError on every publish,
        # a permanent crash loop until the state file was deleted (#208).
        return to_aware(ts)

    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    value = raw.get("last_refresh_at")
    if not isinstance(value, str):
        return None
    try:
        # Naive timestamps (legacy writers) are treated as UTC — see the
        # migration branch above (#208).
        return to_aware(datetime.fromisoformat(value))
    except ValueError:
        return None


def _save_last_refresh(state_dir: str, when: datetime) -> None:
    path = _refresh_state_path(state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write so a kill mid-write can't truncate the state file (matches
        # the invariant used by every other JSON state file — see src/_io.py).
        atomic_write_json(path, {"last_refresh_at": when.isoformat()})
    except OSError as exc:
        logger.warning("Could not write refresh throttle state: %s", exc)


def should_throttle_display_refresh(
    *,
    provider: str,
    now: datetime,
    state_dir: str,
    force_full: bool,
    min_interval_seconds: int,
) -> bool:
    """Return True iff the cooldown window has not yet elapsed.

    ``force_full`` and ``min_interval_seconds <= 0`` always pass through.
    """
    if force_full or min_interval_seconds <= 0:
        return False
    last = _load_last_refresh(state_dir)
    if last is None:
        return False
    elapsed = (now - last).total_seconds()
    return elapsed < min_interval_seconds


class OutputService:
    def __init__(self, cfg, tz):
        self.cfg = cfg
        self.tz = tz

    def publish(
        self,
        image,
        *,
        dry_run: bool,
        force_full: bool,
        now: datetime,
        theme_name: str,
        theme_supports_partial: bool = True,
    ) -> None:
        if dry_run:
            DryRunDisplay(output_dir=self.cfg.output_dir).show(image)
            return

        # Two-stage refresh suppression:
        #   1. Cooldown — minimum seconds between hardware writes regardless
        #      of whether content changed. Blocks rapid-fire refreshes on
        #      slow panels (Inky default 60s; set 3600 to restore v4 hourly).
        #   2. Image hash — short-circuits identical-content refreshes.
        # The cooldown intentionally blocks novel content too; the cap is a
        # rate-limiter on the hardware, not just a dedup filter.
        min_interval = _resolve_min_refresh_seconds(
            self.cfg.display.provider, self.cfg.display.min_refresh_interval_seconds
        )
        if should_throttle_display_refresh(
            provider=self.cfg.display.provider,
            now=now,
            state_dir=self.cfg.state_dir,
            force_full=force_full,
            min_interval_seconds=min_interval,
        ):
            logger.info(
                "Display refresh rate-limited (cooldown %ds, theme '%s') — "
                "deferring any pending content change to the next eligible run",
                min_interval,
                theme_name,
            )
            # The content *did* change; the panel just is not allowed to redraw
            # yet. latest.png claims to be the current render, and the web UI
            # shows it as such — leaving the previous frame there made it wrong
            # for up to min_refresh_interval_seconds, an hour for anyone who
            # sets 3600 on Inky to restore the v4 hourly throttle, which is the
            # configuration the docs recommend (#245).
            self._save_latest_png(image)
            return

        if not image_changed(image, self.cfg.output_dir) and not force_full:
            logger.info("Image unchanged — skipping display refresh")
            return

        # A theme can decline the fast waveform (Theme.allows_partial_refresh).
        # Waveshare's init_fast() does not drive black as deeply as a full init, so a
        # plate built from dithered greyscale fades in bands aligned with its artwork;
        # for those themes the config's opt-in is overridden rather than obeyed (#222).
        enable_partial = self.cfg.display.enable_partial_refresh and theme_supports_partial
        if self.cfg.display.enable_partial_refresh and not theme_supports_partial:
            logger.info(
                "Theme '%s' does not support partial refresh — using the full waveform",
                theme_name,
            )

        build_display_driver(
            provider=self.cfg.display.provider,
            model=self.cfg.display.model,
            enable_partial=enable_partial,
            max_partials=self.cfg.display.max_partials_before_full,
            state_dir=self.cfg.state_dir,
        ).show(image, force_full=force_full)

        # Persist the hash only now that the hardware write succeeded — a
        # failed show() must leave the old hash in place so the next run
        # retries the write instead of skipping it as "unchanged" (#207).
        persist_image_hash(image, self.cfg.output_dir)

        # Record the refresh so the next tick can apply the cooldown. The
        # marker is provider-agnostic now — a Waveshare user who sets
        # min_refresh_interval_seconds gets the same throttling Inky does.
        _save_last_refresh(self.cfg.state_dir, now)

        self._save_latest_png(image)

    def _save_latest_png(self, image) -> None:
        """Write ``output/latest.png`` — the current render, for the web UI.

        Written whether or not the hardware write happened: the unchanged-hash
        path skips it because the file already matches by definition, but the
        cooldown path must not, or the "current display" image is stale for the
        whole cooldown window.
        """
        try:
            latest = Path(self.cfg.output_dir) / "latest.png"
            latest.parent.mkdir(parents=True, exist_ok=True)
            image.save(latest)
        except Exception as exc:
            logger.warning("Could not save latest.png: %s", exc)

    def write_health_marker(self) -> None:
        try:
            marker = Path(self.cfg.output_dir) / "last_success.txt"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(now_local(self.tz).isoformat() + "\n")
        except Exception as exc:
            logger.warning("Could not write last_success.txt: %s", exc)

    def write_error_marker(self, exc: BaseException) -> None:
        """Persist a structured marker describing the most recent run failure.

        The marker is overwritten on each failure and intentionally not deleted
        on success — readers compare its timestamp to ``last_success.txt`` to
        decide whether the error is current or stale.
        """
        try:
            marker = Path(self.cfg.output_dir) / "last_error.txt"
            marker.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "timestamp": now_local(self.tz).isoformat(),
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
            marker.write_text(json.dumps(payload, sort_keys=True) + "\n")
        except Exception as write_exc:
            logger.warning("Could not write last_error.txt: %s", write_exc)
