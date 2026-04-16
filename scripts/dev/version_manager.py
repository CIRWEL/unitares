"""
Version management utility for CI validation.

Usage:
    python scripts/version_manager.py          # Print current version
    python scripts/version_manager.py --check  # Validate version consistency
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_version():
    version_file = os.path.join(PROJECT_ROOT, "VERSION")
    if not os.path.exists(version_file):
        return None
    with open(version_file) as f:
        return f.read().strip()

def check():
    version = get_version()
    if not version:
        print("ERROR: VERSION file not found")
        sys.exit(1)

    # Basic format check
    parts = version.split(".")
    if len(parts) < 2:
        print(f"ERROR: Invalid version format: {version}")
        sys.exit(1)

    print(f"Current version: {version}")
    print("Version check passed")

def main():
    if "--check" in sys.argv:
        check()
    else:
        version = get_version()
        print(f"Current version: {version or 'unknown'}")

if __name__ == "__main__":
    main()
