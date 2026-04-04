"""Circuit breaker for flaky external APIs.

Tracks consecutive failures per data source and skips fetch attempts during
a cooldown period after repeated failures, reducing wasted network calls and
log noise.

States:
  CLOSED    → normal operation, fetches are attempted
  OPEN      → too many failures, fetches are skipped until cooldown expires
  HALF_OPEN → cooldown expired, allow one probe request
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILENAME = "dashboard_breaker_state.json"


@dataclass
class BreakerState:
    consecutive_failures: int = 0
    last_failure_at: str | None = None  # ISO format
    state: str = "closed"  # "closed", "open", "half_open"


class CircuitBreaker:
    """Per-source circuit breaker with persistent state."""

    def __init__(
        self,
        max_failures: int = 3,
        cooldown_minutes: int = 30,
        state_dir: str = "/tmp",
    ):
        self._max_failures = max_failures
        self._cooldown_minutes = cooldown_minutes
        self._state_dir = Path(state_dir)
        self._states: dict[str, BreakerState] = {}
        self._load()

    # --- Public API ---

    def should_attempt(self, source: str) -> bool:
        """Return True if a fetch should be attempted for *source*."""
        st = self._states.get(source, BreakerState())
        if st.state == "closed":
            return True
        if st.state == "open":
            if self._cooldown_expired(st):
                st.state = "half_open"
                self._states[source] = st
                self._save()
                logger.info("Circuit breaker for %s: OPEN → HALF_OPEN", source)
                return True
            return False
        # half_open: allow one probe
        return True

    def record_success(self, source: str) -> None:
        """Reset the breaker for *source* after a successful fetch."""
        st = self._states.get(source, BreakerState())
        if st.state != "closed" or st.consecutive_failures > 0:
            logger.info("Circuit breaker for %s: → CLOSED", source)
        st.consecutive_failures = 0
        st.last_failure_at = None
        st.state = "closed"
        self._states[source] = st
        self._save()

    def record_failure(self, source: str) -> None:
        """Record a failure; transition to OPEN after max_failures."""
        st = self._states.get(source, BreakerState())
        st.consecutive_failures += 1
        st.last_failure_at = datetime.now(timezone.utc).isoformat()

        if st.consecutive_failures >= self._max_failures:
            st.state = "open"
            logger.warning(
                "Circuit breaker for %s: → OPEN after %d failures "
                "(cooldown: %dm)",
                source, st.consecutive_failures, self._cooldown_minutes,
            )
        elif st.state == "half_open":
            # Probe failed — back to open
            st.state = "open"
            logger.warning("Circuit breaker for %s: HALF_OPEN → OPEN", source)

        self._states[source] = st
        self._save()

    # --- Internal ---

    def _cooldown_expired(self, st: BreakerState) -> bool:
        if st.last_failure_at is None:
            return True
        try:
            last = datetime.fromisoformat(st.last_failure_at)
        except ValueError:
            return True
        # Use UTC for consistent cooldown calculation regardless of clock changes
        now = datetime.now(timezone.utc)
        # Handle legacy naive timestamps by assuming UTC
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = (now - last).total_seconds() / 60
        return age >= self._cooldown_minutes

    def _load(self) -> None:
        path = self._state_dir / _STATE_FILENAME
        if not path.exists():
            return
        try:
            with open(path) as f:
                raw = json.load(f)
            for source, data in raw.items():
                self._states[source] = BreakerState(
                    consecutive_failures=data.get("consecutive_failures", 0),
                    last_failure_at=data.get("last_failure_at"),
                    state=data.get("state", "closed"),
                )
            for source, st in self._states.items():
                if st.state != "closed":
                    logger.info(
                        "Circuit breaker for '%s' loaded in %s state "
                        "(%d consecutive failures)",
                        source, st.state.upper(), st.consecutive_failures,
                    )
        except Exception as exc:
            logger.debug("Could not load breaker state: %s", exc)

    def _save(self) -> None:
        path = self._state_dir / _STATE_FILENAME
        self._state_dir.mkdir(parents=True, exist_ok=True)
        try:
            raw = {}
            for source, st in self._states.items():
                raw[source] = {
                    "consecutive_failures": st.consecutive_failures,
                    "last_failure_at": st.last_failure_at,
                    "state": st.state,
                }
            with open(path, "w") as f:
                json.dump(raw, f, indent=2)
        except Exception as exc:
            logger.warning("Could not save breaker state: %s", exc)
