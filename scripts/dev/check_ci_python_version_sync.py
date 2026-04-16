"""
Validate that CI Python version matches project requirements.

Checks .python-version (if present) against the running Python version
to catch CI/local version mismatches early.
"""
import sys
import os

def main():
    print(f"Running Python {sys.version}")

    # Check .python-version if it exists
    python_version_file = os.path.join(os.path.dirname(__file__), "..", ".python-version")
    if os.path.exists(python_version_file):
        with open(python_version_file) as f:
            expected = f.read().strip()
        actual = f"{sys.version_info.major}.{sys.version_info.minor}"
        if not expected.startswith(actual):
            print(f"WARNING: .python-version says {expected}, running {actual}")
            # Warning only — don't fail CI for minor version differences

    # Verify minimum version
    if sys.version_info < (3, 10):
        print(f"ERROR: Python 3.10+ required, got {sys.version}")
        sys.exit(1)

    print("Python version check passed")

if __name__ == "__main__":
    main()
