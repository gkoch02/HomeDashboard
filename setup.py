"""Include checkout assets in installed distributions without duplicating sources."""

from pathlib import Path
from shutil import copy2, copytree

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithAssets(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        assets = Path(self.build_lib) / "src" / "_assets"
        copytree(root / "fonts", assets / "fonts", dirs_exist_ok=True)
        copytree(root / "assets" / "previews", assets / "assets" / "previews", dirs_exist_ok=True)
        for source in ("config/quotes.json", "assets/moon_full.png", "assets/postcard_photo.jpg"):
            destination = assets / source
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy2(root / source, destination)


setup(cmdclass={"build_py": BuildWithAssets})
