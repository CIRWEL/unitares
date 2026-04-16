# Agents Modularization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the three resident agents (Sentinel, Watcher, Vigil) from `scripts/ops/` into self-contained `agents/` packages with shared utilities, so future code-iterating agents have clean module boundaries.

**Architecture:** Each agent becomes its own package under `agents/` with colocated code, config, and tests. Shared patterns (MCP client, log rotation, config) are extracted to `agents/common/`. External references (launchd plists, Claude Code hooks) are updated. `scripts/ops/` keeps non-agent operational scripts.

**Tech Stack:** Python 3.12+, pytest, launchd, Claude Code hooks

---

## File Structure

### New files to create

```
agents/
  __init__.py                    (empty)
  common/
    __init__.py                  (empty)
    config.py                    (PROJECT_ROOT, GOV URLs from env/defaults)
    log.py                       (trim_log extracted from all 3 agents)
    mcp_client.py                (mcp_connect extracted from sentinel + vigil)
  sentinel/
    __init__.py                  (empty)
    tests/
      __init__.py                (empty)
  watcher/
    __init__.py                  (empty)
    tests/
      __init__.py                (empty)
  vigil/
    __init__.py                  (empty)
    tests/
      __init__.py                (empty)
```

### Files to move (git mv)

| From | To |
|------|----|
| `scripts/ops/sentinel_agent.py` | `agents/sentinel/agent.py` |
| `scripts/ops/watcher_agent.py` | `agents/watcher/agent.py` |
| `scripts/ops/watcher_patterns.md` | `agents/watcher/patterns.md` |
| `scripts/ops/heartbeat_agent.py` | `agents/vigil/agent.py` |
| `tests/test_sentinel_cycle_timeout.py` | `agents/sentinel/tests/test_cycle_timeout.py` |
| `tests/test_watcher_agent.py` | `agents/watcher/tests/test_agent.py` |
| `tests/test_heartbeat_groundskeeper.py` | `agents/vigil/tests/test_groundskeeper.py` |
| `tests/test_heartbeat_cycle_timeout.py` | `agents/vigil/tests/test_cycle_timeout.py` |

### Files to modify (not move)

| File | Change |
|------|--------|
| `pyproject.toml` | Add `"agents"` to `testpaths`, add `"--cov=agents"` to addopts |
| `~/Library/LaunchAgents/com.unitares.sentinel.plist` | Update script path |
| `~/Library/LaunchAgents/com.unitares.heartbeat.plist` | Update script path |
| `~/.claude/hooks/watcher-hook.sh` | Update script path |
| `~/.claude/hooks/watcher-surface.sh` | Update script path (if references watcher) |
| `~/.claude/hooks/watcher-chime.sh` | Update script path (if references watcher) |

### Files that stay in `scripts/ops/` (not moving)

Shell scripts (`start_server.sh`, `stop_unitares.sh`, `cleanup_stale.sh`, etc.), plists, `operator_agent.py`, `mcp_agent.py`, `backfill_calibration.py`, `version_manager.py`, and other non-resident-agent operational tools.

---

## Task 1: Create directory structure and common modules

**Files:**
- Create: `agents/__init__.py`, `agents/common/__init__.py`, `agents/common/config.py`, `agents/common/log.py`, `agents/common/mcp_client.py`
- Create: `agents/sentinel/__init__.py`, `agents/sentinel/tests/__init__.py`
- Create: `agents/watcher/__init__.py`, `agents/watcher/tests/__init__.py`
- Create: `agents/vigil/__init__.py`, `agents/vigil/tests/__init__.py`

- [ ] **Step 1: Create all directories and `__init__.py` files**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
mkdir -p agents/common agents/sentinel/tests agents/watcher/tests agents/vigil/tests
touch agents/__init__.py agents/common/__init__.py
touch agents/sentinel/__init__.py agents/sentinel/tests/__init__.py
touch agents/watcher/__init__.py agents/watcher/tests/__init__.py
touch agents/vigil/__init__.py agents/vigil/tests/__init__.py
```

- [ ] **Step 2: Write `agents/common/config.py`**

```python
"""Shared configuration for UNITARES resident agents."""

from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Governance endpoints — override via env vars if needed
GOV_MCP_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8767/mcp/")
GOV_REST_URL = os.getenv("GOV_REST_URL", "http://localhost:8767/v1/tools/call")
GOV_HEALTH_URL = os.getenv("GOV_HEALTH_URL", "http://localhost:8767/health")
GOV_WS_URL = os.getenv("GOV_WS_URL", "ws://localhost:8767/ws/eisv")
```

- [ ] **Step 3: Write `agents/common/log.py`**

```python
"""Shared log rotation for UNITARES resident agents."""

