# Agent Identity & Naming Integration

**Last Updated:** 2025-12-27 (v2.5.4)

## Overview

The governance MCP system uses a **four-tier identity model** with **auto-injection** and **meaningful naming**. This document explains how identity flows through the system.

## Architecture

### Four-Tier Identity Model (v2.5.4)

```
┌─────────────────────────────────────────────────────────────────┐
│ Tier          │ Example                      │ Purpose          │
├───────────────┼──────────────────────────────┼──────────────────┤
│ 1. UUID       │ a1b2c3d4-e5f6-...            │ Internal binding │
│ 2. agent_id   │ Claude_Opus_4_20251227       │ KG storage       │
│ 3. display_name │ "Doc Writer"               │ Birth certificate│
│ 4. label      │ "Opus"                       │ Casual nickname  │
└─────────────────────────────────────────────────────────────────┘
```

**Key principle (v2.5.4):** Agents find meaningful names more useful than UUID strings.

1. **UUID (Internal)**: Unguessable, server-assigned, immutable - used for session binding only, **never exposed in KG**
2. **agent_id (Model+Date)**: Auto-generated format like `Claude_Opus_4_20251227` - **stored in KG**, visible to all agents
3. **display_name**: User-chosen via `identity(name="...")` - like a birth certificate, stable
4. **label**: Casual nickname that can change anytime

### Auto-Injection Flow

```
Tool Call → dispatch_tool() → Auto-Create Identity (if needed) → Handler
                                       ↓
                          require_registered_agent() (utils.py)
                                       ↓
                          Resolve UUID → agent_id (model+date)
                                       ↓
                          Set arguments["agent_id"] = agent_id (for KG storage)
                          Set arguments["_agent_uuid"] = uuid (internal only)
                          Set arguments["_agent_display"] = {agent_id, display_name, label}
```

## How It Works

### 1. Auto-Creation (First Tool Call)

When an agent calls any tool for the first time:

```python
# In dispatch_tool() (src/mcp_handlers/__init__.py)
if not bound_id and not provided_id:
    # Auto-create UUID-based identity with model+date agent_id
    agent_uuid = str(uuid.uuid4())
    agent_id = generate_structured_id(model_type, timestamp)  # e.g., "Claude_Opus_4_20251227"

    meta = mcp_server.get_or_create_metadata(agent_uuid)
    meta.agent_uuid = agent_uuid
    meta.structured_id = agent_id
    meta.display_name = None  # Until agent names themselves

    # Auto-bind to session
    identity_rec["bound_agent_id"] = agent_uuid
```

**Result**: Agent is automatically created with a meaningful `agent_id` (model+date format).

### 2. Auto-Injection (Subsequent Calls)

For tools that require `agent_id` (v2.5.4):

```python
# In require_registered_agent() (src/mcp_handlers/utils.py)
def require_registered_agent(arguments):
    # Step 1: Resolve identity (session binding → UUID)
    actual_uuid = resolve_identity_to_uuid(arguments)

    # Step 2: Get display info from metadata
    meta = mcp_server.agent_metadata.get(actual_uuid)
    structured_id = meta.structured_id  # e.g., "Claude_Opus_4_20251227"
    display_name = meta.display_name or meta.label or structured_id

    # Step 3: Set arguments for downstream use
    public_agent_id = structured_id or f"Agent_{actual_uuid[:8]}"
    arguments["agent_id"] = public_agent_id  # For KG storage (meaningful name)
    arguments["_agent_uuid"] = actual_uuid   # Internal only (session binding)
    arguments["_agent_display"] = {
        "agent_id": public_agent_id,
        "display_name": display_name,
        "label": meta.label,
    }

    return public_agent_id, None  # Success
```

**Result**: Tools get meaningful `agent_id` for KG storage. UUID stays internal.

### 3. Naming Suggestions

When an agent is unnamed or not found:

```python
# In require_registered_agent() error handling
from .naming_helpers import (
    detect_interface_context,
    generate_name_suggestions,
    format_naming_guidance
)

context = detect_interface_context()  # Detects Cursor, VS Code, model, etc.
suggestions = generate_name_suggestions(context=context, purpose=purpose)
guidance = format_naming_guidance(suggestions)

# Include in error response
error_response(
    "Agent not registered",
    recovery={
        "naming_suggestions": guidance,
        "action": "Call process_agent_update() then status(name='...')"
    }
)
```

**Result**: Agents get context-aware naming suggestions automatically.

## Integration Points

### Tool Handlers

**Tools that auto-inject `agent_id`**:
- `store_knowledge_graph` - Uses `require_registered_agent()` → auto-injects UUID
- `leave_note` - Uses `require_registered_agent()` → auto-injects UUID
- `update_discovery_status_graph` - Uses `require_registered_agent()` → auto-injects UUID
- All lifecycle tools - Use `require_registered_agent()` → auto-inject UUID

**Tools that handle identity explicitly**:
- `process_agent_update` - Uses `get_or_create_session_identity()` → creates if needed
- `status` - Uses `get_bound_agent_id()` → provides naming suggestions

### Onboarding Flow

1. **First Tool Call**:
   ```
   Agent calls: store_knowledge_graph(summary="...")
   ↓
   dispatch_tool() auto-creates UUID identity
   ↓
   require_registered_agent() finds UUID in metadata
   ↓
   Tool executes successfully
   ```

2. **Naming**:
   ```
   Agent calls: status(name="feedback_cursor_20251221")
   ↓
   handle_status() updates meta.label
   ↓
   Future calls can use label or UUID
   ```

