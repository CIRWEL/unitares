# UNITARES Identity Threat Model (2026-04-19)

> **Status: DRAFT, unsigned, unadopted.** Subjected to a 4-agent adversarial council review on 2026-04-19 which found material honesty gaps in the body below. **Read the "Council Review Findings" section at the end before relying on any claim in this document.** The core scope declaration (threat class E out of scope) is defensible and aligns with prior art (Vault, MCP STDIO spec, AWS IMDSv2); the *application* of the scope to "closed" claims and in-scope handling is weaker than the body suggests.

Load-bearing scope declaration for the identity & authentication stack. Decides what the current implementation is designed to defend against, what it explicitly does not attempt to defend against, and why.

This doc is operator-facing. It exists because the 2026-04-19 identity audit revealed that the code had been accumulating "defense in depth" against threats the deployment cannot realistically close on a solo-operator single-host footprint, while leaving in-scope threats unaddressed. Without a declared scope, every new hardening proposal re-litigates the same question; with a declared scope, we can say "this attack is out of scope by design" and stop building theater.

## System under threat

- **Governance MCP** (Mac, `~/projects/unitares`): HTTP listener on `127.0.0.1:8767`, stdio transport for per-session clients.
- **Resident agents**: Vigil (launchd cron), Sentinel (launchd continuous), Watcher (PostToolUse hook), Steward (in-process in governance-mcp), Lumen (Pi embodied).
- **Thin clients**: Claude Code plugin, Codex commands, Discord Dispatch, Anima proxy, `unitares-governance-plugin`, `unitares-pi-plugin`.
- **Remote connectors**: `claude.ai` hosted MCP via Cloudflare tunnel.
- **Shared store**: one PostgreSQL@17 on port 5432, one Homebrew launchd-managed service.

All Mac-side components run as UID `cirwel` on one physical machine. Pi-side components run as the `pi` user on one physical Raspberry Pi 5. There is no horizontal scale; there is one of each.

## What we protect

1. **Authenticity** of agent-attributed telemetry. Every EISV check-in row must have been produced by the agent whose UUID it carries, for the thermodynamic model to mean anything.
2. **Authorization** for cross-agent operations. One agent cannot act as another against the governance API without evidence.
3. **Integrity** of the audit trail. The governance decision log is the ground truth for post-hoc forensics; it cannot be silently rewritten.

Notably *not* on this list: confidentiality of telemetry contents. The EISV state of an agent is not secret — it's the identity of the author that we guard.

## Threat actors

| Label | Actor | In scope? |
|---|---|---|
| A | Accidental exposure — operator greps, cats, pastes a file containing secrets | **YES** |
| B | Backup leakage — Time Machine / iCloud / Dropbox snapshots the filesystem as it was | **YES** (limited) |
| C | External network — attackers reaching 127.0.0.1 via tunnel, LAN, or browser connector | **YES** |
| D | Third-party dependency — a pip-installed library reads env vars or writes telemetry | **YES** (reasonable diligence) |
| E | Same-user malicious process — a rogue script running as UID `cirwel` that reads/writes the same files UNITARES does | **NO** (see rationale) |
| F | Physical access — someone sits down at an unlocked Mac | **NO** |
| G | Cloud provider compromise — Anthropic's `claude.ai` connector backend is breached | **OUT** (outside our control) |

## Rationale for out-of-scope E (same-user malicious)

A rogue process running as the same UID as the governance stack has full read access to every file the stack owns, regardless of permission mode (0600 and 0644 are equivalent to a same-UID reader). It has access to `/proc/<pid>/environ` on Linux or equivalent syscalls on macOS, so env-var-based secrets are not private either. It can `ptrace` or attach a debugger to any UNITARES process and exfiltrate live memory, so in-memory secrets are not private either.

The only rigorous defenses against a same-UID attacker on macOS are:

1. **Application sandboxing** (`sandbox_init`, app-sandboxed binaries signed with entitlements). Requires signed per-agent binaries.
2. **Per-agent keys in the Secure Enclave** with access controlled by binary code signature. Requires signed per-agent binaries.
3. **Running each agent under a distinct UID** (separate system users). Requires launchd configuration as root and a systemic rework of the filesystem layout.

UNITARES today ships interpreted Python under a single `python3` interpreter with no binary signing pipeline, and no distinct service users. Adopting any of (1)–(3) is a multi-week project with prerequisites (build pipeline changes, packaging, testing, rollback plan).

