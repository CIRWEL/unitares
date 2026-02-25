"""Version consistency guardrails."""

from scripts.version_manager import (
    PROJECT_ROOT,
    VERSION_REFERENCES,
    check_file_versions,
    get_version,
)


def test_all_version_references_match_version_file():
    """All configured version references should match VERSION."""
    expected_version = get_version()
    mismatches = []

    for relative_path, patterns in VERSION_REFERENCES:
        mismatches.extend(
            check_file_versions(PROJECT_ROOT / relative_path, patterns, expected_version)
        )

    assert mismatches == [], f"Version mismatches found: {mismatches}"
