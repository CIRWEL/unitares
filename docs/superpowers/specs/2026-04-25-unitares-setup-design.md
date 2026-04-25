# Design: `scripts/install/setup.py` — guided UNITARES install

**Status:** Spec, awaiting implementation
**Author:** Kenny Wang + Claude Code (council-reviewed by `dialectic-knowledge-architect` and `feature-dev:code-reviewer` 2026-04-25)
**Companion:** `scripts/dev/unitares_doctor.py` (shipped 2026-04-25, commits `b699c443` + `7bad1405`)

## Goal

Provide a guided, inspectable user-install path for UNITARES that an external adopter (or Kenny on a second MacBook) can run without reading half of `docs/`. The wizard *plans* the install — it prints exact remediation commands and copy-pasteable MCP-client snippets. With `--apply` it makes the minimum filesystem mutations (anchor dir, secrets-file scaffold) needed for the install to be functional.

Non-goal: replace the operator-tier install (HTTP, launchd, Tailscale, cloudflared). That stays manual and undocumented-in-setup.

## Non-magical posture (load-bearing)

UNITARES is governance infrastructure. Its thesis is "agents shouldn't mutate state without an audit trail." A setup script that auto-runs Postgres SQL, installs system packages, or rewrites client configs would contradict the product. **Setup prints commands; the user runs them.** This is intentional and must be defended against future "--auto-fix" requests.

The two filesystem mutations under `--apply` are bounded exceptions:
- `~/.unitares/` (anchor directory) — read by every governance call; nothing meaningful can happen without it.
- `~/.config/cirwel/secrets.env` (mode 0600 template) — small enough to fully template; the alternative is the user having to read three docs to learn the path and mode.

Both are reversible (`rm -r`). No SQL, no client-config edits, no `brew install`.

## Shape

Standalone Python script, stdlib + already-installed deps only. Lives at `scripts/install/setup.py`.

```
python3 scripts/install/setup.py            # interactive, dry-run by default
python3 scripts/install/setup.py --apply    # mutate the two paths above
python3 scripts/install/setup.py --json     # machine-readable plan, no prompts
```

`--json` and `--apply` may combine. Default `--apply` requires the user to type `yes` after the plan is shown. `--non-interactive` skips that prompt (for CI / second-machine bootstrapping).

### Bootstrap prerequisite (Phase 0)

Setup's very first action: verify the MCP SDK is importable.

```python
try:
    import mcp  # noqa
except ImportError:
    print("Run: pip install -r requirements-full.txt")
    sys.exit(2)
```

The doctor is stdlib-only so it can run pre-install. Setup is not — it depends on the same MCP SDK the server needs, because the snippet generation calls into config-shape utilities. If `import mcp` fails, exit before doing anything else.

## Pipeline

### Phase 1 — Server checks via doctor

Setup spawns `python3 scripts/dev/unitares_doctor.py --json --mode=local` as a subprocess. It captures stdout, parses JSON. The doctor's `--json` path always emits a complete payload before exiting; nonzero exit codes are normal (any local check failed) and must not be treated as an error by setup.

For each `fail` or `warn` in `results`, setup emits a remediation block:

| Doctor finding | Remediation block |
|---|---|
| `postgres_running: fail` | `brew install postgresql@17 && brew services start postgresql@17` |
| `governance_database: fail` | `createdb -h localhost -U postgres governance` |
| `pg_extensions: fail (missing X)` | `psql -U postgres -d governance -f db/postgres/init-extensions.sql`<br>**Note:** AGE + pgvector require superuser; the `-U postgres` is intentional, not `-U $USER`. |
| `schema_migrations: fail` | List of `psql` commands derived from scanning `db/postgres/migrations/` in lexical order, plus `db/postgres/schema.sql` and `db/postgres/knowledge_schema.sql` if not yet applied. |
| `secrets_file: warn` (missing) | Under `--apply`: setup creates `~/.config/cirwel/secrets.env` (mode 0600) with a commented template. Otherwise: prints the file content for manual creation. |
| `secrets_file: fail` (wrong mode) | `chmod 600 ~/.config/cirwel/secrets.env` |
| `anchor_directory: warn` (missing) | Under `--apply`: setup creates `~/.unitares/` with mode 0o700 (explicit, not umask-dependent). Otherwise prints `mkdir -m 700 ~/.unitares`. |

Setup does NOT install Postgres, run SQL, or invoke `brew`. Every command is the user's to run.

