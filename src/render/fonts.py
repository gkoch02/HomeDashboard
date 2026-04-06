from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).parent.parent.parent / "fonts"


@lru_cache(maxsize=32)
def get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


@lru_cache(maxsize=32)
def _get_variable_font(name: str, size: int, wght: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / name), size)
    font.set_variation_by_axes([wght])
    return font


# Convenience accessors — Plus Jakarta Sans (warm geometric)
def regular(size: int) -> ImageFont.FreeTypeFont:
    return get_font("PlusJakartaSans-Regular.ttf", size)


def medium(size: int) -> ImageFont.FreeTypeFont:
    return get_font("PlusJakartaSans-Medium.ttf", size)


def semibold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("PlusJakartaSans-SemiBold.ttf", size)


def bold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("PlusJakartaSans-Bold.ttf", size)


def weather_icon(size: int) -> ImageFont.FreeTypeFont:
    return get_font("weathericons-regular.ttf", size)


# Share Tech Mono — monospace terminal font for the Cyberpunk theme.
# Single weight; all four callables use the same file for theme compatibility.
def cyber_mono(size: int) -> ImageFont.FreeTypeFont:
    return get_font("ShareTechMono-Regular.ttf", size)


# DM Sans — screen-optimised geometric sans for the Minimalist theme.
# Variable font with optical-size (opsz 9–40) and weight (wght 100–1000) axes.
# opsz is clamped to the render size so small text auto-uses the screen-optimised cut.
@lru_cache(maxsize=64)
def _get_dm_sans(size: int, wght: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / "DMSans.ttf"), size)
    opsz = max(9, min(40, size))
    font.set_variation_by_axes([opsz, wght])
    return font


def dm_regular(size: int) -> ImageFont.FreeTypeFont:
    return _get_dm_sans(size, 400)


def dm_medium(size: int) -> ImageFont.FreeTypeFont:
    return _get_dm_sans(size, 500)


def dm_semibold(size: int) -> ImageFont.FreeTypeFont:
    return _get_dm_sans(size, 600)


def dm_bold(size: int) -> ImageFont.FreeTypeFont:
    return _get_dm_sans(size, 700)


# Cinzel — Roman inscription caps, used for the D&D Fantasy theme.
# Variable font with a single weight axis (wght 400–900).
@lru_cache(maxsize=32)
def _get_cinzel(size: int, wght: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / "Cinzel.ttf"), size)
    font.set_variation_by_axes([wght])
    return font


def cinzel_regular(size: int) -> ImageFont.FreeTypeFont:
    return _get_cinzel(size, 400)


def cinzel_semibold(size: int) -> ImageFont.FreeTypeFont:
    return _get_cinzel(size, 600)


def cinzel_bold(size: int) -> ImageFont.FreeTypeFont:
    return _get_cinzel(size, 700)


def cinzel_black(size: int) -> ImageFont.FreeTypeFont:
    return _get_cinzel(size, 900)


# Maratype — display font for terminal theme dashboard title and day column headers.
def maratype(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Maratype.otf", size)


# Synthetic Genesis — sci-fi display font for the terminal theme date number.
def synthetic_genesis(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Synthetic Genesis.otf", size)


# UESC Display — clean display font for the terminal theme month title.
def uesc_display(size: int) -> ImageFont.FreeTypeFont:
    return get_font("UESC Display.otf", size)


# Space Grotesk — proportional sans derived from Space Mono; retains the
# monospace family's quirky letterforms (a, G, R, t) for data-dashboard personality
# while remaining legible at all sizes.  Used by the air_quality theme.
# Weights available: Regular (400), Medium (500), Bold (700).
def sg_regular(size: int) -> ImageFont.FreeTypeFont:
    return get_font("SpaceGrotesk-Regular.ttf", size)


def sg_medium(size: int) -> ImageFont.FreeTypeFont:
    return get_font("SpaceGrotesk-Medium.ttf", size)


def sg_bold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("SpaceGrotesk-Bold.ttf", size)


# Playfair Display — newspaper serif font for the Old Fashioned theme.
def playfair_regular(size: int) -> ImageFont.FreeTypeFont:
    return get_font("PlayfairDisplay-Regular.ttf", size)


def playfair_medium(size: int) -> ImageFont.FreeTypeFont:
    return get_font("PlayfairDisplay-Medium.ttf", size)


def playfair_semibold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("PlayfairDisplay-SemiBold.ttf", size)


def playfair_bold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("PlayfairDisplay-Bold.ttf", size)


# NuCore — high-contrast display font for scorecard/sunrise/tides themes.
def nucore(size: int) -> ImageFont.FreeTypeFont:
    return get_font("NuCore.otf", size)


def nucore_condensed(size: int) -> ImageFont.FreeTypeFont:
    return get_font("NuCore Condensed.otf", size)
