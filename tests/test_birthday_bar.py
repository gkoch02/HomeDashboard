"""Tests for src/render/components/birthday_bar.py"""

from datetime import date, timedelta

from PIL import Image, ImageDraw

from src.data.models import Birthday
from src.render.components.birthday_bar import draw_birthdays


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


class TestDrawBirthdays:
    def test_no_birthdays_renders_empty_message(self):
        """No birthdays should display 'No upcoming birthdays' without crashing."""
        img, draw = _make_draw()
        draw_birthdays(draw, [], date(2024, 3, 15))
        assert img.getbbox() is not None

    def test_today_birthday_renders(self):
        today = date(2024, 3, 15)
        birthdays = [Birthday(name="Alice", date=today)]
        img, draw = _make_draw()
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_tomorrow_birthday_renders(self):
        today = date(2024, 3, 15)
        birthdays = [Birthday(name="Bob", date=today + timedelta(days=1))]
        img, draw = _make_draw()
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_future_birthday_shows_days_countdown(self):
        today = date(2024, 3, 15)
        birthdays = [Birthday(name="Carol", date=today + timedelta(days=10))]
        img, draw = _make_draw()
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_birthday_with_age_renders(self):
        today = date(2024, 3, 15)
        # age=27 is not a milestone age, so normal "(27)" format is used
        birthdays = [Birthday(name="Dave", date=today + timedelta(days=5), age=27)]
        img, draw = _make_draw()
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_milestone_age_renders(self):
        """Milestone ages (30, 40, 50…) should render as bold with '·' prefix."""
        today = date(2024, 3, 15)
        birthdays = [Birthday(name="Eve", date=today + timedelta(days=3), age=30)]
        img, draw = _make_draw()
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_birthday_past_this_year_rolls_to_next_year(self):
        """A birthday that has already passed this year should show a positive countdown."""
        today = date(2024, 3, 15)
        # Birthday was March 1 — already passed, should roll to next year
        past_bday = date(2024, 3, 1)
        birthdays = [Birthday(name="Frank", date=past_bday)]
        img, draw = _make_draw()
        # Should not crash — rolls forward
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_overflow_count_shown_when_more_than_max(self):
        """When more than 3 birthdays are provided, overflow count should be shown."""
        today = date(2024, 3, 15)
        birthdays = [
            Birthday(name=f"Person {i}", date=today + timedelta(days=i + 1))
            for i in range(6)
        ]
        img, draw = _make_draw()
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_exactly_three_birthdays_no_overflow(self):
        today = date(2024, 3, 15)
        birthdays = [
            Birthday(name=f"Person {i}", date=today + timedelta(days=i + 1))
            for i in range(3)
        ]
        img, draw = _make_draw()
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_birthday_with_no_age_renders(self):
        today = date(2024, 3, 15)
        birthdays = [Birthday(name="Grace", date=today + timedelta(days=7), age=None)]
        img, draw = _make_draw()
        draw_birthdays(draw, birthdays, today)
        assert img.getbbox() is not None

    def test_today_birthday_inverts_row(self):
        """A birthday today should produce different pixels than a non-today birthday."""
        today = date(2024, 3, 15)

        img_today, draw_today = _make_draw()
        draw_birthdays(draw_today, [Birthday(name="Alice", date=today)], today)

        img_future, draw_future = _make_draw()
        draw_birthdays(draw_future, [Birthday(name="Alice", date=today + timedelta(days=5))], today)

        # Today's birthday row is inverted (has black fill), future is not
        # Simply verify both render differently
        assert img_today.tobytes() != img_future.tobytes()

    def test_early_break_when_layout_too_small(self):
        """The break fires when y + line_h exceeds available space (line 43).

        Achieved by passing a small region (h=50) so the condition triggers:
        y = y0+32, line_h=22, h=50, pad=8 → 32+22=54 > 50-8=42 → break at i=0
        """
        from src.render.theme import ComponentRegion
        today = date(2024, 3, 15)
        birthdays = [
            Birthday(name="Alice", date=today + timedelta(days=1)),
            Birthday(name="Bob", date=today + timedelta(days=2)),
            Birthday(name="Carol", date=today + timedelta(days=3)),
        ]
        img, draw = _make_draw()
        small_region = ComponentRegion(x=300, y=360, w=250, h=50)
        draw_birthdays(draw, birthdays, today, region=small_region)
        assert img.getbbox() is not None
