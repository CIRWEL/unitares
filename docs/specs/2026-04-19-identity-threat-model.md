# UNITARES Identity Threat Model (2026-04-19)

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

Adopted by: [operator signature — Kenny]
Date: 2026-04-19
Next review: on any of (a) the deployment shape changes (untrusted-network peers, multi-UID hosts, shared-tenant infrastructure), (b) a new same-UID attack is observed in the wild against this class of system, (c) 12 months elapse.

Until then, "is this defending against a same-UID rogue process?" is a test an incoming proposal must answer "no" to or be rewritten. Proposals that answer "yes" require reopening this scope first.
