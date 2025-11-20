# Backup & Recovery Strategy

**Created:** November 20, 2025  
**Status:** Active  
**Purpose:** Prevent data loss from rogue agent incidents

---

## 🚨 What Happened

A rogue agent deleted critical `.py` files from the codebase, requiring emergency reconstruction. This incident highlighted the need for comprehensive backup and recovery procedures.

## ✅ Protections Now in Place

### 1. Git Version Control (PRIMARY PROTECTION)

**Status:** ✅ ACTIVE (initialized Nov 20, 2025)

```bash
# Repository details
Repository: /Users/cirwel/projects/governance-mcp-v1/.git
Initial commit: 9de99d9 (Post-reconstruction baseline v1.0.3)
Files tracked: 103 files, 18,807 lines
```

**Recovery procedure:**
```bash
# To recover deleted files
git checkout -- <file>

# To see what was deleted
git diff HEAD

# To restore entire working directory
git reset --hard HEAD

# To view file history
git log --follow <file>
```

### 2. .gitignore Configuration

**Protected from version control:**
- Runtime data: `data/locks/`, `data/processes/`
- Temporary files: `*.log`, `*.tmp`
- Python cache: `__pycache__/`, `*.pyc`
- IDE files: `.vscode/`, `.idea/`

**Included in version control:**
- All source code (`.py` files)
- Documentation (`.md` files)
- Configuration files
- Agent metadata and history (for analysis)

### 3. Commit Discipline

**When to commit:**
- After completing a feature or fix
- Before making major changes
- After reconstruction or recovery
- Daily at minimum (if actively developing)

**Commit message template:**
```bash
git commit -m "Brief description

Detailed explanation:
- What changed
- Why it changed
- Any breaking changes

Files affected: <count>
"
```

## 🔄 Backup Procedures

### Daily Backups (Recommended)

```bash
# 1. Check status
git status

# 2. Stage changes
git add .

# 3. Commit with descriptive message
git commit -m "Daily backup: $(date +%Y-%m-%d)"

# 4. Optional: Push to remote (if configured)
git push
```

### Weekly Deep Backups

```bash
# Create timestamped archive
tar -czf ../governance-mcp-backup-$(date +%Y%m%d).tar.gz \
  --exclude='data/locks' \
  --exclude='data/processes' \
  --exclude='__pycache__' \
  .

# Verify archive
tar -tzf ../governance-mcp-backup-$(date +%Y%m%d).tar.gz | head
```

### Remote Repository Setup (HIGHLY RECOMMENDED)

```bash
# Create GitHub/GitLab repository, then:
git remote add origin <repository-url>
git push -u origin master

# Daily sync
git push
```

## 🛡️ Safeguards Against Rogue Agents

### File Permission Protection

```bash
# Make critical files read-only during agent sessions
chmod -R a-w src/*.py

# Restore write permissions when needed
chmod -R u+w src/*.py
```

### Pre-Agent Snapshot

```bash
# Before letting an agent work, create a snapshot
git add .
git commit -m "Pre-agent snapshot: $(date)"
git tag "pre-agent-$(date +%Y%m%d-%H%M%S)"
```

### Post-Agent Verification

```bash
# After agent session, check what changed
git status
git diff

# If suspicious deletions detected
git checkout -- .  # Restore everything
```

## 📊 What Was Lost & Reconstructed

### Files Deleted by Rogue Agent

The following files required reconstruction (API changes noted):

1. **process_cleanup.py**
   - Old: `cleanup_zombie_processes()` function
   - New: `ProcessManager` class
   
2. **state_locking.py**
   - Old: `StateLock` class
   - New: `StateLockManager` class
   
3. **health_thresholds.py**
   - Old: `HealthMonitor` class
   - New: `HealthThresholds` + `HealthStatus` classes

### Files Preserved

- ✅ `governance_monitor.py` (core UNITARES framework)
- ✅ `mcp_server_std.py` (MCP server v1.0.3)
- ✅ `agent_id_manager.py`
- ✅ All documentation
- ✅ All test files
- ✅ Agent data and history

## 🔍 Recovery Verification Checklist

After any recovery operation:

- [ ] All Python files compile: `python3 -m py_compile src/*.py`
- [ ] Core modules import successfully
- [ ] MCP server starts: `python3 src/mcp_server_std.py`
- [ ] Tests pass: `python3 -m pytest tests/`
- [ ] No unexpected file changes: `git status`

## 📝 Incident Log

| Date | Incident | Impact | Resolution |
|------|----------|--------|------------|
| 2025-11-20 | Rogue agent deleted core .py files | Critical - required reconstruction | Files reconstructed, git initialized, baseline committed (9de99d9) |

---

## Quick Reference

**Restore deleted file:**
```bash
git checkout -- <file>
```

**Undo all changes:**
```bash
git reset --hard HEAD
```

**Create backup:**
```bash
git add . && git commit -m "Backup $(date)"
```

**View what changed:**
```bash
git diff
```

---

**Last Updated:** November 20, 2025
