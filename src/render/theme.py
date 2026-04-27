"""Theme system for the eInk dashboard.

A theme is composed of two objects:
- ``ThemeStyle``: visual properties (fg/bg colors, inversion flags, fonts, spacing).
- ``ThemeLayout``: structural layout (canvas size, per-component bounding boxes,
  component draw order).

Together they are wrapped in a ``Theme`` dataclass.

Usage::

    from src.render.theme import load_theme
    theme = load_theme("default")
    image = render_dashboard(data, config, theme=theme)

Adding a new theme requires only two steps:
1. Create ``src/render/themes/<name>.py`` with a ``<name>_theme() -> Theme`` factory.
2. Register the name in ``load_theme()`` below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from PIL import Image, ImageDraw, ImageFont

FontCallable = Callable[[int], "ImageFont.FreeTypeFont"]
QuantizationMode = Literal["threshold", "floyd_steinberg", "ordered"]


@dataclass
class ComponentRegion:
    """Bounding box for a single component on the canvas."""

    x: int
    y: int
    w: int
    h: int
    visible: bool = True


@dataclass
class ThemeLayout:
    """Full canvas structure: size, per-component bounding boxes, and draw order."""

    canvas_w: int = 800
    canvas_h: int = 480
    # "1" = 1-bit bilevel (default, all existing themes)
    # "L" = 8-bit grayscale (opt-in for new themes that want greyscale rendering)
    # L-mode themes must use fg=0, bg=255 in their ThemeStyle (not 0/1).
    canvas_mode: str = "1"
    header: ComponentRegion | None = field(default_factory=lambda: ComponentRegion(0, 0, 800, 40))
    week_view: ComponentRegion = field(default_factory=lambda: ComponentRegion(0, 40, 800, 320))
    weather: ComponentRegion = field(default_factory=lambda: ComponentRegion(0, 360, 300, 120))
    birthdays: ComponentRegion = field(default_factory=lambda: ComponentRegion(300, 360, 250, 120))
    info: ComponentRegion = field(default_factory=lambda: ComponentRegion(550, 360, 250, 120))
    today_view: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 60, 800, 280, visible=False)
    )
    # Used by the ``qotd`` theme for the full-canvas centered quote area.
    # Hidden by default so existing themes are not affected.
    qotd: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 400, visible=False)
    )
    # Used by the ``weather`` theme for the full-screen weather display.
    # Hidden by default so existing themes are not affected.
    weather_full: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``fuzzyclock`` theme for the full-canvas clock face area.
    # Hidden by default so existing themes are not affected.
    fuzzyclock: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 400, visible=False)
    )
    # Used by the ``diags`` theme for the full-canvas diagnostics readout.
    # Hidden by default so existing themes are not affected.
    diags: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``air_quality`` theme for the full-screen air quality display.
    # Hidden by default so existing themes are not affected.
    air_quality_full: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``moonphase`` theme for the full-canvas moon phase display.
    # Hidden by default so existing themes are not affected.
    moonphase_full: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``message`` theme for the full-canvas user message area.
    # Hidden by default so existing themes are not affected.
    message: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 400, visible=False)
    )
    # Used by the ``timeline`` theme for the hourly day-view timeline.
    # Hidden by default so existing themes are not affected.
    timeline: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 40, 800, 360, visible=False)
    )
    # Used by the ``year_pulse`` theme for the year progress + countdowns area.
    # Hidden by default so existing themes are not affected.
    year_pulse: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 40, 800, 360, visible=False)
    )
    # Used by the ``monthly`` theme for a full-canvas month grid heatmap.
    # Hidden by default so existing themes are not affected.
    monthly: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``sunrise`` theme for the sun-arc + split-schedule panel.
    sunrise: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``scorecard`` theme for the numeric KPI tile grid.
    scorecard: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``tides`` theme for alternating inverted horizontal bands.
    tides: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``countdown`` theme for full-canvas user-configured countdowns.
    countdown: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``astronomy`` theme for the full-canvas sky-tonight panel.
    astronomy: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    draw_order: list[str] = field(
        default_factory=lambda: ["header", "week_view", "weather", "birthdays", "info"]
    )
    # Optional overlay function called after all components are drawn.
    # Signature: (draw, layout, style) -> None.  Use for theme-specific decorations
    # such as ornamental borders that must render on top of all components.
    overlay_fn: Callable[[ImageDraw.ImageDraw, ThemeLayout, ThemeStyle], None] | None = field(
        default=None, repr=False
    )
    # Optional background function called BEFORE component rendering.
    # Receives the raw PIL Image so it can paste photo/grayscale content beneath UI elements.
    # Signature: (image, layout, style) -> None.
    background_fn: Callable[[Image.Image, ThemeLayout, ThemeStyle], None] | None = field(
        default=None, repr=False
    )
    # Allow an L-mode theme to render on RGB canvases for Inky while preserving
    # greyscale output on Waveshare.
    prefer_color_on_inky: bool = False
    # Optional quantization preference for L-mode themes on 1-bit backends.
    preferred_quantization_mode: QuantizationMode | None = None


@dataclass
class ThemeStyle:
    """Visual style: fg/bg colors, inversion policy, font callables, spacing density.

    Font callables default to Plus Jakarta Sans (the bundled default fonts)
    when left as ``None``, via ``__post_init__``.
    """

    # Color values.  For 1-bit / L-mode rendering these are integers (0/1 or 0–255).
    # For Inky RGB rendering _resolve_style replaces them with (R, G, B) tuples.
    fg: int | tuple[int, int, int] = 0
    bg: int | tuple[int, int, int] = 1
    accent_info: int | tuple[int, int, int] | None = None
    accent_warn: int | tuple[int, int, int] | None = None
    accent_alert: int | tuple[int, int, int] | None = None
    accent_good: int | tuple[int, int, int] | None = None
    accent_primary: int | tuple[int, int, int] | None = None
    accent_secondary: int | tuple[int, int, int] | None = None

    # Which regions use inverted color (fg fill + bg text)
    invert_header: bool = True
    invert_today_col: bool = True
    invert_allday_bars: bool = True

    # Font callables — each takes a size (int) and returns a FreeTypeFont.
    # None triggers automatic default-font assignment in __post_init__.
    font_regular: FontCallable | None = None
    font_medium: FontCallable | None = None
    font_semibold: FontCallable | None = None
    font_bold: FontCallable | None = None
    # Optional overrides for specific large display elements in the week view.
    # Falls back to font_bold when None.
    font_date_number: FontCallable | None = None  # large today date numeral
    font_month_title: FontCallable | None = None  # large month name band
    font_title: FontCallable | None = None  # dashboard title + day column headers
    font_section_label: FontCallable | None = None  # WEATHER / BIRTHDAYS / QUOTE OF THE DAY
    font_quote: FontCallable | None = None  # quote body text
    font_quote_author: FontCallable | None = None  # quote attribution line

    # Event spacing multiplier (applied in _fonts_for_tier)
    spacing_scale: float = 1.0

    # Section label style ("WEATHER", "BIRTHDAYS", "QUOTE OF THE DAY")
    label_font_size: int = 12
    label_font_weight: str = "bold"  # "bold" | "semibold" | "regular"

    # Optional overrides for component section labels.
    # Keys: "weather", "birthdays", "info".  Missing keys fall back to defaults.
    component_labels: dict[str, str] = field(default_factory=dict)

    # When False, all structural border lines and separators are suppressed.
    # Useful for borderless themes like minimalist.
    show_borders: bool = True

    # When False, the forecast strip at the bottom of the weather panel is
    # omitted and the current-conditions text rows are spread more evenly
    # across the full panel height.  Useful for compact strip layouts where
    # the panel is too short to accommodate the forecast without overlap.
    show_forecast_strip: bool = True

    # Photo path for the ``photo`` theme.  Set by app.py from cfg.photo.path.
    # Ignored by all other themes (defaults to empty string).
    photo_path: str = ""

    def __post_init__(self) -> None:
        """Fill in default fonts from fonts.py when callables were not provided."""
        if any(
            f is None
            for f in [self.font_regular, self.font_medium, self.font_semibold, self.font_bold]
        ):
            from src.render import fonts

            if self.font_regular is None:
                self.font_regular = fonts.regular
            if self.font_medium is None:
                self.font_medium = fonts.medium
            if self.font_semibold is None:
                self.font_semibold = fonts.semibold
            if self.font_bold is None:
                self.font_bold = fonts.bold

    def label_font(self) -> ImageFont.FreeTypeFont:
        """Return the appropriate font for section labels based on label_font_weight."""
        if self.font_section_label is not None:
            return self.font_section_label(self.label_font_size)  # type: ignore[misc]
        fn = {
            "bold": self.font_bold,
            "semibold": self.font_semibold,
            "regular": self.font_regular,
        }.get(self.label_font_weight, self.font_bold)
        return fn(self.label_font_size)  # type: ignore[misc]

    def primary_accent_fill(self) -> int | tuple[int, int, int]:
        """Return the general-purpose primary accent fill for the current backend."""
        return self.fg if self.accent_primary is None else self.accent_primary

    def secondary_accent_fill(self) -> int | tuple[int, int, int]:
        """Return the softer secondary accent fill for the current backend."""
        return self.fg if self.accent_secondary is None else self.accent_secondary


@dataclass
class Theme:
    """A complete theme: visual style + structural layout."""

    name: str
    style: ThemeStyle
    layout: ThemeLayout


# ---------------------------------------------------------------------------
# Theme registry and built-in theme names
# ---------------------------------------------------------------------------

# Registry mapping theme name → (module_path, factory_function_name).
# To add a new theme, add an entry here — AVAILABLE_THEMES is derived automatically.
_THEME_REGISTRY: dict[str, tuple[str, str]] = {
    "terminal": ("src.render.themes.terminal", "terminal_theme"),
    "minimalist": ("src.render.themes.minimalist", "minimalist_theme"),
    "old_fashioned": ("src.render.themes.old_fashioned", "old_fashioned_theme"),
    "today": ("src.render.themes.today", "today_theme"),
    "fantasy": ("src.render.themes.fantasy", "fantasy_theme"),
    "qotd": ("src.render.themes.qotd", "qotd_theme"),
    "qotd_invert": ("src.render.themes.qotd_invert", "qotd_invert_theme"),
    "weather": ("src.render.themes.weather", "weather_theme"),
    "fuzzyclock": ("src.render.themes.fuzzyclock", "fuzzyclock_theme"),
    "fuzzyclock_invert": ("src.render.themes.fuzzyclock_invert", "fuzzyclock_invert_theme"),
    "diags": ("src.render.themes.diags", "diags_theme"),
    "air_quality": ("src.render.themes.air_quality", "air_quality_theme"),
    "moonphase": ("src.render.themes.moonphase", "moonphase_theme"),
    "moonphase_invert": ("src.render.themes.moonphase_invert", "moonphase_invert_theme"),
    "message": ("src.render.themes.message", "message_theme"),
    "timeline": ("src.render.themes.timeline", "timeline_theme"),
    "year_pulse": ("src.render.themes.year_pulse", "year_pulse_theme"),
    "monthly": ("src.render.themes.monthly", "monthly_theme"),
    "sunrise": ("src.render.themes.sunrise", "sunrise_theme"),
    "scorecard": ("src.render.themes.scorecard", "scorecard_theme"),
    "tides": ("src.render.themes.tides", "tides_theme"),
    "photo": ("src.render.themes.photo", "photo_theme"),
    "countdown": ("src.render.themes.countdown", "countdown_theme"),
    "astronomy": ("src.render.themes.astronomy", "astronomy_theme"),
}

# Derived from the registry — adding a theme to _THEME_REGISTRY is all that's needed.
AVAILABLE_THEMES: frozenset[str] = frozenset(
    set(_THEME_REGISTRY.keys()) | {"default", "random", "random_daily", "random_hourly"}
)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def default_layout() -> ThemeLayout:
    """Build a ThemeLayout that exactly matches the layout.py constants."""
    from src.render import layout as L

    return ThemeLayout(
        canvas_w=L.WIDTH,
        canvas_h=L.HEIGHT,
        header=ComponentRegion(0, L.HEADER_Y, L.WIDTH, L.HEADER_H),
        week_view=ComponentRegion(L.WEEK_X, L.WEEK_Y, L.WEEK_W, L.WEEK_H),
        weather=ComponentRegion(L.WEATHER_X, L.WEATHER_Y, L.WEATHER_W, L.WEATHER_H),
        birthdays=ComponentRegion(L.BIRTHDAY_X, L.BIRTHDAY_Y, L.BIRTHDAY_W, L.BIRTHDAY_H),
        info=ComponentRegion(L.INFO_X, L.INFO_Y, L.INFO_W, L.INFO_H),
    )


def default_theme() -> Theme:
    """Return the default theme.

    Lights up on Inky Spectra 6 (blue section labels, red bullets/glyphs/alerts)
    via accent palette indices; on Waveshare 1-bit, accents fall back to fg so
    the rendering stays monochrome. Tightens section labels from 12pt bold to
    11pt semibold and bumps event spacing from 1.0 to 1.1 for breathing room.
    """
    # Inky Spectra 6 palette indices (mirror of canvas._INKY_* — duplicated here
    # to avoid a circular import; see src/render/canvas.py:43-50).
    inky_red = 3
    inky_blue = 4
    return Theme(
        name="default",
        style=ThemeStyle(
            accent_primary=inky_blue,
            accent_secondary=inky_red,
            accent_alert=inky_red,
            label_font_size=11,
            label_font_weight="semibold",
            spacing_scale=1.1,
        ),
        layout=default_layout(),
    )


def load_theme(name: str) -> Theme:
    """Return a Theme for the given name.

    Raises ``ValueError`` for unknown names.

    Note: ``"random"`` is not handled here — it must be resolved to a concrete
    theme name via ``src.render.random_theme.pick_random_theme`` before calling
    this function (see ``main.py``).
    """
    if name == "default":
        return default_theme()

    if name not in _THEME_REGISTRY:
        raise ValueError(
            f"Unknown theme: {name!r}. Available: {', '.join(sorted(AVAILABLE_THEMES))}"
        )

    module_path, factory_name = _THEME_REGISTRY[name]
    from importlib import import_module

    module = import_module(module_path)
    factory = getattr(module, factory_name)
    return factory()