Until those prerequisites exist, building cryptographic ceremony on top of a shared-UID filesystem — DPoP JWS signed with a private key stored on the same filesystem, peer-cred binding that resolves to `python3`'s cdhash (which is identical across all agent scripts under the same interpreter), anchor-inode binding that invalidates on every atomic write — **does not close the attack**. It adds complexity, produces regression surface, and gives a false sense of protection. Declaring E out of scope is the honest position.

**The acknowledged gap:** if a same-user rogue process exists on the host (malware, compromised dependency, malicious npm/pip postinstall script), it has full access to every UNITARES secret. The mitigation is upstream: keep the dependency tree small, audit `pip install` activity, prefer stdlib and vendored code over new deps, run the operator's shell with minimal extensions.

## Post-audit attack surfaces — closed

| Surface | Status | Reference |
|---|---|---|
| HMAC continuity-secret exposure in launchd plist (mode 0644) | **Closed** | Rotation + chmod 600 on 2026-04-19 |
| Watcher anchor writes continuity token at mode 0644 | **Closed** | PR #52 |
| Steward anchor writes UUID at mode 0644 | **Closed** | `unitares-pi-plugin` PR #1 |
| Session cache writes tokens at mode 0644 | **Closed** | `unitares-governance-plugin` PR #11 + unitares PR #52 |
| Label-based operator privilege escalation (`allow_operator` reads caller-claimed label) | **Closed** | PR #51 |
| Archived-token onboard produces UnboundLocalError with misleading signature echo | **Closed** | PR #53 |

These close threat classes A, B (partially), and C. They do not close E (by design — see above).

## Post-audit attack surfaces — open, in-scope, prioritized

| Surface | Severity | Why it's open |
|---|---|---|
| Backup exposure window post-rotation | Medium | Time Machine snapshots retain old-secret plists; any token minted under the old secret is forgeable from a backup until that token's 30-day TTL expires. Today: mitigated by TM exclusion of `~/.unitares` + plist. Not eliminated — backups made prior to the exclusion still contain old secrets. |
| No rotation cadence | Medium | A single rotation is an event, not a policy. Without a cron schedule, backup windows accumulate indefinitely. |
| No per-token revocation | Medium | A compromised agent token is invalidatable only via global secret rotation, which affects every agent. A blocklist table keyed by token `jti` or agent UUID would let a single compromised token be killed without a fleet-wide re-onboard. |
| No scoped tokens | Low | Every continuity token grants full agent privilege. A scope system (check-in only vs. admin) would limit blast radius of a stolen token. |
| No anomaly detection | Medium | Tokens can be forged silently. There are no counters for "token used from unexpected peer" or "verify failures per minute." A forger goes unnoticed until their actions show up in the audit log. |
| Continuity token lacks `jti` (unique ID) | Low | Required prerequisite for a blocklist table. |
| Plist is re-written at default 0644 by the installer | Low | `scripts/ops/com.unitares.governance-mcp.plist` template + installer script must always write 0600. Currently depends on operator remembering to `chmod`. |

None of these are crypto-architecture-level changes. All live within the bearer-token model.

## Post-audit attack surfaces — out-of-scope by declaration

| Surface | Why out of scope |
|---|---|
| Same-UID process reads 0600 file | Threat class E — see rationale. |
| Same-UID process reads env vars via `KERN_PROCARGS2` / `/proc/<pid>/environ` | Threat class E. |
| Same-UID process `ptrace`s a resident to extract in-memory key | Threat class E. |
| Malicious pip dep reads `os.environ` at import time | Threat class D, but rigorous defense reduces to E. Mitigation is upstream (small dep tree, audit). |
| Physical USB-boot into the Mac | Threat class F. Out of scope. |
| Claude.ai connector backend compromise | Threat class G. Out of our control. If the connector leaks tokens server-side, we find out post-hoc from the audit log and rotate. |

## Recommended work queue (in-scope, deferred)

In priority order:

1. **Rotation cadence.** Cron job (every 30 days) that rotates `UNITARES_CONTINUITY_TOKEN_SECRET` + `UNITARES_HTTP_API_TOKEN`, restarts governance-mcp, and sends a Discord bridge event. One-shot rotation closes a moment; cadence closes the steady state.
2. **Installer hardening.** `scripts/ops/com.unitares.governance-mcp.plist` install path must always land at 0600. Pre-exec check in `mcp_server.py` that refuses to start if the plist it was loaded from is not 0600.
3. **Token `jti` claim + blocklist table.** Minimal schema: `core.revoked_tokens(jti TEXT PRIMARY KEY, revoked_at TIMESTAMPTZ, revoked_by TEXT, reason TEXT)`. Verify rejects blocklisted `jti`. Enables surgical revocation.
4. **Anomaly detection counters.** `unitares_token_verify_fail_total{reason, hostname}`, `unitares_token_used_from_new_peer_total{agent_uuid}`. Surface in Sentinel's SITREP and Discord bridge.
5. **Scoped tokens.** Add `scope` claim (`checkin`, `admin`, `full`). Default continue to issue `full` for backward compatibility; new clients can request narrow scopes. Server-side enforcement per handler.

