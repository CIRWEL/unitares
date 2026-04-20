"""Deprecated shim — use scripts/ops/version_manager.py.

Kept so cached invocations don't silently fail. Re-exports the canonical
module and forwards CLI invocations to it.
"""
import runpy
import sys
from pathlib import Path

_OPS_PATH = Path(__file__).resolve().parent.parent / "ops" / "version_manager.py"

if __name__ == "__main__":
    print(
        "[deprecated] scripts/dev/version_manager.py → use scripts/ops/version_manager.py",
        file=sys.stderr,
    )
    runpy.run_path(str(_OPS_PATH), run_name="__main__")
