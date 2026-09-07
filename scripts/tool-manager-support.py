"""Source-maintenance imports; installed agents use the installed CLI or MCP.

This module contains no deployment implementation. First-install maintenance
imports the same packaged engine from its authoritative editable source.
"""

import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "tools" / "ceratops_tool_manager"
sys.path.insert(0, str(SOURCE.parent))
