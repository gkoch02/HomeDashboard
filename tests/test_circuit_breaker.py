"""Tests for circuit breaker (src/fetchers/circuit_breaker.py)."""

import json
from pathlib import Path

import pytest

from src._time import now_utc
from src.fetchers.circuit_breaker import CircuitBreaker


@pytest.fixture
def tmp_state_dir(tmp_path):
    return str(tmp_path)


class TestCircuitBreaker:
    def test_initial_state_allows_attempt(self, tmp_state_dir):
        cb = CircuitBreaker(state_dir=tmp_state_dir)
        assert cb.should_attempt("weather") is True

    def test_single_failure_stays_closed(self, tmp_state_dir):
        cb = CircuitBreaker(max_failures=3, state_dir=tmp_state_dir)
        cb.record_failure("weather")
        assert cb.should_attempt("weather") is True

    def test_opens_after_max_failures(self, tmp_state_dir):
        cb = CircuitBreaker(max_failures=3, state_dir=tmp_state_dir)
        cb.record_failure("weather")
        cb.record_failure("weather")
        cb.record_failure("weather")
        assert cb.should_attempt("weather") is False

    def test_success_resets_breaker(self, tmp_state_dir):
        cb = CircuitBreaker(max_failures=2, state_dir=tmp_state_dir)
        cb.record_failure("weather")
        cb.record_failure("weather")
        assert cb.should_attempt("weather") is False
        # Force half-open by setting cooldown to 0
        cb._cooldown_minutes = 0
        assert cb.should_attempt("weather") is True  # half_open
        cb.record_success("weather")
        assert cb.should_attempt("weather") is True  # closed

    def test_half_open_failure_reopens(self, tmp_state_dir):
        cb = CircuitBreaker(max_failures=2, cooldown_minutes=0, state_dir=tmp_state_dir)
        cb.record_failure("events")
        cb.record_failure("events")
        assert cb.should_attempt("events") is True  # cooldown=0 → half_open
        cb.record_failure("events")  # probe failed
        # Manually check: should be open again but cooldown=0 so half_open
        assert cb._states["events"].state == "open"

    def test_state_persistence(self, tmp_state_dir):
        cb1 = CircuitBreaker(max_failures=2, state_dir=tmp_state_dir)
        cb1.record_failure("weather")
        cb1.record_failure("weather")
        # Open state persisted
        cb2 = CircuitBreaker(max_failures=2, state_dir=tmp_state_dir)
        assert cb2.should_attempt("weather") is False

    def test_independent_sources(self, tmp_state_dir):
        cb = CircuitBreaker(max_failures=2, state_dir=tmp_state_dir)
        cb.record_failure("weather")
        cb.record_failure("weather")
        assert cb.should_attempt("weather") is False
        assert cb.should_attempt("events") is True

    def test_corrupted_state_file(self, tmp_state_dir):
        path = Path(tmp_state_dir) / "dashboard_breaker_state.json"
        path.write_text("not json")
        cb = CircuitBreaker(state_dir=tmp_state_dir)
        assert cb.should_attempt("weather") is True

    # --- Additional coverage tests ---

    def test_half_open_state_allows_attempt(self, tmp_state_dir):
        """should_attempt returns True when state is already half_open (line 62)."""
        from src.fetchers.circuit_breaker import BreakerState

        cb = CircuitBreaker(max_failures=3, state_dir=tmp_state_dir)
        # Manually place breaker in half_open state
        cb._states["weather"] = BreakerState(
            consecutive_failures=3,
            last_failure_at=None,
            state="half_open",
        )
        assert cb.should_attempt("weather") is True

    def test_half_open_probe_failure_with_low_count_reopens(self, tmp_state_dir):
        """record_failure in half_open when consecutive_failures < max_failures → OPEN (lines 90-91)."""
        from src.fetchers.circuit_breaker import BreakerState

        cb = CircuitBreaker(max_failures=5, state_dir=tmp_state_dir)
        # Set half_open with fewer than max_failures consecutive failures
        cb._states["events"] = BreakerState(
            consecutive_failures=2,
            last_failure_at="2020-01-01T00:00:00",
            state="half_open",
        )
        cb.record_failure("events")  # consecutive_failures → 3, still < 5
        assert cb._states["events"].state == "open"

    def test_cooldown_with_none_last_failure_at_returns_expired(self, tmp_state_dir):
        """_cooldown_expired returns True when last_failure_at is None (line 100)."""
        from src.fetchers.circuit_breaker import BreakerState

        cb = CircuitBreaker(max_failures=3, cooldown_minutes=60, state_dir=tmp_state_dir)
        # Set open state with no last_failure_at
        cb._states["weather"] = BreakerState(
            consecutive_failures=3,
            last_failure_at=None,
            state="open",
        )
        # should_attempt: open → _cooldown_expired returns True → transitions to half_open
        result = cb.should_attempt("weather")
        assert result is True  # half_open allows probe
        assert cb._states["weather"].state == "half_open"

    def test_cooldown_with_invalid_timestamp_treated_as_expired(self, tmp_state_dir):
        """_cooldown_expired returns True on ValueError when parsing timestamp (lines 103-104)."""
        from src.fetchers.circuit_breaker import BreakerState

        cb = CircuitBreaker(max_failures=3, cooldown_minutes=60, state_dir=tmp_state_dir)
        cb._states["weather"] = BreakerState(
            consecutive_failures=3,
            last_failure_at="not-a-valid-iso-timestamp",
            state="open",
        )
        result = cb.should_attempt("weather")
        assert result is True  # invalid timestamp → expired → half_open → True

    def test_cooldown_with_legacy_naive_timestamp_honored(self, tmp_state_dir, monkeypatch):
        """A naive ISO timestamp must be treated as UTC (not local) for cooldown math.

        Regression: previously _cooldown_expired() called astimezone(UTC) on the
        naive value, which Python interprets as system local time. On a host
        ahead of UTC (e.g. Tokyo, +9h), a naive failure 5 minutes old would be
        shifted ~9h into the past, falsely satisfying the 30-minute cooldown
        and re-hammering the failing API.

        Pin TZ to a non-UTC zone with a positive offset so the buggy and fixed
        paths produce diverging results — a UTC-only CI host masks the bug.
        """
        import time
        from datetime import datetime, timedelta, timezone

        from src.fetchers.circuit_breaker import BreakerState

        if not hasattr(time, "tzset"):
            import pytest

            pytest.skip("time.tzset() unavailable on this platform")

        monkeypatch.setenv("TZ", "Asia/Tokyo")  # UTC+9
        time.tzset()
        try:
            cb = CircuitBreaker(max_failures=3, cooldown_minutes=30, state_dir=tmp_state_dir)
            # Naive timestamp captured 5 minutes ago in UTC (legacy format).
            five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(tzinfo=None)
            cb._states["weather"] = BreakerState(
                consecutive_failures=3,
                last_failure_at=five_min_ago.isoformat(),
                state="open",
            )
            # Buggy code (astimezone(UTC) on naive) reads this as Tokyo-local,
            # shifts ~9h backward in UTC, age becomes ~545 min, cooldown
            # appears expired → should_attempt returns True (incorrect).
            # Fixed code (replace(tzinfo=UTC)) keeps age at 5 min → still OPEN.
            assert cb.should_attempt("weather") is False
            assert cb._states["weather"].state == "open"
        finally:
            monkeypatch.delenv("TZ", raising=False)
            time.tzset()

    def test_save_uses_atomic_write(self, tmp_state_dir):
        """A power-loss simulation mid-write must not corrupt the breaker state file.

        Triggers an exception inside the atomic-write tempfile path; the failure
        is swallowed by _save() and the existing on-disk state remains intact.
        """
        from unittest.mock import patch

        cb = CircuitBreaker(state_dir=tmp_state_dir)
        # Seed a known-good state on disk first.
        cb.record_failure("weather")
        path = cb._state_dir / "dashboard_breaker_state.json"
        good = path.read_text()
        # Simulate a write crash inside atomic_write_json.
        with patch("src._io.os.fdopen", side_effect=OSError("disk full")):
            cb.record_failure("weather")  # _save() must not raise
        # Original file is unchanged (atomic write didn't replace it).
        assert path.read_text() == good

    def test_save_exception_does_not_propagate(self, tmp_state_dir):
        """_save() exception is silently swallowed (lines 137-138)."""
        from unittest.mock import patch

        cb = CircuitBreaker(state_dir=tmp_state_dir)
        # Patch json.dump in the shared atomic-write helper so that _save() hits
        # the exception handler.
        with patch("src._io.json.dump", side_effect=OSError("disk full")):
            cb.record_failure("weather")  # triggers _save(), should not raise