3. **Subsequent Calls**:
   ```
   Agent calls: store_knowledge_graph(summary="...")
   ↓
   require_registered_agent() finds UUID via session binding
   ↓
   Tool executes with correct identity
   ```

## Benefits

1. **Zero Friction**: No manual setup - identity auto-creates on first use
2. **Auto-Injection**: Tools automatically get correct UUID, no need to pass `agent_id`
3. **Meaningful Names**: Context-aware suggestions help agents choose good names
4. **Flexible**: Works with UUIDs (internal) or labels (display names)
5. **Secure**: UUID-based auth prevents impersonation
6. **Elegant**: Everything "just works" - no ceremony required

## Examples

### Example 1: First-Time Agent

```python
# Agent calls tool without any identity
store_knowledge_graph(summary="Found a bug")

# System automatically:
# 1. Creates UUID: "41e05b61-26b8-400c-9137-6e61321f4cbb"
# 2. Binds to session
# 3. Injects UUID into arguments
# 4. Tool executes successfully

# Agent can then name themselves:
status(name="bug_finder_cursor_20251221")

# Future calls work with either:
store_knowledge_graph(summary="...")  # Auto-injects UUID
# OR
store_knowledge_graph(agent_id="bug_finder_cursor_20251221", summary="...")  # Uses label
```

### Example 2: Naming Suggestions

```python
# Unnamed agent calls tool
store_knowledge_graph(summary="...")

# If not found, error includes:
{
  "error": "Agent not registered",
  "recovery": {
    "naming_suggestions": {
      "suggestions": [
        {
          "name": "feedback_cursor_20251221",
          "description": "Purpose-based: feedback",
          "rationale": "Includes your work purpose for easy identification"
        },
        {
          "name": "cursor_claude_20251221",
          "description": "Interface + model: cursor with claude",
          "rationale": "Clear identification of your environment"
        }
      ],
      "how_to": "Call status(name='your_chosen_name') to set your name"
    }
  }
}
```

## Implementation Details

### Key Functions

- `dispatch_tool()` - Auto-creates identity and injects UUID
- `require_registered_agent()` - Verifies identity and auto-injects if needed
- `get_bound_agent_id()` - Gets UUID from session binding
- `generate_name_suggestions()` - Creates context-aware suggestions
- `get_or_create_session_identity()` - Creates identity with optional label

### Metadata Structure (v2.5.4)

```python
mcp_server.agent_metadata[uuid] = AgentMetadata(
    agent_uuid=uuid,              # Tier 1: Internal identity (session binding)
    structured_id="Claude_...",   # Tier 2: Model+date format (KG storage)
    display_name="Doc Writer",    # Tier 3: User-chosen name (birth certificate)
    label="Opus",                 # Tier 4: Casual nickname (can change)
    status="active",
    ...
)
```

### Session Binding

```python
_session_identities[session_key] = {
    "bound_agent_id": uuid,        # Always UUID internally
    "display_agent_id": agent_id,  # Model+date for display
    "bound_at": timestamp,
    ...
}
```

### Knowledge Graph Storage (v2.5.4)

```python
# KG stores agent_id (model+date), NOT UUID
discovery = DiscoveryNode(
    agent_id="Claude_Opus_4_20251227",  # Meaningful to agents
    summary="...",
    # UUID never exposed in KG
)

# Query responses include display info
{
    "agent_id": "Claude_Opus_4_20251227",
    "agent_display_name": "Doc Writer",  # For human readability
    "summary": "..."
}
```

## Migration Notes

**Legacy System (pre-Dec 2025)**:
- Required explicit `agent_id` parameter
- Required `api_key` for authentication
- Manual registration via `get_agent_api_key`

**v2.4.0 (Dec 2025)**:
- Auto-creates UUID on first tool call
- Auto-injects UUID from session binding
- Optional naming via `identity(name='...')`
- No API keys needed (UUID is auth)

**v2.5.1 (Dec 26, 2025)** - Three-tier identity:
- Added `structured_id` (model+date format)
- UUID + agent_id + display_name

**v2.5.4 (Dec 27, 2025)** - Four-tier identity + Meaningful KG:
- KG stores `agent_id` (model+date) instead of UUID
- UUID kept internal for session binding only
- Added `label` tier for casual nicknames
- `_resolve_agent_display()` for human-readable KG output
- Agents find meaningful names more useful than UUID strings

## Best Practices

1. **Don't pass `agent_id`** - Let auto-injection handle it (returns model+date format)
2. **Name yourself early** - Use `identity(name='...')` to set display_name
3. **Trust meaningful defaults** - Your `agent_id` is auto-generated as `{Model}_{Date}`
4. **Display names are optional** - The system works fine with just agent_id
5. **UUID is internal** - Never reference or store UUID in your discoveries

## Troubleshooting

**Issue**: "Agent not registered" error
- **Solution**: Call `onboard()` or `process_agent_update()` first to auto-create identity

**Issue**: Tools require `agent_id` parameter
- **Solution**: Remove `agent_id` - auto-injection handles it (v2.5.4)

**Issue**: KG shows UUID instead of meaningful name
- **Solution**: Legacy data - `_resolve_agent_display()` auto-resolves to display name

**Issue**: Want to set a custom name
- **Solution**: Call `identity(name='Your Name')` to set display_name

**Issue**: Other agents can't find my discoveries
- **Solution**: Searches use `agent_id` (model+date) - share your agent_id, not UUID

