---
title: Code-architect review — s19-attestation-mechanism.md
reviewer: feature-dev:code-architect (subagent dispatch 2026-04-25)
date: 2026-04-25
status: M3 conditionally confirmed; three implementation constraints require resolution before code opens
---

# Code-Architect Review: S19 Attestation Mechanism

Reviewing `docs/proposals/s19-attestation-mechanism.md` (gate S19 resolved-when (f)) against the live codebase. No implementation code is written here; this is design review only.

---

## Q1 — Server-observed PID: transport reality

**Short answer: HTTP-on-loopback is the only live listener. Stdio is not active. UDS is additive, not a refactor, but the anyio-deadlock constraint governs where the attestation call lands.**

`src/mcp_server.py` runs a single `uvicorn.Server` under Starlette + `StreamableHTTPSessionManager` (`mcp_server.py:738–963`). The startup banner explicitly names "Streamable HTTP" as the only MCP transport (`mcp_server.py:714`). There is no stdio server anywhere in `main()`, no `mcp.run(transport="stdio")` call, and no alternate entry point in `scripts/` that activates stdio. The FastMCP instance is constructed with no `transport` parameter override (`mcp_server.py:217–223`).

Adding a UDS listener is additive surface. The existing Starlette ASGI `app` is what uvicorn serves; a UDS socket can feed that same ASGI app via a second `asyncio` Unix socket server or a second uvicorn `Server`. Neither requires changes to handler modules, tool schemas, or any registered tool. The identity-step middleware (`src/mcp_handlers/middleware/identity_step.py`) resolves identity from `SessionSignals` populated by the ASGI wrapper in `streamable_mcp_asgi` (`mcp_server.py:819–868`). A UDS-parallel wrapper would (a) extract peer PID via `LOCAL_PEERCRED` at connection time, (b) set that PID as an additional field on `SessionSignals`, and (c) route to the same `_streamable_session_manager.handle_request`. The current `SessionSignals` dataclass carries `transport`, `ip_ua_fingerprint`, `x_session_id`, and related fields. Adding `peer_pid: Optional[int]` is a one-line change; reading `LOCAL_PEERCRED` at accept time is ~10 lines of `getsockopt`. Neither forces a rewrite of `identity_step.py:resolve_identity` — that function reads `get_session_signals()` from a contextvar; the UDS path just populates the signals instance differently.