from pathlib import Path


def trim_log(log_file: Path, max_lines: int) -> None:
    """Keep log file bounded to the last *max_lines* lines."""
    if not log_file.exists():
        return
    try:
        lines = log_file.read_text().splitlines()
    except OSError:
        return
    if len(lines) <= max_lines:
        return
    try:
        log_file.write_text("\n".join(lines[-max_lines:]) + "\n")
    except OSError:
        pass
```

- [ ] **Step 4: Write `agents/common/mcp_client.py`**

```python
"""Shared MCP client transport for UNITARES resident agents."""

from contextlib import asynccontextmanager

import httpx


def mcp_connect(url: str):
    """Auto-detect MCP transport: /mcp -> Streamable HTTP, otherwise SSE."""
    if "/mcp" in url:
        from mcp.client.streamable_http import streamable_http_client

        @asynccontextmanager
        async def _connect():
            async with httpx.AsyncClient(http2=False, timeout=30) as http_client:
                async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                    yield read, write

        return _connect()
    else:
        from mcp.client.sse import sse_client

        return sse_client(url)
```

- [ ] **Step 5: Commit**

```bash
git add agents/
git commit -m "feat(agents): create modular directory structure with common utilities"
```

---

## Task 2: Move Sentinel

**Files:**
- Move: `scripts/ops/sentinel_agent.py` -> `agents/sentinel/agent.py`
- Move: `tests/test_sentinel_cycle_timeout.py` -> `agents/sentinel/tests/test_cycle_timeout.py`
- Modify: the moved agent (imports, paths)
- Modify: the moved test (module path)

- [ ] **Step 1: git mv both files**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git mv scripts/ops/sentinel_agent.py agents/sentinel/agent.py
git mv tests/test_sentinel_cycle_timeout.py agents/sentinel/tests/test_cycle_timeout.py
```

- [ ] **Step 2: Update agent imports and path constants**

In `agents/sentinel/agent.py`, replace the sys.path and path constants block.

Find the existing block (around lines 39-59):
```python
# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
```
...
```python
GOVERNANCE_PROJECT = Path("/Users/cirwel/projects/governance-mcp-v1")
SESSION_FILE = GOVERNANCE_PROJECT / ".sentinel_session"
STATE_FILE = GOVERNANCE_PROJECT / ".sentinel_state"
LOG_FILE = Path("/Users/cirwel/Library/Logs/unitares-sentinel.log")
MAX_LOG_LINES = 1000
```

Replace with:
```python
# Add project root to path for agents.common and src imports
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.common.config import GOV_MCP_URL, GOV_HEALTH_URL, GOV_WS_URL
from agents.common.log import trim_log as _trim_log
from agents.common.mcp_client import mcp_connect

SESSION_FILE = PROJECT_ROOT / ".sentinel_session"
STATE_FILE = PROJECT_ROOT / ".sentinel_state"
LOG_FILE = Path.home() / "Library" / "Logs" / "unitares-sentinel.log"
MAX_LOG_LINES = 1000
```

- [ ] **Step 3: Replace the local `_mcp_connect` function**

Delete the `_mcp_connect` function definition (around lines 190-202). Search for all calls to `_mcp_connect(` and replace with `mcp_connect(`.

- [ ] **Step 4: Replace the local `trim_log` function**

Delete the `trim_log` function definition (around lines 139-146). Replace all calls from `trim_log()` to `_trim_log(LOG_FILE, MAX_LOG_LINES)`.

- [ ] **Step 5: Replace hardcoded URL constants**

Replace these constants (keep only those not covered by `agents.common.config`):
- `GOVERNANCE_HEALTH_URL = "http://localhost:8767/health"` -> use `GOV_HEALTH_URL`
- `WEBSOCKET_URL = "ws://localhost:8767/ws/eisv"` -> use `GOV_WS_URL`  
- `MCP_URL = "http://127.0.0.1:8767/mcp/"` -> use `GOV_MCP_URL`

Update the `SentinelAgent.__init__` defaults to reference the common config values:
```python
def __init__(
    self,
    mcp_url: str = GOV_MCP_URL,
    ws_url: str = GOV_WS_URL,
    label: str = "Sentinel",
    analysis_interval: int = ANALYSIS_INTERVAL,
):
```

