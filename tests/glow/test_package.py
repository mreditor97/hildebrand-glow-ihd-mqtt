"""Tests that the glow package stays independent of Home Assistant."""

import ast
from pathlib import Path

from custom_components.hildebrand_glow_ihd import glow

GLOW_DIR = Path(glow.__file__).parent


def test_glow_has_no_homeassistant_imports() -> None:
    """The glow package must not import Home Assistant."""
    for path in GLOW_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            assert not any(
                name == "homeassistant" or name.startswith("homeassistant.")
                for name in names
            ), f"{path.name} imports {names}"
