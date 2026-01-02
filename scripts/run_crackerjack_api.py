#!/usr/bin/env python3
"""
Script to run crackerjack quality checks with skylos patch applied in the same Python process.
"""

import os
import sys


def main():
    """Apply the patch and run crackerjack using subprocess to ensure patched settings are used."""
    # Add the current directory to the Python path to import scripts
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Apply the patch first
    from patch_crackerjack_skylos import patch_skylos_command

    if not patch_skylos_command():
        print("Failed to apply skylos patch", file=sys.stderr)
        return 1

    print("Skylos patch applied successfully.")

    # Now run crackerjack with a longer timeout
    import subprocess
    try:
        # Use a longer timeout for the entire crackerjack process
        result = subprocess.run([
            sys.executable, "-m", "crackerjack", "run", "--comp"
        ], timeout=1200)  # 20 minutes timeout
        return result.returncode
    except subprocess.TimeoutExpired:
        print("crackerjack timed out after 20 minutes", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