- [ ] **Step 6: Update the test's module path**

In `agents/sentinel/tests/test_cycle_timeout.py`, find:
```python
module_path = project_root / "scripts" / "ops" / "sentinel_agent.py"
```

Replace with:
```python
module_path = project_root / "agents" / "sentinel" / "agent.py"
```

- [ ] **Step 7: Run sentinel tests**

```bash
python3 -m pytest agents/sentinel/tests/ -v --tb=short
```
Expected: all 3 tests pass.

- [ ] **Step 8: Commit**

```bash
git add agents/sentinel/ scripts/ops/sentinel_agent.py tests/test_sentinel_cycle_timeout.py
git commit -m "refactor: move sentinel agent to agents/sentinel/"
```

---

## Task 3: Move Watcher

**Files:**
- Move: `scripts/ops/watcher_agent.py` -> `agents/watcher/agent.py`
- Move: `scripts/ops/watcher_patterns.md` -> `agents/watcher/patterns.md`
- Move: `tests/test_watcher_agent.py` -> `agents/watcher/tests/test_agent.py`
- Modify: the moved agent (paths)
- Modify: the moved test (module path)

- [ ] **Step 1: git mv all three files**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git mv scripts/ops/watcher_agent.py agents/watcher/agent.py
git mv scripts/ops/watcher_patterns.md agents/watcher/patterns.md
git mv tests/test_watcher_agent.py agents/watcher/tests/test_agent.py
```

- [ ] **Step 2: Update agent path constants**

In `agents/watcher/agent.py`, find:
```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
```

This is still correct (3 levels up from `agents/watcher/agent.py` = project root). Keep it.

Find:
```python
PATTERNS_FILE = PROJECT_ROOT / "scripts" / "ops" / "watcher_patterns.md"
```

Replace with:
```python
PATTERNS_FILE = Path(__file__).resolve().parent / "patterns.md"
```

- [ ] **Step 3: Replace the local `_rotate_log_if_needed` function**

Add import at the top (watcher has NO sys.path manipulation currently, so add it):
```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.common.log import trim_log as _common_trim_log
```

Delete the `_rotate_log_if_needed` function definition (around lines 184-202).

Find all calls to `_rotate_log_if_needed()` and replace with `_common_trim_log(LOG_FILE, MAX_LOG_LINES)`.

- [ ] **Step 4: Update the test's module path**

In `agents/watcher/tests/test_agent.py`, find:
```python
module_path = project_root / "scripts" / "ops" / "watcher_agent.py"
```

Replace with:
```python
module_path = project_root / "agents" / "watcher" / "agent.py"
```

Also update the module name in `spec_from_file_location` if it references `"watcher_agent"` — keep as-is (the name is arbitrary for importlib).

- [ ] **Step 5: Run watcher tests**

```bash
python3 -m pytest agents/watcher/tests/ -v --tb=short
```
Expected: all 68 tests pass.

- [ ] **Step 6: Commit**

```bash
git add agents/watcher/ scripts/ops/watcher_agent.py scripts/ops/watcher_patterns.md tests/test_watcher_agent.py
git commit -m "refactor: move watcher agent to agents/watcher/"
```

---

## Task 4: Move Vigil

**Files:**
- Move: `scripts/ops/heartbeat_agent.py` -> `agents/vigil/agent.py`
- Move: `tests/test_heartbeat_groundskeeper.py` -> `agents/vigil/tests/test_groundskeeper.py`
- Move: `tests/test_heartbeat_cycle_timeout.py` -> `agents/vigil/tests/test_cycle_timeout.py`
- Modify: agent imports and paths
- Modify: both test files

- [ ] **Step 1: git mv all files**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git mv scripts/ops/heartbeat_agent.py agents/vigil/agent.py
git mv tests/test_heartbeat_groundskeeper.py agents/vigil/tests/test_groundskeeper.py
git mv tests/test_heartbeat_cycle_timeout.py agents/vigil/tests/test_cycle_timeout.py
```

- [ ] **Step 2: Update agent imports and path constants**

In `agents/vigil/agent.py`, find the path constants (around lines 47-52):
```python
GOVERNANCE_PROJECT = Path("/Users/cirwel/projects/governance-mcp-v1")
ANIMA_PROJECT = Path("/Users/cirwel/projects/anima-mcp")
SESSION_FILE = GOVERNANCE_PROJECT / ".vigil_session"
STATE_FILE = GOVERNANCE_PROJECT / ".vigil_state"
LOG_FILE = Path("/Users/cirwel/Library/Logs/unitares-heartbeat.log")
MAX_LOG_LINES = 500
```

