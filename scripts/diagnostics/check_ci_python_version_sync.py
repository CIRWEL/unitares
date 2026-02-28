#!/usr/bin/env python3
"""
Validate Python version sync between pyproject and CI workflow matrix.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
TEST_WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "tests.yml"


def _parse_version_tuple(version_text: str) -> tuple[int, int]:
    major_text, minor_text = version_text.split(".", 1)
    return int(major_text), int(minor_text)


def _read_requires_python() -> tuple[int, int]:
    pyproject_data = tomllib.loads(PYPROJECT_PATH.read_text())
    requires_python = pyproject_data["project"]["requires-python"].strip()

    match = re.match(r"^>=\s*(\d+\.\d+)$", requires_python)
    if not match:
        raise ValueError(
            f"Unsupported requires-python format: {requires_python!r} "
            "(expected exact form like '>=3.12')"
        )
    return _parse_version_tuple(match.group(1))


def _read_ci_matrix_versions() -> list[tuple[int, int]]:
    workflow_text = TEST_WORKFLOW_PATH.read_text()
    match = re.search(r"python-version:\s*\[([^\]]+)\]", workflow_text)
    if not match:
        raise ValueError("Could not find python-version matrix in tests.yml")

    raw_entries = [entry.strip().strip("'\"") for entry in match.group(1).split(",")]
    versions: list[tuple[int, int]] = []
    for entry in raw_entries:
        if not re.match(r"^\d+\.\d+$", entry):
            raise ValueError(f"Unsupported matrix version format: {entry!r}")
        versions.append(_parse_version_tuple(entry))
    return versions


def main() -> int:
    required_min = _read_requires_python()
    ci_versions = _read_ci_matrix_versions()

    too_low = [v for v in ci_versions if v < required_min]
    if too_low:
        print(
            "❌ CI matrix includes versions lower than requires-python: "
            f"{too_low} < {required_min}"
        )
        return 1

    if required_min not in ci_versions:
        print(
            "❌ CI matrix must include minimum supported version from pyproject: "
            f"{required_min}"
        )
        return 1

    rendered = ", ".join(f"{major}.{minor}" for major, minor in ci_versions)
    print(
        "✅ CI Python matrix matches project requirement: "
        f">={required_min[0]}.{required_min[1]} with [{rendered}]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
