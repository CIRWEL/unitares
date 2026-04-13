# unitares_sdk — Agent SDK for UNITARES Governance

**Date:** 2026-04-13
**Status:** Draft
**Scope:** Phase 1 of UNITARES refactoring — extract agent-facing modules into a standalone, pip-installable SDK

## Problem

The three resident agents (vigil, sentinel, watcher) each implement their own governance communication layer. This means:

- ~200 LOC of identical boilerplate duplicated across vigil and sentinel (call_tool, session injection, response parsing, identity extraction, persistence, notifications)
- Magic string tool names with unvalidated dict arguments — no type safety, no discoverability
- New agents must copy-paste and adapt from existing agents, inheriting their quirks
- External consumers have no clean entry point for talking to governance

## Goals

1. A standalone Python package (`unitares_sdk`) that any agent can `pip install` to talk to UNITARES governance
2. Two clean layers: a low-level client for scripts/tools, and an opinionated base class for long-running agents
3. Zero imports from `src/` — communicates with governance exclusively over MCP (HTTP) and REST
4. Designed for extraction: lives in-repo at `agents/sdk/` now, moves to its own repo later

## Non-Goals

- Replacing or modifying the governance server itself
- Splitting the god modules in `src/` (Phase 2, separate effort)
- WebSocket fleet monitoring (sentinel-specific, not general SDK concern — sentinel will continue to manage its own `/ws/eisv` connection)

## Package Structure

```
agents/sdk/
├── pyproject.toml
├── src/
│   └── unitares_sdk/
│       ├── __init__.py          # re-exports public API
│       ├── client.py            # GovernanceClient (async)
│       ├── sync_client.py       # SyncGovernanceClient (sync)
│       ├── agent.py             # GovernanceAgent base class
│       ├── models.py            # Pydantic response models
│       ├── errors.py            # Error hierarchy
│       └── utils.py             # Shared utilities
└── tests/
    ├── test_client.py
    ├── test_sync_client.py
    ├── test_agent.py
    └── test_utils.py
```

**Dependencies:** `httpx`, `mcp` (for streamable HTTP transport), `pydantic` (v2).

## Layer 1: GovernanceClient (async)

The core communication layer. Every MCP tool gets a typed method. Returns Pydantic models.

### API

```python
class GovernanceClient:
    def __init__(
        self,
        mcp_url: str = "http://127.0.0.1:8767/mcp/",
        timeout: float = 30.0,
        retry_delay: float = 3.0,
    ): ...

    # Connection lifecycle — per-cycle, not persistent across sleeps
    async def connect(self) -> None
    async def disconnect(self) -> None
    async def __aenter__(self) / __aexit__

    # Identity
    async def onboard(self, name: str, model_type: str = "resident_agent",
                      client_hint: str = "resident",
                      force_new: bool = False, **kwargs) -> OnboardResult
    async def identity(self, name: str, resume: bool = True,
                       continuity_token: str | None = None,
                       **kwargs) -> IdentityResult

    # Check-in
    async def checkin(self, response_text: str,
                      complexity: float = 0.3,
                      confidence: float = 0.7,
                      mode: str = "compact",
                      **kwargs) -> CheckinResult

    # Knowledge graph
    async def leave_note(self, summary: str, tags: list[str] | None = None,
                         **kwargs) -> NoteResult
    async def search_knowledge(self, query: str, **kwargs) -> SearchResult
    async def store_discovery(self, summary: str, discovery_type: str,
                              severity: str, tags: list[str] | None = None,
                              details: str | None = None,
                              **kwargs) -> NoteResult
    async def audit_knowledge(self, scope: str = "open",
                              top_n: int = 10, **kwargs) -> AuditResult
    async def cleanup_knowledge(self, dry_run: bool = False,
                                **kwargs) -> CleanupResult

    # Lifecycle
    async def archive_orphan_agents(self, **kwargs) -> ArchiveResult
    async def self_recovery(self, action: str = "quick",
                            **kwargs) -> RecoveryResult

    # Metrics
    async def get_metrics(self, **kwargs) -> MetricsResult

    # Model inference (routes through governance to Ollama)
    async def call_model(self, prompt: str, provider: str = "ollama",
                         model: str = "qwen3-coder-next:latest",
                         max_tokens: int = 1024,
                         temperature: float = 0.0,
                         **kwargs) -> ModelResult

    # Escape hatch
    async def call_tool(self, tool_name: str, arguments: dict) -> dict
```

