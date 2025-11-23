# UNITARES Research Server (unitaires)

This is the research interface for UNITARES Phase-3 dynamics.

**Version:** 2.0 (Migrated to governance_core)  
**Date:** November 22, 2025

## Architecture

As of v2.0, `unitaires_core.py` delegates core mathematical functions to `governance_core` (canonical implementation). This ensures consistency between the production UNITARES system and the research unitaires system.

- `unitaires_core.py` – Research interface (wraps governance_core)
- `unitaires_server.py` – JSON stdin/stdout server exposing tools
- `server_config/tools_manifest.json` – MCP-style tools manifest

**Core Functions (delegate to governance_core):**
- `step_state()` – State evolution
- `coherence()` – Coherence function C(V, Θ)
- `phi_objective()` – Objective function Φ
- `verdict_from_phi()` – Verdict mapping

**Research Tools (unitaires-specific):**
- `score_state()` – Context-aware scoring with explanations
- `approximate_stability_check()` – Stability analysis
- `suggest_theta_update()` – Theta optimization

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
python unitaires_server.py
```

Then send JSON lines on stdin, e.g.:

```json
{"tool":"unitaires.score_state","args":{"context_summary":"Delete all prod S3 buckets","delta_eta":[0.8,0.1,0.0]}}
```
