"""Tests for src/display/refresh_tracker.py."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from src.display.refresh_tracker import RefreshTracker


@pytest.fixture(autouse=True)
def _patch_state_file(tmp_path):
    """Redirect STATE_FILE to a temp path so tests don't touch /tmp."""
    state = tmp_path / "refresh_state.json"
    with patch("src.display.refresh_tracker.STATE_FILE", state):
        yield state


class TestNeedsFullRefresh:
    def test_no_last_full_requires_full(self):
        t = RefreshTracker(partial_count=0, last_full=None)
        assert t.needs_full_refresh() is True

    def test_below_max_partials_no_full_needed(self):
        t = RefreshTracker(partial_count=2, last_full=datetime.now(), max_partials=5)
        assert t.needs_full_refresh() is False

    def test_at_max_partials_requires_full(self):
        t = RefreshTracker(partial_count=5, last_full=datetime.now(), max_partials=5)
        assert t.needs_full_refresh() is True

    def test_exceeds_max_partials_requires_full(self):
        t = RefreshTracker(partial_count=9, last_full=datetime.now(), max_partials=5)
        assert t.needs_full_refresh() is True

    def test_custom_max_partials(self):
        t = RefreshTracker(partial_count=1, last_full=datetime.now(), max_partials=1)
        assert t.needs_full_refresh() is True


class TestRecording:
    def test_record_partial_increments_count(self):
        t = RefreshTracker(partial_count=2, last_full=datetime.now())
        t.record_partial()
        assert t.partial_count == 3

    def test_record_full_resets_count(self):
        t = RefreshTracker(partial_count=4, last_full=None)
        t.record_full()
        assert t.partial_count == 0
        assert t.last_full is not None

    def test_record_full_sets_last_full_timestamp(self):
        t = RefreshTracker()
        before = datetime.now()
        t.record_full()
        after = datetime.now()
        assert before <= t.last_full <= after


class TestSaveLoad:
    def test_save_creates_file(self, _patch_state_file):
        t = RefreshTracker(partial_count=2, last_full=datetime(2024, 1, 15, 12, 0))
        t.save()
        assert _patch_state_file.exists()

    def test_save_load_round_trip(self, _patch_state_file):
        original = RefreshTracker(
            partial_count=3,
            last_full=datetime(2024, 6, 1, 8, 30),
            max_partials=7,
        )
        original.save()

        loaded = RefreshTracker.load(max_partials=7)
        assert loaded.partial_count == 3
        assert loaded.last_full == datetime(2024, 6, 1, 8, 30)
        assert loaded.max_partials == 7

    def test_load_missing_file_returns_fresh(self, _patch_state_file):
        # File doesn't exist yet
        t = RefreshTracker.load(max_partials=4)
        assert t.partial_count == 0
        assert t.last_full is None
        assert t.max_partials == 4

    def test_load_corrupt_file_returns_fresh(self, _patch_state_file):
        _patch_state_file.write_text("not valid json {{{")
        t = RefreshTracker.load()
        assert t.partial_count == 0
        assert t.last_full is None

    def test_save_null_last_full(self, _patch_state_file):
        t = RefreshTracker(partial_count=0, last_full=None)
        t.save()
        data = json.loads(_patch_state_file.read_text())
        assert data["last_full"] is None

    def test_load_respects_max_partials_parameter(self, _patch_state_file):
        RefreshTracker(partial_count=1, last_full=datetime.now()).save()
        t = RefreshTracker.load(max_partials=10)
        assert t.max_partials == 10

    def test_save_cleans_up_temp_file_on_write_failure(self, _patch_state_file):
        """If json.dump raises, the temp file is removed so the state dir stays clean."""
        tracker = RefreshTracker(partial_count=1, last_full=datetime(2024, 6, 1, 8, 0))

        with patch("json.dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                tracker.save()

        # No stray .tmp files left behind; the real state file was never created
        tmp_files = list(_patch_state_file.parent.glob("*.tmp"))
        assert tmp_files == []
        assert not _patch_state_file.exists()

    def test_save_cleans_up_temp_file_on_base_exception(self, _patch_state_file):
        """Keyboard-interrupt style failure must still unlink the temp file."""
        tracker = RefreshTracker(partial_count=1, last_full=None)

        with patch("json.dump", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                tracker.save()

        assert list(_patch_state_file.parent.glob("*.tmp")) == []
