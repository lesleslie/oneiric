#!/usr/bin/env python3
"""
Script to run comprehensive quality checks with special handling for skylos.
This script runs all crackerjack checks except skylos, then runs skylos separately
using the batching approach to avoid timeout issues.
"""

import subprocess
import sys
from pathlib import Path


def run_quality_checks():
    """Run quality checks, handling skylos separately to avoid timeouts."""
    print("Running comprehensive quality checks...")
    
    # First, run all crackerjack checks except skylos
    # We'll do this by running crackerjack with a modified configuration
    # that excludes skylos, then run skylos separately
    
    print("Running crackerjack checks (excluding skylos)...")
    
    # Temporarily modify the comprehensive hooks to exclude skylos
    # by running individual tools
    tools_to_run = [
        "zuban", "pyscn", "gitleaks", "semgrep", "pip-audit", 
        "refurb", "creosote", "complexipy", "check-jsonschema", "linkcheckmd"
    ]
    
    all_passed = True
    
    for tool in tools_to_run:
        print(f"Running {tool}...")
        result = subprocess.run([sys.executable, "-m", "crackerjack", "run", tool])
        if result.returncode != 0:
            print(f"❌ {tool} failed")
            all_passed = False
        else:
            print(f"✅ {tool} passed")
    
    # Now run skylos using the batching script which handles timeouts better
    print("Running skylos using batching approach...")
    batching_script = Path("scripts/run_skylos_batched.py")
    if batching_script.exists():
        result = subprocess.run([sys.executable, str(batching_script)])
        if result.returncode != 0:
            print("❌ skylos batching failed")
            all_passed = False
        else:
            print("✅ skylos batching completed successfully")
    else:
        print("❌ skylos batching script not found")
        all_passed = False
    
    if all_passed:
        print("\n✅ All quality checks passed!")
        return 0
    else:
        print("\n❌ Some quality checks failed!")
        return 1


def main():
    """Main entry point."""
    return run_quality_checks()


if __name__ == "__main__":
    sys.exit(main())