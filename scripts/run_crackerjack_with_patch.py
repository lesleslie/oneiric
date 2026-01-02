#!/usr/bin/env python3
"""
Wrapper script to run crackerjack with skylos patch applied.
This ensures the skylos command uses the correct configuration and timeout.
"""

import os
import subprocess
import sys
from pathlib import Path


def main():
    """Apply the skylos patch and run crackerjack."""
    # First, apply the skylos patch
    patch_script = Path("scripts/patch_crackerjack_skylos.py")
    if not patch_script.exists():
        print(f"Error: Patch script {patch_script} not found", file=sys.stderr)
        return 1

    # Run the patch script
    print("Applying skylos patch...")
    result = subprocess.run([sys.executable, str(patch_script)],
                           capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error applying patch: {result.stderr}", file=sys.stderr)
        return result.returncode

    print("Patch applied successfully.")

    # Now run crackerjack
    print("Running crackerjack...")
    cmd = [sys.executable, "-m", "crackerjack", "run", "--comp"]

    # Set environment to allow longer timeouts
    env = os.environ.copy()
    # Note: crackerjack may have its own timeout mechanisms that we can't control from here

    try:
        # Use a longer timeout for the entire crackerjack process
        result = subprocess.run(cmd, env=env, timeout=1200)  # 20 minutes timeout
        return result.returncode
    except subprocess.TimeoutExpired:
        print("crackerjack timed out after 20 minutes", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
