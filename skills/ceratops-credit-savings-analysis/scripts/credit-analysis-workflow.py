#!/usr/bin/env python3
"""Stable entry point for the modular credit-analysis controller."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

_ENTRY_DIR = Path(__file__).resolve().parent
_ENTRY_DIR_TEXT = str(_ENTRY_DIR)
_ADDED_ENTRY_DIR = _ENTRY_DIR_TEXT not in sys.path
if _ADDED_ENTRY_DIR:
    sys.path.insert(0, _ENTRY_DIR_TEXT)
try:
    from credit_analysis import command_line_interface as _command_line_interface
    from credit_analysis import thread_review_orchestration as _thread_review_orchestration
    from credit_analysis import single_surface_analysis as _single_surface_analysis
finally:
    if _ADDED_ENTRY_DIR:
        sys.path.remove(_ENTRY_DIR_TEXT)

_IMPLEMENTATION_MODULES = (
    _single_surface_analysis,
    _thread_review_orchestration,
    _command_line_interface,
)
for _module in _IMPLEMENTATION_MODULES:
    for _name in _module.__all__:
        globals()[_name] = getattr(_module, _name)
main = _command_line_interface.main


class _ForwardingModule(ModuleType):
    """Keep test/runtime patches visible in each defining module."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name.startswith("__"):
            return
        for module in _IMPLEMENTATION_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


_LOADED_MODULE = sys.modules.get(__name__)
if _LOADED_MODULE is not None:
    _LOADED_MODULE.__class__ = _ForwardingModule


if __name__ == "__main__":
    raise SystemExit(main())
