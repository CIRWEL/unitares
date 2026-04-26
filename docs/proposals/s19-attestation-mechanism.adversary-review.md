---
title: Adversary stress-test review — s19-attestation-mechanism.md
reviewer: feature-dev:code-reviewer (subagent dispatch 2026-04-25)
date: 2026-04-25
status: M3 confirmed in principle; threat-model refinement required before code opens; adversary-matrix over-claims must be qualified
---

# S19 Attestation Mechanism — Adversary Review

**Reviewing:** `docs/proposals/s19-attestation-mechanism.md`
**Reviewer role:** adversary stress-test, council-review gate (S19 resolved-when (f))

---

## Critical Issues

### 1. Q3 Variant (b): launchctl bootstrap is a real same-UID capability — M3 does not cleanly defeat it

**Confidence: 92**

The proposal lists variant (b) — "spawn a process under the resident's launchd label by invoking `launchctl bootstrap` / `launchctl kickstart`" — as the harder case and then defers judgment to the reviewer. The answer is: this is a genuine same-UID capability that M3's label-match step does not defeat alone.

On macOS, a user-space process running as the same UID as the LaunchAgent owner can call `launchctl kickstart user/$(id -u)/com.unitares.sentinel` without elevation. This restarts the actual Sentinel job under the correct launchd label. If the attacker can control what binary that label points to (e.g., by swapping the binary at the plist-referenced path before kickstarting), the process that spawns will have a kernel-attested peer PID belonging to a process with the correct `com.unitares.sentinel` label. M3's label-match step would then return "accept."

The key gate M3 does impose is: the `launchctl kickstart` path restarts the *actual* launchd service entry — the attacker cannot spawn an *arbitrary* binary under that label without modifying the plist or the binary path. Modifying either requires write access to the plist (mode 644 under `~/Library/LaunchAgents/`, same-UID writable) or write access to the referenced binary (also same-UID writable if in a user-writable path).

The proposal's over-claim is calling M3's defeat of (b) implicit. The defeat is conditional: M3 closes (b) only when the binary path in the plist is not same-UID writable. For a development Mac where the binary is at `~/projects/unitares/...` or any user-writable location, the same-UID attacker can replace the binary before issuing `launchctl kickstart`. The proposal does not name this dependency. **This is not a marginal concern: the binary for all four residents lives in a user-writable directory (`~/projects/unitares/` tree) on this machine.**

Concrete fix: the proposal must either (a) state explicitly that M3's defeat of (b) requires the resident binary to live in a non-user-writable path (e.g., `/usr/local/bin/` or `/opt/homebrew/bin/`), or (b) add a fourth check that the peer PID's executable path matches an operator-registered expected binary path (queryable same-UID via `proc_pidpath()` in macOS). The substrate-claim registry row `(agent_uuid, expected_launchd_label, enrolled_at)` should also store an `expected_executable_path` field.

The proposal's adversary-mechanism table ("A1, A2 defeated" for M3) is too strong without this caveat. M3 with label-match-only is incomplete against a same-UID attacker who can write to the binary path.

---

### 2. A2 Walk-through: M3 does defeat A2, but the path requires a more careful statement

**Confidence: 85**

Walking the A2 attacker step-by-step under M3:

1. Attacker reads `~/.unitares/anchors/sentinel.json` — gets `agent_uuid` (and formerly `continuity_token`; under M3 the anchor collapses to UUID-only, so the token is gone from the attack surface at this layer, which is genuine progress).
2. Attacker cannot connect via UDS and forge `SO_PEERCRED` — the kernel writes peer PID/UID at `accept()` from the kernel side; there is no user-space operation to alter it. Correct; this is a real kernel guarantee on macOS.
3. Attacker's process connects to the UDS. Its peer PID belongs to a process that is *not* under any launchd label (or the wrong one). Server's launchctl query returns no matching label. Reject. A2 in the naive form is defeated.
4. Escalated A2: attacker performs step (b) above — replaces binary, kickstarts the service. Now the peer PID is the attacker-controlled binary running under the correct launchd label. M3 accepts.

