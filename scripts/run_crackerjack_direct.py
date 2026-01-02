#!/usr/bin/env python3
"""
Script to run crackerjack with skylos patch applied in the same Python process.
"""

import sys


def main():
    """Apply the skylos patch and run crackerjack from within the same process."""
    # Apply the skylos patch first
    print("Applying skylos patch...")
    
    # Import and run the patch script logic directly
    from scripts.patch_crackerjack_skylos import patch_skylos_command
    
    if not patch_skylos_command():
        print("Failed to apply skylos patch", file=sys.stderr)
        return 1
    
    print("Skylos patch applied successfully.")
    
    # Now run crackerjack directly from Python
    print("Running crackerjack...")
    
    # Import crackerjack and run it
    try:
        from crackerjack.cli import main as crackerjack_main
        # Override sys.argv to simulate command line arguments
        original_argv = sys.argv[:]
        sys.argv = ["crackerjack", "run", "--comp"]
        
        try:
            # Call crackerjack main function directly
            return crackerjack_main()
        finally:
            # Restore original argv
            sys.argv = original_argv
            
    except ImportError as e:
        print(f"Error importing crackerjack: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error running crackerjack: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())