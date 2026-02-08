# Why UNITARES?

## The Problem

You deploy an agent. It runs. Is it working?

Real failure modes from agent systems:

- An agent loops on the same decision 47 times before anyone notices
- A multi-agent handoff silently fails - Agent B never picks up what Agent A handed off
- An agent's context slowly corrupts over a long session, outputs degrade gradually
- Token spend spikes because an agent is retrying a doomed approach

By the time you notice, the damage is done. Logs tell you what happened, not that it's happening.

## What This Looks Like

Here's a real pattern: an agent starts a task, makes progress (Energy rising), but its context is getting polluted with irrelevant information (Integrity dropping). Traditional monitoring shows steady API calls - everything looks fine. UNITARES shows the divergence:

```
E: 0.72 → 0.68 → 0.61 → 0.54    (productive work declining)
I: 0.85 → 0.71 → 0.58 → 0.44    (coherence degrading faster)
S: 0.12 → 0.24 → 0.38 → 0.51    (disorder accumulating)
```

Twenty minutes before failure, you see the trend. Intervene, or let the circuit breaker pause it automatically.

## Why Not Just Logs and Alerts?

Logs are post-mortem. You read them after something breaks.

Alerts are binary. "Agent crashed" or silence.

Dashboards show request counts - activity, not quality.

None of these answer: *is this agent making progress, or spinning?*

## The Approach

UNITARES tracks continuous state using four variables borrowed from thermodynamics:

| Variable | Intuition |
|----------|-----------|
| **Energy** | Useful work being done |
| **Integrity** | Information staying coherent |
| **Entropy** | Disorder accumulating |
| **Void** | Cumulative imbalance (debt accruing) |

Physics gives us vocabulary for systems that *trend* rather than *crash*. An agent doesn't suddenly fail - it drifts toward failure. Continuous variables let you see the drift.

## What You Get

- **Early warning** — Catch stuck agents, loops, drift before they cost real money
- **Circuit breakers** — Automatic pause at risk thresholds, resume when stable
- **Cross-agent visibility** — Compare agents, spot anomalies, aggregate health
- **Dialectic resolution** — When agents disagree: thesis → antithesis → synthesis
- **Knowledge persistence** — Discoveries survive sessions, agents learn from each other

## Who This Is For

You're a good fit if:
- You're running agent systems that need to work unattended (overnight jobs, batch processing)
- You're spending enough on inference that waste matters (>$100/month)
- You're coordinating multiple agents and handoffs are failure points
- You want observability without building it yourself

You're not a good fit if:
- You're running single-shot agents with human review after each response
- You're still prototyping and not at reliability-matters stage

## Why Now

MCP just shipped. Agent frameworks are proliferating. Everyone's building multi-agent systems, few are building governance for them. The patterns for agent observability aren't established yet.

UNITARES is one approach: physics-grounded continuous state. It may not be the only way, but it's a real system running in production.

## Integration

Three calls:

```
1. onboard()                  → Establish identity
2. process_agent_update()     → Log work as you go
3. get_governance_metrics()   → Check state
```

MCP server drops into Claude Desktop, Cursor, or any MCP client. REST API for everything else.

```bash
git clone https://github.com/CIRWEL/governance-mcp-v1.git
cd governance-mcp-v1
pip install -r requirements-core.txt
python src/mcp_server.py --port 8767
```

Point your client at `http://localhost:8767/mcp/` and call `onboard()`.

→ [Getting Started](guides/GETTING_STARTED_SIMPLE.md) for the full walkthrough.

---

Questions? Open an issue or reach out to [@CIRWEL](https://github.com/CIRWEL).
