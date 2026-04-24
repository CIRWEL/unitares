# Cross-Machine Install Surface

A grep-derived inventory of every value in this repo that varies between machines, plus an explicit list of values that **intentionally** vary and must not be unified.

**Audit date:** 2026-04-24 against `chore/install-audit` branch.
**Scope:** unitares server only. Pi-side anima-mcp deferred to v2.
**Acceptance:** the install playbook (`docs/install/PLAYBOOK.md`) must not assume any value classified MUST-FIX below.

---

## How to use this doc

Every entry has a **disposition**:

- **OK** — already env-var overridable with a sensible default; safe for a stranger's box.
- **MUST-FIX** — operator-specific value shipping as a default; will mislead or break a fresh install.
- **TEMPLATE** — file is a template that needs `__VAR__` substitution at install time.
- **INTENTIONAL** — varies by design; do not unify (see *Intentional Heterogeneity* below).

When adding new files that touch any of the patterns in *Audit Patterns*, re-check this doc and add an entry.

---

## MUST-FIX (operator-specific defaults)

These values bake one operator's environment into code that ships to others. Each must change before a stranger install will work.

| File | Line | Value | Fix |
|------|------|-------|-----|
| `scripts/ops/start_unitares.sh` | 14 | `UNITARES_MCP_ALLOWED_HOSTS` default = `192.168.1.151:*,192.168.1.164:*,100.96.201.46:*,gov.cirwel.org` | Default to empty (loopback-only); document opt-in env var |
| `scripts/ops/start_unitares.sh` | 15 | `UNITARES_MCP_ALLOWED_ORIGINS` default = same LAN/Tailscale/`gov.cirwel.org` set | Same as above |
| `scripts/ops/start_unitares.sh` | 37 | Prints `https://gov.cirwel.org/v1/tools` example | Use `${UNITARES_PUBLIC_URL:-http://localhost:$PORT}` |
| `scripts/ops/start_unitares.sh` | 121 | Prints `Tunnel: https://gov.cirwel.org/mcp/` unconditionally | Only print when `CLOUDFLARE_TUNNEL_HOSTNAME` is set |
| `scripts/ops/start_server.sh` | 60 | Same `gov.cirwel.org` example string | Same as start_unitares.sh:37 |
| `scripts/ops/health_watchdog.sh` | 28 | Hardcoded Pi Tailscale IP `100.79.215.83` | `${ANIMA_HEALTH_URL:-}`; skip anima check if unset |
| `scripts/ops/answer_lumen_questions.py` | 19 | Default `https://lumen.cirwel.org/mcp/` | Require `PI_MCP_URL`, error if unset |
| `scripts/ops/answer_lumen_questions.py` | 84 | Hardcoded Pi LAN IP `192.168.1.165` | Same — env-var-required |
| `requirements-core.txt` | 22 | Comment example uses `https://gov.cirwel.org/v1/tools` | Use `https://your-host.example/v1/tools` |
| `scripts/ops/com.unitares.ipv6-loopback-proxy.plist.template` | 33 | Hardcoded `/Users/cirwel/projects/unitares/scripts/ops/ipv6_loopback_proxy.py` | Use `__UNITARES_ROOT__` placeholder (matches chronicler template convention) |

---

## TEMPLATE GAP (gitignored plists with no in-repo template)

`.gitignore` excludes `scripts/ops/*.plist` because installed copies contain secrets. Only three templates are tracked: `governance-mcp.plist` (sanitized), `chronicler.plist.template`, `ipv6-loopback-proxy.plist.template`. The four below exist on the operator's disk but **a stranger has nothing to copy from**.

| LaunchAgent | Status | Fix |
|------------|--------|-----|
| `com.unitares.governance-mcp.plist` | Tracked, sanitized with `/PATH/TO/UNITARES`, `GENERATE_YOUR_OWN_TOKEN` | Rename to `.template` for naming consistency (low priority) |
| `com.unitares.chronicler.plist.template` | Tracked template using `__UNITARES_ROOT__`, `__HOME__` | OK |
| `com.unitares.ipv6-loopback-proxy.plist.template` | Tracked template, but hardcodes `/Users/cirwel/...` (see MUST-FIX above) | Convert to `__UNITARES_ROOT__` |
| `com.unitares.sentinel.plist` | **Gitignored — no template tracked** | Create `.template` |
| `com.unitares.vigil.plist` | **Gitignored — no template tracked** | Create `.template` |
| `com.unitares.gateway-mcp.plist` | **Gitignored — no template tracked** | Create `.template` |
| `com.unitares.governance-backup.plist` | **Gitignored — no template tracked** | Create `.template` |

---

## ARCHITECTURE GAPS (block stranger install entirely)

Beyond per-line edits, two structural issues will prevent a fresh install:

1. **`unitares-core` is a private compiled wheel.** `pyproject.toml:14` instructs symlinking from `~/projects/unitares-core/governance_core`, which only exists on Kenny's machine. CI uses `UNITARES_CORE_TOKEN` (`.github/workflows/tests.yml:20,68`); fork PRs can't run CI. **Decision in flight: publish `unitares-core` to PyPI / public GitHub.** Until that ships, any third-party install fails at `pip install -r requirements-full.txt`.
2. **Apple Silicon assumed in scripts.** `/opt/homebrew/opt/postgresql@17/bin` is hardcoded in:
   - `scripts/ops/emergency_fix_postgres.sh:6`
   - `scripts/ops/backup_governance.sh:10`
   - `scripts/ops/start_with_deps.sh:12`
   - `db/postgres/README.md:30` (instructional, but no Intel alternative shown)

   On an Intel Mac the prefix is `/usr/local/opt/postgresql@17/bin`. **Fix:** replace each with `PG_BIN="$(brew --prefix postgresql@17)/bin"`. The `chronicler.plist.template:48` PATH already covers both prefixes — pattern to follow.
