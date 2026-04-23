"""Tests for DST transition edge cases in run policy and cache TTL calculations."""

import zoneinfo
from datetime import datetime

from src.data.models import StalenessLevel
from src.fetchers.cache import check_staleness
from src.services.run_policy import (
    in_quiet_hours,
    is_morning_startup_window,
    should_skip_refresh,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# US Eastern: DST springs forward at 2 AM on second Sunday of March
# (2:00 AM → 3:00 AM, losing one hour)
# Falls back at 2 AM on first Sunday of November
# (2:00 AM → 1:00 AM, gaining one hour)
ET = zoneinfo.ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Quiet hours around DST transitions
# ---------------------------------------------------------------------------


class TestQuietHoursDST:
    def test_spring_forward_quiet_hours_wrap_midnight(self):
        """Quiet hours 23:00-06:00 should work across spring-forward DST."""
        # 1:30 AM EST (before spring forward) → should be in quiet hours
        before_dst = datetime(2026, 3, 8, 1, 30, tzinfo=ET)
        assert in_quiet_hours(before_dst, 23, 6) is True

        # 3:30 AM EDT (after spring forward, 2 AM → 3 AM) → still quiet
        after_dst = datetime(2026, 3, 8, 3, 30, tzinfo=ET)
        assert in_quiet_hours(after_dst, 23, 6) is True

        # 6:30 AM EDT → out of quiet hours
        morning = datetime(2026, 3, 8, 6, 30, tzinfo=ET)
        assert in_quiet_hours(morning, 23, 6) is False

    def test_fall_back_quiet_hours_wrap_midnight(self):
        """Quiet hours 23:00-06:00 should work across fall-back DST."""
        # 1:30 AM EDT (before fall back) → quiet
        before_dst = datetime(2026, 11, 1, 1, 30, tzinfo=ET)
        assert in_quiet_hours(before_dst, 23, 6) is True

        # 1:30 AM EST (after fall back, the repeated 1 AM hour) → quiet
        # Python's fold=1 represents the second occurrence of the ambiguous time
        after_dst = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=ET)
        assert in_quiet_hours(after_dst, 23, 6) is True

    def test_spring_forward_morning_startup(self):
        """Morning startup detection should work when 2 AM is skipped."""
        # quiet_hours_end=6, so morning startup is 06:00-06:29
        # Even during DST transition, the function checks hour/minute
        morning = datetime(2026, 3, 8, 6, 15, tzinfo=ET)
        assert is_morning_startup_window(morning, 6) is True

        # 06:30 → no longer morning startup
        late_morning = datetime(2026, 3, 8, 6, 30, tzinfo=ET)
        assert is_morning_startup_window(late_morning, 6) is False


# ---------------------------------------------------------------------------
# Cache staleness across DST
# ---------------------------------------------------------------------------


class TestCacheStalenessAcrossDST:
    def test_fresh_cache_across_spring_forward(self):
        """Cache saved at 1:30 AM EST should be fresh at 3:30 AM EDT (1 hour real elapsed)."""
        cached_at = datetime(2026, 3, 8, 1, 30, tzinfo=ET)
        now = datetime(2026, 3, 8, 3, 30, tzinfo=ET)
        # Real elapsed: 1 hour (wall clock jumped from 2 AM to 3 AM)
        # TTL: 120 minutes = 2 hours → should be FRESH
        level = check_staleness(cached_at, ttl_minutes=120, now=now)
        assert level == StalenessLevel.FRESH

    def test_stale_cache_across_spring_forward(self):
        """Cache saved at 1:00 AM EST should be stale at 7:00 AM EDT (5 hours real elapsed)."""
        cached_at = datetime(2026, 3, 8, 1, 0, tzinfo=ET)
        now = datetime(2026, 3, 8, 7, 0, tzinfo=ET)
        # Real elapsed: 5 hours (300 min). TTL: 120 min.
        # 300 > 2*120=240 → STALE
        level = check_staleness(cached_at, ttl_minutes=120, now=now)
        assert level == StalenessLevel.STALE

    def test_fresh_cache_across_fall_back(self):
        """Cache should track real elapsed time, not wall-clock difference, during fall-back."""
        cached_at = datetime(2026, 11, 1, 1, 0, tzinfo=ET)  # 1 AM EDT
        # After fall-back: 1:30 AM EST (fold=1) — ~1.5 hours real elapsed
        now = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=ET)
        level = check_staleness(cached_at, ttl_minutes=120, now=now)
        assert level == StalenessLevel.FRESH


# ---------------------------------------------------------------------------
# should_skip_refresh respects dry_run across DST
# ---------------------------------------------------------------------------


class TestSkipRefreshDST:
    def test_dry_run_bypasses_quiet_hours_during_dst(self):
        """--dry-run should bypass quiet hours even during DST transition."""
        during_dst = datetime(2026, 3, 8, 2, 30, tzinfo=ET)
        assert should_skip_refresh(during_dst, 23, 6, dry_run=True) is False

    def test_quiet_hours_enforced_during_dst(self):
        """Quiet hours should be enforced during DST transition (non-dry-run)."""
        during_dst = datetime(2026, 3, 8, 3, 30, tzinfo=ET)
        assert should_skip_refresh(during_dst, 23, 6, dry_run=False) is True
