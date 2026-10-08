"""Tests for src/render/primitives.py."""

from datetime import date

import pytest
from PIL import Image, ImageDraw, ImageFont

from src.render.primitives import (
    BLACK,
    WHITE,
    draw_staleness_glyph,
    draw_text_truncated,
    draw_text_wrapped,
    filled_rect,
    hline,
    location_line,
    next_birthday,
    text_height,
    text_width,
    truncate_to_width,
    vline,
)
from tests.inkutils import ink, ink_x_extent, record_text


# Use a default bitmap font so tests don't require bundled TTF files
@pytest.fixture
def font():
    return ImageFont.load_default()


@pytest.fixture
def canvas():
    """Return a fresh 200×100 1-bit image and its draw handle."""
    img = Image.new("1", (200, 100), WHITE)
    draw = ImageDraw.Draw(img)
    return img, draw


class TestTextWidth:
    def test_returns_positive_int(self, canvas, font):
        _, draw = canvas
        w = text_width(draw, "Hello", font)
        assert isinstance(w, int)
        assert w > 0

    def test_longer_text_is_wider(self, canvas, font):
        _, draw = canvas
        assert text_width(draw, "Hello World", font) > text_width(draw, "Hi", font)

    def test_empty_string(self, canvas, font):
        _, draw = canvas
        assert text_width(draw, "", font) == 0


class TestTextHeight:
    def test_returns_positive_int(self, font):
        h = text_height(font)
        assert isinstance(h, int)
        assert h > 0


class TestDrawTextTruncated:
    def test_short_text_fits_without_ellipsis(self, canvas, font):
        img, draw = canvas
        # Draw "Hi" in a wide space — it should not add ellipsis
        draw_text_truncated(draw, (0, 0), "Hi", font, max_width=200)
        # Short text is drawn in full: no ellipsis, so no wider than "Hi" alone.
        assert ink(img) > 0, "nothing drawn"
        wide = Image.new("1", img.size, WHITE)
        draw_text_truncated(ImageDraw.Draw(wide), (0, 0), "Hi", font, max_width=2000)
        assert img.tobytes() == wide.tobytes(), "a generous width changed the result"

    def test_long_text_is_truncated(self, canvas, font):
        img, draw = canvas
        very_long = "A" * 100
        draw_text_truncated(draw, (0, 0), very_long, font, max_width=30)
        assert ink(img) > 0, "nothing drawn"
        extent = ink_x_extent(img, (0, 0, img.width, img.height))
        assert extent is not None and extent[1] <= 30 + 2, (
            f"truncated text ran to x={extent[1]}, past its 30px budget"
        )

    def test_returns_width(self, canvas, font):
        _, draw = canvas
        w = draw_text_truncated(draw, (0, 0), "Test", font, max_width=200)
        assert isinstance(w, int)
        assert w > 0

    def test_truncated_width_within_max(self, canvas, font):
        _, draw = canvas
        w = draw_text_truncated(draw, (0, 0), "A" * 100, font, max_width=30)
        assert w <= 30

    def test_fill_is_honoured(self, canvas, font):
        """White-on-white leaves no ink; the default fill does."""
        img, draw = canvas
        draw_text_truncated(draw, (0, 0), "Test", font, max_width=200, fill=WHITE)
        assert ink(img) == 0, "fill=WHITE still drew ink"
        draw_text_truncated(draw, (0, 0), "Test", font, max_width=200)
        assert ink(img) > 0

    def test_zero_max_width_draws_ellipsis_only(self, canvas, font):
        """When max_width is 0, even a 1-char text can't fit with ellipsis;
        the function falls through to draw just the ellipsis."""
        _, draw = canvas
        calls = record_text(draw)
        w = draw_text_truncated(draw, (0, 0), "Hello World", font, max_width=0)
        assert [text for text, _box in calls] == ["..."]
        assert w == text_width(draw, "...", font)


