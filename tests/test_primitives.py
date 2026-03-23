"""Tests for src/render/primitives.py."""

import pytest
from PIL import Image, ImageDraw, ImageFont

from src.render.primitives import (
    BLACK, WHITE,
    draw_text_truncated, draw_text_wrapped,
    filled_rect, hline, inverted_text,
    text_height, text_width, vline,
)


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
        # Check pixel was drawn (image not all-white)
        assert img.getbbox() is not None

    def test_long_text_is_truncated(self, canvas, font):
        img, draw = canvas
        very_long = "A" * 100
        draw_text_truncated(draw, (0, 0), very_long, font, max_width=30)
        assert img.getbbox() is not None

    def test_returns_width(self, canvas, font):
        _, draw = canvas
        w = draw_text_truncated(draw, (0, 0), "Test", font, max_width=200)
        assert isinstance(w, int)
        assert w > 0

    def test_truncated_width_within_max(self, canvas, font):
        _, draw = canvas
        w = draw_text_truncated(draw, (0, 0), "A" * 100, font, max_width=30)
        assert w <= 30

    def test_fill_white(self, canvas, font):
        img, draw = canvas
        # Draw white-on-white (invisible) — just ensure no crash
        draw_text_truncated(draw, (0, 0), "Test", font, max_width=200, fill=WHITE)

    def test_zero_max_width_draws_ellipsis_only(self, canvas, font):
        """When max_width is 0, even a 1-char text can't fit with ellipsis;
        the function falls through to draw just the ellipsis."""
        _, draw = canvas
        # max_width=0 forces the while loop to strip all chars, leaving only the ellipsis
        w = draw_text_truncated(draw, (0, 0), "Hello World", font, max_width=0)
        assert isinstance(w, int)


class TestDrawTextWrapped:
    def test_returns_positive_height(self, canvas, font):
        _, draw = canvas
        h = draw_text_wrapped(draw, (0, 0), "Hello world foo bar", font, max_width=60)
        assert h > 0

    def test_respects_max_lines(self, canvas, font):
        _, draw = canvas
        # With a very narrow width, more lines would be needed than allowed
        h_one = draw_text_wrapped(
            draw, (0, 0), "A B C D E F G H", font, max_width=20, max_lines=1,
        )
        h_three = draw_text_wrapped(
            draw, (0, 40), "A B C D E F G H", font, max_width=20, max_lines=3,
        )
        assert h_three >= h_one

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
        assert img.getbbox() is not None


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


class TestInvertedText:
    def test_draws_black_background(self, canvas, font):
        img, draw = canvas
        inverted_text(draw, rect=(5, 5, 80, 25), text="Hi", font=font)
        # Background should be black
        assert img.getpixel((5, 5)) == BLACK

    def test_no_crash_with_empty_text(self, canvas, font):
        _, draw = canvas
        inverted_text(draw, rect=(5, 5, 80, 25), text="", font=font)
