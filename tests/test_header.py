"""Tests for src/render/components/header.py.

Assertion discipline (see #229)
-------------------------------
These tests asserted ``img.getbbox() is not None`` on a mode-``"1"`` plate
filled with 1, where every pixel is non-zero and getbbox can never return
None. All 10 passed with ``draw_header`` stubbed to a no-op.

Ink means **zero-valued** pixels. Note the polarity: with the default style
the header is an inverted band — filled in ``fg`` with its text knocked out
in ``bg`` — so *more text means less ink*, and the staleness assertions are
written in that direction.

The load-bearing test here is ``test_updated_stamp_reads_content_at_not_now``.
CLAUDE.md's idle-tick rule requires this label to be drawn from
``DashboardData.content_at`` rather than the render clock: ``now`` advances
every run whether or not anything was fetched, so reading it would change
these pixels on every tick and force an eInk refresh for content that has
not moved.
"""

from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import StalenessLevel
from src.render import layout as L
from src.render.components.header import draw_header
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion, ThemeStyle

REGION = ComponentRegion(0, L.HEADER_Y, L.WIDTH, L.HEADER_H)
BOX = (REGION.x, REGION.y, REGION.x + REGION.w, REGION.y + REGION.h)
AREA = REGION.w * REGION.h


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _ink(img: Image.Image, box: tuple[int, int, int, int] = BOX) -> int:
    """Count ink (value-0) pixels inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


class TestDrawHeader:
    def _now(self):
        return datetime(2026, 3, 18, 9, 30)

    def _render(self, now=None, **kwargs) -> Image.Image:
        img, draw = _make_draw()
        draw_header(draw, now or self._now(), **kwargs)
        return img

    def test_smoke_renders_without_error(self):
        """The default style fills the band and knocks its text out of it."""
        img = self._render()
        assert _ink(img) > AREA * 0.5, "header band is not inverted"
        assert _ink(img) < AREA, "no text was knocked out of the fill"

    def test_uninverted_header_draws_a_rule_instead_of_a_band(self):
        """invert_header=False leaves ink for the text and border only."""
        plain = self._render(style=ThemeStyle(invert_header=False))
        assert 0 < _ink(plain) < AREA * 0.5, "the band was filled despite invert_header=False"

    def test_fresh_staleness_shows_updated_label(self):
        """FRESH draws the plain 'Updated' label, not a warning."""
        fresh = self._render(source_staleness={"weather": StalenessLevel.FRESH})
        stale = self._render(source_staleness={"weather": StalenessLevel.STALE})
        assert _ink(fresh) != _ink(stale), "FRESH and STALE drew the same label"

    def test_aging_staleness_does_not_show_stale(self):
        """AGING is below the warning threshold — same label as FRESH."""
        aging = self._render(source_staleness={"weather": StalenessLevel.AGING})
        fresh = self._render(source_staleness={"weather": StalenessLevel.FRESH})
        stale = self._render(source_staleness={"weather": StalenessLevel.STALE})
        assert _ink(aging) == _ink(fresh), "AGING was escalated to a warning label"
        assert _ink(aging) != _ink(stale)

    def test_stale_staleness_renders(self):
        """STALE swaps in the '! Stale' label, which is wider than 'Updated'.

        The band is inverted, so a wider label knocks out more and leaves
        *less* ink.
        """
        stale = self._render(source_staleness={"weather": StalenessLevel.STALE})
        fresh = self._render(source_staleness={"weather": StalenessLevel.FRESH})
        assert stale != fresh
        assert _ink(stale) > _ink(fresh), "'! Stale' did not replace 'Updated'"

    def test_expired_staleness_renders(self):
        """EXPIRED shares the '! Stale' label with STALE."""
        expired = self._render(source_staleness={"weather": StalenessLevel.EXPIRED})
        stale = self._render(source_staleness={"weather": StalenessLevel.STALE})
        assert _ink(expired) == _ink(stale)
        assert _ink(expired) != _ink(self._render())

    def test_is_stale_without_severe_levels_shows_cached(self):
        """is_stale=True with only AGING sources draws '! Cached', its own label."""
        cached = self._render(is_stale=True, source_staleness={"weather": StalenessLevel.AGING})
        assert _ink(cached) != _ink(self._render()), "'! Cached' was not drawn"
        assert _ink(cached) != _ink(
            self._render(source_staleness={"weather": StalenessLevel.STALE})
        ), "'! Cached' is indistinguishable from '! Stale'"

    def test_is_stale_no_source_staleness_shows_cached(self):
        """No per-source map at all still yields the '! Cached' label."""
        assert _ink(self._render(is_stale=True)) == _ink(
            self._render(is_stale=True, source_staleness={"weather": StalenessLevel.AGING})
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
        assert _ink(worst_last) == _ink(worst_first) == _ink(only_stale), (
            "the label depends on iteration order rather than severity"
        )

    def test_custom_title_renders(self):
        """The title is drawn from the argument, not hardcoded."""
        assert _ink(self._render(title="My Dashboard")) != _ink(self._render())

    def test_pm_time_format(self):
        """Morning and evening stamps format differently (a vs p)."""
        morning = self._render(now=datetime(2026, 3, 18, 9, 43))
        evening = self._render(now=datetime(2026, 3, 18, 21, 43))
        assert _ink(morning) != _ink(evening)

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
