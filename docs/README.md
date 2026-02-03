# Documentation Structure

**UNITARES Governance Monitor - Documentation Hub**

**Last Updated:** 2026-01-04

---

## Quick Start - Choose Your Path

| You are... | Start here |
|------------|------------|
| **⭐ New agent (simplest)** | [GETTING_STARTED_SIMPLE.md](guides/GETTING_STARTED_SIMPLE.md) — 3 tools, 3 steps |
| **Claude Code (CLI)** | [CLAUDE_CODE_START_HERE.md](guides/CLAUDE_CODE_START_HERE.md) |
| **MCP Client (Cursor, etc.)** | [START_HERE.md](guides/START_HERE.md) — Full onboarding |
| **Developer/Debugger** | [.agent-guides/DEVELOPER_AGENTS.md](../.agent-guides/DEVELOPER_AGENTS.md) |
| **Human setting up MCP** | [MCP_SETUP.md](guides/MCP_SETUP.md) |

**Navigation:** [NAVIGATION.md](guides/NAVIGATION.md) — Find what you need quickly.

---

## Directory Structure

### `/guides/` - User Guides (36 files)

**Entry Points (Start Here):**
- ⭐ [GETTING_STARTED_SIMPLE.md](guides/GETTING_STARTED_SIMPLE.md) - **Simplest path** (3 tools, 3 steps)
- [UNITARES_LITE.md](guides/UNITARES_LITE.md) - Essential tools explained simply
- [NAVIGATION.md](guides/NAVIGATION.md) - Find what you need quickly
- [START_HERE.md](guides/START_HERE.md) - Full onboarding (MCP clients)
- [CLAUDE_CODE_START_HERE.md](guides/CLAUDE_CODE_START_HERE.md) - Claude Code specific guide
- [ONBOARDING.md](guides/ONBOARDING.md) - Comprehensive onboarding

**Understanding the System:**
- [ESSENTIAL_TOOLS.md](guides/ESSENTIAL_TOOLS.md) - Tool tiers and 80/20 breakdown
- [PHILOSOPHY.md](guides/PHILOSOPHY.md) - Why complexity exists (optional reading)
- [TOOL_DISCOVERY.md](guides/TOOL_DISCOVERY.md) - How to find tools without overwhelm
- [SIMPLIFICATION_SUMMARY.md](guides/SIMPLIFICATION_SUMMARY.md) - What we built and why

**Quick Reference:**
- [QUICK_REFERENCE.md](guides/QUICK_REFERENCE.md) - One-page cheat sheet
- [QUICK_START_CLI.md](guides/QUICK_START_CLI.md) - Simple CLI wrapper

**Setup & Configuration:**
- [MCP_SETUP.md](guides/MCP_SETUP.md) - MCP server setup
- [THRESHOLDS.md](guides/THRESHOLDS.md) - Governance thresholds
- [NGROK_DEPLOYMENT.md](guides/NGROK_DEPLOYMENT.md) - Remote access setup
- [NGROK_GATEWAY.md](guides/NGROK_GATEWAY.md) - AI Gateway configuration
- [HUGGINGFACE_EMBEDDINGS.md](guides/HUGGINGFACE_EMBEDDINGS.md) - Embedding model optimization

**Tutorials:**
- [MULTI_AGENT_TUTORIAL.md](guides/MULTI_AGENT_TUTORIAL.md) - Multi-agent coordination
- [MULTI_PROVIDER_SETUP.md](guides/MULTI_PROVIDER_SETUP.md) - Multi-provider configuration
- [MODEL_INFERENCE_SETUP.md](guides/MODEL_INFERENCE_SETUP.md) - Model inference setup

**Identity & Auth:**
- [OAUTH_IDENTITY.md](guides/OAUTH_IDENTITY.md) - OAuth integration
- [AGENT_IDENTITY_INTEGRATION.md](guides/AGENT_IDENTITY_INTEGRATION.md) - Identity integration

