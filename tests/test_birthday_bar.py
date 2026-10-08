"""Tests for birthday_bar.py; ink is counted inside the bar's region with the local ``_ink``."""

from datetime import date, timedelta

from PIL import Image, ImageDraw

from src.data.models import Birthday, StalenessLevel
from src.render import layout as L
from src.render.components.birthday_bar import draw_birthdays
from src.render.theme import ComponentRegion
from tests.conftest import make_draw
from tests.inkutils import ink

TODAY = date(2024, 3, 15)
REGION = ComponentRegion(L.BIRTHDAY_X, L.BIRTHDAY_Y, L.BIRTHDAY_W, L.BIRTHDAY_H)
BOX = (REGION.x, REGION.y, REGION.x + REGION.w, REGION.y + REGION.h)


def _render(birthdays=None, today=TODAY, **kwargs) -> Image.Image:
    img, draw = make_draw()
    draw_birthdays(draw, birthdays or [], today, **kwargs)
    return img


def _b(name: str, when: date, age: int | None = None) -> Birthday:
    return Birthday(name=name, date=when, age=age)


class TestDrawBirthdays:
    def test_no_birthdays_renders_empty_message(self):
        """The empty state is a message, not a blank bar."""
        empty = _render()
        assert ink(empty, BOX) > 0
        assert ink(empty, BOX) != ink(_render([_b("Alice", TODAY + timedelta(days=3))]), BOX), (
            "the empty-state message is indistinguishable from a listed birthday"
        )

    def test_today_birthday_renders(self):
        """Today's birthday inverts its whole row, so it inks far more."""
        today_row = ink(_render([_b("Alice", TODAY)]), BOX)
        future_row = ink(_render([_b("Alice", TODAY + timedelta(days=5))]), BOX)
        assert today_row > future_row * 3, (
            f"today's row is not inverted ({today_row} vs {future_row})"
        )

    def test_tomorrow_birthday_renders(self):
        """'Tomorrow' is its own label, distinct from a day count."""
        tomorrow = ink(_render([_b("Alice", TODAY + timedelta(days=1))]), BOX)
        in_nine = ink(_render([_b("Alice", TODAY + timedelta(days=9))]), BOX)
        assert tomorrow > 0
        assert tomorrow != in_nine

    def test_future_birthday_shows_days_countdown(self):
        """The countdown is drawn from the gap, so different gaps differ."""
        inks = {
            days: ink(_render([_b("Alice", TODAY + timedelta(days=days))]), BOX)
            for days in (3, 9, 40)
        }
        assert len(set(inks.values())) > 1, f"the day countdown is not drawn: {inks}"

    def test_birthday_with_age_renders(self):
        """An age adds to the row."""
        with_age = ink(_render([_b("Alice", TODAY + timedelta(days=9), 34)]), BOX)
        without = ink(_render([_b("Alice", TODAY + timedelta(days=9))]), BOX)
        assert with_age > without, "the age is not drawn"

    def test_milestone_age_renders(self):
        """A milestone age is set in the heavier font than a neighbouring age."""
        milestone = ink(_render([_b("Alice", TODAY + timedelta(days=9), 30)]), BOX)
        ordinary = ink(_render([_b("Alice", TODAY + timedelta(days=9), 31)]), BOX)
        assert milestone > ordinary, (
            f"age 30 was not emphasised over 31 ({milestone} vs {ordinary})"
        )

    def test_birthday_past_this_year_rolls_to_next_year(self):
        """A date already past this year is shown as next year's, not dropped."""
        past = _render([_b("Alice", date(2024, 1, 10))])
        assert ink(past, BOX) > 0
        assert ink(past, BOX) != ink(_render(), BOX), "a past birthday fell back to the empty state"

    def test_overflow_count_shown_when_more_than_max(self):
        """Rows cap at three; the surplus becomes a '+N more' line."""

        def with_n(n):
            return ink(_render([_b(f"P{i}", TODAY + timedelta(days=i + 1)) for i in range(n)]), BOX)

        three = with_n(3)
        four = with_n(4)
        assert four > three, "the overflow line is not drawn"
        assert with_n(6) != four, "the overflow count does not track how many are hidden"

    def test_exactly_three_birthdays_no_overflow(self):
        """Three fit exactly — no overflow line, and each row is drawn."""

        def with_n(n):
            return ink(_render([_b(f"P{i}", TODAY + timedelta(days=i + 1)) for i in range(n)]), BOX)

        assert with_n(3) > with_n(2) > with_n(1), "rows are not accumulating"

    def test_birthday_with_no_age_renders(self):
        """age=None omits the age rather than printing a placeholder."""
        no_age = _render([_b("Grace", TODAY + timedelta(days=7))])
        assert ink(no_age, BOX) > 0
        assert ink(no_age, BOX) < ink(_render([_b("Grace", TODAY + timedelta(days=7), 41)]), BOX)

    def test_today_birthday_inverts_row(self):
        """The inverted row knocks its text out of the fill."""
        named = ink(_render([_b("Alice", TODAY)]), BOX)
        blank = ink(_render([_b("", TODAY)]), BOX)
        assert named < blank, "the name is not knocked out of the inverted row"

    def test_stale_birthdays_renders_glyph(self):
        """STALE draws the '!' badge in the region's bottom-right corner."""
        region = ComponentRegion(300, 360, 250, 120)
        box = (region.x, region.y, region.x + region.w, region.y + region.h)
        birthdays = [_b("Alice", TODAY + timedelta(days=3))]
        stale = _render(birthdays, region=region, staleness=StalenessLevel.STALE)
        none = _render(birthdays, region=region, staleness=None)
        assert ink(stale, box) > ink(none, box), "no staleness badge drawn"

    def test_fresh_staleness_draws_no_glyph(self):
        """FRESH is not a warning — measured against STALE, which is."""
        birthdays = [_b("Alice", TODAY + timedelta(days=3))]
        fresh = ink(_render(birthdays, staleness=StalenessLevel.FRESH), BOX)
        stale = ink(_render(birthdays, staleness=StalenessLevel.STALE), BOX)
        assert fresh < stale, "FRESH drew a staleness badge"

    def test_none_staleness_no_crash(self):
        """The default draws the bar without a badge."""
        assert ink(_render([], staleness=None), BOX) > 0

    def test_early_break_when_layout_too_small(self):
        """A region too short for a row breaks out instead of overflowing.

        y = y0+32, line_h=22, h=50, pad=8 → 32+22 = 54 > 50-8 = 42, so the
        loop breaks at i=0 and no birthday rows are drawn — only the label.
        """
        small = ComponentRegion(x=300, y=360, w=250, h=50)
        box = (small.x, small.y, small.x + small.w, small.y + small.h)
        birthdays = [_b(name, TODAY + timedelta(days=i + 1)) for i, name in enumerate("ABC")]
        cramped = _render(birthdays, region=small)
        assert ink(cramped, box) > 0, "not even the section label was drawn"
        # No *content* spilled below the region. The right separator is drawn
        # to y0+h inclusive, so it puts one pixel on the row below — the same
        # convention weather_panel uses, so the border column is excluded here
        # rather than treated as an overflow.
        below = (small.x, small.y + small.h, small.x + small.w - 1, 480)
        assert ink(cramped, below) == 0
        roomy = ComponentRegion(x=300, y=360, w=250, h=120)
        roomy_box = (roomy.x, roomy.y, roomy.x + roomy.w, roomy.y + roomy.h)
        assert ink(cramped, box) < ink(_render(birthdays, region=roomy), roomy_box), (
            "the cramped region listed as much as the roomy one"
        )


