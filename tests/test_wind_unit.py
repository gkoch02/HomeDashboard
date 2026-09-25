"""``primitives.wind_unit`` — the one rule for labelling a wind speed (#270).

OpenWeatherMap reports wind in m/s for ``metric`` and ``standard`` and in mph
only for ``imperial``. Five panels used to hardcode "mph" while three switched
on ``weather.units`` (two of those treated ``standard`` as mph), so a metric
install read "Wind 12mph" for a 12 m/s wind on the default theme and "12 m/s"
on the wide ones. Every panel now labels through this helper.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.data.models import WeatherData
from src.render.primitives import wind_unit


@pytest.mark.parametrize(
    ("units", "label"),
    [
        ("imperial", "mph"),
        ("metric", "m/s"),
        ("standard", "m/s"),
        (None, "mph"),  # older cache entries never recorded the unit system
        ("kelvin", "mph"),  # unknown → the historical default
    ],
)
def test_wind_unit_follows_the_owm_unit_system(units, label):
    weather = WeatherData(
        current_temp=10.0,
        current_icon="01d",
        current_description="clear",
        high=12.0,
        low=8.0,
        humidity=50,
        units=units,
    )
    assert wind_unit(weather) == label


def test_wind_unit_tolerates_no_weather_and_no_units_attribute():
    assert wind_unit(None) == "mph"
    assert wind_unit(SimpleNamespace()) == "mph"
