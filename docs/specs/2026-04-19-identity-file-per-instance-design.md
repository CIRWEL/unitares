# Identity: File-Per-Instance Design (2026-04-19)

> **Status: v0 DRAFT, not adopted.** Subjected to a 4-agent adversarial council review on 2026-04-19. The core direction (file-per-instance, path assigned by launcher, delete bearer-token stack) is defensible and aligns with prior art (systemd `machine-id`, Kubernetes UIDs, W3C DIDs). **Phase 2 of the migration plan as written is not implementable** — Claude Code spawns the MCP child from its own config and does not inherit env vars set by the plugin hook. A wrapper-executable prerequisite is missing. **Read the "Council Review Findings" section at the end before taking any implementation step.** The audit that produced this doc closed on 2026-04-19 with Option 2 (incident hardening only, no redesign); this document is preserved as an artifact-in-place, not an active plan.

Positive design for how UNITARES establishes and persists agent identity. Replaces (not layers on) the continuity-token / bearer-auth model inherited from the 2025 prototype era.

## Why this exists

The identity failures observed during the 2026-04-19 audit were not attacks. They were the system's own confusion — agents inheriting other agents' UUIDs because the system had no clear rule about *which file* an arriving agent reads. Concretely:

- A fresh Claude Code session read `~/.unitares/session.json` (shared, unslotted), inherited an archived agent's continuity token, and was briefly resolved to that archived identity by the server. Not a break-in. A filesystem race the system was architecturally unable to distinguish from the legitimate case.
- Residents resuming after crashes or launchd respawns vs. brand-new subagents entering the same workspace were indistinguishable to the identity layer. Both paths led through the same `continuity_token` / `resume` logic with the same fallback chains.
- Compaction produces a new Claude Code process with the same workspace. The system had no way to say "this is a continuation" vs "this is a fresh actor" except by *guessing* from filesystem hints.

The fix isn't stronger auth. It's clearer identity. An agent that can't answer "who am I?" cleanly at startup can't make any downstream claim trustworthy, no matter how cryptographic the wrapper.

## Design principle

**One anchor file per instance. No two instances ever read the same path. The path is assigned by the launcher before the agent runs.**

That's the whole design. Everything else follows.

## The anchor file

Contents:

```json
{"agent_uuid": "40056caf-3b2e-4588-add4-643916b9fa6d"}
```

That's it. No continuity token. No session ID. No label. No tags. No timestamps. Just the UUID the agent was assigned at first onboard.