class TestConcurrentWebWrites:
    """The web UI rewrites this file from a separate process (#242).

    A reset is most likely to be pressed *while* a run is in flight, and the
    renderer holds its own in-memory copy of every source loaded at startup.
    Writing that whole copy back erased the reset, and the UI reported success
    while the breaker stayed open.
    """

    def _raw(self, tmp_path) -> dict:
        return json.loads((tmp_path / "dashboard_breaker_state.json").read_text())

    def _open_entry(self) -> dict:
        # A recent failure keeps the breaker OPEN rather than probing.
        return {
            "consecutive_failures": 5,
            "last_failure_at": now_utc().isoformat(),
            "state": "open",
        }

    def test_a_reset_made_after_load_is_not_clobbered(self, tmp_path):
        state_path = tmp_path / "dashboard_breaker_state.json"
        state_path.write_text(json.dumps({"weather": self._open_entry()}))

        breaker = CircuitBreaker(state_dir=str(tmp_path))
        assert breaker.should_attempt("weather") is False

        # The web process resets weather while this run is in flight.
        state_path.write_text(
            json.dumps(
                {
                    "weather": {
                        "consecutive_failures": 0,
                        "last_failure_at": None,
                        "state": "closed",
                    }
                }
            )
        )

        # The renderer then records an unrelated source's outcome.
        breaker.record_success("events")

        assert self._raw(tmp_path)["weather"]["state"] == "closed"
        assert self._raw(tmp_path)["events"]["state"] == "closed"

    def test_this_runs_own_changes_still_win(self, tmp_path):
        """Merging must not turn into "the file always wins"."""
        state_path = tmp_path / "dashboard_breaker_state.json"
        state_path.write_text(json.dumps({"weather": self._open_entry()}))

        breaker = CircuitBreaker(state_dir=str(tmp_path))
        breaker.record_success("weather")

        assert self._raw(tmp_path)["weather"]["state"] == "closed"
        assert self._raw(tmp_path)["weather"]["consecutive_failures"] == 0

    def test_sources_written_by_another_process_are_preserved(self, tmp_path):
        breaker = CircuitBreaker(state_dir=str(tmp_path))
        breaker.record_failure("weather")

        # Another process adds a source this instance has never seen.
        raw = self._raw(tmp_path)
        raw["air_quality"] = self._open_entry()
        (tmp_path / "dashboard_breaker_state.json").write_text(json.dumps(raw))

        breaker.record_failure("weather")

        merged = self._raw(tmp_path)
        assert merged["air_quality"]["state"] == "open"
        assert merged["weather"]["consecutive_failures"] == 2

    def test_the_write_goes_through_the_shared_locked_helper(self):
        """One implementation of the locked read-modify-write, not a private copy."""
        from src import _io
        from src.fetchers import circuit_breaker as cb

        assert cb.locked_update_json is _io.locked_update_json
        assert not hasattr(cb, "atomic_write_json")


