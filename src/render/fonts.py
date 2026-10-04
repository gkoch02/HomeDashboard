from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).parent.parent.parent / "fonts"


def _glyph_bits(font: ImageFont.FreeTypeFont, ch: str) -> bytes:
    side = int(font.size) * 2
    img = Image.new("1", (side, side), 0)
    ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=1)
    return img.tobytes()


@lru_cache(maxsize=4096)
def _has_glyph(path: str, ch: str) -> bool:
    font = ImageFont.truetype(path, 24)
    # U+FFFF is a noncharacter, so every font draws its .notdef box for it.
    return _glyph_bits(font, ch) != _glyph_bits(font, "\uffff")


def has_glyphs(font: ImageFont.FreeTypeFont, text: str) -> bool:
    """Whether *font* draws every character of *text*, rather than its .notdef box.

    Pillow has no per-character font fallback, so a face missing a script
    renders it as a row of boxes; callers use this to pick a fallback face.
    """
    return all(ch.isspace() or _has_glyph(str(font.path), ch) for ch in text)


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
# column headers, and quote body, and (at ExtraBold) the ``wide_night`` labels;
# narrow enough to stay legible in a 14px day header and a wrapped quote line.
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


def oxanium_extrabold(size: int) -> ImageFont.FreeTypeFont:
    return _get_oxanium(size, 800)


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


# Jura — a squarish, slightly rounded technical sans (Daniel Johnson, OFL),
# drawn after the lettering on Soviet-era instrument panels. Variable font,
# wght 300-700. Sets the ``wide_night`` temperature at display size, where its
# open, even forms read across a dark room; SemiBold (600) keeps the stems
# solid on the four-ink panel without the numerals clotting. Its 700 is too
# light for the 20-px labels, which are set in Oxanium ExtraBold instead.
@lru_cache(maxsize=32)
def _get_jura(size: int, wght: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / "Jura-Variable.ttf"), size)
    font.set_variation_by_axes([wght])
    return font


def jura_semibold(size: int) -> ImageFont.FreeTypeFont:
    return _get_jura(size, 600)


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


# Literata — the text serif Google drew for Play Books, i.e. for reading on
# screens and e-readers (TypeTogether, OFL).  Low stroke contrast and sturdy
# serifs, so it survives bilevel rasterisation at text sizes where a display
# serif like Playfair breaks into hairlines.  Carries the wide_week rail's quote.
#
# The upstream file is variable (opsz 7-72, wght 200-900) and ~1 MB; these are
# static instances cut from it with fontTools at opsz 12 — the small-text
# optical size, whose sturdier forms suit a 16-19 px quote — and wght 600/700
# (`fonttools varLib.instancer <variable file> wght=600 opsz=12
# --update-name-table`, from google/fonts ofl/literata).
def literata_semibold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Literata-SemiBold.ttf", size)


def literata_bold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Literata-Bold.ttf", size)


# Figtree — a friendly geometric sans (OFL). Static ExtraBold, full glyph
# set, the Google Fonts build (as repackaged by @expo-google-fonts/figtree).
# Sets a 3-px stem at both 17 and 21 px on a 1-bit plate, where DM Sans Bold
# hints to 2 px.
def figtree_extrabold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("Figtree-ExtraBold.ttf", size)


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


# Big Shoulders Display — Chicago-signage condensed grotesque (Patric King /
# XOTYPE, OFL).  Static cuts converted from the Fontsource latin subset, which
# covers ASCII, the degree sign, the en dash and the arrows.  Condensed enough
# that a 100-px numeral sits in a narrow column, so the wide_horizon theme sets
# its day names, temperatures and hero reading in it.
def big_shoulders_semibold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("BigShouldersDisplay-SemiBold.ttf", size)


def big_shoulders_extrabold(size: int) -> ImageFont.FreeTypeFont:
    return get_font("BigShouldersDisplay-ExtraBold.ttf", size)


def big_shoulders_black(size: int) -> ImageFont.FreeTypeFont:
    return get_font("BigShouldersDisplay-Black.ttf", size)
