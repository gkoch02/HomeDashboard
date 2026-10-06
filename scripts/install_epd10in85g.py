#!/usr/bin/env python3
"""Add the Waveshare 10.85" (G) driver to the installed ``waveshare_epd`` package.

The panel's driver is not part of the vendor library; it ships as demo code in
``E-paper_Separate_Program/10.85inch_e-Paper_G/RaspberryPi/python/lib`` with its
own ``epdconfig`` (two chip selects, driven through a prebuilt ``DEV_Config``
shared object). That ``epdconfig`` cannot replace the library's, so it is
installed beside it as ``epdconfig_10in85g`` and the driver's one top-level
``import epdconfig`` is rewritten to the package-relative import. Everything
else is copied unchanged.

Run with the venv's interpreter, after the vendor library is installed::

    venv/bin/python scripts/install_epd10in85g.py <vendor lib dir>

``make install-waveshare-driver`` does this from the pinned commit.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

DRIVER = "epd10in85g.py"
CONFIG = "epdconfig.py"
INSTALLED_CONFIG = "epdconfig_10in85g.py"
VENDOR_IMPORT = re.compile(r"^import epdconfig[ \t]*$", re.MULTILINE)
PACKAGE_IMPORT = "from . import epdconfig_10in85g as epdconfig"


class InstallError(RuntimeError):
    """The vendor files are not the shape this installer knows how to adapt."""


def adapt_driver(source: str) -> str:
    """Point the vendor driver at ``epdconfig_10in85g`` inside the package."""
    adapted, count = VENDOR_IMPORT.subn(PACKAGE_IMPORT, source)
    if count != 1:
        raise InstallError(
            f"expected one 'import epdconfig' line in {DRIVER}, found {count}; "
            "the vendor driver changed, so check it before installing"
        )
    return adapted


def install(vendor_lib: Path, package_dir: Path) -> list[Path]:
    """Copy the driver, its config and its shared objects; return what was written."""
    libraries = sorted(vendor_lib.glob("DEV_Config_*.so"))
    for name in (DRIVER, CONFIG):
        if not (vendor_lib / name).is_file():
            raise InstallError(f"{vendor_lib} has no {name}")
    if not libraries:
        raise InstallError(f"{vendor_lib} has no DEV_Config_*.so")

    driver = package_dir / DRIVER
    driver.write_text(adapt_driver((vendor_lib / DRIVER).read_text()))
    config = package_dir / INSTALLED_CONFIG
    shutil.copyfile(vendor_lib / CONFIG, config)
    written = [driver, config]
    for library in libraries:
        written.append(Path(shutil.copy2(library, package_dir / library.name)))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("vendor_lib", type=Path, help="the demo code's python/lib directory")
    args = parser.parse_args(argv)

    import waveshare_epd

    package_dir = Path(waveshare_epd.__file__).parent
    try:
        written = install(args.vendor_lib, package_dir)
    except InstallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f'  Waveshare 10.85" (G): {len(written)} files into {package_dir}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
