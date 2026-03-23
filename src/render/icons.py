from PIL import ImageDraw
from src.render.fonts import weather_icon

# OpenWeatherMap icon code -> Weather Icons font glyph
# See: https://erikflowers.github.io/weather-icons/api-list.html
OWM_ICON_MAP = {
    # Day icons
    "01d": "\uf00d",  # clear sky
    "02d": "\uf002",  # few clouds
    "03d": "\uf041",  # scattered clouds
    "04d": "\uf013",  # broken clouds
    "09d": "\uf009",  # shower rain
    "10d": "\uf008",  # rain
    "11d": "\uf010",  # thunderstorm
    "13d": "\uf00a",  # snow
    "50d": "\uf003",  # mist
    # Night icons
    "01n": "\uf02e",  # clear sky night
    "02n": "\uf086",  # few clouds night
    "03n": "\uf041",  # scattered clouds
    "04n": "\uf013",  # broken clouds
    "09n": "\uf009",  # shower rain
    "10n": "\uf028",  # rain night
    "11n": "\uf010",  # thunderstorm
    "13n": "\uf00a",  # snow
    "50n": "\uf003",  # mist
}

FALLBACK_ICON = "\uf07b"  # N/A


def draw_weather_icon(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    owm_icon_code: str,
    size: int = 48,
    fill: int = 0,
):
    font = weather_icon(size)
    glyph = OWM_ICON_MAP.get(owm_icon_code, FALLBACK_ICON)
    draw.text(xy, glyph, font=font, fill=fill)