class TestTruncateToWidth:
    def test_text_that_fits_is_returned_unchanged(self, canvas, font):
        _img, draw = canvas
        assert truncate_to_width(draw, "Hi", font, 200) == "Hi"

    def test_long_text_is_cut_to_fit_with_an_ellipsis(self, canvas, font):
        _img, draw = canvas
        out = truncate_to_width(draw, "Rear Admiral Grace Brewster Murray Hopper", font, 80)
        assert out.endswith("...") and out.startswith("Rear")
        assert text_width(draw, out, font) <= 80

    def test_nothing_fits_returns_a_bare_ellipsis(self, canvas, font):
        _img, draw = canvas
        assert truncate_to_width(draw, "Wolfeschlegelsteinhausen", font, 1) == "..."


class TestDrawTextWrapped:
    def test_returns_positive_height(self, canvas, font):
        _, draw = canvas
        h = draw_text_wrapped(draw, (0, 0), "Hello world foo bar", font, max_width=60)
        assert h > 0

    def test_respects_max_lines(self, canvas, font):
        _, draw = canvas
        # With a very narrow width, more lines would be needed than allowed
        h_one = draw_text_wrapped(
            draw,
            (0, 0),
            "A B C D E F G H",
            font,
            max_width=20,
            max_lines=1,
        )
        h_three = draw_text_wrapped(
            draw,
            (0, 40),
            "A B C D E F G H",
            font,
            max_width=20,
            max_lines=3,
        )
        assert h_three >= h_one

    def test_unbreakable_word_is_bounded_by_max_width(self, canvas, font):
        """A word with no spaces used to be drawn at full width, straight
        across every column of the week view (#288)."""
        img, draw = canvas
        draw_text_wrapped(draw, (0, 0), "A" * 200, font, max_width=80, max_lines=2)
        extent = ink_x_extent(img, (0, 0, img.width, img.height))
        assert extent is not None
        assert extent[1] - extent[0] <= 80

    def test_unbreakable_word_ellipsizes_past_max_lines(self, canvas, font):
        img, draw = canvas
        h = draw_text_wrapped(draw, (0, 0), "A" * 200, font, max_width=80, max_lines=2)
        one_line = draw_text_wrapped(
            ImageDraw.Draw(Image.new("1", (10, 10), 1)), (0, 0), "A", font, max_width=80
        )
        assert h == 2 * one_line, "more than max_lines were drawn"

    def test_wrap_lines_breaks_an_over_wide_word(self, font):
        from src.render.primitives import wrap_lines

        lines = wrap_lines("short " + "B" * 120 + " tail", font, 80)
        assert len(lines) > 3
        assert all(font.getlength(line) <= 80 for line in lines)
        assert "".join(lines).replace(" ", "") == "short" + "B" * 120 + "tail"

    def test_single_word_no_wrap(self, canvas, font):
        _, draw = canvas
        h = draw_text_wrapped(draw, (0, 0), "Hello", font, max_width=200)
        assert h > 0

    def test_empty_string(self, canvas, font):
        _, draw = canvas
        h = draw_text_wrapped(draw, (0, 0), "", font, max_width=200)
        assert h == 0

    def test_draws_something(self, canvas, font):
        img, draw = canvas
        draw_text_wrapped(draw, (0, 0), "Hello world", font, max_width=200)
        assert ink(img) > 0, "wrapped text drew nothing"


