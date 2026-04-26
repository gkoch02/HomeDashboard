"""Tests for API quota tracker (src/fetchers/quota_tracker.py)."""

from pathlib import Path

import pytest

from src.fetchers.quota_tracker import QuotaTracker


@pytest.fixture
def tmp_state_dir(tmp_path):
    return str(tmp_path)


class TestQuotaTracker:
    def test_initial_count_is_zero(self, tmp_state_dir):
        qt = QuotaTracker(state_dir=tmp_state_dir)
        assert qt.daily_count("events") == 0

    def test_record_increments_count(self, tmp_state_dir):
        qt = QuotaTracker(state_dir=tmp_state_dir)
        qt.record_call("events")
        qt.record_call("events")
        assert qt.daily_count("events") == 2

    def test_independent_sources(self, tmp_state_dir):
        qt = QuotaTracker(state_dir=tmp_state_dir)
        qt.record_call("events", count=5)
        qt.record_call("weather", count=3)
        assert qt.daily_count("events") == 5
        assert qt.daily_count("weather") == 3

    def test_persistence(self, tmp_state_dir):
        qt1 = QuotaTracker(state_dir=tmp_state_dir)
        qt1.record_call("events", count=10)
        qt2 = QuotaTracker(state_dir=tmp_state_dir)
        assert qt2.daily_count("events") == 10

    def test_auto_reset_on_new_day(self, tmp_state_dir):
        qt = QuotaTracker(state_dir=tmp_state_dir)
        qt.record_call("events", count=10)
        # Simulate day change
        qt._today = "2020-01-01"
        qt._save()
        qt2 = QuotaTracker(state_dir=tmp_state_dir)
        assert qt2.daily_count("events") == 0

    def test_check_warning_below_threshold(self, tmp_state_dir):
        qt = QuotaTracker(state_dir=tmp_state_dir)
        qt.record_call("events", count=5)
        assert qt.check_warning("events", threshold=100) is False

    def test_check_warning_above_threshold(self, tmp_state_dir):
        qt = QuotaTracker(state_dir=tmp_state_dir)
        qt.record_call("events", count=501)
        assert qt.check_warning("events", threshold=500) is True

    def test_corrupted_state_file(self, tmp_state_dir):
        path = Path(tmp_state_dir) / "api_quota_state.json"
        path.write_text("bad json")
        qt = QuotaTracker(state_dir=tmp_state_dir)
        assert qt.daily_count("events") == 0

    def test_ensure_today_resets_counts_on_day_change(self, tmp_state_dir):
        """_ensure_today resets _counts when the day changes in a live instance (lines 55-56)."""
        qt = QuotaTracker(state_dir=tmp_state_dir)
        qt.record_call("events", count=10)
        # Simulate the day ticking over on the same instance without reloading
        qt._today = "2020-01-01"
        # Next call to record_call triggers _ensure_today → resets counts
        qt.record_call("events", count=1)
        assert qt.daily_count("events") == 1  # reset + 1, not 11

    def test_save_exception_does_not_propagate(self, tmp_state_dir):
        """_save() silently swallows write errors."""
        from unittest.mock import patch

        qt = QuotaTracker(state_dir=tmp_state_dir)
        with patch("src._io.json.dump", side_effect=OSError("disk full")):
            qt.record_call("events")  # triggers _save(), should not raise
