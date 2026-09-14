"""Deterministic local tool deployment; source stays in the owning repository."""

from importlib.metadata import PackageNotFoundError, version

TOOL_NAME = "ceratops_tool_manager"
try:
    __version__ = version(TOOL_NAME)
except PackageNotFoundError:
    __version__ = "source"