## Decision points requiring operator input

**If threat class E becomes in-scope**, the bearer-token model is insufficient and the deployment needs:

- Asymmetric per-agent keypairs (one private key per agent, kept in macOS Keychain with access restricted by binary code signature).
- A code-signing pipeline for each agent binary (Watcher, Vigil, Sentinel, Steward, SDK) — prerequisite.
- DPoP-style request signing, with server-side public key registry and nonce cache.
- Rollout strategy and migration window for existing bearer-holders.

Order-of-magnitude estimate: 1500–2500 LOC across three repos, 4–8 weeks of focused work, and the code-signing pipeline as a hard prerequisite.

**If threat class E stays out of scope** (the current declaration), the deferred queue above is the complete list. No further crypto architecture is warranted. Focus is on operational hygiene + detection + revocation, not new primitives.

## Signing off

**Not signed.** The audit that produced this doc closed on 2026-04-19 with Option 2 (incident hardening only, no identity redesign). The scope declaration is captured here as an artifact for future reference, not as an adopted policy. A future operator who wants to adopt the scope should either sign this doc after addressing the council findings below, or supersede it with a revised document.

Proposed review triggers if adopted: (a) deployment shape changes (untrusted-network peers, multi-UID hosts, shared-tenant infrastructure), (b) a new same-UID attack is observed in the wild against this class of system, (c) 12 months elapse.

---

## Council Review Findings (2026-04-19)

Four independent subagents reviewed this doc: red-team (try to break the scope), prior-art (compare to industry), priority (stress-test the deferred queue), philosophical (self-consistency). Their convergent findings — **any one of which should be fixed before signing**:

### 1. "Closed" claims are operationally optimistic

Three rows in the "Post-audit attack surfaces — closed" table contradict entries in the "open" table:

