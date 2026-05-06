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

# Spectra-6 palette indices. Mirrored in ``src.render.canvas`` (kept here so
# theme modules can name their inky palette without importing canvas, which
# would create a cycle).
INKY_BLACK = 0
INKY_WHITE = 1
INKY_YELLOW = 2
INKY_RED = 3
INKY_BLUE = 4
INKY_GREEN = 5

# Default key-color pair used by themes that don't declare one explicitly.
_DEFAULT_INKY_PALETTE: tuple[int, int] = (INKY_BLUE, INKY_RED)


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
    # Used by the ``light_cycle`` theme for the full-canvas radial 24-hour clock.
    light_cycle: ComponentRegion = field(
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

    # Inky Spectra-6 (primary, secondary) palette index pair used to fill
    # ``accent_primary`` / ``accent_secondary`` when the inky backend is
    # active and the theme didn't supply explicit accent values. ``None``
    # falls back to ``(INKY_BLUE, INKY_RED)``. See palette index constants
    # exported above.
    inky_palette: tuple[int, int] | None = None

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
# Theme registry — derived from src.render.themes.registry, populated as a
# side effect of importing each theme module. The package
# `src.render.themes.__init__` triggers all the imports.
# ---------------------------------------------------------------------------


def _ensure_themes_imported() -> None:
    """Import the themes package so each theme module's registration runs.

    Done lazily so the dataclasses defined in this module are fully
    constructed by the time a theme module imports ``Theme`` /
    ``ThemeStyle`` / ``ThemeLayout`` from us.
    """
    import src.render.themes  # noqa: F401  side-effect imports populate registry


def _theme_registry() -> dict[str, Callable[[], Theme]]:
    _ensure_themes_imported()
    from src.render.themes.registry import _REGISTRY

    return _REGISTRY


class _ThemeRegistryView(dict):
    """Read-through proxy preserving the legacy ``_THEME_REGISTRY`` dict API.

    Existing tests do ``set(_THEME_REGISTRY.keys())`` and similar; we keep a
    dict-shaped view rather than break those callers. Values are now the
    factory callables themselves; the legacy ``(module_path, attr)`` tuples
    are no longer used by ``load_theme`` and were never read by tests.
    """

    def __getitem__(self, key):  # noqa: D401
        return _theme_registry()[key]

    def __iter__(self):
        return iter(_theme_registry())

    def __len__(self):
        return len(_theme_registry())

    def __contains__(self, key):
        return key in _theme_registry()

    def keys(self):
        return _theme_registry().keys()

    def values(self):
        return _theme_registry().values()

    def items(self):
        return _theme_registry().items()

    def get(self, key, default=None):
        return _theme_registry().get(key, default)

    # Mutating dict methods are explicit failures rather than silent operations
    # on the empty parent ``dict``. New themes register themselves via
    # ``src.render.themes.registry.register_theme``; no caller should be poking
    # at this proxy directly.
    def _readonly(self, *_args, **_kwargs):
        raise TypeError(
            "_THEME_REGISTRY is a read-through proxy; register themes via "
            "src.render.themes.registry.register_theme(...)"
        )

    __setitem__ = _readonly
    __delitem__ = _readonly
    pop = _readonly
    popitem = _readonly
    setdefault = _readonly
    update = _readonly
    clear = _readonly


_THEME_REGISTRY: _ThemeRegistryView = _ThemeRegistryView()


class _AvailableThemesView:
    """Read-through proxy for the legacy ``AVAILABLE_THEMES`` frozenset.

    Module-import-time consumers (``src.cli`` builds argparse choices) need a
    live view of the registry, since theme modules register themselves only
    after the package is imported.
    """

    def _set(self) -> frozenset[str]:
        _ensure_themes_imported()
        from src.render.themes.registry import available_themes

        return available_themes()

    def __iter__(self):
        return iter(self._set())

    def __contains__(self, item):
        return item in self._set()

    def __len__(self):
        return len(self._set())

    def __sub__(self, other):
        return self._set() - other

    def __or__(self, other):
        return self._set() | other

    def __and__(self, other):
        return self._set() & other

    def __eq__(self, other):
        return self._set() == other

    def __hash__(self):
        return hash(self._set())

    def __repr__(self):
        return repr(self._set())


AVAILABLE_THEMES: _AvailableThemesView = _AvailableThemesView()


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
    return Theme(
        name="default",
        style=ThemeStyle(
            accent_primary=INKY_BLUE,
            accent_secondary=INKY_RED,
            accent_alert=INKY_RED,
            inky_palette=(INKY_BLUE, INKY_RED),
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

    _ensure_themes_imported()
    from src.render.themes.registry import get_theme_factory

    factory = get_theme_factory(name)
    if factory is None:
        raise ValueError(
            f"Unknown theme: {name!r}. Available: {', '.join(sorted(AVAILABLE_THEMES))}"
        )
    return factory()
