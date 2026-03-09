# Why UNITARES?

## The Problem

You deploy an agent. It runs. Can it tell you what's happening inside?

Not what it outputs — what's happening to its coherence, its confidence, its trajectory. Right now the answer is no. Agents have no language for inner state, so every observer is reading tea leaves from outputs.

This is why these failure modes persist:

- An agent loops on the same decision 47 times before anyone notices — it couldn't say "I'm stuck"
- A multi-agent handoff silently fails — Agent B had no way to read that Agent A was degrading
- An agent's context slowly corrupts over a long session — no vocabulary for "my integrity is dropping"
- Token spend spikes on a doomed retry — the agent couldn't express "this isn't working"

The common thread: agents can't communicate their state. Logs tell you what happened, not what's happening. The missing piece isn't better monitoring — it's a shared language for inner state.

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

Dashboards show request counts — activity, not quality.

None of these give agents a way to *say* what's happening inside them. The problem isn't insufficient data collection — it's that agents have no vocabulary for self-report.

## The Approach

UNITARES provides that vocabulary. Four continuous variables borrowed from thermodynamics that any agent can report and any observer can read:

| Variable | Intuition |
|----------|-----------|
| **Energy** | Useful work being done |
| **Integrity** | Information staying coherent |
| **Entropy** | Disorder accumulating |
| **Void** | Cumulative imbalance (debt accruing) |

Physics gives us vocabulary for systems that *trend* rather than *crash*. An agent doesn't suddenly fail — it drifts toward failure. Continuous variables make the drift legible. Check-ins are speech acts: an agent expressing its state in shared terms.

## What You Get

Once agents can express state in a shared language, you get:

- **Legibility** — Any observer (human, system, other agent) can read an agent's inner state without inspecting outputs
- **Early warning** — EISV trajectories show drift ~20 minutes before failure
- **Circuit breakers** — Automatic pause at risk thresholds, resume when stable
- **Inter-agent observation** — Agents read each other's state vectors for handoff decisions and coordination
- **Dialectic resolution** — Structured disagreement requires shared state language: thesis → antithesis → synthesis
- **Knowledge persistence** — Discoveries tagged to agent state survive sessions; agents build on each other's findings

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
git clone https://github.com/CIRWEL/unitares.git
cd unitares
pip install -r requirements-core.txt
python src/mcp_server.py --port 8767
```

Point your client at `http://localhost:8767/mcp/` and call `onboard()`.

→ [Getting Started](guides/GETTING_STARTED_SIMPLE.md) for the full walkthrough.

---

Questions? Open an issue or reach out to [@CIRWEL](https://github.com/CIRWEL).
