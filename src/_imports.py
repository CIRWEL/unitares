"""
Centralized import path setup.

This module ensures the project root is in sys.path for proper imports.
All modules should import this before importing project modules.

Usage:
    from src._imports import ensure_project_root
    ensure_project_root()
    
    # Now imports work:
    from governance_core import ...
    from config import ...
"""

import sys
from pathlib import Path

# Cache the project root to avoid repeated path operations
_project_root: Path | None = None


def ensure_project_root() -> Path:
    """
    Ensure project root is in sys.path for imports.
    
    Returns:
        Path to project root
    """
    global _project_root
    
    if _project_root is None:
        # Find project root (parent of src/)
        current_file = Path(__file__).resolve()
        _project_root = current_file.parent.parent
    
    project_root_str = str(_project_root)
    
    # Only add if not already present (avoid duplicates)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    
    return _project_root


def get_project_root() -> Path:
    """Get project root path (cached)."""
    if _project_root is None:
        ensure_project_root()
    return _project_root



