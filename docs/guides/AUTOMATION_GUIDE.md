# Automation Guide - Preventing Documentation Drift

**Purpose:** Eliminate manual synchronization of tool counts, versions, and documentation
**Created:** 2025-12-08
**Status:** Active

---

## Problem We're Solving

**Before automation:** Tool count, version numbers, and other metadata had to be manually updated across multiple files, leading to drift and inconsistency.

**Examples of drift:**
- README said "43 tools" while code had 47
- Version "2.1" in one place, "2.3.0" in another
- Bridge script referenced wrong data directory

---

## Automation Tools

### 1. **Tool Count Management** 🔢

**Single Source of Truth:** Code itself (via `@mcp_tool` decorators)

**Scripts:**
```bash
# Count tools (always accurate)
python3 scripts/count_tools.py                # Show total
python3 scripts/count_tools.py --by-module    # Breakdown by category
python3 scripts/count_tools.py --json         # JSON output

# Check documentation
python3 scripts/update_docs_tool_count.py --check   # Verify sync
python3 scripts/update_docs_tool_count.py --update  # Auto-fix docs
```

**How it works:**
1. Scans `src/mcp_handlers/*.py` for `@mcp_tool(` decorators
2. Excludes utility files (decorators, utils, validators)
3. Returns authoritative count
4. Updates all documentation automatically

**Files updated:**
- `README.md`
- `START_HERE.md`
- `docs/guides/ONBOARDING.md`
- `scripts/claude_code_bridge.py`

### 2. **Version Management** 📌

**Single Source of Truth:** `VERSION` file (plain text, one line)

**Scripts:**
```bash
# Check current version
python3 scripts/version_manager.py

# Check for mismatches
python3 scripts/version_manager.py --check

# Update all references
python3 scripts/version_manager.py --update

# Bump version
python3 scripts/version_manager.py --bump patch   # 2.3.0 → 2.3.1
python3 scripts/version_manager.py --bump minor   # 2.3.0 → 2.4.0
python3 scripts/version_manager.py --bump major   # 2.3.0 → 3.0.0
```

**Workflow for new release:**
```bash
# 1. Bump version
python3 scripts/version_manager.py --bump minor

# 2. Update all references
python3 scripts/version_manager.py --update

# 3. Commit
git add VERSION README.md CHANGELOG.md
git commit -m "Bump version to 2.4.0"
```

**Files checked:**
- `VERSION` (source of truth)
- `README.md` (production ready badge)
- `CHANGELOG.md` (version headers)
- `setup.py` (if created)

### 3. **Pre-commit Validation** ✓

**Automatic checks on every commit:**

The `.pre-commit-markdown-check.sh` hook now validates:
1. **Tool count sync** - Fails if docs don't match reality
2. **Version consistency** - Fails if versions are mismatched
3. **Markdown proliferation** - Prevents small (<500 word) docs
4. **Markdown formatting** - Checks dates, code blocks, links

**To install (already done for this project):**
```bash
# Hook is at: .pre-commit-markdown-check.sh
# Already runs automatically on `git commit`
```

**To bypass (not recommended):**
```bash
git commit --no-verify -m "message"
```

---

## Workflow Examples

### Adding a New MCP Tool

**Old way (manual):**
1. Add tool code ❌
2. Remember to update README ❌
3. Remember to update START_HERE ❌
4. Remember to update ONBOARDING ❌
5. Hope you got them all ❌

**New way (automated):**
1. Add tool code ✓
2. Commit ✓
3. Pre-commit hook updates everything automatically ✓

### Releasing a New Version

**Old way (manual):**
1. Update VERSION file ❌
2. Update README version badge ❌
3. Update CHANGELOG ❌
4. Miss a few references ❌
5. Create drift ❌

**New way (automated):**
```bash
python3 scripts/version_manager.py --bump minor
python3 scripts/version_manager.py --update
git add -A
git commit -m "Release v2.4.0"
```

### Detecting Drift

**Tool count drift:**
```bash
$ python3 scripts/update_docs_tool_count.py --check
Actual tool count: 47

❌ Found 1 mismatches:
  README.md:115
    Found: 43, Expected: 47

Fix: python3 scripts/update_docs_tool_count.py --update
```

**Version drift:**
```bash
$ python3 scripts/version_manager.py --check
Current version: 2.3.0

❌ Found 1 version mismatches:
  README.md:961
    Found: 2.1, Expected: 2.3.0
```

---

## CI/CD Integration (Future)

**GitHub Actions workflow (recommended):**

```yaml
name: Documentation Validation
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Check tool count
        run: python3 scripts/update_docs_tool_count.py --check
      - name: Check version
        run: python3 scripts/version_manager.py --check
      - name: Run tests
        run: python3 -m pytest
```

This prevents drift from ever reaching main branch.

---

## Maintenance

### Adding New Documentation Files

If you add a new file that references tool count or version:

**For tool count:**
1. Edit `scripts/update_docs_tool_count.py`
2. Add file to `DOC_FILES` list
3. Add pattern to `PATTERNS` list

**For version:**
1. Edit `scripts/version_manager.py`
2. Add file and patterns to `VERSION_REFERENCES`

### Excluding Files from Tool Count

If you add a new handler file that shouldn't be counted (like `utils.py`):

1. Edit `scripts/count_tools.py`
2. Add to `EXCLUDE` set in `get_tool_breakdown()`

---

## Benefits

✅ **Zero drift** - Source of truth is always code
✅ **No manual updates** - Scripts do the work
✅ **Catch errors early** - Pre-commit hook blocks bad commits
✅ **Single command** - `--update` fixes everything
✅ **Auditability** - Always know what changed and why

---

## Quick Reference

```bash
# Daily development
# (nothing special needed - automation handles it)

# Adding tools
# (no action needed - pre-commit validates)

# Releasing new version
python3 scripts/version_manager.py --bump minor
python3 scripts/version_manager.py --update
git commit -m "Release v2.4.0"

# Manual validation
python3 scripts/update_docs_tool_count.py --check
python3 scripts/version_manager.py --check

# Manual fixes
python3 scripts/update_docs_tool_count.py --update
python3 scripts/version_manager.py --update
```

---

**Last Updated:** 2025-12-08
