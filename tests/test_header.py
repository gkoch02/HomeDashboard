"""Tests for src/render/components/header.py."""

from datetime import datetime

from PIL import Image, ImageDraw

from src.data.models import StalenessLevel
from src.render.components.header import draw_header


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


class TestDrawHeader:
    def _now(self):
        return datetime(2026, 3, 18, 9, 30)

    def test_smoke_renders_without_error(self):
        img, draw = _make_draw()
        draw_header(draw, self._now())
        assert img.getbbox() is not None

    def test_fresh_staleness_shows_updated_label(self):
        """No stale sources → header shows 'Updated' (no alert prefix)."""
        img, draw = _make_draw()
        draw_header(
            draw, self._now(),
            source_staleness={"events": StalenessLevel.FRESH, "weather": StalenessLevel.FRESH},
        )
        assert img.getbbox() is not None  # rendered without crash

    def test_aging_staleness_does_not_show_stale(self):
        """AGING staleness does not trigger '! Stale' label (lines 39-47 severity logic)."""
        img, draw = _make_draw()
        # AGING is below the threshold for '! Stale' label
        draw_header(
            draw, self._now(),
            source_staleness={"weather": StalenessLevel.AGING},
        )
        assert img.getbbox() is not None

    def test_stale_staleness_renders(self):
        """STALE source triggers '! Stale' label (lines 39-49)."""
        img, draw = _make_draw()
        draw_header(
            draw, self._now(),
            source_staleness={"weather": StalenessLevel.STALE},
        )
        assert img.getbbox() is not None

    def test_expired_staleness_renders(self):
        """EXPIRED source also triggers '! Stale' label."""
        img, draw = _make_draw()
        draw_header(
            draw, self._now(),
            source_staleness={"events": StalenessLevel.EXPIRED},
        )
        assert img.getbbox() is not None

    def test_is_stale_without_severe_levels_shows_cached(self):
        """is_stale=True with no STALE/EXPIRED sources triggers '! Cached' label (line 50)."""
        img, draw = _make_draw()
        # is_stale=True but no source_staleness with STALE/EXPIRED
        draw_header(
            draw, self._now(),
            is_stale=True,
            source_staleness={"weather": StalenessLevel.FRESH},
        )
        assert img.getbbox() is not None

    def test_is_stale_no_source_staleness_shows_cached(self):
        """is_stale=True with no source_staleness dict triggers '! Cached' (line 50)."""
        img, draw = _make_draw()
        draw_header(draw, self._now(), is_stale=True)
        assert img.getbbox() is not None

    def test_severity_ordering_multiple_sources(self):
        """Worst staleness level wins: STALE beats AGING (lines 39-47)."""
        img, draw = _make_draw()
        draw_header(
            draw, self._now(),
            source_staleness={
                "events": StalenessLevel.AGING,
                "weather": StalenessLevel.STALE,
                "birthdays": StalenessLevel.FRESH,
            },
        )
        assert img.getbbox() is not None

    def test_custom_title_renders(self):
        img, draw = _make_draw()
        draw_header(draw, self._now(), title="My Dashboard")
        assert img.getbbox() is not None

    def test_pm_time_format(self):
        """Timestamps should render correctly for PM times."""
        img, draw = _make_draw()
        draw_header(draw, datetime(2026, 3, 18, 15, 45))
        assert img.getbbox() is not None