3. **Apache AGE has no Homebrew formula.** `db/postgres/README.md` walks through `git clone apache/age && make && make install` against `pg_config`. Real failure modes: Xcode CLT missing; `bison`/`flex` versions mismatch; AGE tag not pinned to a known-good against PG 17. The install playbook needs to pin AGE 1.7.0 explicitly and surface build failures with a link to the AGE issue tracker.

---

## OK (already env-var overridable, defaults are correct)

These appear in the audit but need no change. Listed so future audits don't re-flag them.

| Pattern | Where it's centralized | Why OK |
|---------|----------------------|--------|
| Bind address (`127.0.0.1` / `0.0.0.0`) | `src/mcp_listen_config.py` | Single source; `UNITARES_BIND_ALL_INTERFACES` and `UNITARES_MCP_HOST` env vars override |
| Governance port `8767` | `src/mcp_server.py:531` (`DEFAULT_PORT`) | `--port` CLI arg + `SERVER_PORT` env var override; this is the canonical port |
| MCP / REST / WS / health URLs in agents | `agents/common/config.py` | All env-var-fallback defaults to `http://localhost:8767` |
| DB connection string | `os.environ.get("DB_POSTGRES_URL", "...")` everywhere | Env var wins; default DSN works on a fresh Homebrew Postgres because Homebrew uses trust auth on localhost (the literal `postgres:postgres` password is illustrative — Homebrew ignores it) |
| Tailscale CGNAT range `100.64.0.0/10` | `src/http_api.py:147` | This is the entire Tailscale network spec, not a specific operator's IP — correct as a constant |
| LAN / private network ranges `192.168.0.0/16`, `10.0.0.0/8` | `src/http_api.py:148-149` | RFC 1918 ranges, machine-independent |
| `~/Library/LaunchAgents` install path | All plist install instructions | Standard macOS path, identical across machines |
| `~/.unitares/anchors`, `~/backups/governance` | `scripts/ops/rotate-secrets.sh`, `backup_governance.sh` | Use `${HOME}` correctly |
| `$HOME` substitution in chronicler template | `scripts/ops/com.unitares.chronicler.plist.template` | Pattern to follow for the other plist templates |

---

## INTENTIONAL HETEROGENEITY (do not unify)

**This section exists so a future grep-audit doesn't "fix" things that are intentional. Memory anchor: `MEMORY.md` *Ports & Endpoints — DO NOT NORMALIZE*.**

| Value | Where it appears | Why heterogeneous |
|-------|------------------|------------------|
| Port `8767` | Governance MCP (Mac) — `src/mcp_server.py`, dashboards, all governance clients | Canonical governance port |
| Port `8766` | Anima MCP (Pi) — `scripts/ops/health_watchdog.sh`, `config/claude-desktop-mcp-config.json`, plus skill docs | Canonical anima/Lumen port; lives on a different host |
| Port `8768` | Gateway MCP (Mac) — `src/gateway/constants.py`, `src/gateway_server.py` | Reduced-surface proxy (6 tools vs 76) for weak external clients; same host as 8767 but **different process** |
| `claude-ai_UNITARES` and `unitares-governance` MCP names | MCP client configs across plugin repos | Stable IDs that external clients persist; renaming churns user state |

**The pattern that will trip a future agent:** they'll see `8767` everywhere in governance code and `8766` in one watchdog line, "fix" the watchdog to `8767`, and silently break the anima health check. Reference the `DEFINITIVE_PORTS.md` table before changing any port literal.

---

## Audit Patterns (reproduce this audit)

Run these from the repo root. Excludes `.git`, `.worktrees`, `data/`, `papers/`, `__pycache__`, and `tests/` (test fixtures legitimately use any of these strings).

```bash
# Operator path
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' -g '!tests/**' '/Users/cirwel'

# Operator's home LAN / Tailscale IPs
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' -g '!tests/**' '\b100\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b|\b192\.168\.1\.[0-9]{1,3}\b'

# Operator's domain
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' 'cirwel\.org|lumen\.local|\.ts\.net'

# Apple Silicon / Intel brew prefix
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' '/opt/homebrew|/usr/local/opt/postgres'

# Bind addresses + ports (read alongside DEFINITIVE_PORTS.md)
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' -g '!tests/**' '\b(8766|8767|8768|5432)\b'
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' -g '!tests/**' '\b127\.0\.0\.1\b|\b0\.0\.0\.0\b'

# DB credentials literal
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' 'postgres:postgres@localhost'

# Plist install path
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' 'Library/LaunchAgents|launchctl'

# Personal identifiers
rg -n --hidden -g '!.git' -g '!.worktrees' -g '!data/' -g '!papers/**' -g '!**/__pycache__/**' -g '!tests/**' 'hikewa|@gmail|kenny'
```

A drift in the **MUST-FIX** count between this audit and a future re-run is a regression — either fix the new entry or add it here with justification.
