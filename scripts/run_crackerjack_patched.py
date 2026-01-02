#!/usr/bin/env python3
"""
Script to run crackerjack with skylos patch in a single command.
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Create a temporary script that applies patch and runs crackerjack."""
    # Create a temporary Python script that applies the patch and runs crackerjack
    script_content = '''
import sys
# Apply the patch first
from scripts.patch_crackerjack_skylos import patch_skylos_command

if not patch_skylos_command():
    print("Failed to apply skylos patch", file=sys.stderr)
    sys.exit(1)

print("Skylos patch applied successfully.")

# Now run crackerjack
from crackerjack.cli import main
sys.argv = ["crackerjack", "run", "--comp"]
main()
'''

    # Write the script to a temporary file
    temp_script_path = Path("temp_crackerjack_runner.py")
    with open(temp_script_path, "w") as f:
        f.write(script_content)

    try:
        # Run the temporary script with a long timeout
        result = subprocess.run([sys.executable, str(temp_script_path)], timeout=1200)
        return result.returncode
    except subprocess.TimeoutExpired:
        print("crackerjack timed out after 20 minutes", file=sys.stderr)
        return 1
    finally:
        # Clean up the temporary script
        if temp_script_path.exists():
            temp_script_path.unlink()


if __name__ == "__main__":
    sys.exit(main())
