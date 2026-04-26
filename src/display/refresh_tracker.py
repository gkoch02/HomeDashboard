from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src._io import atomic_write_json

# Fallback used when no state_path is provided (e.g. tests that patch this).
STATE_FILE = Path("/tmp/dashboard_refresh_state.json")


class RefreshTracker:
    def __init__(
        self,
        partial_count: int = 0,
        last_full: datetime | None = None,
        max_partials: int = 6,
        state_path: Path | None = None,
    ):
        self.partial_count = partial_count
        self.last_full = last_full
        self.max_partials = max_partials
        self._state_path = state_path if state_path is not None else STATE_FILE

    @classmethod
    def load(cls, max_partials: int = 6, state_path: Path | None = None) -> RefreshTracker:
        path = state_path if state_path is not None else STATE_FILE
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls(
                    partial_count=data.get("partial_count", 0),
                    last_full=(
                        datetime.fromisoformat(data["last_full"]) if data.get("last_full") else None
                    ),
                    max_partials=max_partials,
                    state_path=path,
                )
            except (json.JSONDecodeError, KeyError):
                pass
        return cls(max_partials=max_partials, state_path=path)

    def needs_full_refresh(self) -> bool:
        if self.last_full is None:
            return True
        if self.partial_count >= self.max_partials:
            return True
        return False

    def record_full(self):
        self.partial_count = 0
        self.last_full = datetime.now()

    def record_partial(self):
        self.partial_count += 1

    def save(self):
        data = {
            "partial_count": self.partial_count,
            "last_full": self.last_full.isoformat() if self.last_full else None,
        }
        atomic_write_json(self._state_path, data)
