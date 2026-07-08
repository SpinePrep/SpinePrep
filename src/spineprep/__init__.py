"""SpinePrep package bootstrap."""
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("spineprep")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "1.0.0"

__all__ = ["policy", "__version__"]