class TestDirtySourcesDoNotAccumulate:
    """`_save()` must write the source it was given, not every source so far.

    Caught in review on #242: an accumulating dirty set means the *second*
    source saved in a run also rewrites the first from this instance's stale
    in-memory copy — so a reset made between the two silently disappears. A
    multi-source fetch does exactly that on every run.
    """

    def _raw(self, tmp_path) -> dict:
        return json.loads((tmp_path / "dashboard_breaker_state.json").read_text())

    def test_a_reset_between_two_saves_survives(self, tmp_path):
        breaker = CircuitBreaker(state_dir=str(tmp_path))

        # The run records weather first.
        breaker.record_failure("weather")
        assert self._raw(tmp_path)["weather"]["consecutive_failures"] == 1

        # The user resets weather from the web UI, mid-run.
        raw = self._raw(tmp_path)
        raw["weather"] = {
            "consecutive_failures": 0,
            "last_failure_at": None,
            "state": "closed",
        }
        (tmp_path / "dashboard_breaker_state.json").write_text(json.dumps(raw))

        # The same run then records a *different* source. weather must not move.
        breaker.record_success("events")

        merged = self._raw(tmp_path)
        assert merged["weather"]["consecutive_failures"] == 0
        assert merged["weather"]["state"] == "closed"
        assert merged["events"]["state"] == "closed"

    def test_only_the_saved_source_is_written(self, tmp_path):
        breaker = CircuitBreaker(state_dir=str(tmp_path))
        breaker.record_failure("weather")
        breaker.record_failure("events")

        # Another process changes weather; saving a third source must not touch it.
        raw = self._raw(tmp_path)
        raw["weather"]["state"] = "open"
        (tmp_path / "dashboard_breaker_state.json").write_text(json.dumps(raw))

        breaker.record_failure("birthdays")

        assert self._raw(tmp_path)["weather"]["state"] == "open"
