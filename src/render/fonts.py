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


# Oxanium — techno/cyberpunk display sans whose squared geometric terminals read
# as retro-future (Sev Meyer, OFL).  Carries the terminal theme's title, day
# column headers, and quote body.  Chosen over the wider Orbitron for these roles
# because it stays legible in a 14px day header and a wrapped quote line, where a
# wide face would force the text size down.
#
# Variable font, wght 200-800, whose DEFAULT axis instance is ExtraLight (200) —
# every accessor must pin a weight explicitly or the terminal theme renders as
# near-invisible hairlines on the panel.
@lru_cache(maxsize=32)
def _get_oxanium(size: int, wght: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / "Oxanium-Variable.ttf"), size)
    font.set_variation_by_axes([wght])
    return font


def oxanium(size: int) -> ImageFont.FreeTypeFont:
    return _get_oxanium(size, 400)


def oxanium_bold(size: int) -> ImageFont.FreeTypeFont:
    return _get_oxanium(size, 700)


# Orbitron — the canonical geometric sci-fi display face (Matt McInerney, OFL).
# Very wide, so it is reserved for the terminal theme's single hero element: the
# large today date numeral.  Variable font, wght 400-900; Black (900) gives the
# numeral enough stroke mass to hold against the black canvas.
@lru_cache(maxsize=32)
def _get_orbitron(size: int, wght: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / "Orbitron-Variable.ttf"), size)
    font.set_variation_by_axes([wght])
    return font


def orbitron_black(size: int) -> ImageFont.FreeTypeFont:
    return _get_orbitron(size, 900)


# Rajdhani — squarish semi-condensed techno sans drawn for UI legibility at small
# sizes (Indian Type Foundry, OFL).  Carries the terminal theme's chrome: month
# band, section labels (11px), and quote attribution.  Static weights rather than
# the variable cut because only two are needed and the variable file also ships
# Devanagari.
def rajdhani(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Rajdhani-Regular.ttf", size)


def rajdhani_semibold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Rajdhani-SemiBold.ttf", size)


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


# Cormorant Garamond — high-contrast Garamond-revival serif (OFL).  Variable
# font with a wght axis (300–700); paired with Cinzel for moonphase's
# mystical/celestial body text.
@lru_cache(maxsize=32)
def _get_cormorant(size: int, wght: int, italic: bool) -> ImageFont.FreeTypeFont:
    name = "CormorantGaramond-Italic.ttf" if italic else "CormorantGaramond.ttf"
    font = ImageFont.truetype(str(FONT_DIR / name), size)
    font.set_variation_by_axes([wght])
    return font


def cormorant_regular(size: int) -> ImageFont.FreeTypeFont:
    return _get_cormorant(size, 400, italic=False)


def cormorant_medium(size: int) -> ImageFont.FreeTypeFont:
    return _get_cormorant(size, 500, italic=False)


def cormorant_semibold(size: int) -> ImageFont.FreeTypeFont:
    return _get_cormorant(size, 600, italic=False)


def cormorant_italic(size: int) -> ImageFont.FreeTypeFont:
    return _get_cormorant(size, 400, italic=True)


# Tangerine — calligraphic script display face (OFL).  Single-weight regular
# (a bold variant also exists upstream; bring in if needed later).  Used by
# the moonphase theme for the quote attribution to give a poetic, handwritten feel.
def tangerine_regular(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Tangerine-Regular.ttf", size)


# Manufacturing Consent — Fraktur blackletter modernised with contemporary
# proportions (OFL, by Fredrick Brennan).  Used by the moonphase theme for the
# phase-name headline; reads as mystical newspaper-incipit rather than the
# heavier medieval feel of Astloch.
def manufacturing_consent(size: int) -> ImageFont.FreeTypeFont:
    return get_font("ManufacturingConsent-Regular.ttf", size)


# Astloch — antique blackletter / fraktur display face (OFL).  Two weights;
# perfect "character" font for editorial mastheads and 19th-century almanacs.
def astloch(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Astloch-Regular.ttf", size)


def astloch_bold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Astloch-Bold.ttf", size)


# Righteous — single-weight condensed display sans (OFL).  Heavier strokes
# and tighter aperture than DM Sans; used for hero numerals where the digits
# need to read clearly at scale.
def righteous(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Righteous-Regular.ttf", size)


# Audiowide — single-weight retro-futuristic display sans (OFL).  Tall, even
# strokes with squared apertures; reads as an "observatory" / sci-fi face.
# Used by the constellation_map theme for the chart's star, constellation,
# and cardinal labels — stays legible at small sizes against the dark sky.
def audiowide(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Audiowide-Regular.ttf", size)


# Rye — single-weight Western-saloon display serif (OFL).  Heavy slab serifs
# with an inline highlight; reads as an antique sign-painted masthead.
# Used by the weatherglass theme for the WEATHERGLASS wordmark.
def rye(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Rye-Regular.ttf", size)


# Antonio — tall narrow condensed sans (Vernon Adams, OFL).  Carries the
# high-contrast condensed display role in the sunrise and tides themes: their
# titles and section labels.  Variable font, wght 100-700; the accessors pin
# Bold (700) and SemiBold (600) rather than relying on the axis default.
@lru_cache(maxsize=32)
def _get_antonio(size: int, wght: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / "Antonio-Variable.ttf"), size)
    font.set_variation_by_axes([wght])
    return font


def antonio_semibold(size: int) -> ImageFont.FreeTypeFont:
    return _get_antonio(size, 600)


def antonio_bold(size: int) -> ImageFont.FreeTypeFont:
    return _get_antonio(size, 700)
