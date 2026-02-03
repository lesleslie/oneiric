#!/usr/bin/env python3

import subprocess
import sys
from pathlib import Path


def run_skylos_on_directory(directory, exclude_folders):
    cmd = ["uv", "run", "skylos", str(directory), "--json", "--confidence", "86"]

    for folder in exclude_folders:
        cmd.extend(["--exclude-folder", folder])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"Error running skylos on {directory}: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"Timeout running skylos on {directory}")
        return False
    except Exception as e:
        print(f"Exception running skylos on {directory}: {e}")
        return False


def main():
    base_dir = Path("oneiric")
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
    ]


    directories = [
        "core",
        "adapters/cache",
        "adapters/database",
        "adapters/dns",
        "adapters/embedding",
        "adapters/file_transfer",
        "adapters/graph",
        "adapters/http",
        "adapters/identity",
        "adapters/llm",
        "adapters/messaging",
        "adapters/monitoring",
        "adapters/nosql",
        "adapters/queue",
        "adapters/secrets",
        "adapters/storage",
        "adapters/vector",
        "actions",
        "domains",
        "remote",
        "runtime",
    ]

    success_count = 0
    total_count = len(directories)

    for directory in directories:
        full_path = base_dir / directory
        if full_path.exists():
            print(f"Running skylos on {directory}...")
            if run_skylos_on_directory(full_path, exclude_folders):
                success_count += 1
                print(f"✓ Completed {directory}")
            else:
                print(f"✗ Failed {directory}")
        else:
            print(f"Skipping {directory} (does not exist)")

    print(
        f"\nCompleted: {success_count}/{total_count} directories successfully analyzed"
    )

    if success_count == total_count:
        print("✓ All directories analyzed successfully")
        return 0
    else:
        print("✗ Some directories failed to analyze")
        return 1


if __name__ == "__main__":
    sys.exit(main())
