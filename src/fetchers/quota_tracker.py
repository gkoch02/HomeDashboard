"""Lightweight daily API call counter for quota awareness.

Tracks the number of API calls per source per day and logs warnings when
a configurable threshold is exceeded.  The state file auto-resets on each
new calendar day.
"""

import json
import logging
import threading
from datetime import date
from pathlib import Path

from src._io import atomic_write_json

logger = logging.getLogger(__name__)

_STATE_FILENAME = "api_quota_state.json"


class QuotaTracker:
    """Per-source daily API call counter with persistent state."""

    def __init__(self, state_dir: str = "output"):
        self._state_dir = Path(state_dir)
        self._today = date.today().isoformat()
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()
        self._load()

    def record_call(self, source: str, count: int = 1) -> None:
        """Increment the daily call counter for *source*."""
        with self._lock:
            self._ensure_today()
            self._counts[source] = self._counts.get(source, 0) + count
            self._save()

    def daily_count(self, source: str) -> int:
        """Return the number of API calls recorded for *source* today."""
        with self._lock:
            self._ensure_today()
            return self._counts.get(source, 0)

    def check_warning(self, source: str, threshold: int) -> bool:
        """Return True and log a warning if *source* exceeds *threshold*."""
        count = self.daily_count(source)
        if count > threshold:
            logger.warning(
                "API quota warning: %s has made %d calls today (threshold: %d)",
                source,
                count,
                threshold,
            )
            return True
        return False

    # --- Internal ---

    def _ensure_today(self) -> None:
        """Reset counters if the day has changed."""
        today = date.today().isoformat()
        if today != self._today:
            self._today = today
            self._counts = {}

    def _load(self) -> None:
        path = self._state_dir / _STATE_FILENAME
        if not path.exists():
            return
        try:
            with open(path) as f:
                raw = json.load(f)
            if raw.get("date") == self._today:
                self._counts = raw.get("counts", {})
            # else: stale file from a previous day — start fresh
        except Exception as exc:
            logger.debug("Could not load quota state: %s", exc)

    def _save(self) -> None:
        path = self._state_dir / _STATE_FILENAME
        try:
            raw = {"date": self._today, "counts": self._counts}
            atomic_write_json(path, raw, indent=2)
        except Exception as exc:
            logger.warning("Could not save quota state: %s", exc)