**Anyio-deadlock constraint (CLAUDE.md "Known Issue"):** The substrate-claim verification step — launchctl subprocess call + registry lookup — cannot be awaited directly from the ASGI handler path. It must be structured as either a cached verification pre-warmed at UDS connection time (stored in a contextvar for that connection's lifetime) or wrapped in `loop.run_in_executor`. The existing `src/agent_loop_detection.py:374` synchronous-function-via-executor idiom is the right pattern. A synchronous `subprocess.run(["launchctl", "print", f"pid/{peer_pid}"])` wrapped in `run_in_executor(None, ...)` is the correct fit.

---

## Q2 — launchctl introspection feasibility

**Short answer: verified same-user, no elevation; label field is present and stable; no JSON output flag; plain-text grep is the right extraction approach; ~40–80ms round-trip acceptable for per-connection-accept, not per-tool-call.**

Running `launchctl print pid/$$` (bash child of zsh under the aqua user context) confirms:

(a) **Elevation:** Works for same-UID processes without `sudo`. For a PID not under the calling user's launchd domain, the command returns "Could not find service" — itself a useful signal that the process is not launchd-managed.

(b) **Stable label field:** Output for launchd-managed PIDs includes a line of the form `label = com.unitares.vigil`. The `label` key name has been stable across macOS 12–15. Other useful fields present: `state`, `program`, `pid`. A targeted `grep "^\s*label = "` is more robust than any attempt at full format parsing.

(c) **JSON output flag:** There is no `-j` or `--json` flag on `launchctl print`. Output is Apple's custom plist-like format. Extraction must be done by line matching, not `json.loads`.

(d) **Speed:** ~40–80ms per call on this machine. Acceptable at UDS connection-accept time (one call per resident restart). Not acceptable if called per-tool-call — the proposal's framing of verification at onboard/resume time is correct.

**Version fragility:** The `label` field has not changed format across tested releases. Recommend wrapping the parse in a try/except that degrades to `None` (unverifiable) on unexpected output, logs the raw first 10 lines at DEBUG level on failure, and treats `None` from `read_service_label` as a substrate-claim rejection rather than an exception.

---

## Q3 — Same-UID adversary matrix

For each variant (a)–(f), analysis against actual code surface:

**(a) Spoof a PID claim in a JSON field.** M1/M2/M3 all defeat this trivially. The UDS path never reads a client-declared PID; no `pid` field exists in the `onboard` or `identity` tool schemas. `SessionSignals` extraction at `mcp_server.py:834–868` does not read any PID from the request body.

**(b) Spawn under the resident's launchd label via `launchctl bootstrap`/`launchctl kickstart`.** The hard case. Under M2-only (UDS + `SO_PEERCRED`), the server has the kernel-attested PID of a legitimate launchd-managed process with the expected label — but if the attacker successfully bootstrapped their own service under `com.unitares.sentinel`, the label query returns the expected value. M3's enrollment registry closes this: the operator pre-seeds `{agent_uuid → expected_launchd_label}`, and an attacker-spawned process gets a fresh UUID minted (or must present a UUID already in the registry). To present a registry UUID they need the continuity_token, which they lack post-S19. **M3 defeats (b) only when enrollment is operator-seeded, not TOFU.** The distinction is critical: TOFU means the first process to claim `com.unitares.sentinel` wins; operator-seeded means enrollment happens with the server in a known-clean state before any process can race.

**(c) Invoke the resident binary manually outside launchd.** `launchctl print pid/<PID>` returns "Could not find service." Server treats this as unverifiable substrate claim → reject. Defeated by M1/M2/M3.

**(d) Copy plist + env vars and re-run.** Same as (c) — not run via `launchctl`, no launchd context. Defeated.

**(e) Race the resident's process exit + claim its PID.** Current codebase has no mitigation. PID reuse on macOS is rare but possible in the post-exit window. M2 + M3 give kernel-attested PID at connection time but do not prevent a race where the attacker's process acquires the departed resident's PID before the server handles the next connection. The practical mitigation is: at first successful substrate-claim verification in a server lifetime, record `(verified_uuid, peer_pid, process_start_time)` in an in-process dict (not Redis/DB — memory only, per-server-lifetime). At each subsequent substrate-anchored resume, verify the PID + start_time match the record. `process_start_time` is available via `proc_pidinfo(pid, PROC_PIDTBSDINFO)` on macOS; this is a C-level call but available via `ctypes`. Cost is O(4) entries; no persistence needed. **This mitigation is absent from the proposal's sequencing and must be added.**

**(f) Read resident process memory via `task_for_pid`.** Correctly classified as out of threat model. Root-only on macOS without entitlements. Not addressed by any mechanism below A3 boundary.

**Net:** include (b) explicitly in scope (requires operator-seeded enrollment). Include (e) with the per-connection start-time cache. (a), (c), (d) are defeated by basic M2.

---

## Q4 — Watcher and Chronicler as distinct cases

**Watcher is incompatible with the launchd-label mechanism as drafted and requires a separate sub-mechanism. Chronicler fits M3 cleanly with a one-line SDK env-var gate.**

**Watcher:** `agents/watcher/watcher-hook.sh` fires `python3 agents/watcher/agent.py` from a PostToolUse hook (hook lines 99–106). This process is a child of the Claude Code process, not under any launchd job. `launchctl print pid/<watcher_pid>` returns "Could not find service." There is no `com.unitares.watcher` plist — memory notes this explicitly and `watcher-hook.sh` confirms it structurally. Watcher's identity flow (`agents/watcher/agent.py:136–237`) reads `~/.unitares/anchors/watcher.json` and uses UUID-direct or token resume, exactly the Hermes-incident path.

**M3's launchd-label mechanism does not apply to Watcher.** The alternative: (a) UDS transport (kernel-attested PID via `SO_PEERCRED`) + (b) executable-path-hash match instead of launchd-label match. The server, at UDS accept time, calls `proc_pidpath(peer_pid)` (macOS) or reads `/proc/<peer_pid>/exe` (Linux) to get the binary path, hashes it (SHA-256), and compares to the enrollment-time hash of `agents/watcher/agent.py`. This is registered as **M3-hook** to distinguish it from M3-launchd for the long-running residents. M3-hook defeats A1 (Hermes is not running `agents/watcher/agent.py`) and A2 (attacker cannot forge `proc_pidpath` without replacing the binary — root-equivalent operation, outside A1/A2 boundary). It is weaker against (b) — an attacker who replaces the watcher binary defeats it — but that is A3 territory.

One open question for M3-hook: Watcher runs as short-lived invocations, many per day. Each invocation opens a fresh UDS connection; the server hashes the binary on each accept. The hash check is fast (SHA-256 of a ~300KB Python file is sub-millisecond) but the `proc_pidpath` call adds ~5ms. Acceptable for hook-driven cadence.

**Watcher's `_save_session()` at `agents/watcher/agent.py:162–180` writes `{client_session_id, continuity_token, agent_uuid}`.** Under M3 the anchor transitions to `{agent_uuid}` only. The `_save_session` function must be gated on substrate-anchored mode (env var or anchor schema version detection) to skip the `continuity_token` write. The same gating applies to `agents/sdk/src/unitares_sdk/agent.py:279–301` (`_ensure_identity`), which reads the saved token and injects it into `client.continuity_token` on the fast-path resume.

**Chronicler:** `agents/chronicler/agent.py` is launched by `com.unitares.chronicler` (daily launchd job, confirmed in memory). It uses `GovernanceAgent.run_once()` via `asyncio.run(agent.run_once())` (`chronicler/agent.py:212`). Short-lived per invocation but launchd-managed. M3-launchd applies. The MCP SDK client `GovernanceClient.connect()` (`agents/sdk/src/unitares_sdk/client.py:75–99`) currently opens an HTTP connection via `streamable_http_client`. Under M3, Chronicler's SDK must use UDS when `UNITARES_UDS_SOCKET` is set. The detection is a one-line `__init__` check; the transport construction branches on the env var. This is consistent with what the proposal already scopes as the SDK change.

**Summary for Q4 (per-resident mechanism table):**

| Resident | Launchd | Mechanism |
|---|---|---|
| Vigil | Yes (`com.unitares.vigil`) | M3-launchd: UDS + SO_PEERCRED + launchctl label match |
| Sentinel | Yes (`com.unitares.sentinel`) | M3-launchd |
| Chronicler | Yes (`com.unitares.chronicler`) | M3-launchd |
| Watcher | No (hook-driven) | M3-hook: UDS + SO_PEERCRED + executable-path-hash |

The proposal's step 5 ("per-resident migration") must enumerate this split explicitly.

---

## Q5 — Non-macOS fallback

**Linux systemd analogue is tractable as a two-backend module. Cross-platform abstraction is the right shape; macOS-only is acceptable for current scope with a documented constraint.**

On Linux, systemd unit name from a PID is available by reading `/proc/<pid>/cgroup`, which contains lines of the form `1:name=systemd:/system.slice/myservice.service`. A targeted regex is sufficient; no external library dependency, no elevation required. `SO_PEERCRED` on Linux uses `getsockopt(sock, SOL_SOCKET, SO_PEERCRED, ...)` with `struct ucred {pid, uid, gid}` — same pattern as macOS `LOCAL_PEERCRED`, different struct layout. `libsystemd` Python bindings (`systemd-python` package) also expose `sd_pid_get_unit()` if a library dependency is acceptable, but the `/proc/cgroup` parse is dependency-free.

The cross-platform abstraction is a single module, e.g., `src/substrate/peer_attestation.py`, with three functions: `read_peer_pid(sock)`, `read_service_label(pid) -> Optional[str]`, `read_executable_path(pid) -> Optional[str]`. macOS implementations use `LOCAL_PEERCRED`, `launchctl print pid/<N>` subprocess, and `proc_pidpath` via ctypes. Linux implementations use `SO_PEERCRED`, `/proc/<pid>/cgroup` regex, and `/proc/<pid>/exe` symlink. Both backends expose identical interfaces; the module selects by `sys.platform`. This is two implementations under one module, not two parallel architectures.

**For current scope** (four launchd residents on one Mac), Linux is a documented constraint, not a blocker. The `peer_attestation.py` module should raise `NotImplementedError` for platforms other than `darwin` and `linux`, with a comment referencing S19 for forward work.

---

## Sequencing review

The proposed 5-step sequencing is correct in order. Two steps have hidden costs; one step is missing.

**Step 1 (schema + enrollment CLI):** The schema is right. The enrollment CLI must be operator-seeded, not TOFU, to close adversary (b). TOFU allows an attacker to race the first enrollment. Document in the CLI's `--help` text: enrollment must be run with a fresh server restart and no resident connections in flight. This is an operational procedure, not a code change, but it is load-bearing for M3's (b) defeat.

**Step 2 (UDS listener + SO_PEERCRED + launchctl + substrate-claim verification):** The anyio-deadlock constraint means `launchctl` must be called synchronously via `run_in_executor`, not awaited directly. The verification must be pre-warmed at connection-accept time and stored in a contextvar, not repeated on each tool call.

**Missing step 2a (PID reuse mitigation for Q3(e)):** After step 2, before step 3: server records `(verified_uuid, peer_pid, process_start_time)` in an in-process per-server-lifetime dict. At each substrate-anchored resume, verify PID + start_time match. `process_start_time` via `proc_pidinfo` (macOS) or `/proc/<pid>/stat` field 22 (Linux). O(4) entries, no persistence. Cost is trivial; omission is a correctness gap against Q3(e).

**Step 3 (PATH 2.8 explicit-rejection for substrate-anchored UUIDs):** Correct as ordered. Must come after step 2 so residents can resume via UDS before the token path is blocked. The rejection at `src/mcp_handlers/identity/resolution.py:682–694` should check `core.substrate_claims` for `token_agent_uuid`: if present, return an explicit error naming the UDS path, not a generic resume failure.

**Step 4 (SDK: UDS transport + no token persistence):** `GovernanceClient.connect()` at `agents/sdk/src/unitares_sdk/client.py:86–99` and `_save_session()` at `agents/watcher/agent.py:162–180` are the two affected sites. The UDS transport detection should be `UNITARES_UDS_SOCKET` env var (set in each resident's launchd plist). The `_save_session` token-skip gate should be checked against anchor schema version (an `"anchor_version": 2` field presence) so the old path works during migration.

**Step 5 (per-resident migration):** Must enumerate M3-launchd vs M3-hook per resident (see Q4 table above).

**Step 6 (regression test):** Correct. The test for PATH 2.8 rejection should use a real `core.substrate_claims` row (or a mock DB fixture) and confirm the rejection message names the UDS path. A second test should confirm the UDS accept path succeeds for a mock peer PID with a matching launchctl stub.

---

## Verdict

- **M3 confirmed as the right mechanism.** The design is sound; the code surface (HTTP-only server, no stdio, additive UDS path, anyio-safe `run_in_executor` pattern) supports it without structural refactoring. The `peer_attestation.py` module is a clean abstraction boundary.

- **Three constraints must be resolved before code opens:**

  1. **Watcher sub-mechanism split.** Watcher is hook-invoked with no launchd label. The proposal must specify M3-hook (UDS + SO_PEERCRED + executable-path-hash via `proc_pidpath`) as Watcher's variant and add `read_executable_path(pid)` to `peer_attestation.py`. Code owners for step 4 need this split explicitly; otherwise the SDK change will be written as if all four residents are launchd-managed.

  2. **Enrollment must be operator-seeded, not TOFU.** This is the only thing that defeats Q3(b) (launchctl bootstrap adversary). It is an operational constraint, not new code, but it must be documented in the enrollment CLI before step 5 migration runs.

  3. **Add step 2a: PID reuse mitigation.** Record `(peer_pid, process_start_time)` in an in-process dict at first substrate-claim verification; verify on each subsequent resume. Without this, Q3(e) is unaddressed. Cost is trivial; it belongs in step 2 as a sub-requirement, not deferred.
