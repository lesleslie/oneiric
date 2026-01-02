#!/usr/bin/env python3
"""Patch crackerjack's complexipy command to respect pyproject.toml configuration.

This script monkey-patches crackerjack's tool_commands to use the max_complexity
value from [tool.complexipy] in pyproject.toml instead of the hardcoded 15.

Usage:
    python -m patch_crackerjack_complexipy
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import tomllib


def patch_complexipy_command():
    """Patch crackerjack's complexipy tool command to use pyproject.toml config."""
    try:
        # Import crackerjack's tool_commands module
        from crackerjack.config import tool_commands

        # Load max_complexity from pyproject.toml
        pyproject_path = project_root / "pyproject.toml"
        if not pyproject_path.exists():
            print("No pyproject.toml found", file=sys.stderr)
            return False

        with pyproject_path.open("rb") as f:
            toml_config = tomllib.load(f)

        max_complexity = toml_config.get("tool", {}).get("complexipy", {}).get("max_complexity", 35)

        # Update the complexipy command in _DEFAULT_COMMANDS
        # The command is at index 4 in the list: ["uv", "run", "complexipy", "--max-complexity-allowed", "15", package_name]
        if "complexipy" in tool_commands._DEFAULT_COMMANDS:
            # Convert tuple to list, modify, and convert back
            cmd_list = list(tool_commands._DEFAULT_COMMANDS["complexipy"])
            cmd_list[4] = str(max_complexity)
            tool_commands._DEFAULT_COMMANDS = dict(tool_commands._DEFAULT_COMMANDS)
            tool_commands._DEFAULT_COMMANDS["complexipy"] = tuple(cmd_list)

            print(f"✅ Patched crackerjack complexipy command to use max_complexity={max_complexity}", file=sys.stderr)
            return True
        else:
            print("complexipy not found in tool commands", file=sys.stderr)
            return False

    except Exception as e:
        print(f"Failed to patch complexipy command: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = patch_complexipy_command()
    sys.exit(0 if success else 1)