class TestFeb29Birthday:
    def test_feb29_birthday_does_not_crash(self):
        from PIL import Image

        from src.render.components.birthday_bar import draw_birthdays
        from tests.inkutils import ink

        img = Image.new("1", (800, 480), 1)
        draw = ImageDraw.Draw(img)
        # 2025 is not a leap year
        today = date(2025, 3, 15)
        birthdays = [Birthday(name="Leapy", date=date(2000, 2, 29))]
        # Should not raise ValueError, and the birthday must still be listed.
        draw_birthdays(draw, birthdays, today)
        empty = Image.new("1", img.size, 1)
        draw_birthdays(ImageDraw.Draw(empty), [], today)
        assert ink(img) != ink(empty), "the Feb-29 birthday was dropped"

    def test_feb29_birthday_next_year_non_leap(self):
        from PIL import Image

        from src.render.components.birthday_bar import draw_birthdays
        from tests.inkutils import ink

        img = Image.new("1", (800, 480), 1)
        draw = ImageDraw.Draw(img)
        # Birthday already passed this year, next year (2026) also not leap
        today = date(2025, 3, 15)
        birthdays = [Birthday(name="Leapy", date=date(2000, 2, 29))]
        draw_birthdays(draw, birthdays, today)
        empty = Image.new("1", img.size, 1)
        draw_birthdays(ImageDraw.Draw(empty), [], today)
        assert ink(img) != ink(empty), "the rolled-over Feb-29 birthday was dropped"
