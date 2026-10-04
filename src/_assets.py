"""Locate bundled assets in a checkout or an installed wheel."""

from pathlib import Path


def asset_root() -> Path:
    package = Path(__file__).resolve().parent
    bundled = package / "_assets"
    return bundled if bundled.is_dir() else package.parent
