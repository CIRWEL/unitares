"""S19: enrollment-time path safety checks.

Verifies ``is_path_user_writable`` and ``first_user_writable_ancestor``
correctly identify paths that a same-UID process could replace. Used to
warn operators at enrollment time when binaries live in user-writable
locations.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.substrate.path_safety import (
    first_user_writable_ancestor,
    is_path_user_writable,
)


# -----------------------------------------------------------------------------
# is_path_user_writable
# -----------------------------------------------------------------------------


def test_user_owned_tmp_path_is_writable(tmp_path: Path) -> None:
    """A file under pytest's tmp_path is owned by the test runner."""
    target = tmp_path / "binary"
    target.write_bytes(b"#!/usr/bin/env python3\n")
    assert is_path_user_writable(str(target)) is True


def test_nonexistent_target_walks_to_first_existing_parent(tmp_path: Path) -> None:
    """The check walks from the first existing parent when the target is absent."""
    target = tmp_path / "subdir" / "binary_not_yet_created"
    assert is_path_user_writable(str(target)) is True


def test_relative_path_is_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative paths resolve against cwd before the writability check."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "binary").write_bytes(b"")
    assert is_path_user_writable("./binary") is True


def test_symlink_is_resolved(tmp_path: Path) -> None:
    """Symlinks resolve before the writability check (we attest the real file)."""
    real = tmp_path / "real_binary"
    real.write_bytes(b"")
    link = tmp_path / "link_to_binary"
    link.symlink_to(real)
    assert is_path_user_writable(str(link)) is True


def test_root_owned_path_is_not_writable() -> None:
    """A path entirely under root-owned directories is not user-writable.

    ``/usr/bin/env`` exists on every macOS/Linux deployment and is root-owned;
    not user-writable for non-root users.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root cannot test non-root unwritable path")
    assert is_path_user_writable("/usr/bin/env") is False


def test_nonexistent_root_owned_path_is_not_writable() -> None:
    """When the target doesn't exist but the entire ancestor chain is root-
    owned, the helper still reports unwritable."""
    if os.geteuid() == 0:
        pytest.skip("running as root cannot test non-root unwritable path")
    # /usr/bin/<random-uuid-name> does not exist; /usr/bin and /usr are
    # root-owned; the helper walks to the first existing parent and finds
    # no writable directory.
    assert is_path_user_writable("/usr/bin/this_path_should_never_exist_z19") is False


# -----------------------------------------------------------------------------
# first_user_writable_ancestor
# -----------------------------------------------------------------------------


def test_first_user_writable_ancestor_returns_file_when_file_writable(
    tmp_path: Path,
) -> None:
    """When the file itself is user-writable, the helper returns that path."""
    target = tmp_path / "binary"
    target.write_bytes(b"")
    result = first_user_writable_ancestor(str(target))
    assert result == str(target.resolve())


def test_first_user_writable_ancestor_returns_parent_when_file_absent(
    tmp_path: Path,
) -> None:
    """When the file doesn't exist, returns the deepest writable parent."""
    target = tmp_path / "subdir" / "absent_binary"
    result = first_user_writable_ancestor(str(target))
    # tmp_path is user-owned; subdir doesn't exist, so the deepest existing
    # writable ancestor is tmp_path itself.
    assert result == str(tmp_path.resolve())


def test_first_user_writable_ancestor_none_for_root_owned_path() -> None:
    """No user-writable ancestor → None (signal: deployment is hardened)."""
    if os.geteuid() == 0:
        pytest.skip("running as root cannot test non-root unwritable path")
    assert first_user_writable_ancestor("/usr/bin/env") is None
