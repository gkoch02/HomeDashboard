"""Tests for src/render/components/birthday_bar.py

Assertion discipline (see #229)
-------------------------------
These tests asserted ``img.getbbox() is not None`` on a mode-``"1"`` plate
filled with 1, where every pixel is non-zero and getbbox can never return
None. 13 of the 14 tests passed with ``draw_birthdays`` stubbed to a no-op.

Ink means **zero-valued** pixels, counted inside the bar's own region. The
strongest signal here is the today-birthday row, which is inverted — a
filled_rect with its text knocked out — so it inks roughly five times what
an ordinary row does.

Verification: with ``draw_birthdays`` stubbed to a no-op, every test in this
file fails.
"""

from datetime import date, timedelta

from PIL import Image, ImageDraw

from src.data.models import Birthday, StalenessLevel
from src.render import layout as L
from src.render.components.birthday_bar import draw_birthdays
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion

TODAY = date(2024, 3, 15)
REGION = ComponentRegion(L.BIRTHDAY_X, L.BIRTHDAY_Y, L.BIRTHDAY_W, L.BIRTHDAY_H)
BOX = (REGION.x, REGION.y, REGION.x + REGION.w, REGION.y + REGION.h)


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _ink(img: Image.Image, box: tuple[int, int, int, int] = BOX) -> int:
    """Count ink (value-0) pixels inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _render(birthdays=None, today=TODAY, **kwargs) -> Image.Image:
    img, draw = _make_draw()
    draw_birthdays(draw, birthdays or [], today, **kwargs)
    return img


def _b(name: str, when: date, age: int | None = None) -> Birthday:
    return Birthday(name=name, date=when, age=age)


class TestDrawBirthdays:
    def test_no_birthdays_renders_empty_message(self):
        """The empty state is a message, not a blank bar."""
        empty = _render()
        assert _ink(empty) > 0
        assert _ink(empty) != _ink(_render([_b("Alice", TODAY + timedelta(days=3))])), (
            "the empty-state message is indistinguishable from a listed birthday"
        )

    def test_today_birthday_renders(self):
        """Today's birthday inverts its whole row, so it inks far more."""
        today_row = _ink(_render([_b("Alice", TODAY)]))
        future_row = _ink(_render([_b("Alice", TODAY + timedelta(days=5))]))
        assert today_row > future_row * 3, (
            f"today's row is not inverted ({today_row} vs {future_row})"
        )

    def test_tomorrow_birthday_renders(self):
        """'Tomorrow' is its own label, distinct from a day count."""
        tomorrow = _ink(_render([_b("Alice", TODAY + timedelta(days=1))]))
        in_nine = _ink(_render([_b("Alice", TODAY + timedelta(days=9))]))
        assert tomorrow > 0
        assert tomorrow != in_nine

    def test_future_birthday_shows_days_countdown(self):
        """The countdown is drawn from the gap, so different gaps differ."""
        inks = {
            days: _ink(_render([_b("Alice", TODAY + timedelta(days=days))])) for days in (3, 9, 40)
        }
        assert len(set(inks.values())) > 1, f"the day countdown is not drawn: {inks}"

    def test_birthday_with_age_renders(self):
        """An age adds to the row."""
        with_age = _ink(_render([_b("Alice", TODAY + timedelta(days=9), 34)]))
        without = _ink(_render([_b("Alice", TODAY + timedelta(days=9))]))
        assert with_age > without, "the age is not drawn"

    def test_milestone_age_renders(self):
        """A milestone age is set in the heavier font than a neighbouring age."""
        milestone = _ink(_render([_b("Alice", TODAY + timedelta(days=9), 30)]))
        ordinary = _ink(_render([_b("Alice", TODAY + timedelta(days=9), 31)]))
        assert milestone > ordinary, (
            f"age 30 was not emphasised over 31 ({milestone} vs {ordinary})"
        )

    def test_birthday_past_this_year_rolls_to_next_year(self):
        """A date already past this year is shown as next year's, not dropped."""
        past = _render([_b("Alice", date(2024, 1, 10))])
        assert _ink(past) > 0
        assert _ink(past) != _ink(_render()), "a past birthday fell back to the empty state"

    def test_overflow_count_shown_when_more_than_max(self):
        """Rows cap at three; the surplus becomes a '+N more' line."""

        def with_n(n):
            return _ink(_render([_b(f"P{i}", TODAY + timedelta(days=i + 1)) for i in range(n)]))

        three = with_n(3)
        four = with_n(4)
        assert four > three, "the overflow line is not drawn"
        assert with_n(6) != four, "the overflow count does not track how many are hidden"

    def test_exactly_three_birthdays_no_overflow(self):
        """Three fit exactly — no overflow line, and each row is drawn."""

        def with_n(n):
            return _ink(_render([_b(f"P{i}", TODAY + timedelta(days=i + 1)) for i in range(n)]))

        assert with_n(3) > with_n(2) > with_n(1), "rows are not accumulating"

    def test_birthday_with_no_age_renders(self):
        """age=None omits the age rather than printing a placeholder."""
        no_age = _render([_b("Grace", TODAY + timedelta(days=7))])
        assert _ink(no_age) > 0
        assert _ink(no_age) < _ink(_render([_b("Grace", TODAY + timedelta(days=7), 41)]))

    def test_today_birthday_inverts_row(self):
        """The inverted row knocks its text out of the fill."""
        named = _ink(_render([_b("Alice", TODAY)]))
        blank = _ink(_render([_b("", TODAY)]))
        assert named < blank, "the name is not knocked out of the inverted row"

    def test_stale_birthdays_renders_glyph(self):
        """STALE draws the '!' badge in the region's bottom-right corner."""
        region = ComponentRegion(300, 360, 250, 120)
        box = (region.x, region.y, region.x + region.w, region.y + region.h)
        birthdays = [_b("Alice", TODAY + timedelta(days=3))]
        stale = _render(birthdays, region=region, staleness=StalenessLevel.STALE)
        none = _render(birthdays, region=region, staleness=None)
        assert _ink(stale, box) > _ink(none, box), "no staleness badge drawn"

    def test_fresh_staleness_draws_no_glyph(self):
        """FRESH is not a warning — measured against STALE, which is."""
        birthdays = [_b("Alice", TODAY + timedelta(days=3))]
        fresh = _ink(_render(birthdays, staleness=StalenessLevel.FRESH))
        stale = _ink(_render(birthdays, staleness=StalenessLevel.STALE))
        assert fresh < stale, "FRESH drew a staleness badge"

    def test_none_staleness_no_crash(self):
        """The default draws the bar without a badge."""
        assert _ink(_render([], staleness=None)) > 0

    def test_early_break_when_layout_too_small(self):
        """A region too short for a row breaks out instead of overflowing.

        y = y0+32, line_h=22, h=50, pad=8 → 32+22 = 54 > 50-8 = 42, so the
        loop breaks at i=0 and no birthday rows are drawn — only the label.
        """
        small = ComponentRegion(x=300, y=360, w=250, h=50)
        box = (small.x, small.y, small.x + small.w, small.y + small.h)
        birthdays = [_b(name, TODAY + timedelta(days=i + 1)) for i, name in enumerate("ABC")]
        cramped = _render(birthdays, region=small)
        assert _ink(cramped, box) > 0, "not even the section label was drawn"
        # No *content* spilled below the region. The right separator is drawn
        # to y0+h inclusive, so it puts one pixel on the row below — the same
        # convention weather_panel uses, so the border column is excluded here
        # rather than treated as an overflow.
        below = (small.x, small.y + small.h, small.x + small.w - 1, 480)
        assert _ink(cramped, below) == 0
        roomy = ComponentRegion(x=300, y=360, w=250, h=120)
        roomy_box = (roomy.x, roomy.y, roomy.x + roomy.w, roomy.y + roomy.h)
        assert _ink(cramped, box) < _ink(_render(birthdays, region=roomy), roomy_box), (
            "the cramped region listed as much as the roomy one"
        )
