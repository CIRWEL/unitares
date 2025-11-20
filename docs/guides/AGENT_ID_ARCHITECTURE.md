# Agent ID Architecture Guide

**Critical Design Pattern: Interface vs. Identity**

---

## 🎯 The Two-Layer Architecture

The governance system separates **HOW** (interface) from **WHO** (identity):

```
Layer 1: Interface (HOW)        Layer 2: Identity (WHO)
├── MCP Server                  ├── cursor_session_20251119_001
├── Bridge Script               ├── claude_cli_debugging_gov
└── Python Direct               └── cli_user_alice_exploration
```

**Why This Matters:**
- **Interface** = How you connect (MCP, bridge, direct Python)
- **Identity** = Who you are (unique session/purpose identifier)

**The Problem:** Conflating interface with identity causes:
- ❌ State corruption (multiple sessions writing to same agent)
- ❌ Zombie accumulation (can't differentiate sessions)
- ❌ Governance confusion (which session triggered what?)

---

## 🚨 Common Mistakes

### ❌ Bad: Generic Interface-Based IDs

```python
# DON'T DO THIS - causes collisions!
bridge = ClaudeCodeBridge(agent_id="claude_code_cli")
# Multiple CLI sessions → same ID → state corruption
```

### ✅ Good: Unique Session/Purpose-Based IDs

```python
# DO THIS - unique per session
bridge = ClaudeCodeBridge()  # Auto-generates: claude_cli_user_20251119_1430
# OR
bridge = ClaudeCodeBridge(agent_id="claude_cli_debugging_20251119")
```

---

## 📝 Agent ID Generation Options

### Option 1: Auto-Generate Session ID (Recommended)

```python
from src.agent_id_manager import get_agent_id

agent_id = get_agent_id()  # Prompts for choice
# Generates: claude_cli_username_20251119_1430
```

**Use when:** Starting a new session, don't care about specific naming.

### Option 2: Purpose-Based ID

```python
agent_id = get_agent_id()  # Select option 2, enter "debugging"
# Generates: claude_cli_debugging_20251119
```

**Use when:** You want meaningful names for different use cases.

### Option 3: Custom ID

```python
agent_id = get_agent_id()  # Select option 3, enter custom ID
# Your custom ID (with collision warnings)
```

**Use when:** You need specific naming conventions.

---

## 🔍 Collision Detection

The system automatically detects and warns about collisions:

```python
# If agent_id is already active:
🚨 WARNING: 'claude_code_cli' is already active!
This will mix states and cause corruption.

Options:
1. Resume existing session (recommended)
2. Create new session with different ID
3. Force continue (NOT recommended)
```

**Always choose option 1 or 2** - option 3 risks state corruption!

---

## 💡 Best Practices

### For Bridge Scripts

```python
# scripts/claude_code_bridge.py
from src.agent_id_manager import get_agent_id

# Let user choose or auto-generate
bridge = ClaudeCodeBridge()  # Prompts for agent ID
```

### For MCP Clients

```python
# MCP clients should pass unique agent_id
# Example: cursor_session_20251119_001
# NOT: "claude_code_cli" (too generic)
```

### For Testing

```python
# Use unique test IDs
agent_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
```

---

## 🏗️ Implementation Details

### Session Persistence

Agent IDs are cached in `.governance_session`:

```bash
# Resume previous session
cat .governance_session
# claude_cli_user_20251119_1430

# Clear session
rm .governance_session
```

### Validation Rules

1. **Generic IDs trigger warnings:**
   - `claude_code_cli`, `claude_chat`, `test`, `demo`
   - System appends timestamp if non-interactive

2. **Active agent detection:**
   - Checks `data/agent_metadata.json`
   - Warns if agent is already active

3. **Session resumption:**
   - Cached IDs can be resumed
   - Prevents accidental new sessions

---

## 📊 Real-World Example

### The Problem (Before)

```python
# Multiple developers, same ID
Developer A: bridge = ClaudeCodeBridge(agent_id="claude_code_cli")
Developer B: bridge = ClaudeCodeBridge(agent_id="claude_code_cli")
# Result: State corruption, zombie processes, confusion
```

### The Solution (After)

```python
# Each developer gets unique ID
Developer A: bridge = ClaudeCodeBridge()  # → claude_cli_alice_20251119_1430
Developer B: bridge = ClaudeCodeBridge()  # → claude_cli_bob_20251119_1435
# Result: Clean separation, no collisions, traceable sessions
```

---

## 🎬 For VC Meetings

**Key Message:**

> "We discovered agent identity collision - multiple CLI sessions sharing 'claude_code_cli' ID caused state corruption. We now enforce unique session identities. Every interaction is traceable."

**This demonstrates:**
- ✅ Production thinking (not just "does it work?")
- ✅ Multi-user safety (what happens with 10 developers?)
- ✅ Traceability (which session had the issue?)

---

## 🔧 Migration Guide

### Updating Existing Code

**Before:**
```python
bridge = ClaudeCodeBridge(agent_id="claude_code_cli")
```

**After:**
```python
# Option 1: Auto-generate (recommended)
bridge = ClaudeCodeBridge()

# Option 2: Explicit unique ID
bridge = ClaudeCodeBridge(agent_id="claude_cli_debugging_20251119")
```

### Non-Interactive Mode

```python
# For scripts/automation
bridge = ClaudeCodeBridge(interactive=False)  # Uses defaults
```

---

## 📚 Related Documentation

- `docs/guides/TROUBLESHOOTING.md` - Common issues
- `docs/analysis/COHERENCE_ANALYSIS.md` - Coherence and state management
- `src/agent_id_manager.py` - Implementation details

---

**Last Updated:** November 19, 2025  
**Version:** 1.0

