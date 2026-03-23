"""Tests for circuit breaker (src/fetchers/circuit_breaker.py)."""

from pathlib import Path

import pytest

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

    def test_save_exception_does_not_propagate(self, tmp_state_dir):
        """_save() exception is silently swallowed (lines 137-138)."""
        from unittest.mock import patch
        cb = CircuitBreaker(state_dir=tmp_state_dir)
        # Patch json.dump to raise so that _save() hits the exception handler
        with patch("src.fetchers.circuit_breaker.json.dump", side_effect=OSError("disk full")):
            cb.record_failure("weather")  # triggers _save(), should not raise
