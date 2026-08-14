from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any

import pytest


@pytest.fixture(scope="session")
def test_runner_module() -> Any:
    """Load the hyphenated repository runner as one shared infrastructure module."""

    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "scripts" / "run-tests.py"
    spec = importlib.util.spec_from_file_location("repository_test_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