### Key Behaviors

**Session injection:** Automatically appends `client_session_id` and `continuity_token` to every call except `onboard` and `identity`. The client tracks these internally after successful identity/onboard responses.

**Response parsing:** The MCP `result.content[0].text -> json.loads()` chain lives here once. Multi-path session extraction (`result["client_session_id"]` -> `result["session_continuity"]["client_session_id"]` -> `result["identity_summary"]["client_session_id"]["value"]`) runs on raw dicts before Pydantic model construction.

**Per-call timeout:** Every MCP call is wrapped in `asyncio.wait_for(call, timeout)`. This is critical because the anyio/asyncpg deadlock can cause calls to hang indefinitely without erroring. The default timeout is 30 seconds, configurable per-client and per-call via `timeout` kwarg.

**Retry:** One automatic retry on transient connection errors (`httpx.ConnectError`, `httpx.TimeoutException`, `ConnectionError`, `OSError`, `asyncio.TimeoutError`). Configurable delay (default 3s).

**Per-cycle connection:** The client opens one MCP transport connection via `connect()` (or `async with`), makes multiple tool calls within that session, then closes via `disconnect()`. Connections are not held open across long sleeps — vigil sleeps 30 min between cycles, so each cycle gets a fresh connection. This matches the existing pattern in vigil/sentinel.

**Transport:** Streamable HTTP only. SSE is dropped — all governance URLs use `/mcp/`.

**`**kwargs` passthrough:** Every typed method accepts `**kwargs` so new server-side parameters don't require SDK updates.

## Layer 2: SyncGovernanceClient

Mirrors the async API for synchronous consumers (watcher, scripts, one-off tools).

```python
class SyncGovernanceClient:
    def __init__(
        self,
        mcp_url: str = "http://127.0.0.1:8767/mcp/",
        rest_url: str = "http://127.0.0.1:8767/v1/tools/call",
        timeout: float = 30.0,
        transport: str = "rest",  # "rest" or "mcp"
    ): ...

    def connect(self) -> None
    def disconnect(self) -> None
    def __enter__(self) / __exit__

    # Same method signatures as GovernanceClient, synchronous
    def onboard(self, ...) -> OnboardResult
    def checkin(self, ...) -> CheckinResult
    def leave_note(self, ...) -> NoteResult
    # ... etc
```

**Dual transport:**

- `transport="rest"` (default): Uses `urllib.request` to `POST /v1/tools/call`. This is the safe sync path that avoids the anyio deadlock. No event loop needed. This is what watcher uses today.
- `transport="mcp"`: Uses `asyncio.run()` around the async client. Safe in standalone processes but unsafe inside a running event loop. The SDK will raise `RuntimeError` if it detects a running loop and `transport="mcp"`.

REST transport parses the two-level success envelope (`data["result"]["content"][0]["text"]` -> `json.loads`).

## Layer 3: GovernanceAgent Base Class

Lifecycle management for long-running agents. Built on GovernanceClient.