So M3 defeats naive A2 (copy anchor + connect directly) fully. It is the escalated A2 via (b) that survives if the binary path is user-writable. The proposal presents M3 as defeating "A2 (copy + replay)" unconditionally. That is an over-claim relative to the actual threat model. The correct statement is: **M3 defeats A2 as long as the resident binaries are not world- or same-UID-writable by a process that isn't the governance system itself.** That constraint must be in the proposal.

---

### 3. Q3 Variant (e): PID reuse race is real and M3's mitigation is unspecified

**Confidence: 88**

The proposal identifies variant (e) (PID reuse race) as requiring "server-side cache + nonce or short re-verify window," then leaves both options undefined. This is an honest flag, not a resolution.

The race is: resident process exits → short window → attacker process starts and reuses the same PID → attacker connects to the UDS → server calls `launchctl print pid/<PID>` → the PID now belongs to the attacker's new process; launchctl may (a) return stale data if launchd hasn't yet noticed the exit, (b) return the attacker's process label if the attacker got a launchd-managed PID somehow, or (c) return an error.

The most dangerous subcase: launchd's per-user bootstrap session hasn't yet reaped the previous job when the attacker connects; `launchctl print pid/<OLD_PID>` still returns the prior label. Window is kernel-scheduling-scale (milliseconds to seconds). On a loaded system this is a real race.

The correct mitigation for continuous daemons (Sentinel, Vigil) is a server-side verified pair cache: on first successful attestation, server stores `(agent_uuid, pid, pid_start_time)` and re-verifies start-time on subsequent connects. The `pidinfo` / `proc_pidinfo` macOS syscall returns `pbi_start_tvsec` — the process start time, which cannot be reused: even if PID is recycled, a new process has a different start time. This is the correct nonce-free mitigation and should be stated as the required implementation, not left open.

The proposal says "needs server-side cache + nonce or short re-verify window" but does not pick one. That leaves (e) as a known-open gap in the threat model. If the reviewer pass exists to close open questions before code, this one must be closed.

**Required resolution:** M3 implementation must query process start time alongside peer PID via `proc_pidinfo(PROC_PIDTBSDINFO)` on macOS (equivalent: `/proc/<pid>/stat` start time on Linux) and store the `(uuid, pid, start_tvsec)` triple in the substrate-claim registry on first successful connect. On each subsequent connect, if the PID matches but `start_tvsec` differs, reject.

---

### 4. Watcher: M3 scope is narrower than stated — Watcher is outside M3

**Confidence: 95**

The proposal includes Watcher in scope but immediately acknowledges it is event-driven with no launchd label. Q4 says "there may be no launchd label to query." There is no label. The proposal does not resolve this.

`hooks/post-edit` invokes `agents/watcher/watcher-hook.sh` via a PostToolUse Claude Code hook — this is a shell script spawned by Claude Code's hook machinery, not by launchd. There is no `com.unitares.watcher` launchd job that the launchctl introspection would find. `launchctl print pid/<watcher_pid>` on Watcher's per-invocation process would return an error or the caller's bootstrap session context, not a stable service label.

M3 as described does not work for Watcher. The proposal lists Watcher as in-scope and lists M3 as the recommendation for all four residents. **This is an internal inconsistency the proposal itself flags but does not resolve.**