Replace with:
```python
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.common.config import GOV_MCP_URL
from agents.common.log import trim_log as _trim_log
from agents.common.mcp_client import mcp_connect

ANIMA_PROJECT = Path(os.getenv("ANIMA_PROJECT", str(PROJECT_ROOT.parent / "anima-mcp")))
SESSION_FILE = PROJECT_ROOT / ".vigil_session"
STATE_FILE = PROJECT_ROOT / ".vigil_state"
LOG_FILE = Path.home() / "Library" / "Logs" / "unitares-heartbeat.log"
MAX_LOG_LINES = 500
```

- [ ] **Step 3: Replace local `_mcp_connect` and `trim_log`**

Delete the `_mcp_connect` function definition (around lines 117-130). Replace all calls to `_mcp_connect(` with `mcp_connect(`.

Delete the `trim_log` function definition (around lines 194-202). Replace all calls from `trim_log()` to `_trim_log(LOG_FILE, MAX_LOG_LINES)`.

- [ ] **Step 4: Update `__init__` default for mcp_url**

In `HeartbeatAgent.__init__`, change:
```python
mcp_url: str = "http://127.0.0.1:8767/mcp/",
```
to:
```python
mcp_url: str = GOV_MCP_URL,
```

- [ ] **Step 5: Update test_groundskeeper.py imports**

In `agents/vigil/tests/test_groundskeeper.py`, find:
```python
project_root = Path(__file__).parent.parent
scripts_dir = project_root / "scripts" / "ops"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(scripts_dir))

import heartbeat_agent as _hb_module
from heartbeat_agent import (
```

Replace with:
```python
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Load from new location
agent_dir = project_root / "agents" / "vigil"
sys.path.insert(0, str(agent_dir))

import agent as _hb_module
from agent import (
```

Note: The test imports `HeartbeatAgent`, `_atomic_write`, `_get_anima_urls`, `detect_changes`, `notify` — these are all top-level names in the module file, so importing from `agent` (the filename without .py) works.

**Alternative (safer, preserves module name):** Use importlib like the other tests:
```python
import importlib.util
project_root = Path(__file__).resolve().parent.parent.parent.parent
module_path = project_root / "agents" / "vigil" / "agent.py"
spec = importlib.util.spec_from_file_location("heartbeat_agent", module_path)
assert spec and spec.loader
_hb_module = importlib.util.module_from_spec(spec)
sys.modules["heartbeat_agent"] = _hb_module
spec.loader.exec_module(_hb_module)
from heartbeat_agent import (
    HeartbeatAgent,
    _atomic_write,
    ...
)
```

Use whichever approach minimizes diff. Read the existing test file to decide.

- [ ] **Step 6: Update test_cycle_timeout.py module path**

In `agents/vigil/tests/test_cycle_timeout.py`, find:
```python
HEARTBEAT_PATH = REPO_ROOT / "scripts" / "ops" / "heartbeat_agent.py"
```

Replace with:
```python
HEARTBEAT_PATH = REPO_ROOT / "agents" / "vigil" / "agent.py"
```

Also update `REPO_ROOT` derivation — it's currently `Path(__file__).resolve().parent.parent` (2 levels from `tests/`). Now it needs 4 levels from `agents/vigil/tests/`:
```python
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
```

- [ ] **Step 7: Run vigil tests**

```bash
python3 -m pytest agents/vigil/tests/ -v --tb=short
```
Expected: all tests pass (groundskeeper: ~20, cycle_timeout: ~14).

- [ ] **Step 8: Commit**

```bash
git add agents/vigil/ scripts/ops/heartbeat_agent.py tests/test_heartbeat_groundskeeper.py tests/test_heartbeat_cycle_timeout.py
git commit -m "refactor: move vigil agent to agents/vigil/"
```

---

## Task 5: Update pytest config and external references

**Files:**
- Modify: `pyproject.toml`
- Modify: `~/Library/LaunchAgents/com.unitares.sentinel.plist`
- Modify: `~/Library/LaunchAgents/com.unitares.heartbeat.plist`
- Modify: `~/.claude/hooks/watcher-hook.sh`
- Modify: `~/.claude/hooks/watcher-surface.sh` (if references watcher path)
- Modify: `~/.claude/hooks/watcher-chime.sh` (if references watcher path)