```python
class GovernanceAgent:
    def __init__(
        self,
        name: str,
        mcp_url: str = "http://127.0.0.1:8767/mcp/",
        state_dir: Path | None = None,
        session_file: Path | None = None,
        notify_on_error: bool = True,
    ):
        self.name = name
        self.client = GovernanceClient(mcp_url)
        self.state_dir = state_dir  # defaults to PROJECT_ROOT/data/<name_lower>/
        self.session_file = session_file  # defaults to PROJECT_ROOT/.<name_lower>_session

    # --- Subclass implements ---
    async def run_cycle(self, client: GovernanceClient) -> str | None:
        """One unit of work. Return summary string for full check-in, or None to skip."""
        raise NotImplementedError

    # --- Lifecycle (handled for you) ---
    async def run_once(self) -> None:
        """Single cycle: connect -> ensure_identity -> run_cycle -> checkin -> disconnect."""

    async def run_forever(self, interval: int = 60, heartbeat_interval: int = 1800) -> None:
        """Loop: run_cycle repeatedly. Sends compact heartbeat check-in every
        heartbeat_interval seconds if run_cycle keeps returning None."""

    # --- Identity (handled for you) ---
    # Automatic three-step identity resolution:
    #   1. Token resume (strong) — decode token, validate embedded aid matches stored UUID
    #   2. Name resume (weak)
    #   3. Fresh onboard (fallback)
    # Identity drift detection: raises IdentityDriftError if UUID changes unexpectedly

    # --- Session persistence (handled for you) ---
    # Atomic file writes to session_file
    # Loads client_session_id + continuity_token on startup
    # Saves after every successful identity/onboard response
    # Token validation: base64-decodes continuity_token, extracts aid field,
    #   verifies against stored agent UUID before using. Discards stale tokens.

    # --- State persistence ---
    def load_state(self) -> dict:
        """Load agent-specific cross-cycle state from state_dir."""
    def save_state(self, state: dict) -> None:
        """Save agent-specific cross-cycle state to state_dir."""

    # --- Graceful shutdown ---
    # Installs signal handlers (SIGTERM, SIGINT)
    # Sets self.running = False, current cycle completes before exit
```

### Check-in Logic

The base class handles check-ins based on `run_cycle` return value:

- `str` returned: calls `client.checkin(result, mode="full")` with complexity/confidence the subclass can override via properties or per-return metadata
- `None` returned: skips check-in for this cycle
- Heartbeat timer: in `run_forever` mode, if `heartbeat_interval` seconds pass without a full check-in, the base class sends `client.checkin("heartbeat", mode="compact")` to keep the EISV trajectory alive

### How Agents Would Look After Migration

**Vigil (~800 LOC -> ~400 LOC):**
```python
class Vigil(GovernanceAgent):
    def __init__(self, with_tests=False):
        super().__init__("Vigil", session_file=PROJECT_ROOT / ".vigil_session")
        self.with_tests = with_tests

    async def run_cycle(self, client: GovernanceClient) -> str | None:
        summaries = []
        # Health checks (governance + anima)
        # KG groundskeeping (audit + cleanup)
        # Optional test run
        # Leave notes for changes
        return "; ".join(summaries) if summaries else None
```

**Sentinel (~1100 LOC -> ~600 LOC):**
```python
class Sentinel(GovernanceAgent):
    def __init__(self):
        super().__init__("Sentinel", session_file=PROJECT_ROOT / ".sentinel_session")
        self.fleet = FleetState()
        # Sentinel still manages its own WebSocket connection to /ws/eisv

    async def run_cycle(self, client: GovernanceClient) -> str | None:
        # Analyze fleet state from WebSocket feed
        # Detect anomalies, generate findings
        # Leave notes for high-severity findings
        return summary if findings else None
```

**Watcher (no base class, uses SyncGovernanceClient directly):**
```python
# Replace raw urllib calls with:
client = SyncGovernanceClient(transport="rest")
result = client.call_model(prompt=review_prompt, model="qwen3-coder-next:latest")
# For critical findings:
client.store_discovery(summary=finding, discovery_type="bug_found", severity="critical", tags=[...])
```

## Response Models

Pydantic v2 models with generous `Optional` fields and `extra="ignore"` to handle the server's variable response shapes.

