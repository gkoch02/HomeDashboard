"""Tests for header.py; ink is counted with ``inkutils.ink`` (the band is inverted, so more
text means less ink, and the ``updated`` stamp must read ``content_at``, never ``now``).
"""

from datetime import datetime

from PIL import Image

from src.data.models import StalenessLevel
from src.render import layout as L
from src.render.components.header import draw_header
from src.render.theme import ComponentRegion, ThemeStyle
from tests.conftest import make_draw
from tests.inkutils import ink

REGION = ComponentRegion(0, L.HEADER_Y, L.WIDTH, L.HEADER_H)
BOX = (REGION.x, REGION.y, REGION.x + REGION.w, REGION.y + REGION.h)
AREA = REGION.w * REGION.h


class TestDrawHeader:
    def _now(self):
        return datetime(2026, 3, 18, 9, 30)

    def _render(self, now=None, **kwargs) -> Image.Image:
        img, draw = make_draw()
        draw_header(draw, now or self._now(), **kwargs)
        return img

    def test_smoke_renders_without_error(self):
        """The default style fills the band and knocks its text out of it."""
        img = self._render()
        assert ink(img, BOX) > AREA * 0.5, "header band is not inverted"
        assert ink(img, BOX) < AREA, "no text was knocked out of the fill"

    def test_uninverted_header_draws_a_rule_instead_of_a_band(self):
        """invert_header=False leaves ink for the text and border only."""
        plain = self._render(style=ThemeStyle(invert_header=False))
        assert 0 < ink(plain, BOX) < AREA * 0.5, "the band was filled despite invert_header=False"

    def test_fresh_staleness_shows_updated_label(self):
        """FRESH draws the plain 'Updated' label, not a warning."""
        fresh = self._render(source_staleness={"weather": StalenessLevel.FRESH})
        stale = self._render(source_staleness={"weather": StalenessLevel.STALE})
        assert ink(fresh, BOX) != ink(stale, BOX), "FRESH and STALE drew the same label"

    def test_aging_staleness_does_not_show_stale(self):
        """AGING is below the warning threshold — same label as FRESH."""
        aging = self._render(source_staleness={"weather": StalenessLevel.AGING})
        fresh = self._render(source_staleness={"weather": StalenessLevel.FRESH})
        stale = self._render(source_staleness={"weather": StalenessLevel.STALE})
        assert ink(aging, BOX) == ink(fresh, BOX), "AGING was escalated to a warning label"
        assert ink(aging, BOX) != ink(stale, BOX)

    def test_stale_staleness_renders(self):
        """STALE swaps in the '! Stale' label, which is wider than 'Updated'.

        The band is inverted, so a wider label knocks out more and leaves
        *less* ink.
        """
        stale = self._render(source_staleness={"weather": StalenessLevel.STALE})
        fresh = self._render(source_staleness={"weather": StalenessLevel.FRESH})
        assert stale != fresh
        assert ink(stale, BOX) > ink(fresh, BOX), "'! Stale' did not replace 'Updated'"

    def test_expired_staleness_renders(self):
        """EXPIRED shares the '! Stale' label with STALE."""
        expired = self._render(source_staleness={"weather": StalenessLevel.EXPIRED})
        stale = self._render(source_staleness={"weather": StalenessLevel.STALE})
        assert ink(expired, BOX) == ink(stale, BOX)
        assert ink(expired, BOX) != ink(self._render(), BOX)

    def test_is_stale_without_severe_levels_shows_cached(self):
        """is_stale=True with only AGING sources draws '! Cached', its own label."""
        cached = self._render(is_stale=True, source_staleness={"weather": StalenessLevel.AGING})
        assert ink(cached, BOX) != ink(self._render(), BOX), "'! Cached' was not drawn"
        assert ink(cached, BOX) != ink(
            self._render(source_staleness={"weather": StalenessLevel.STALE}), BOX
        ), "'! Cached' is indistinguishable from '! Stale'"

    def test_is_stale_no_source_staleness_shows_cached(self):
        """No per-source map at all still yields the '! Cached' label."""
        assert ink(self._render(is_stale=True), BOX) == ink(
            self._render(is_stale=True, source_staleness={"weather": StalenessLevel.AGING}), BOX
        )

    def test_severity_ordering_multiple_sources(self):
        """The worst level across sources wins, regardless of dict order."""
        worst_last = self._render(
            source_staleness={"a": StalenessLevel.AGING, "b": StalenessLevel.STALE}
        )
        worst_first = self._render(
            source_staleness={"a": StalenessLevel.STALE, "b": StalenessLevel.AGING}
        )
        only_stale = self._render(source_staleness={"b": StalenessLevel.STALE})
        assert ink(worst_last, BOX) == ink(worst_first, BOX) == ink(only_stale, BOX), (
            "the label depends on iteration order rather than severity"
        )

    def test_long_title_does_not_overprint_the_timestamp(self):
        """A title long enough to reach the stamp is truncated short of it (#310)."""
        long_title = "The Family Command Center, Weekly Household Planner and Chore Board"
        # The stamp block is ~141 px wide, right-aligned inside the pad.
        stamp_x = REGION.x + REGION.w - L.PAD - 142
        right = (stamp_x, REGION.y, REGION.x + REGION.w, REGION.y + REGION.h)
        assert ink(self._render(title=long_title), right) == ink(self._render(), right)

    def test_custom_title_renders(self):
        """The title is drawn from the argument, not hardcoded."""
        assert ink(self._render(title="My Dashboard"), BOX) != ink(self._render(), BOX)

    def test_pm_time_format(self):
        """Morning and evening stamps format differently (a vs p)."""
        morning = self._render(now=datetime(2026, 3, 18, 9, 43))
        evening = self._render(now=datetime(2026, 3, 18, 21, 43))
        assert ink(morning, BOX) != ink(evening, BOX)

    def test_updated_stamp_reads_content_at_not_now(self):
        """The stamp must track when the data changed, not when we painted.

        This is CLAUDE.md's idle-tick rule. If this label were drawn from
        `now`, every tick of the 5-minute timer would change these pixels,
        the image hash would differ, and the panel would be rewritten to
        repaint a timestamp for data that had not moved.
        `tests/test_idle_tick_no_redraw.py` guards the whole-plate version of
        this; here it is pinned at the component.
        """
        content_at = datetime(2026, 3, 18, 9, 0)
        early = self._render(now=datetime(2026, 3, 18, 9, 30), content_at=content_at)
        later = self._render(now=datetime(2026, 3, 18, 10, 7), content_at=content_at)
        assert early.tobytes() == later.tobytes(), (
            "the header changed on an idle tick — it is reading the render clock"
        )

    def test_updated_stamp_moves_when_the_content_does(self):
        """The converse: a newer content_at must reach the plate."""
        now = datetime(2026, 3, 18, 10, 7)
        old = self._render(now=now, content_at=datetime(2026, 3, 18, 9, 0))
        fresh = self._render(now=now, content_at=datetime(2026, 3, 18, 10, 5))
        assert old.tobytes() != fresh.tobytes(), "content_at is not being drawn at all"

    def test_now_is_used_when_content_at_is_absent(self):
        """Without content_at the stamp falls back to the render clock."""
        a = self._render(now=datetime(2026, 3, 18, 9, 30))
        b = self._render(now=datetime(2026, 3, 18, 10, 7))
        assert a.tobytes() != b.tobytes()