- [ ] **Step 1: Update pyproject.toml**

Find:
```toml
testpaths = ["tests"]
```

Replace with:
```toml
testpaths = ["tests", "agents"]
```

Find:
```toml
"--cov=src",
```

Replace with:
```toml
"--cov=src",
"--cov=agents",
```

- [ ] **Step 2: Update sentinel launchd plist**

Read `~/Library/LaunchAgents/com.unitares.sentinel.plist`. Find the `<string>` containing `scripts/ops/sentinel_agent.py` inside `ProgramArguments`. Replace the path:

```
scripts/ops/sentinel_agent.py -> agents/sentinel/agent.py
```

The full path will be something like:
```xml
<string>/Users/cirwel/projects/governance-mcp-v1/agents/sentinel/agent.py</string>
```

- [ ] **Step 3: Update heartbeat launchd plist**

Same pattern for `~/Library/LaunchAgents/com.unitares.heartbeat.plist`:
```
scripts/ops/heartbeat_agent.py -> agents/vigil/agent.py
```

- [ ] **Step 4: Update Claude Code hooks**

Read each hook file and update the watcher path:

In `~/.claude/hooks/watcher-hook.sh`, find:
```bash
python3 /Users/cirwel/projects/governance-mcp-v1/scripts/ops/watcher_agent.py
```
Replace with:
```bash
python3 /Users/cirwel/projects/governance-mcp-v1/agents/watcher/agent.py
```

Do the same for `watcher-surface.sh` and `watcher-chime.sh` if they contain the old path.

- [ ] **Step 5: Reload launchd services**

```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.sentinel.plist
launchctl load ~/Library/LaunchAgents/com.unitares.sentinel.plist
launchctl unload ~/Library/LaunchAgents/com.unitares.heartbeat.plist
launchctl load ~/Library/LaunchAgents/com.unitares.heartbeat.plist
```

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add pyproject.toml
git commit -m "chore: update pytest config and external references for agents/ layout"
```

Note: launchd plists in `~/Library/LaunchAgents/` and hook scripts in `~/.claude/hooks/` are outside the repo and not committed.

---

## Task 6: Full verification and final commit

- [ ] **Step 1: Run the full test suite**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
python3 -m pytest tests/ agents/ -q --tb=short -x
```

Expected: all tests pass (138+ from `tests/` + agent tests).

- [ ] **Step 2: Verify no broken imports**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
python3 -c "from agents.common.config import PROJECT_ROOT, GOV_MCP_URL; print('config OK')"
python3 -c "from agents.common.log import trim_log; print('log OK')"
python3 -c "from agents.common.mcp_client import mcp_connect; print('mcp_client OK')"
```

- [ ] **Step 3: Verify launchd services are running**

```bash
launchctl list | grep unitares
```

Expected: sentinel and heartbeat entries present.

- [ ] **Step 4: Smoke test — run watcher on a file**

```bash
python3 /Users/cirwel/projects/governance-mcp-v1/agents/watcher/agent.py --file agents/common/config.py
```

Expected: runs without import errors (findings are irrelevant for this test).

- [ ] **Step 5: Verify sentinel can start**

```bash
timeout 10 python3 /Users/cirwel/projects/governance-mcp-v1/agents/sentinel/agent.py --sitrep 2>&1 | head -5
```

Expected: starts without import errors.

---

## Parallelization Notes

Tasks 2, 3, and 4 are fully independent and can be dispatched as parallel subagents. Each touches different files with zero overlap:

| Task | Agent files | Test files |
|------|------------|------------|
| Task 2 (Sentinel) | `sentinel_agent.py` | `test_sentinel_cycle_timeout.py` |
| Task 3 (Watcher) | `watcher_agent.py`, `watcher_patterns.md` | `test_watcher_agent.py` |
| Task 4 (Vigil) | `heartbeat_agent.py` | `test_heartbeat_*.py` |

Task 1 must complete before Tasks 2-4 (they import from `agents.common`).
Task 5 must complete after Tasks 2-4.
Task 6 runs last.

## Follow-up (not in this plan)

- Consider moving `operator_agent.py` and `mcp_agent.py` if they are active agents
- Sentinel's optional `from src.audit_db import query_audit_events_async` — replace with MCP call for full decoupling
- Update CLAUDE.md and MEMORY.md with new agent paths (inform user)