### Phase 2 — Filesystem scaffolding (`--apply` only)

Two writes:

1. `~/.unitares/`: `Path.mkdir(mode=0o700, parents=True, exist_ok=True)`. The mode is explicit because the default mkdir mode is `(0o777 & ~umask)` and on a typical Mac dev machine with `umask 022` that's 0o755 — world-readable. The anchor dir holds session state; world-readable is wrong.

2. `~/.config/cirwel/secrets.env`: created if missing, with mode 0o600 set explicitly via `os.chmod` after write. Content is a commented template:

```bash
# UNITARES external secrets — mode 0600, never commit.
# Used by handlers that call out to LLM providers.
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
```

If the file already exists, setup leaves it alone — it does not overwrite. The doctor still flags wrong-mode separately.

### Phase 3 — MCP client detection + snippet generation

Setup probes for installed MCP clients by checking known config paths:

| Client | Detection path | Config target |
|---|---|---|
| Claude Code | `~/.claude/` | `~/.claude/settings.json` (`mcpServers` key) |
| Codex | `~/.codex/` | `~/.codex/config.toml` (`[mcp_servers.unitares-governance]` table) |
| Gemini CLI | `~/.config/gemini/` | `~/.config/gemini/settings.json` (`mcpServers` key) |
| Copilot CLI | `~/.config/github-copilot-cli/` | format speculative; print TODO note, don't fail |

For each detected client, setup prints a copy-pasteable snippet pointing at the local stdio entry point:

```json
"unitares-governance": {
  "command": "python3",
  "args": ["<ABS_REPO_ROOT>/src/mcp_server.py", "--stdio"],
  "env": {"DB_POSTGRES_URL": "postgresql://postgres:postgres@localhost:5432/governance"}
}
```

`<ABS_REPO_ROOT>` is derived from `Path(__file__).resolve().parent.parent.parent` — the same three-parent-step pattern doctor uses. This is robust against `cd`, symlinks, and worktrees. **Comment in the code documents the derivation explicitly** to discourage future "simplification".

Setup does NOT modify client config files. It detects, prints, points at the right config path. The user pastes manually. This boundary is non-negotiable: governance does not silently rewrite user files.

### Phase 4 — Final doctor pass

After phase 2's mutations, setup re-runs `unitares_doctor.py --json --mode=local` and prints the result. This confirms the install is at least *self-consistent* — anchor dir present, secrets file mode correct, etc. It does not prove the server actually runs (that requires the user to run it).

### Phase 5 — Next steps

Print the canonical post-install sequence:

```
1. Restart your MCP client(s) to pick up the new mcpServers entry.
2. (Optional) Run `python src/mcp_server.py --port 8767` to start the HTTP server.
3. Verify with `scripts/unitares health`.
4. Read docs/guides/START_HERE.md for the agent-side workflow.
```

The HTTP-server invocation matches CLAUDE.md's setup section verbatim.

## Companion change: `--stdio` rejection in `mcp_server.py`

The snippet above points at `python3 .../src/mcp_server.py --stdio`. Today, `mcp_server.py` accepts `--port` and runs HTTP only. If a user pastes the snippet and restarts their client, the server starts in HTTP mode and the client tries to talk stdio to it; the result is silent failure that produces no actionable error.

To convert silent-broken into loud-immediate, **the same PR adds a `--stdio` flag to `mcp_server.py`'s argparse that errors out**:

```python
parser.add_argument("--stdio", action="store_true",
                    help="(reserved) stdio MCP transport — not yet implemented")
# ...
if args.stdio:
    parser.error(
        "--stdio is not yet implemented. "
        "Run `--port 8767` for HTTP transport, or check "
        "docs/superpowers/specs/2026-04-25-unitares-setup-design.md "
        "for the stdio plan."
    )
```

This is ~8 lines, ships in the same change, and converts the failure mode. Real stdio implementation is its own piece of work, gated by a separate spec.

## `--json` output schema

Pinned schema, versioned envelope:

```json
{
  "schema_version": 1,
  "doctor_initial": { /* doctor's full --json output, phase 1 input */ },
  "plan": [
    {"phase": 1, "kind": "remediation", "finding": "postgres_running",
     "command": "brew install postgresql@17 && brew services start postgresql@17",
     "applied": false},
    {"phase": 2, "kind": "mkdir", "path": "/Users/.../.unitares",
     "mode": "0o700", "applied": false},
    {"phase": 3, "kind": "snippet", "client": "claude_code",
     "config_path": "/Users/.../.claude/settings.json",
     "snippet": "..."}
  ],
  "doctor_final": null,
  "exit_code": 0
}
```

