import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("/tmp/dashboard_refresh_state.json")


class RefreshTracker:
    def __init__(self, partial_count: int = 0, last_full: datetime | None = None,
                 max_partials: int = 6):
        self.partial_count = partial_count
        self.last_full = last_full
        self.max_partials = max_partials

    @classmethod
    def load(cls, max_partials: int = 6) -> "RefreshTracker":
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                return cls(
                    partial_count=data.get("partial_count", 0),
                    last_full=(
                        datetime.fromisoformat(data["last_full"])
                        if data.get("last_full") else None
                    ),
                    max_partials=max_partials,
                )
            except (json.JSONDecodeError, KeyError):
                pass
        return cls(max_partials=max_partials)

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
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STATE_FILE.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, STATE_FILE)
        except BaseException:
            os.unlink(tmp)
            raise