Options: (a) Watcher is explicitly excluded from substrate-claim attestation and continues under the session-like path (the least disruption; Watcher's per-invocation lifespan and the hook-driven identity pattern make it ontologically closer to the session-like class anyway — see `identity.md` worked examples: "Watcher — weak [behavioral continuity] — bound to LLM call, not trajectory"); (b) Watcher's anchor becomes a per-invocation onboard with `force_new + parent_agent_id` (B-relaxed posture for Watcher specifically); (c) the hook machinery is changed to invoke Watcher via a launchd-managed wrapper, making the label queryable.

Option (a) is honest and cheap. The proposal should say: **Watcher's scope is excluded from M3; it follows B-relaxed or session-like semantics per invocation.** Failing to say this leaves the code author guessing.

---

### 5. Chronicler: M3 works but the enrollment lifecycle is different from what the proposal implies

**Confidence: 80**

Chronicler is launchd-daily (`com.unitares.chronicler`) and short-lived per invocation. M3 is structurally applicable: when Chronicler's daily job fires, its PID is under the launchd label, `SO_PEERCRED` captures it kernel-side, and `launchctl print pid/<PID>` returns the correct label.

However, the PID pinning cache described in the (e) mitigation section has a different lifecycle. For continuous daemons (Sentinel, Vigil), the `(uuid, pid, start_tvsec)` triple is stable for days-to-weeks between restarts. For Chronicler, it changes daily. The enrollment registry row `(agent_uuid, expected_launchd_label)` is stable; the cache entry turns over daily. The server must not reject Chronicler's daily re-attestation as a "stale triple" — the re-verify step applies on-connect within a single process lifetime, not across invocations.

This is a correctness concern for the implementation, not a conceptual flaw in M3. The proposal should state it explicitly so the implementation doesn't apply the continuous-daemon re-verify logic to short-lived launchd residents.

---

## Important Issues

### 6. TOFU bootstrap: the proposal flags it honestly but understates the severity

**Confidence: 83**

The proposal acknowledges TOFU as an open question between first-onboard registry creation versus operator pre-seed. From an adversary angle:

If first-onboard creates the registry row, the attacker who beats the legitimate resident to the first connect owns the substrate-claim permanently (until an operator manually clears it). On a development Mac where governance-mcp and the residents start together at deployment time, this is a narrow but real race. The window is: governance-mcp finishes starting and begins accepting UDS connections, resident process not yet connected, attacker connects first. This is not an abstract race — anything running as the same UID at deployment time (another agent dispatch, a Claude Code session, etc.) could connect first.

Operator pre-seed is materially safer, not just operationally more painful. The difference: pre-seed means the registry row exists before governance-mcp is accepting connections for attestation; there is no race. TOFU means the first connecting process under any given launchd label wins the uuid-binding. Pre-seed is achievable with one CLI invocation per resident at initial deployment and on any registry rebuild; the operational cost is one `enroll-resident.sh` call per resident, not per restart.

The proposal should recommend operator pre-seed as the default and TOFU as an explicitly opt-in degradation mode with a logged warning, not leave it as an open question.

---

### 7. Q2 (launchctl introspection stability) is left unverified

**Confidence: 81**

The proposal explicitly asks the reviewer to verify `launchctl print pid/<PID>` on the running macOS. This review cannot perform live shell execution (operating as a read-only reviewer). What can be assessed from the proposal text:

The mechanism's assumption that `launchctl print pid/<PID>` returns a stable parseable format across macOS versions is reasonable in principle but has a concrete historical risk: Apple changed `launchctl print` output between macOS Monterey and Ventura, and between Ventura and Sonoma. The output is a human-readable dictionary blob, not a stable structured format. Parsing the label out with a regex or line-grep is fragile; the correct approach is `SMJobCopyDictionary` from `ServiceManagement.framework` (private-ish but stable since macOS 10.6) or the `launchctl procinfo <PID>` subcommand (available macOS 13+, machine-readable).

The proposal should note: if the governance-mcp implementation uses subprocess `launchctl print` + string parsing, it must include a format-version check and a test against the exact macOS version in production. If it uses `ServiceManagement.framework` or `proc_pidinfo` with the BSD task info, these are more stable.

This is not a blocker for M3's design, but it is a blocker for a naive subprocess-based implementation.

---

## Over-Claim Audit

The proposal uses "kernel-attested" correctly for `SO_PEERCRED` / `LOCAL_PEERCRED` peer PID — the kernel writes this field, user-space cannot forge it. This is accurate.

The proposal uses "non-exportable" in the S19 row in `plan.md` (line describing viable strict forms) but does not apply that term to M3 — correctly, because M3 does not use a non-exportable key. M3 makes no claim of non-exportability. No over-claim here.

The adversary-mechanism matrix at the proposal's §"Adversary × Mechanism matrix" marks M3 as "✓ defeats" against both A1 and A2. As shown in findings 1 and 2 above, this is accurate for A2 in the naive form but inaccurate for A2 in the escalated form with binary substitution. The table over-claims unless qualified.

The proposal's claim that "no client-declared fields are trusted" under M3 is accurate for the transport layer (peer PID is kernel-attested) but does not extend to the binary's content — M3 cannot verify that the binary under the launchd label is the unmodified resident, only that a process is running under that label.

---

## M3 vs. A-with-server-side-nonce: Is the transport change justified?

The plan.md appendix entry "2026-04-25 — S19 framing" explicitly addresses this: "A well-behaved client sends accurate values; a leaky/malicious one sends what it wants. Without server-side pre-registration (e.g., a nonce minted at process-start, stored Redis-side, matched at resume), Hermes-style leaks remain possible — the leaking process just copies the PID claim too."

A-done-right requires the server to mint a nonce at process-start that only the legitimate process can obtain, and the legitimate process to present that nonce at resume. But: how does the server deliver the nonce to the process at start-time without an authenticated channel? The bootstrap problem is: if the nonce is written to a file at `~/.unitares/nonces/sentinel.nonce`, a same-UID process can read it — same problem as the anchor token. If the nonce is passed via an environment variable in the launchd plist, same-UID launchctl introspection can read plist env vars. If the nonce is passed via a UDS at process-start, we've already committed to UDS transport.

The gap between A-done-right and M3 is not small. A-done-right requires a channel for nonce delivery that same-UID processes cannot read — and the only candidate channels are (a) UDS peer-credential binding (i.e., M3 without the label check, which is just M2) or (b) non-exportable keys (M4). A without a secure delivery channel is also declaration-only.

Therefore: the UDS transport change is not overhead for M3; it is the mechanism that makes any nonce-based approach honest. M3 is the correct minimal commitment. A-done-right degrades to M2 or M4 at implementation time. The cost-benefit does favor M3 as described.

---

## Verdict

**Is M3 honest about what it defeats?**

Partially. M3 correctly defeats naive A1 and A2. It is honest that peer PID is kernel-attested. It is not honest in the adversary-matrix about the binary-substitution escalation of A2 via Q3(b). The phrase "A1, A2 defeated — Strongest minimal mechanism short of TPM" is too strong without the binary-path constraint caveat.

**Recommendation:**

Refine the threat model, then ship M3.

Specifically, before any code:

1. Add to the substrate-claim registry schema: `expected_executable_path TEXT` alongside `expected_launchd_label`. Enrollment CLI verifies the binary path is in a non-user-writable location or warns loudly if not. On this Mac, residents running from `~/projects/unitares/` fail that check and should be flagged as deployment-configuration weak spots, not silently attested.

2. State explicitly in the proposal: M3 defeats Q3(b) only when the resident binary is not same-UID-writable. If it is (current state on this Mac), M3 is still stronger than the status quo but the residual Q3(b) risk must be documented as an accepted deployment constraint, not hidden.

3. Close Q3(e) by specifying `proc_pidinfo(PROC_PIDTBSDINFO).pbi_start_tvsec` as the required additional field in the `(uuid, pid, start_tvsec)` server-side cache entry.

4. Narrow Watcher's scope explicitly: Watcher is excluded from M3; it follows B-relaxed (per-invocation `force_new` with `parent_agent_id`) or session-like semantics. Remove Watcher from M3's "defeated" column.

5. Specify operator pre-seed as the default enrollment path, not TOFU.

6. For Chronicler: note the daily cache-entry rotation behavior as distinct from continuous daemon semantics.

None of these changes require a different mechanism. M3 (UDS + `SO_PEERCRED` + launchctl label match + executable path verification + process start-time cache) is the right answer for Sentinel, Vigil, and Chronicler. The proposal is honestly structured; the required refinements are additive clarifications, not a design change.

**M3 should not be marked as defeating A2 unconditionally in the adversary matrix until the binary-path constraint and process-start-time nonce are added.** With those additions, the "strongest minimal mechanism short of TPM" claim holds.
