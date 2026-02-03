# Scripts Overview

This page summarizes active scripts and where to find historical/one‑off utilities.

## Active scripts (core)

**Server + diagnostics**
- `scripts/start_sse_server.sh`
- `scripts/diagnose_date_context_connection.py`
- `scripts/diagnose_unresponsive_agents.py`
- `scripts/reset_calibration.py`

**DB migration + repair**
- `scripts/migrate_sqlite_to_postgres.py`
- `scripts/migrate_to_postgres_age.py`
- `scripts/migrate_dialectic_to_postgres.py`
- `scripts/sync_discoveries_to_age.py`
- `scripts/repair_identity_agent_links.py`

**Docs + tooling**
- `scripts/generate_tool_docs.py`
- `scripts/update_readme_metadata.py`
- `scripts/update_docs_tool_count.py`
- `scripts/validate_all.py`
- `scripts/validate_markdown_formatting.py`

## Historical / one‑off scripts

See `scripts/archive/` for:
- ad‑hoc experiments
- one‑time analyses
- legacy debugging helpers

If you promote a script back to active use, move it to `scripts/` and add it to the list above.
