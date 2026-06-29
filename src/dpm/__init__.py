"""DPM — Data Product Manifest toolkit."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dpm")
except PackageNotFoundError:  # package is not installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
