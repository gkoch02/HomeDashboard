"""Tests for src/render/random_theme.py — daily random theme rotation."""

import json
from datetime import date
from unittest.mock import patch


from src.render.random_theme import _EXCLUDED_FROM_POOL, eligible_themes, pick_random_theme
from src.render.theme import AVAILABLE_THEMES

# Themes that can actually appear in a pool (everything except hard-excluded themes)
_REAL_THEMES = AVAILABLE_THEMES - _EXCLUDED_FROM_POOL


# ---------------------------------------------------------------------------
# eligible_themes
# ---------------------------------------------------------------------------

class TestEligibleThemes:
    def test_no_filters_returns_all_real_themes(self):
        pool = eligible_themes([], [])
        assert set(pool) == _REAL_THEMES
        assert pool == sorted(pool)  # must be sorted

    def test_include_restricts_pool(self):
        pool = eligible_themes(["terminal", "minimalist"], [])
        assert set(pool) == {"terminal", "minimalist"}

    def test_exclude_removes_themes(self):
        pool = eligible_themes([], ["fantasy", "qotd"])
        assert "fantasy" not in pool
        assert "qotd" not in pool
        assert set(pool) == _REAL_THEMES - {"fantasy", "qotd"}

    def test_include_then_exclude(self):
        pool = eligible_themes(["terminal", "minimalist", "fantasy"], ["fantasy"])
        assert set(pool) == {"terminal", "minimalist"}

    def test_include_unknown_theme_returns_empty(self):
        pool = eligible_themes(["nonexistent"], [])
        assert pool == []

    def test_exclude_all_returns_empty(self):
        pool = eligible_themes([], list(_REAL_THEMES))
        assert pool == []

    def test_include_does_not_admit_random(self):
        # "random" should never appear even if somehow passed in include
        pool = eligible_themes(["random", "terminal"], [])
        assert "random" not in pool
        assert "terminal" in pool


# ---------------------------------------------------------------------------
# pick_random_theme — persistence logic
# ---------------------------------------------------------------------------

class TestPickRandomTheme:
    def test_new_day_picks_and_persists(self, tmp_path):
        today = date(2026, 3, 22)
        chosen = pick_random_theme([], [], str(tmp_path), today=today)
        assert chosen in _REAL_THEMES

        state = json.loads((tmp_path / "random_theme_state.json").read_text())
        assert state["date"] == "2026-03-22"
        assert state["theme"] == chosen

    def test_same_day_reuses_persisted_theme(self, tmp_path):
        today = date(2026, 3, 22)
        state_path = tmp_path / "random_theme_state.json"
        state_path.write_text(json.dumps({"date": "2026-03-22", "theme": "terminal"}))

        chosen = pick_random_theme([], [], str(tmp_path), today=today)
        assert chosen == "terminal"

    def test_new_day_overwrites_old_state(self, tmp_path):
        state_path = tmp_path / "random_theme_state.json"
        state_path.write_text(json.dumps({"date": "2026-03-21", "theme": "terminal"}))

        today = date(2026, 3, 22)
        chosen = pick_random_theme([], [], str(tmp_path), today=today)
        assert chosen in _REAL_THEMES

        state = json.loads(state_path.read_text())
        assert state["date"] == "2026-03-22"

    def test_persisted_invalid_theme_ignored(self, tmp_path):
        """If the persisted theme is no longer valid (e.g. removed), pick a new one."""
        state_path = tmp_path / "random_theme_state.json"
        state_path.write_text(json.dumps({"date": "2026-03-22", "theme": "nonexistent"}))

        today = date(2026, 3, 22)
        chosen = pick_random_theme([], [], str(tmp_path), today=today)
        assert chosen in _REAL_THEMES

    def test_corrupt_state_file_handled(self, tmp_path):
        state_path = tmp_path / "random_theme_state.json"
        state_path.write_text("not valid json{{{")

        today = date(2026, 3, 22)
        chosen = pick_random_theme([], [], str(tmp_path), today=today)
        assert chosen in _REAL_THEMES

    def test_empty_pool_falls_back_to_default(self, tmp_path):
        today = date(2026, 3, 22)
        chosen = pick_random_theme([], list(_REAL_THEMES), str(tmp_path), today=today)
        assert chosen == "default"

    def test_output_dir_created_if_missing(self, tmp_path):
        subdir = tmp_path / "deep" / "nested"
        today = date(2026, 3, 22)
        chosen = pick_random_theme([], [], str(subdir), today=today)
        assert chosen in _REAL_THEMES
        assert (subdir / "random_theme_state.json").exists()

    def test_include_restricts_choice(self, tmp_path):
        today = date(2026, 3, 22)
        for _ in range(20):
            # Clear state each iteration to force a new pick
            state_path = tmp_path / "random_theme_state.json"
            if state_path.exists():
                state_path.unlink()
            chosen = pick_random_theme(["terminal"], [], str(tmp_path), today=today)
            assert chosen == "terminal"

    def test_exclude_never_chosen(self, tmp_path):
        today = date(2026, 3, 22)
        exclude = ["fantasy", "qotd", "today"]
        for _ in range(30):
            state_path = tmp_path / "random_theme_state.json"
            if state_path.exists():
                state_path.unlink()
            chosen = pick_random_theme([], exclude, str(tmp_path), today=today)
            assert chosen not in exclude

    def test_random_never_returned(self, tmp_path):
        today = date(2026, 3, 22)
        for _ in range(20):
            state_path = tmp_path / "random_theme_state.json"
            if state_path.exists():
                state_path.unlink()
            chosen = pick_random_theme([], [], str(tmp_path), today=today)
            assert chosen != "random"

    def test_unwritable_state_does_not_crash(self, tmp_path):
        """If the state file can't be written, the theme is still returned."""
        today = date(2026, 3, 22)
        with patch("src.render.random_theme.Path.write_text", side_effect=OSError("disk full")):
            chosen = pick_random_theme([], [], str(tmp_path), today=today)
        assert chosen in _REAL_THEMES