**Troubleshooting:**
- [TROUBLESHOOTING.md](guides/TROUBLESHOOTING.md) - Common issues and solutions
- [NGROK_GATEWAY_TROUBLESHOOTING.md](guides/NGROK_GATEWAY_TROUBLESHOOTING.md) - Gateway issues
- [SSE_VS_STDIO.md](guides/SSE_VS_STDIO.md) - Transport comparison

### `/reference/` - Reference Documentation

- [AI_ASSISTANT_GUIDE.md](reference/AI_ASSISTANT_GUIDE.md) - Complete guide for AI agents
- [CONCEPT_TRANSLATION_GUIDE.md](reference/CONCEPT_TRANSLATION_GUIDE.md) - Patent-to-code mapping
- [PATENT_TO_IMPLEMENTATION_MAP.md](reference/PATENT_TO_IMPLEMENTATION_MAP.md) - Implementation map
- [SSE_SERVER.md](reference/SSE_SERVER.md) - SSE server reference

### `/theory/` - Theoretical Documentation

- [EISV_THEORETICAL_FOUNDATIONS.md](theory/EISV_THEORETICAL_FOUNDATIONS.md) - EISV framework theory
- [Enactive_Identity_Paper_Draft.md](theory/Enactive_Identity_Paper_Draft.md) - Research paper draft
- [META_COGNITIVE_AI_DEEP_DIVE.md](theory/META_COGNITIVE_AI_DEEP_DIVE.md) - Meta-cognitive analysis

### `/business/` - Business Documentation

- [DEPLOYMENT_MODELS.md](business/DEPLOYMENT_MODELS.md) - Deployment strategies
- [CUSTOMER_FEATURES_ANALYSIS.md](business/CUSTOMER_FEATURES_ANALYSIS.md) - Feature analysis
- [ITERATION_STRATEGY.md](business/ITERATION_STRATEGY.md) - Development strategy

### `/friction/` - UX Testing & Improvements

Active UX testing logs and improvements.

### `/archive/` - Historical Documentation

Session artifacts and superseded documentation:
- [2025-12/INDEX.md](archive/2025-12/INDEX.md) - December 2025 archive
- [2026-01/INDEX.md](archive/2026-01/INDEX.md) - January 2026 archive (session artifacts)

---

## Current Tool Count: 45+ Tools

- **Essential (Tier 1):** ~11 tools
- **Common (Tier 2):** ~22 tools
- **Advanced (Tier 3):** ~12 tools

Use `list_tools()` for the current list, or `list_tools(lite=true)` for essential tools only.

---

## Primary Entry Points

```
                      AGENT ENTRY POINTS

  Claude Code (CLI)          MCP Clients (Cursor, etc.)
        |                            |
        v                            v
  CLAUDE_CODE_START_HERE      START_HERE.md
        |                            |
        +------------+---------------+
                     v
         onboard() / identity() (MCP tools)
                     |
                     v
           AI_ASSISTANT_GUIDE.md (deep understanding)
```

---

## Documentation Philosophy

**Simplified structure:**
- Choose your entry point based on your context
- Essential guides cover 90% of use cases
- Use `search_knowledge_graph()` for discoveries, insights, patterns

**Knowledge Graph vs Markdown:**
- **Knowledge Graph:** Insights, discoveries, bugs, patterns, quick notes
- **Markdown:** Reference guides, comprehensive documentation

**Anti-proliferation:**
- Session artifacts go to `/archive/YYYY-MM/`
- Consolidate related docs rather than creating new ones
- Update existing docs instead of creating variants

---

## Recent Cleanup (2026-01-04)

Archived 61 session artifacts:
- 17 GATEWAY configuration session files → `archive/2026-01/session-artifacts/gateway/`
- 8 tool enhancement session files → `archive/2026-01/session-artifacts/tool-enhancements/`
- 5 investigation trails → `archive/2026-01/session-artifacts/investigations/`
- 31 one-off fixes → `archive/2026-01/session-artifacts/fixes/`

Consolidated:
- Multiple GATEWAY docs → `guides/NGROK_GATEWAY.md`
- Fix docs → `guides/TROUBLESHOOTING.md`

---

**Last Updated:** 2026-01-04