Under `--apply`, `applied: true` is set per item that actually mutated. `doctor_final` is populated after phase 4. `exit_code` is 0 if all phase-1 doctor checks pass after phase 4, 1 otherwise.

CI consumers (and Kenny's second-MacBook test scripts) can rely on this shape; bumps are versioned via `schema_version`.

## Idempotency

Re-running setup must be safe. Invariants:

- Phase 1: doctor is read-only.
- Phase 2: `mkdir(exist_ok=True)`, `if file.exists(): skip`.
- Phase 3: print-only.
- Phase 4: doctor is read-only.

A second `--apply` run on a healthy install prints a plan with all `applied: false` items (because the work is already done), runs phase 4, and exits 0. **This is tested.**

## Tests

`tests/test_setup_install_script.py` — mirrors `tests/test_unitares_doctor_script.py`'s pattern exactly:

- Load setup as a module via `importlib.util.spec_from_file_location` + `sys.modules` registration (Python 3.14 dataclass requirement, captured by the doctor tests).
- Patch `setup.run_doctor()` (the internal subprocess wrapper) rather than `subprocess.run` globally.
- Use `tmp_path` for filesystem mutations; never touch real `~/.unitares/` or real client configs.
- ~10 tests covering:
  - Phase 1: doctor JSON parses correctly; nonzero exit + valid JSON is not an error
  - Phase 1: each remediation block content matches the doctor finding
  - Phase 2 dry-run: no filesystem writes
  - Phase 2 `--apply`: anchor dir created with mode 0o700
  - Phase 2 `--apply`: secrets file created with mode 0o600 + correct template content
  - Phase 2 `--apply`: existing secrets file not overwritten
  - Phase 3: snippet generation for each detected client; correct absolute path derivation
  - Phase 3: gracefully handles missing client paths
  - Idempotency: second `--apply` run on healthy state produces all `applied: false`
  - `--json` schema: emitted JSON validates against the pinned shape

## File layout

```
scripts/install/setup.py                              (new, ~450 lines)
scripts/install/__init__.py                           (new, empty)
src/mcp_server.py                                     (modified: --stdio rejection)
tests/test_setup_install_script.py                    (new, ~180 lines)
docs/superpowers/specs/2026-04-25-unitares-setup-design.md  (this doc)
```

No changes to `scripts/dev/unitares_doctor.py`, `scripts/unitares`, or `db/postgres/`.

## Out of scope (deliberately, for v0)

- Postgres auto-install (brew, apt, etc.)
- SQL execution by setup itself
- Client config file mutation
- `curl ... | bash` installer (hermes-style — separate spec, depends on this)
- Non-Mac platforms (Linux, WSL2)
- Operator-tier setup (HTTP launchd plist, Tailscale, cloudflared, IPv6 sidecar, resident agents)
- Uninstall / rollback (pattern noted; not implemented; revisit when filesystem mutations broaden)
- Real stdio transport in `mcp_server.py` (this spec lands the rejection flag only; a separate spec covers the implementation)

## Acceptance criteria

1. `python3 scripts/install/setup.py` on a fresh second MacBook (Postgres + AGE + pgvector + repo cloned + deps installed) produces a plan with zero `fail` items and exits 0.
2. `python3 scripts/install/setup.py --apply` on the same machine creates `~/.unitares/` (0o700) and `~/.config/cirwel/secrets.env` (0o600 template) and re-runs doctor showing all-pass.
3. The printed Claude Code snippet, pasted into `~/.claude/settings.json`, causes Claude Code to attempt the stdio connection. The server (run via `--stdio`) errors with the rejection message instead of silent broken.
4. `pytest tests/test_setup_install_script.py` passes.
5. `python3 scripts/install/setup.py --json | jq .schema_version` returns `1`.

## Decisions deferred

- **Real stdio implementation in `mcp_server.py`.** Separate spec. Likely lands shortly after this; the rejection flag is a short-lived bridge.
- **Auto-write client configs (`A+B hybrid` from brainstorm).** If snippet-paste UX proves unbearable for adopters, revisit. Not in v0.
- **`curl | bash` installer.** Depends on the repo being public + this spec landing + adopter demand. Tracked separately.
