# Markdown File Creation Policy

## TL;DR
**Don't create markdown files in the project root.** Use the structured docs/ hierarchy.

## Policy (Established Dec 15, 2024)

### ✅ Allowed Locations
1. **Root level** - ONLY these permanent files:
   - `README.md` - Project overview
   - `CHANGELOG.md` - Version history
   - That's it.

2. **Documentation hierarchy**:
   - `docs/guides/` - How-to guides, tutorials
   - `docs/reference/` - API docs, technical specs
   - `docs/theory/` - Conceptual/theoretical content
   - `docs/architecture/` - System design docs
   - `docs/archive/YYYY-MM/` - Session notes, temporary analysis

3. **Specs**:
   - `specs/` - Feature specifications, design proposals

4. **Agent-specific**:
   - `.agent-guides/` - Instructions for AI agents

### ❌ Anti-Patterns
- ❌ `MIGRATION_HANDOFF.md` in root → Should be `docs/archive/2025-12/postgres_migration_handoff.md`
- ❌ `PHASE5_CUTOVER_COMPLETE.md` in root → Archive it
- ❌ `ANALYSIS_20251215.md` in root → Goes to `docs/archive/2025-12/`
- ❌ Creating duplicate docs instead of updating existing ones

### Decision Tree
```
Need to create a markdown file?
│
├─ Is it the main README or CHANGELOG?
│  └─ YES → Root level OK
│
├─ Is it a permanent guide/tutorial?
│  └─ YES → docs/guides/
│
├─ Is it technical reference?
│  └─ YES → docs/reference/
│
├─ Is it a feature spec/proposal?
│  └─ YES → specs/
│
├─ Is it session notes/temporary analysis?
│  └─ YES → docs/archive/YYYY-MM/
│
└─ Is it for AI agents specifically?
   └─ YES → .agent-guides/
```

## Rationale
**Problem**: 81 markdown files scattered across the project, many at root level, causing:
- Hard to find relevant docs
- Duplicate/overlapping content
- Root directory clutter
- Unclear what's current vs historical

**Solution**: Strict hierarchy with clear purpose per directory.

## Enforcement
- **AI Agents**: Check this file before creating markdown
- **Humans**: Review PR for markdown in wrong locations
- **Automated**: (Future) Pre-commit hook to reject root-level markdown except README/CHANGELOG

## Examples from Dec 15 Migration

**What happened** (before policy):
- Created `MIGRATION_HANDOFF.md` in root
- Cursor agent created `PHASE5_CUTOVER_COMPLETE.md` in root
- `VERIFICATION_REPORT.md` in root

**What should happen** (after policy):
- All moved to `docs/archive/2025-12/postgres_migration_*.md`
- Consolidated session notes in archive
- Root stays clean

## Migration Complete
As of Dec 15, 2024, all root-level markdown (except README/CHANGELOG) has been moved to proper locations.

**Current root-level markdown files**:
```bash
$ ls *.md
README.md
CHANGELOG.md
```

That's it. Keep it that way! 🧹
