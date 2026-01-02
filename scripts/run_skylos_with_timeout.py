#!/usr/bin/env python3
"""
Wrapper script to run skylos with proper timeout handling for crackerjack.
This script is designed to be called by crackerjack instead of running skylos directly.
"""

import subprocess
import sys


def run_skylos_with_timeout():
    """Run skylos with appropriate timeout and configuration."""
    # Define the exclude folders as per the project configuration
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
        "adapters",  # Exclude external service integration wrappers
    ]
    
    # Build the command
    cmd = ["skylos", "./oneiric", "--json", "--confidence", "86"]
    
    for folder in exclude_folders:
        cmd.extend(["--exclude-folder", folder])
    
    try:
        # Run with 600-second timeout (10 minutes) to match the test timeout
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        # Print stdout and stderr for crackerjack to capture
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        
        # Return the exit code from skylos
        return result.returncode
        
    except subprocess.TimeoutExpired:
        print("skylos timed out after 600 seconds", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error running skylos: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run_skylos_with_timeout())