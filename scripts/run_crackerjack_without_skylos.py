#!/usr/bin/env python3
"""
Script to run crackerjack with skylos handled separately to avoid timeout issues.
"""

import subprocess
import sys
from pathlib import Path


def run_crackerjack_without_skylos():
    """Run crackerjack with a temporary configuration that excludes skylos."""
    # Read the original pyproject.toml
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        print("pyproject.toml not found", file=sys.stderr)
        return 1

    with open(pyproject_path) as f:
        original_content = f.read()

    try:
        # Create a modified version without skylos in comprehensive_hooks
        # Find the comprehensive_hooks section and remove "skylos" from it
        import re
        # Pattern to match the comprehensive_hooks list and remove "skylos"
        pattern = r'(comprehensive_hooks = \[)([^\]]*?)("skylos",?)([^\]]*?\])'
        modified_content = re.sub(pattern, r'\1\2\4', original_content)

        # Remove any double commas that might result from removing skylos
        modified_content = re.sub(r',\s*,', ',', modified_content)

        # Write the modified content temporarily
        with open(pyproject_path, 'w') as f:
            f.write(modified_content)

        print("Running crackerjack without skylos...")
        result = subprocess.run([sys.executable, "-m", "crackerjack", "run", "--comp"])

        if result.returncode != 0:
            print("❌ Crackerjack (without skylos) failed")
            return result.returncode
        else:
            print("✅ Crackerjack (without skylos) completed successfully")

        # Now run skylos separately using the batching script
        print("Running skylos using batching approach...")
        batching_script = Path("scripts/run_skylos_batched.py")
        if batching_script.exists():
            result = subprocess.run([sys.executable, str(batching_script)])
            if result.returncode != 0:
                print("❌ skylos batching failed")
                return result.returncode
            else:
                print("✅ skylos batching completed successfully")
        else:
            print("❌ skylos batching script not found")
            return 1

        print("\n✅ All quality checks completed successfully!")
        return 0

    finally:
        # Restore the original content
        with open(pyproject_path, 'w') as f:
            f.write(original_content)
        print("✅ Original pyproject.toml restored")


def main():
    """Main entry point."""
    return run_crackerjack_without_skylos()


if __name__ == "__main__":
    sys.exit(main())
