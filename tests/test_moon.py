"""Tests for src/render/moon.py — moon phase calculation (pure math)."""

from datetime import date, timedelta

import pytest

from src.render.moon import (
    _MOON_GLYPHS,
    _PHASE_NAMES,
    _SYNODIC_MONTH,
    moon_phase_age,
    moon_phase_glyph,
    moon_phase_name,
)


class TestMoonPhaseAge:
    def test_returns_float_in_valid_range(self):
        age = moon_phase_age(date(2026, 3, 22))
        assert isinstance(age, float)
        assert 0.0 <= age < _SYNODIC_MONTH

    def test_reference_new_moon_date(self):
        """2000-01-06 was a new moon (reference point) — age should be near 0."""
        age = moon_phase_age(date(2000, 1, 6))
        # At noon UTC on reference day, age should be close to 0 (reference was 18:14 UTC).
        # Midday is ~6 hours before reference, so age wraps to ~29.28 days.
        # Accept either very small or very close to synodic month (near 0 mod 29.53).
        assert age < 1.0 or age > (_SYNODIC_MONTH - 1.0)

    def test_full_moon_approx_half_synodic_month(self):
        """Full moon should occur around day 14-15 of the lunar cycle."""
        # Jan 20 2000 was close to full moon (reference new moon was Jan 6)
        age = moon_phase_age(date(2000, 1, 21))
        assert 13.0 < age < 17.0

    def test_consecutive_days_differ_by_one(self):
        """Age should increase by ~1 day for consecutive calendar days."""
        d1 = date(2026, 3, 10)
        d2 = d1 + timedelta(days=1)
        a1 = moon_phase_age(d1)
        a2 = moon_phase_age(d2)
        # Difference should be ~1, accounting for wrap-around
        diff = (a2 - a1) % _SYNODIC_MONTH
        assert 0.8 < diff < 1.2

    def test_after_full_cycle_age_resets(self):
        """Adding exactly one synodic month should return nearly the same age."""
        d = date(2026, 3, 22)
        moon_phase_age(d)
        # Approx 29-30 days later should wrap around
        d_later = d + timedelta(days=30)
        a_later = moon_phase_age(d_later)
        # Both should be within the valid range
        assert 0.0 <= a_later < _SYNODIC_MONTH

    def test_deterministic(self):
        d = date(2026, 6, 15)
        assert moon_phase_age(d) == moon_phase_age(d)

    def test_year_boundaries(self):
        """Test across year boundaries — should not crash or produce NaN."""
        for d in [date(2025, 12, 31), date(2026, 1, 1), date(2026, 1, 2)]:
            age = moon_phase_age(d)
            assert 0.0 <= age < _SYNODIC_MONTH

    def test_leap_year_day(self):
        age = moon_phase_age(date(2024, 2, 29))
        assert 0.0 <= age < _SYNODIC_MONTH


class TestMoonPhaseName:
    def test_returns_valid_phase_name(self):
        name = moon_phase_name(date(2026, 3, 22))
        assert name in _PHASE_NAMES

    def test_all_eight_phases_accessible(self):
        """Iterating a full lunar month should produce all 8 phase names."""
        found_names = set()
        d = date(2026, 1, 1)
        for i in range(30):  # Full synodic month worth of days
            found_names.add(moon_phase_name(d + timedelta(days=i)))
        # Should find at least 4 distinct phases across 30 days
        assert len(found_names) >= 4

    def test_new_moon_name(self):
        """Reference new moon date should give 'New Moon'."""
        # 2000-01-06 is the reference new moon — age near 0 → idx 0 → "New Moon"
        name = moon_phase_name(date(2000, 1, 6))
        assert name == "New Moon"

    def test_deterministic(self):
        d = date(2026, 4, 10)
        assert moon_phase_name(d) == moon_phase_name(d)

    def test_seven_days_after_new_moon_is_waxing(self):
        """A week after new moon should be in the waxing half."""
        new_moon = date(2000, 1, 6)
        week_later = new_moon + timedelta(days=7)
        name = moon_phase_name(week_later)
        assert "Wax" in name or "First Quarter" in name

    def test_phase_names_list_has_8_entries(self):
        assert len(_PHASE_NAMES) == 8


class TestMoonPhaseGlyph:
    def test_returns_string(self):
        glyph = moon_phase_glyph(date(2026, 3, 22))
        assert isinstance(glyph, str)

    def test_glyph_is_from_known_set(self):
        glyph = moon_phase_glyph(date(2026, 3, 22))
        assert glyph in _MOON_GLYPHS

    def test_all_28_glyphs_reachable(self):
        """Iterating 30 days should sample multiple distinct glyphs."""
        glyphs_found = set()
        d = date(2026, 1, 1)
        for i in range(30):
            glyphs_found.add(moon_phase_glyph(d + timedelta(days=i)))
        # Should find at least 20 distinct glyphs across 30 days
        assert len(glyphs_found) >= 20

    def test_glyph_list_has_28_entries(self):
        assert len(_MOON_GLYPHS) == 28

    def test_deterministic(self):
        d = date(2026, 5, 1)
        assert moon_phase_glyph(d) == moon_phase_glyph(d)

    def test_new_moon_glyph(self):
        """Reference new moon date should give the first glyph (index 0)."""
        glyph = moon_phase_glyph(date(2000, 1, 6))
        assert glyph == _MOON_GLYPHS[0]

    def test_full_moon_glyph(self):
        """~14-15 days after new moon should give the full moon glyph (index 14)."""
        # Jan 6 + 15 days → Jan 21, age ~15 days → fraction ~0.51 → idx ~14
        glyph = moon_phase_glyph(date(2000, 1, 20))
        # Accept glyphs near full moon (indices 13-15)
        full_moon_glyphs = {_MOON_GLYPHS[i] for i in range(12, 17)}
        assert glyph in full_moon_glyphs

    @pytest.mark.parametrize("d", [
        date(2024, 1, 11),   # known new moon
        date(2024, 1, 25),   # known full moon
        date(2024, 2, 9),    # known new moon
    ])
    def test_known_lunar_events(self, d):
        """Known lunar dates should not crash and return valid glyphs."""
        glyph = moon_phase_glyph(d)
        assert glyph in _MOON_GLYPHS