- **Plist 0644**: closed row says "Rotation + chmod 600 on 2026-04-19" but open row 7 says "operator remembering to `chmod`" is the only guard against re-install regression. Not closed — closed for this instance.
- **Rotation**: one-time event; open row 1 admits cadence is deferred. Closure is a moment, not a state.
- **Anchor-perm writes** (PRs #52, #11, pi-plugin #1): code path is structurally fixed, but pre-existing 0644 files persist on disk until the next overwrite. No explicit sweep was prescribed.

Rewrite these as **"structurally fixed, operationally incomplete"** with a concrete operational tail-off condition.

### 2. D → E smuggling is a shell game

The threat-actors table places D (third-party dep) in-scope with "reasonable diligence," but the rationale section explicitly concedes "Threat class D, but rigorous defense reduces to E. Mitigation is upstream." This lets anything in D slip to out-of-scope via relabeling. Concretely: `pip install langchain` is outside "reasonable diligence" today and nothing in the repo detects or stops it; D is in-scope on paper, undefended in code.

Needs either: (a) define "reasonable diligence" as concrete controls (pinned hashes, SBOM check, CI audit), or (b) promote supply-chain to its own row with named controls, or (c) honestly move D to out-of-scope with rationale.

### 3. Missing threat surfaces entirely

The red-team agent found attack surfaces not enumerated in any category:

- **Watcher's `patterns.md`** — committed-prompt-data with privileged LLM ingestion. Contributor with push access modifies the file; Watcher reads it on next invocation; LLM response can be crafted to exfiltrate filesystem contents. Neither D nor E cleanly — "committed data with execution-relevant ingestion" is a class the doc doesn't name.
- **In-process import bypass** — `from src.mcp_handlers.identity.handlers import handle_onboard_v2` from Steward or any same-process caller bypasses HMAC auth entirely. The "Authorization" invariant is silent about this parallel channel.
- **HMAC-secret fallback chain** — `src/mcp_handlers/identity/session.py:45-54` reads `UNITARES_CONTINUITY_TOKEN_SECRET` OR `UNITARES_HTTP_API_TOKEN` OR `UNITARES_API_TOKEN`. Rotating one without the others leaves a live forgery oracle. The "closed" claim for rotation should specify *which* of the three was rotated (on 2026-04-19 only `UNITARES_CONTINUITY_TOKEN_SECRET` was rotated; the others should be audited).
- **`extract_token_agent_uuid` skips `exp` intentionally** — `session.py:86-121` docstring argues this is correct for resident long-idle resume. Every caller of this function is a replay oracle against old-secret backups for as long as that secret isn't rotated. Not a bug to fix, but needs calling out.
- **Audit log integrity** — doc declares audit log as "ground truth for forensics" but any agent with DB write access can UPDATE historical rows. Append-only constraint (trigger or hash-chain) missing.
- **Pi-side parity** — doc is Mac-only. Lumen on Pi has its own `~/.unitares/` state under user `pi`, and threats A-E apply symmetrically. Needs either parity analysis or explicit Pi-out-of-scope rationale.
- **Discord Dispatch lifecycle** — separate auth surface per `discord-dispatch.md` memory; not covered.

### 4. Queue priority is inverted

The priority-review agent's proposed reordering:

1. **`jti` claim + `core.revoked_tokens` blocklist + anomaly counters + HTTP-layer rate limit** (bundled). Today the only remediation for any compromised token is global rotation (fleet-wide blast radius). Blocklist enables surgical response. Anomaly counters (`unitares_token_verify_fail_total`, `unitares_token_used_from_new_peer_total`) are the trigger for revocation. `rate_limit_step.py:55` keys on caller-supplied `agent_id` — trivially bypassed by anyone with the HMAC secret, so rate-limiting needs to happen pre-identity-resolution.
2. **Scoped tokens** (Watcher → `checkin`-only). Not low-priority — Watcher runs arbitrary code on every edit. Scoping bounds blast radius of Watcher compromise.
3. **Rotation cadence** — extend to 90 days, not 30. Event-driven rotation on suspicion (once blocklist exists) replaces preemptive churn. Current 30-day proposal creates ops churn without matching security gain.

Demote: installer pre-exec refuse-to-start check → ship as preflight script, not hard server gate (risks bricking 2am startup on misconfigured hosts).

### 5. Prior-art lineage should be named

The E-out-of-scope declaration aligns with accepted industry positions — this doc should cite them rather than appearing to invent the position:

- **HashiCorp Vault Security Model**: "Vault should be the sole user process running on a machine" — explicitly declares same-host co-tenancy out of scope via operator discipline.
- **MCP Authorization Spec (draft)**: "Implementations using STDIO transport SHOULD NOT follow this specification, and instead retrieve credentials from the environment" — MCP itself concedes same-UID is the OS's problem.
- **AWS IMDSv2 design**: "An adversary who has gained code execution on the EC2 instance can retrieve credentials from the IMDS regardless of the version" — AWS explicitly accepts this.
- **MITRE ATT&CK T1098.004**: treats same-user key theft as a technique to *detect*, not prevent.
- **SPIFFE/SPIRE**: the one system that addresses same-UID separation seriously, via binary-cdhash / cgroup / container-ID selectors — confirms the three mitigations this doc identifies (app sandbox / Secure Enclave / distinct UIDs) are the real cost.

The doc is above industry median for honesty when it does these things; it should own that lineage.

### 6. "When E is realized, everything collapses" should be explicit

The three protected properties (authenticity, authorization, audit integrity) all bottom out on bearer-token validity. When E is realized (rogue same-UID process), bearer tokens can be forged and all three properties fail *simultaneously*. The doc describes them as independently defended. A future reader should know that E-realization is total failure, not graceful degradation.

### 7. Philosophical-agent verdict (harsh but worth recording)

> "It's a rationalization dressed as a threat model — technical reasoning about E is sound, but the taxonomy routes hard cases out, marks surfaces closed that it concurrently lists as open, suppresses that bearer tokens assume E never happens, and presents opinion-grade claims as settled; it reaches a conclusion the author already held and constructs a scope to fit it, rather than letting the scope fall out of adversarial analysis."

This verdict is preserved verbatim as the stress-test of last resort. A revised version of this doc should be able to withstand it.

### What to do with this

If a future operator revives this scope question:
1. Rewrite "closed" table as "structurally fixed / operationally incomplete" with tail-off conditions.
2. Fix D taxonomy: either define diligence as code-enforced controls or supply-chain gets its own row.
3. Add missing surfaces (patterns.md, in-process bypass, fallback chain, audit integrity, Pi parity, Discord Dispatch).
4. Reorder the deferred queue per council priority.
5. Cite Vault / MCP / IMDSv2 / SPIFFE as prior art.
6. Make the E-realization total-failure property explicit.
7. Only then attempt to sign.
