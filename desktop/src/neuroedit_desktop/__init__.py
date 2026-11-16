"""NeuroEdit desktop application package."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib

try:
    __version__ = version("neuroedit-desktop")
except PackageNotFoundError:
    # An uninstalled source checkout can still run with PYTHONPATH=src.
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    __version__ = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]

__all__: list[str] = ["__version__"]
