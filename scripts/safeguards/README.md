# Safeguards Against Rogue Agents

**Purpose:** Prevent file deletion and enable easy recovery from agent incidents  
**Created:** November 20, 2025 (after rogue agent deletion incident)

---

## Quick Start

### Before Agent Session

```bash
# Create snapshot + protect files
scripts/safeguards/pre_agent_snapshot.sh "cursor-agent-session"
scripts/safeguards/protect_files.sh protect
```

### After Agent Session

```bash
# Unprotect and verify
scripts/safeguards/protect_files.sh unprotect
scripts/safeguards/post_agent_verify.sh
```

---

## Available Scripts

### 1. protect_files.sh

**Purpose:** Make source files read-only to prevent deletion

**Usage:**
```bash
# Make files read-only
scripts/safeguards/protect_files.sh protect

# Restore write permissions
scripts/safeguards/protect_files.sh unprotect

# Check protection status
scripts/safeguards/protect_files.sh status
```

**What it protects:**
- All `.py` files in `src/`
- All `.py` files in `config/`

**Limitations:**
- Agent can still use `chmod` to remove protection
- Best used as a gentle reminder, not absolute security

---

### 2. pre_agent_snapshot.sh

**Purpose:** Create git snapshot before agent modifies files

**Usage:**
```bash
scripts/safeguards/pre_agent_snapshot.sh "agent-description"
```

**What it does:**
1. Commits current state
2. Creates tagged snapshot: `pre-agent-YYYYMMDD-HHMMSS`
3. Prints recovery commands

**Example:**
```bash
scripts/safeguards/pre_agent_snapshot.sh "cursor-refactor"
# Creates: pre-agent-20251120-123456
```

**Recovery:**
```bash
# List all snapshots
git tag -l 'pre-agent-*'

# Restore to snapshot
git reset --hard pre-agent-20251120-123456

# Compare current state to snapshot
git diff pre-agent-20251120-123456
```

---

### 3. post_agent_verify.sh

**Purpose:** Check for suspicious changes after agent session

**Usage:**
```bash
scripts/safeguards/post_agent_verify.sh
```

**What it does:**
1. Shows changed/deleted files
2. Warns if files were deleted
3. Offers interactive options:
   - Review changes (git diff)
   - Commit changes
   - Discard all changes
   - Exit

**Example output:**
```
🔍 Post-Agent Verification Script
=================================

📝 Changed files:
 M src/governance_monitor.py
 D src/process_cleanup.py  ← WARNING

⚠️  WARNING: 1 file(s) deleted!

Deleted files:
 D src/process_cleanup.py

To restore deleted files:
  git checkout -- src/process_cleanup.py
```

---

## Recommended Workflow

### Safe Agent Session Pattern

```bash
# 1. Before starting
git status  # Ensure clean state
scripts/safeguards/pre_agent_snapshot.sh "my-agent"
scripts/safeguards/protect_files.sh protect

# 2. Let agent work
# ... agent makes changes ...

# 3. After agent finishes
scripts/safeguards/protect_files.sh unprotect
scripts/safeguards/post_agent_verify.sh

# 4. If changes look good
git add .
git commit -m "Agent changes: description"

# 5. If changes look bad
git reset --hard HEAD
```

### Quick Recovery from Bad Agent

```bash
# Immediate rollback
git reset --hard HEAD

# Or restore to specific snapshot
git reset --hard pre-agent-20251120-123456

# Clean untracked files too
git clean -fd
```

---

## What These Scripts DON'T Prevent

❌ Agent using `chmod` to remove read-only protection  
❌ Agent using `sudo` to bypass permissions  
❌ Agent modifying files in unprotected directories  
❌ Agent committing malicious code that passes review  

## What These Scripts DO Provide

✅ Easy snapshot/restore workflow  
✅ Automatic detection of deletions  
✅ Interactive recovery options  
✅ Tagged checkpoints for rollback  
✅ Visual warnings about suspicious changes  

---

## Integration with Git

These scripts are **wrappers around git** for convenience:

| Script | Git Equivalent |
|--------|---------------|
| `pre_agent_snapshot.sh` | `git add . && git commit && git tag` |
| `post_agent_verify.sh` | `git status && git diff` |
| `protect_files.sh` | `chmod` (not git-related) |

You can always use git commands directly if you prefer.

---

## Troubleshooting

### "Git repository not initialized"

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git init
```

### "Permission denied" when running scripts

```bash
chmod +x scripts/safeguards/*.sh
```

### Files still deleted despite protection

```bash
# Restore from git
git checkout -- <deleted-file>

# Or restore everything
git reset --hard HEAD
```

---

**Last Updated:** November 20, 2025  
**Related Docs:** 
- `docs/BACKUP_STRATEGY.md`
- `docs/API_CHANGES_POST_RECONSTRUCTION.md`
