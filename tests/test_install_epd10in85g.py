"""``scripts/install_epd10in85g.py``: the 10.85" (G) demo driver into ``waveshare_epd``."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_epd10in85g.py"

VENDOR_DRIVER = """import time
import epdconfig

import PIL

EPD_WIDTH       = 1360//2

class EPD():
    def Init(self):
        epdconfig.module_init()
"""


def _load():
    spec = importlib.util.spec_from_file_location("_install_epd10in85g_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = _load()


@pytest.fixture
def vendor(tmp_path):
    lib = tmp_path / "vendor"
    lib.mkdir()
    (lib / "epd10in85g.py").write_text(VENDOR_DRIVER)
    (lib / "epdconfig.py").write_text("EPD_CS_S_PIN = 7\n")
    for name in ("DEV_Config_64_b.so", "DEV_Config_64_w.so"):
        (lib / name).write_bytes(b"\x7fELF")
    package = tmp_path / "waveshare_epd"
    package.mkdir()
    (package / "epdconfig.py").write_text("# the library's own config\n")
    return lib, package


def test_driver_imports_its_own_config_from_the_package(vendor):
    lib, package = vendor
    installer.install(lib, package)

    driver = (package / "epd10in85g.py").read_text()
    assert "from . import epdconfig_10in85g as epdconfig" in driver
    assert "\nimport epdconfig\n" not in driver
    assert driver.replace(installer.PACKAGE_IMPORT, "import epdconfig") == VENDOR_DRIVER


def test_config_and_shared_objects_sit_beside_the_library(vendor):
    lib, package = vendor
    installer.install(lib, package)

    assert (package / "epdconfig_10in85g.py").read_text() == "EPD_CS_S_PIN = 7\n"
    assert (package / "epdconfig.py").read_text() == "# the library's own config\n"
    assert (package / "DEV_Config_64_b.so").read_bytes() == b"\x7fELF"
    assert (package / "DEV_Config_64_w.so").is_file()


@pytest.mark.parametrize(
    "source",
    [VENDOR_DRIVER.replace("import epdconfig\n", ""), VENDOR_DRIVER + "import epdconfig\n"],
    ids=["no-import", "two-imports"],
)
def test_an_unrecognised_driver_is_refused(vendor, source):
    lib, package = vendor
    (lib / "epd10in85g.py").write_text(source)
    with pytest.raises(installer.InstallError, match="import epdconfig"):
        installer.install(lib, package)
    assert not (package / "epd10in85g.py").exists()


def test_missing_shared_objects_are_refused(vendor):
    lib, package = vendor
    for so in lib.glob("*.so"):
        so.unlink()
    with pytest.raises(installer.InstallError, match="DEV_Config"):
        installer.install(lib, package)