```python
from pydantic import BaseModel, ConfigDict

class _GovModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

class OnboardResult(_GovModel):
    success: bool
    client_session_id: str
    uuid: str | None = None
    continuity_token: str | None = None
    continuity_token_supported: bool = False
    is_new: bool = False
    verdict: str = "proceed"
    guidance: str | None = None
    session_resolution_source: str | None = None
    welcome: str | None = None

class IdentityResult(_GovModel):
    client_session_id: str
    uuid: str
    continuity_token: str | None = None
    resolution_source: str | None = None

class CheckinResult(_GovModel):
    success: bool
    verdict: str  # proceed/guide/pause/reject
    guidance: str | None = None
    margin: str | None = None  # "tight" when near basin edge
    coherence: float | None = None
    risk: float | None = None
    metrics: dict | None = None  # {E, I, S, V, coherence}

class NoteResult(_GovModel):
    success: bool
    discovery_id: str | None = None

class SearchResult(_GovModel):
    results: list[dict] = []  # [{id, summary, tags, agent_id, timestamp, ...}]

class AuditResult(_GovModel):
    success: bool
    results: list[dict] = []

class CleanupResult(_GovModel):
    success: bool
    cleaned: int = 0

class ArchiveResult(_GovModel):
    success: bool
    archived: int = 0

class RecoveryResult(_GovModel):
    success: bool
    action_taken: str | None = None

class MetricsResult(_GovModel):
    success: bool
    metrics: dict = {}

class ModelResult(_GovModel):
    success: bool
    response: str | None = None
```

Fields will be refined during implementation by inspecting actual server responses. The `extra="ignore"` config means unknown fields don't break the model — the SDK gracefully handles server-side additions.

## Error Hierarchy

```python
class GovernanceError(Exception):
    """Base exception for all SDK errors."""

class GovernanceConnectionError(GovernanceError):
    """Cannot reach governance server."""

class GovernanceTimeoutError(GovernanceError):
    """MCP call exceeded timeout (likely anyio deadlock)."""

class IdentityDriftError(GovernanceError):
    """Agent UUID changed unexpectedly during session."""
    expected_uuid: str
    received_uuid: str

class VerdictError(GovernanceError):
    """Governance issued a pause or reject verdict."""
    verdict: str          # "pause" or "reject"
    guidance: str | None
```

`GovernanceTimeoutError` is distinct from `GovernanceConnectionError` because the remediation is different: timeout likely means the anyio deadlock, not a network issue.

## Shared Utilities (`utils.py`)

Extracted from the duplicated code across vigil/sentinel:

```python
def atomic_write(path: Path, data: str) -> None:
    """Write data to a file atomically via temp file + os.replace."""

def notify(title: str, message: str) -> None:
    """Send a macOS notification via osascript. No-op on non-macOS."""

def load_json_state(path: Path) -> dict:
    """Load JSON state from file. Returns {} if missing or corrupt."""

def save_json_state(path: Path, state: dict) -> None:
    """Save JSON state atomically."""

def decode_continuity_token(token: str) -> dict | None:
    """Base64-decode a continuity token and extract the aid field.
    Returns None if decode fails."""

def validate_token_uuid(token: str, expected_uuid: str) -> bool:
    """Decode token, extract aid, return True if it matches expected_uuid."""
```

## Testing Strategy

- **Unit tests** for client methods: mock the MCP transport, verify correct tool names, argument shapes, session injection, timeout behavior, retry logic
- **Unit tests** for response parsing: feed realistic server response shapes (from existing test fixtures), verify Pydantic models construct correctly
- **Unit tests** for agent base class: mock GovernanceClient, verify identity resolution flow, session persistence, heartbeat timing, graceful shutdown
- **Unit tests** for utils: atomic_write, token decode/validation
- **Integration tests** (optional, require running governance server): end-to-end onboard -> checkin -> leave_note flow

## Migration Path

1. Build the SDK with tests
2. Migrate watcher first (simplest — just swap urllib calls for SyncGovernanceClient)
3. Migrate vigil (extract business logic into GovernanceAgent subclass)
4. Migrate sentinel (same, plus keep its WebSocket management separate)
5. Remove duplicated code from agents, slim agents/common/ to just re-export from SDK
6. Verify all existing agent tests still pass

Each migration is a separate commit. Agents keep working throughout — the SDK is additive until the final cleanup.

## Open Questions

None. All design decisions are resolved. Implementation will surface any remaining gaps — the Pydantic model fields will be refined against actual server responses during development.