- Written once, at first onboard.
- Read at every subsequent startup.
- Never re-derived, never looked up by label, never "resumed."
- Mode 0600. Not because the UUID is secret (it isn't — UUIDs are identifiers, not credentials), but for consistency with the general discipline of "files in `~/.unitares/` are owner-only."

If the file is missing: you're new. Call `/onboard`, receive a UUID, write the file. Done.

If the file exists: you are that UUID. Use it.

If the file contains a UUID the governance DB doesn't recognize (e.g., because the DB was reset): refuse to start. The operator's call whether to re-onboard; the agent doesn't get to decide silently.

## Instance taxonomy

| Instance type | What makes instances distinct | Anchor path | Who sets the path |
|---|---|---|---|
| **Resident** (Vigil, Sentinel, Watcher, Steward) | Role — one per host, forever | `~/.unitares/anchors/<name>.json` | hardcoded in agent module |
| **Session client** (Claude Code, Codex) | Per-session ID from the harness | `~/.unitares/sessions/<session_id>/anchor.json` | launcher sets `UNITARES_ANCHOR_PATH` env var |
| **Subagent / Task spawn** | Spawn ID (fresh UUID minted at spawn) | `~/.unitares/spawns/<spawn_id>/anchor.json` | parent process sets `UNITARES_ANCHOR_PATH` env var |
| **Dispatched worker** (Discord) | Dispatch ID per invocation | `~/.unitares/dispatches/<dispatch_id>/anchor.json` | dispatcher sets `UNITARES_ANCHOR_PATH` env var |

The SDK reads the anchor path from (in order):

1. `UNITARES_ANCHOR_PATH` env var — if set, authoritative.
2. Built-in resident default (only for agents that declare themselves residents) — `~/.unitares/anchors/<name>.json`.
3. Refuse to start.

There is **no fallback to a shared default path.** The shared `~/.unitares/session.json` is deleted by this design. A launcher that fails to set the anchor path is a launcher bug, not an excuse to inherit state.

## Why this kills inheritance

- **Shared-cache inheritance** (the 44e4d02b incident): Claude Code session B starts, its anchor path is `~/.unitares/sessions/<session_B_id>/anchor.json` — doesn't exist → fresh onboard → new UUID. Session A's file is elsewhere; B never sees it.
- **Subagent-carries-parent-UUID**: spawner sets `UNITARES_ANCHOR_PATH=~/.unitares/spawns/$(uuidgen)/anchor.json` in subagent env before exec. Child can't read parent anchor — different path.
- **Compaction-as-continuation**: explicit operator choice. Either the new post-compaction process is pointed at the old session's anchor (continuation) or given a fresh spawn path (new identity). The decision is made by whoever triggers the compaction, never by filesystem accident.
- **Restart-after-crash for residents**: resident re-reads its name-scoped anchor, continues as the same UUID. Which is correct — residents are supposed to be persistent.

## What this deletes

- **Continuity tokens.** No `continuity_token` field in requests, no HMAC signing, no `UNITARES_CONTINUITY_TOKEN_SECRET` env var, no plist secrets, no rotation cadence, no `jti`, no blocklist, no DPoP.
- **`resume` flag.** Every `onboard()` call is implicitly: "create if no anchor, resume if anchor exists." The flag becomes meaningless — the anchor's presence is the answer.
- **`force_new` flag.** Delete the anchor file → next run is new. No flag needed.
- **Session-ID-as-identity-key.** Session IDs remain useful for request correlation and observability, but they're no longer authoritative for identity.
- **`extract_token_agent_uuid` and its expiry-skip footgun.** No tokens → nothing to extract.
- **Name-based lookup (already deleted 2026-04-17).** Stays deleted.
- **HMAC fallback chain** (`UNITARES_CONTINUITY_TOKEN_SECRET` → `UNITARES_HTTP_API_TOKEN` → `UNITARES_API_TOKEN`). All three env vars deleted.
- **Most of `src/mcp_handlers/middleware/identity_step.py`.** Identity becomes a one-line lookup: `agent_uuid = request.arguments["agent_uuid"]`. Middleware's job is to validate that the UUID exists in the DB and that the agent is active, not to *derive* it.

Estimate: net deletion of 1500–2500 LOC across the repo.

## What this preserves

- **UUID registry** in `core.agents` table. Every UUID that's ever onboarded is a row. Status, label, tags, parent-agent, spawn reason — all retained as *descriptive* metadata, not credentials.
- **Audit log.** Every action records `agent_uuid`. No "authentication result" column because there is none — the UUID is the assertion.
- **Operational metadata.** Label ("Watcher"), tags ("persistent"), parent, spawn reason, thread membership — all still meaningful for observability and governance rules, but never consulted to *decide who this agent is*.
- **ACL table for authorization** (new, clean). `core.agent_roles(agent_uuid, role, granted_at, granted_by)`. Roles are operator-granted explicitly. No "claim a label, get a role." No "operator" role minted by anyone who isn't already an operator.

## Authentication vs. identification

UNITARES under this design does *identification*, not *authentication*. The two are distinct:

- **Identification**: the agent asserts "I am UUID X." The system records this.
- **Authentication**: the system proves cryptographically that the assertion is true.

For the declared threat model (threat class E — same-UID malicious — is out of scope; see `2026-04-19-identity-threat-model.md`), identification is sufficient. The trust boundary is the OS user. A process running as UID `cirwel` is trusted by the OS to be acting on behalf of that user; we don't add a second layer that would only matter if we didn't trust the OS.

For network-origin callers (claude.ai connector is the only real example today), identification alone is insufficient, and those paths carry bearer tokens. See §Exceptions.

## Authorization stays a server-side decision

Does UUID X have permission to do Y? Check the ACL table. This is independent of the identity layer:

```
SELECT 1 FROM core.agent_roles WHERE agent_uuid = $1 AND role = $2;
```

Roles are explicit grants by an operator. "Kenny's session can do admin" means Kenny's UUID is in `agent_roles` with role `admin`. There's no privilege that comes from the label string or tag contents.

This is how the `allow_operator` vulnerability (PR #51) is closed permanently: there's no path where a caller-supplied field affects authorization.

## Exceptions

**claude.ai connector** is a genuine bearer-token case because Anthropic's hosted MCP runs on the public internet and connects to our tunnel. The connector uses a long-lived PAT-style token, issued once, documented as "this is a trust-Anthropic point," rotatable on incident. Token is scope-limited (read/observe only) so a compromised connector can't act destructively. Audit log records origin=`claude.ai`.

This is the only exception. Everything local runs on anchor files.

## Migration plan

This is a phased transition, not a flag day.

**Phase 1 — SDK behavior** (additive, non-breaking):

- SDK reads `UNITARES_ANCHOR_PATH` env var when set. If set and the file exists, uses that UUID unconditionally. If set and file is missing, onboards fresh and writes.
- Default behavior (no env var) preserved for backward compat: reads from legacy paths.
- Launchers that want the new behavior start setting the env var.

**Phase 2 — Launcher migration** (per-launcher, independent):

- Claude Code plugin: `hooks/session-start` writes `UNITARES_ANCHOR_PATH=~/.unitares/sessions/${CLAUDE_SESSION_ID}/anchor.json` into the env consumed by MCP children.
- Codex plugin: same pattern, keyed on Codex's session identifier.
- Residents: plists already set per-name paths implicitly; make it explicit with `UNITARES_ANCHOR_PATH` in `EnvironmentVariables`.
- Discord Dispatch: each dispatch writes a fresh spawn path.

**Phase 3 — Delete the bearer-token stack** (after all launchers migrated and soak period):

- Stop issuing continuity tokens in `/onboard` responses.
- Delete `extract_token_agent_uuid`, `resolve_continuity_token`, HMAC secret plumbing.
- Delete `resume` and `force_new` flags from request schemas.
- Delete plist secrets.
- Delete session-cache scripts (both `unitares` and `unitares-governance-plugin` copies).

**Phase 4 — Delete the shared unslotted cache**:

- `~/.unitares/session.json` removed. Any launcher still relying on it is broken — the migration window at Phase 2 should have caught this.

The phases can span weeks. At no point is the system in a half-migrated state that can't identify agents; the old and new paths coexist during Phase 1–2.

## What this does not address

- **Supply-chain (malicious dep running as UID cirwel).** Still out of scope per the threat model (threat class E). If a compromised dep runs, it can read any anchor and assert any UUID. This design doesn't pretend otherwise.
- **Anthropic backend compromise.** Still out of our control. The claude.ai PAT is the only surface affected; rotating it is the only remediation.
- **Operational accidents.** A launcher that sets `UNITARES_ANCHOR_PATH` to the wrong directory will produce the wrong identity. Discipline over cleverness — the design relies on launcher correctness, not on the SDK guessing.

## Why this is simpler

The existing identity stack accreted around a question the deployment doesn't need to answer: "how do we cryptographically prove, over the network, that this caller is who they claim to be?" The answer involves HMAC secrets, continuity tokens, session IDs, resume flags, fallback chains, strict/permissive modes, and several layers of middleware trying to figure out what agent is on the other end of the call.

The deployment's actual question is: "how does this agent remember its own identifier across process restarts?" The answer is one file per instance. The complexity difference is orders of magnitude.

The security properties the old stack was trying to provide were mostly theater in this deployment anyway (see threat model for why). Dropping the ceremony and being honest that we do identification not authentication loses *no real defense* and gains a system that's understandable top-to-bottom.

## What changes operationally

- Deleting `~/.unitares/sessions/<id>/anchor.json` makes that session a new identity next run. Easy recovery.
- Moving an anchor file between hosts deliberately ports the identity. Also easy.
- Corrupted anchor file → agent refuses to start. Operator decides: restore from backup, or delete to force fresh onboard.
- No secret rotation drills. No token expiry surprises. No "why is the resume flag defaulting to X" bugs.

## Next steps

1. **Operator decision**: adopt this direction, adopt with revisions, or reject.
2. If adopted: write a Phase 1 implementation PR in `unitares-sdk` that adds `UNITARES_ANCHOR_PATH` support non-breakingly.
3. Sequence Phase 2 launcher migrations. Claude Code and Codex plugins first (highest inheritance blast radius). Residents next. Discord Dispatch last.
4. Once all migrated, Phase 3 deletion PRs across the three repos.
5. Update the threat model doc to reflect the simpler attack surface.

---

## Council Review Findings (2026-04-19)

Four independent subagents reviewed this doc: feasibility (grounded in code), migration-plan rigor, inheritance-claim red-team, prior-art comparison. Convergent findings:

### 1. Phase 2 is not implementable as written — blocker

The feasibility agent confirmed by reading `unitares-governance-plugin/hooks/session-start:1-172`: the plugin's SessionStart hook emits `additional_context` JSON. **It does not spawn the MCP child.** Claude Code starts MCP children from its own MCP config with env inherited from the operator's shell. The plugin has no channel to set `UNITARES_ANCHOR_PATH` on the MCP child process.

**Prerequisite that's missing from the doc**: ship a wrapper executable (e.g., `unitares-mcp-wrapper`) that Claude Code is configured to invoke as the MCP command. The wrapper reads the session-id from the hook payload (or a per-session state file), sets `UNITARES_ANCHOR_PATH`, then `exec`s the real governance server. Without this prerequisite, Phase 2 for Claude Code is aspirational.

Session-id stability across Claude Code compaction was separately verified via documented `SessionStart` hook spec (fires on `startup|resume|clear|compact` with stable `session_id` across compaction) — so *once* a wrapper exists, the compaction case works as the design claims.

### 2. Phase 0 is missing — Phase 1 is not actually additive

The migration-rigor agent's key finding: when the first session-client onboards under Phase 2 (new path), its anchor path is empty → fresh onboard → new UUID. **Every Claude Code session forks once at cutover.** The doc frames this as "correct behavior for per-session instances" but doesn't call it a fleet-size identity reset.

**Proposed fix (insert before Phase 1)**:

- **Phase 0**: server exposes `/identity/anchor_census` endpoint. SDK gets a *dual-write* mode — when started under legacy behavior, also writes the UUID to the future anchor path if `UNITARES_ANCHOR_PATH` is set. Legacy path stays authoritative.
- Operator runs census across existing `~/.unitares/*` files, builds a ground-truth map of "legacy → UUID → server state" *before* cutover.
- Phase 2 becomes "flip authoritativeness" rather than "onboard fresh" — the new anchor already contains the correct UUID from dual-write.
- Makes rollback through Phase 2 trivial (legacy path still populated).
- Makes "soak passed" measurable (anchor-census delta → 0).

### 3. "Eliminates inheritance" is overstated

The red-team agent walked through scenarios the design doesn't close:

- **Launcher path-collision bugs** — if a parent spawner uses non-unique spawn IDs (e.g., `hash(cwd)`), multiple subagents share an anchor. Same inheritance bug, new filesystem namespace.
- **Compaction-as-operator-choice** — there is no operator in the loop. Claude Code compaction is automatic; whoever writes the launcher bakes in the policy. Calling it "operator choice" is a documentation trick.
- **Copy / backup-restore** — operator `cp watcher.json vigil.json` or Time Machine restore propagates UUIDs into wrong slots. Anchor content is not self-describing (`{"agent_uuid": X}` doesn't say "for slot Y"), so the SDK can't cross-check.
- **Client-asserted UUID ≠ anchor content** — server-side, `identity_step.py` extracts `agent_uuid` from request arguments, not from the anchor file. A drifted/buggy SDK asserts the wrong UUID and the server has no cross-check (deleting continuity tokens removes the only current mechanism that does cross-check).
- **DB state inheritance** — the anchor is a shallow pointer; the UUID's real state (EISV history, check-ins, audit trail) lives in `core.agents`. Any vector that lands on the wrong UUID inherits full history.
- **In-process residents** — Steward runs inside `governance-mcp`. "File-per-instance" is undefined for threads in a shared process.
- **Cross-host UUID collision** — `~/.unitares/` synced to a second Mac (iCloud/Tailscale/backup restore) produces dual-assertion of the same UUID against one DB. Design doesn't address.

**Corrected claim** (the body of the doc should be revised to match): file-per-instance *eliminates automatic inheritance from shared filesystem caches (the 44e4d02b-class bug) and relocates the remaining inheritance vectors to launcher discipline and operator process*. Not "solves inheritance."

### 4. LOC estimate is plausible but undercounts collateral

The feasibility agent measured the identity layer and found:
- `src/mcp_handlers/identity/`: 3208 LOC
- `middleware/identity_step.py`: 454 LOC
- `schemas/identity.py`: 142 LOC
- `services/identity_payloads.py`: 270 LOC
- `thread_identity.py`: 159 LOC
- `agents/sdk/src/unitares_sdk/`: 1590 LOC
- Plugin scripts: 759 LOC combined

**Total candidate surface: ~6500 LOC.** 1500–2500 net deletion is plausible for the token/resume/force_new plumbing plus plugin scripts, but *understates collateral damage*: `derive_session_key` / `SessionSignals` is load-bearing beyond identity (sticky transport-binding cache, audit correlation, SSE plumbing). ~400-700 LOC of new plumbing needed to replace orphaned responsibilities. Realistic net: ~1500 LOC deletion, at the low end of the original claim.

Tests: **631 occurrences of `continuity_token|resume|force_new|client_session_id` across 50 test files.** Not accounted for in the migration plan. Conservatively 15-20 test files need rewriting; 5 deleted outright.

### 5. `extract_token_agent_uuid` has a real job the design hand-waves

Its docstring at `session.py:86-121` explicitly documents: a resident whose process has been idle 30+ days should still resume with a stale token rather than fork identity. Under file-per-instance, if the DB archives an inactive agent (tombstones the row) but the anchor file persists, the design says "refuse to start." That's a regression vs. current behavior. Needs spec work: either `archive_orphan_agents` becomes anchor-aware (cross-process invariant), or anchor-holders can get stuck.

### 6. Existing resident anchors are not UUID-only

Three of four current resident anchors (`sentinel.json`, `vigil.json`, `watcher.json`) contain `client_session_id` + `continuity_token` + `agent_uuid`. Only `steward.json` is UUID-only. Phase 3's "stop issuing tokens" breaks residents that actively refresh their anchor with the token returned from `/onboard` — needs audit of each resident's write-back path before Phase 3.

### 7. claude.ai connector PAT infrastructure doesn't exist

The doc says "connector keeps PAT-style token" as if PAT exists. It doesn't. Current connector rides `UNITARES_HTTP_API_TOKEN`/HMAC plumbing which Phase 3 deletes wholesale. **Phase 2.5 prerequisite**: build PAT verification surface (issuance, rotation, audit tagging, scope-limit enforcement) as an independent code path *before* Phase 3 removes HMAC.

### 8. Rollback is not possible post-Phase 2 without a fleet double

If Phase 2 ships with a subtle launcher bug and needs rollback, sessions that already onboarded under new paths have anchors at new paths. Rolling back the plugin → legacy code → next session reads `~/.unitares/session.json` → fresh UUID. No merge, no dedup. Only remediation is `archive_orphan_agents` sweeping half the fleet. Phase 3 is effectively irreversible once the HMAC secret is deleted.

**Phase 0 (census + dual-write) closes this** — if legacy is always authoritative through Phase 2, rollback is a config flip.

### 9. Operator failure surface is undefined

"SDK refuses to start" is stated as a safety property but never spec'd for operator visibility. Where does the error surface? Which log? What exit code? If the MCP child refuses to start, Claude Code's MCP client sees "server failed to connect" — no breadcrumb pointing at anchor config. Kenny debugs at 2am with no signal. Doc owes an operator-experience section.

### 10. Pi-side parity absent

Lumen runs on Raspberry Pi as user `pi` with systemd, not launchd. `unitares-pi-plugin` has no launcher that would carry `UNITARES_ANCHOR_PATH` into anima-mcp's env. Steward does Pi→Mac EISV sync; how does Pi's anima-mcp get its anchor? Phase 2 as written silently excludes the Pi.

### 11. Prior-art lineage should be named

The prior-art agent identified three systems the design directly parallels:

- **systemd `machine-id(5)`**: one file per instance, UUID, owner-only, empty-file convention ("empty means mint at first boot — ship VM templates with empty files so clones regenerate"). Design could adopt this directly.
- **Kubernetes object UIDs**: system-assigned, never reused, distinct from `name`, persist for lifetime; delete-and-recreate = new UID. Design already mirrors this.
- **W3C DIDs (`did:key`)**: holder-generated, self-controlled, no central registry needed for resolution. Design approximates this.

**Concrete patterns to adopt** (with zero cost):
- Empty-file convention from `machine-id(5)` — ship empty anchor in templates; populated anchor in a template means someone cloned a live machine and hasn't regenerated.
- Server-side active-UUID collision detection (K8s API-server pattern) — flag dual-assertion as an anomaly event. Costs one DB index. Catches the rsync-anchor-between-hosts case the design admits is open.
- DID-style `did:unitares:<uuid>` canonical form for external references / audit log.

The doc should also add an **explicit "non-choices" section** naming: why not mTLS, why not content-addressed hashes, why identification not authentication. The design's rejections of these patterns are deliberate and defensible but unnamed.

### 12. Realistic timeline

Not "weeks." Feasibility + migration agents converged on **10–14 weeks** for a solo operator given prerequisites (wrapper executable, Phase 0 census, PAT infrastructure, coordinated 4-repo releases with version-gate protocol). Every phase-boundary is a coordinated release across `unitares` + `unitares-governance-plugin` + `unitares-pi-plugin` + `discord-dispatch`.

### What to do with this

If a future operator revives this design:

1. Replace "eliminates inheritance" with "eliminates automatic inheritance from shared caches; relocates remaining vectors to launcher discipline."
2. Add **Phase 0 (census + dual-write)** as the load-bearing non-breaking prerequisite.
3. Add **wrapper-executable Phase 2 prerequisite** for Claude Code / Codex.
4. Add **Phase 2.5 (PAT infrastructure)** for claude.ai connector before Phase 3 HMAC deletion.
5. Add **Pi-side parity** analysis (systemd equivalent of launchd env plumbing).
6. Add **operator failure surface** spec (log path, exit codes, debug breadcrumb).
7. Add **non-choices** section (why not mTLS / content-addressed / authentication).
8. Adopt **empty-file convention** + **active-UUID collision detection** from prior art.
9. Name the **lineage**: systemd machine-id + K8s UIDs + DIDs, not invented.
10. Audit existing resident anchors (`sentinel.json`, `vigil.json`, `watcher.json` carry tokens today — migration must account for write-back path).
11. Spec resolution for `extract_token_agent_uuid`'s long-idle-resident job under the new model.
12. Replace "weeks" with realistic 10-14 week estimate + prereq checklist.
