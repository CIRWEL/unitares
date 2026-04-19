"""scripts/client/session_cache.py writes 0600.

Guards against Path.write_text regression — that helper inherits umask 022,
producing 0644 files which are readable by any same-UID process. The cache
carries continuity tokens, so 0644 was an impersonation-by-file-read vector.
"""

from __future__ import annotations

import importlib.util
import os
import stat as _stat
from pathlib import Path


def _load_session_cache_module():
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "client" / "session_cache.py"
    spec = importlib.util.spec_from_file_location("client_session_cache", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_write_json_produces_mode_0600(tmp_path):
    sc = _load_session_cache_module()
    path = tmp_path / "session.json"
    sc._write_json(path, {"continuity_token": "secret"})
    assert _stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_write_json_overwrite_tightens_loose_mode(tmp_path):
    """Overwriting a pre-existing 0644 cache file drops it to 0600 —
    old loose permissions must not leak through."""
    sc = _load_session_cache_module()
    path = tmp_path / "session.json"
    path.write_text('{"old": "data"}')
    os.chmod(path, 0o644)

    sc._write_json(path, {"continuity_token": "secret"})
    assert _stat.S_IMODE(os.stat(path).st_mode) == 0o600
