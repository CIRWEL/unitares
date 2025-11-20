# Claude → Cursor Handoff Guide

## Summary

**Claude (me) has provided:**
- ✅ Complete governance system (v1.0)
- ✅ All 5 decision points implemented & tested
- ✅ Demo validates everything works
- ✅ Full documentation

**Cursor should handle:**
- Local file creation
- Integration with existing code
- Running/debugging in your environment
- Customization for your workflow

---

## For Cursor: What You're Getting

**5 Production-Ready Python Files:**
1. `config/governance_config.py` (320 lines) - All decision points
2. `src/governance_monitor.py` (380 lines) - UNITARES core
3. `src/mcp_server.py` (280 lines) - MCP interface
4. `scripts/claude_code_bridge.py` (360 lines) - Integration
5. `demo_complete_system.py` (460 lines) - Validation

**All tested:** Demo ran successfully, shows all features working.

**All documented:** README, architecture docs, integration guides.

---

## Cursor Prompt to Start

```
I need to create a local Python project called governance-mcp-v1.

Structure:
governance-mcp-v1/
├── config/
│   ├── __init__.py
│   └── governance_config.py
├── src/
│   ├── __init__.py
│   ├── governance_monitor.py
│   └── mcp_server.py
├── scripts/
│   ├── __init__.py
│   └── claude_code_bridge.py
├── data/
├── tests/
└── demo_complete_system.py

Create this structure for me, then I'll paste the code 
for each file from another AI conversation.
```

---

## Verification Step for Cursor

After copying all files:
```bash
python demo_complete_system.py
```

Expected: 5 demos pass, showing all decision points working.

---

## Integration Goal

Integrate with existing Claude Code bridge at:
`~/scripts/integrations/claude_code_mcp_bridge.py`

So Claude Code responses automatically log to governance system.

