#!/usr/bin/env python3
"""Patch crackerjack's skylos command to use project-specific exclusions.

Crackerjack's default skylos invocation can be too broad (slow) and time out.
We patch the internal command list to pass the exclusion list + confidence
threshold defined in this repo.
"""

from __future__ import annotations

import sys


def patch_skylos_command() -> bool:
    """Patch crackerjack's skylos tool command to use repo exclude folders."""
    try:
        from crackerjack.config import tool_commands

        if "skylos" not in tool_commands._DEFAULT_COMMANDS:
            print("skylos not found in tool commands", file=sys.stderr)
            return False

        original_cmd = list(tool_commands._DEFAULT_COMMANDS["skylos"])
        print(f"Original skylos command: {original_cmd}", file=sys.stderr)

        exclude_folders = [
            ".venv",
            ".git",
            "__pycache__",
            "build",
            "dist",
            ".tox",
            ".mypy_cache",
            "htmlcov",
            ".pytest_cache",
            "tests",
            "adapters",
        ]

        confidence_threshold = 86

        # Preserve the existing target path if present.
        target = "./oneiric"
        for token in reversed(original_cmd):
            if token.endswith("oneiric"):
                target = token
                break

        new_cmd = ["uv", "run", "skylos", "--confidence", str(confidence_threshold)]
        for folder in exclude_folders:
            new_cmd.extend(["--exclude-folder", folder])
        new_cmd.append(target)

        tool_commands._DEFAULT_COMMANDS = dict(tool_commands._DEFAULT_COMMANDS)
        tool_commands._DEFAULT_COMMANDS["skylos"] = tuple(new_cmd)

        print(
            "✅ Patched crackerjack skylos command to include exclude folders",
            file=sys.stderr,
        )
        print(f"New skylos command: {tool_commands._DEFAULT_COMMANDS['skylos']}", file=sys.stderr)
        return True

    except Exception as e:
        print(f"Failed to patch skylos command: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = patch_skylos_command()
    sys.exit(0 if success else 1)