class TestDrawingPrimitives:
    def test_hline_draws_pixels(self, canvas):
        img, draw = canvas
        hline(draw, y=10, x0=0, x1=50)
        # At least one pixel should be black on row 10
        pixels = [img.getpixel((x, 10)) for x in range(51)]
        assert any(p == BLACK for p in pixels)

    def test_vline_draws_pixels(self, canvas):
        img, draw = canvas
        vline(draw, x=10, y0=0, y1=50)
        pixels = [img.getpixel((10, y)) for y in range(51)]
        assert any(p == BLACK for p in pixels)

    def test_filled_rect_fills_area(self, canvas):
        img, draw = canvas
        filled_rect(draw, (10, 10, 30, 30))
        assert img.getpixel((20, 20)) == BLACK

    def test_filled_rect_white_fill(self, canvas):
        # First fill black, then overwrite with white
        img, draw = canvas
        filled_rect(draw, (0, 0, 50, 50), fill=BLACK)
        filled_rect(draw, (10, 10, 20, 20), fill=WHITE)
        assert img.getpixel((15, 15)) == WHITE


class TestDrawStalenessGlyph:
    def test_glyph_draws_pixels_in_bottom_right(self, canvas):
        """draw_staleness_glyph should draw a filled rectangle near the bottom-right."""
        img, draw = canvas
        from unittest.mock import MagicMock

        region = MagicMock()
        region.x, region.y, region.w, region.h = 0, 0, 200, 100
        style = MagicMock()
        style.fg = BLACK
        style.bg = WHITE
        draw_staleness_glyph(draw, region, style)
        # The badge occupies the bottom-right corner — at least one black pixel there
        assert img.getpixel((200 - 4, 100 - 4)) == BLACK

    def test_glyph_no_crash_on_small_region(self):
        """Should not raise even when the region is very small."""
        img = Image.new("1", (30, 20), WHITE)
        draw = ImageDraw.Draw(img)
        from unittest.mock import MagicMock

        region = MagicMock()
        region.x, region.y, region.w, region.h = 0, 0, 30, 20
        style = MagicMock()
        style.fg = BLACK
        style.bg = WHITE
        draw_staleness_glyph(draw, region, style)
        assert ink(img, (0, 0, 30, 20)) > 0, "no badge drawn in the small region"


class TestLocationLine:
    """A panel row gets the location's first line: business name or street."""

    def test_business_name_over_street(self):
        # Google Calendar's shape: name, newline, street + city on one line.
        loc = "Ultimate Condition Fitness\n535 W Hamilton Ave, Campbell, CA  95008, United States"
        assert location_line(loc) == "Ultimate Condition Fitness"

    def test_street_when_it_is_the_first_line(self):
        assert location_line("123 Main St\nSuite 200, Springfield") == "123 Main St"

    def test_first_comma_segment_of_a_single_line(self):
        assert location_line("Conference Room B, Floor 3, HQ") == "Conference Room B"

    def test_whitespace_collapsed(self):
        assert location_line("  Blue   Bottle ,  Market St") == "Blue Bottle"

    def test_leading_blank_lines_skipped(self):
        assert location_line("\n  \nRooftop Lounge") == "Rooftop Lounge"

    def test_crlf(self):
        assert location_line("Studio 12\r\n1 Elm St") == "Studio 12"

    @pytest.mark.parametrize("loc", [None, "", "   ", "\n", ", ,"])
    def test_nothing_usable_is_empty(self, loc):
        assert location_line(loc) == ""


class TestNextBirthday:
    def test_this_year_when_ahead(self):
        assert next_birthday(date(1990, 6, 1), date(2026, 4, 6)) == date(2026, 6, 1)

    def test_today_counts(self):
        assert next_birthday(date(1990, 4, 6), date(2026, 4, 6)) == date(2026, 4, 6)

    def test_rolls_to_next_year(self):
        assert next_birthday(date(1990, 1, 5), date(2026, 4, 6)) == date(2027, 1, 5)

    def test_leap_day_off_leap_years(self):
        assert next_birthday(date(1992, 2, 29), date(2027, 1, 1)) == date(2027, 2, 28)
        assert next_birthday(date(1992, 2, 29), date(2028, 1, 1)) == date(2028, 2, 29)
        # Past Feb 28 in a non-leap year: next year, which is a leap year.
        assert next_birthday(date(1992, 2, 29), date(2027, 3, 1)) == date(2028, 2, 29)
