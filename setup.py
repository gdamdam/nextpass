"""Copy the one editable root catalog into installed package data."""
from pathlib import Path
from shutil import copyfile
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        copyfile(root / 'catalog.json', Path(self.build_lib) / 'nextpass' / 'catalog.json')


setup(cmdclass={'build_py': BuildPy})
