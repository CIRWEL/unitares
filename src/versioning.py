"""
Version loading utilities.

Keeps all VERSION file fallback behavior in one module so server entrypoints
cannot drift independently.
"""

from pathlib import Path


DEFAULT_VERSION_FALLBACK = "0.0.0"


def load_version_from_file(project_root: Path) -> str:
    """Load version from project VERSION file, with centralized fallback."""
    version_file = project_root / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return DEFAULT_VERSION_FALLBACK
