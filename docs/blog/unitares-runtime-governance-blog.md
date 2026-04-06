# Runtime governance is not a rubric — it is a loop

**Status:** narrative companion. For operational truth and authority ordering, see [CANONICAL_SOURCES.md](../CANONICAL_SOURCES.md) and [UNIFIED_ARCHITECTURE.md](../UNIFIED_ARCHITECTURE.md).

---

Most “AI safety” stories are about judging outputs: pass the test, avoid the toxic completion, ship the eval. That is useful, but it leaves a gap. An agent can produce acceptable text while drifting in how it works: overconfident, inconsistent about difficulty, noisy in its own sense of stability. **Runtime governance** is the practice of closing that gap by maintaining a shared, readable notion of *condition* while work is happening — not only after the fact.

UNITARES implements that idea as a server-side loop agents can join through a simple protocol: identify, report what you did, read governance back.

## Why a loop beats a scorecard

A scorecard answers “was this answer OK?” A governance loop answers “what is happening to this agent over time, and should it continue, adjust, or stop?” The difference matters for anything that runs longer than a single turn: coding agents, embodied systems, or any workflow where the *trajectory* is part of the product.

UNITARES compresses inner state into four continuous variables — **E, I, S, V** (energy, integrity, entropy, void) — derived from what actually happens in the check-in stream, not from a model’s self-story alone. Reflective fields like self-reported complexity and confidence can inform the picture, but they are cross-checked against operational signals, continuity, tool usage, and calibration history. That dual perspective is what keeps the system from mistaking fluent narration for grounded behavior.

## What happens on each check-in

When an agent calls `process_agent_update`, the server does not merely append a log line. The request flows through a **governance pipeline**: identity and session continuity, behavioral state update, drift-related signals, calibration hooks, and a **verdict** that tells the agent whether to proceed, take guidance, pause, or escalate.

The primary driver of verdicts is **behavioral EISV**: exponentially smoothed observations built from grounded signals, with per-agent baselines after enough history so scoring can be **self-relative** — meaningful variation against *this* agent’s operating point, not only global thresholds.

In parallel, a **thermodynamic ODE** over the same four variables can run as analysis and diagnostic context. The important architectural point is simple: **behavioral state leads verdicts**; the ODE is a lens, not a silent autopilot for action. When documentation and intuition disagree, the code paths in `docs/CANONICAL_SOURCES.md` settle the argument.

## Drift, calibration, and “ethics” without a oracle

“Ethical drift” in this system is not a hand-labeled moral score. It is a small vector of **observable mismatches** — calibration deviation, complexity divergence, coherence deviation, stability deviation — that feeds entropy dynamics. Calibration ties stated confidence to outcomes where objective signals exist (tests, exit codes, lint). Over time, systematic overconfidence becomes visible in state, not just in a one-off critique.

That design matters for operators: you can run governance without pretending the server has private access to an agent’s intentions. It has access to **what happened** and **what was claimed**, bridged by machinery that resists both blind trust and blind cynicism.

## When things go wrong, structure beats panic

High-friction states route toward **recovery** rather than an ambiguous “error”: circuit breaker behavior, self-recovery where thresholds allow, and **dialectic** flows — sometimes LLM-assisted, sometimes peer-based — that turn disagreement into a structured path back to coherence. The goal is not theatrical punishment; it is to keep the fleet from silently training itself into a corner.

Behind the scenes, a **knowledge graph** lets discoveries accumulate across agents so the system does not relitigate the same dead ends forever. PostgreSQL and Apache AGE ground that persistence; Redis, when present, is a cache layer, not the source of truth.

## How to actually use it

The default path is intentionally small:

1. `onboard()` — establish identity and continuity handles  
2. `process_agent_update()` — describe work; optional reflective fields  
3. `get_governance_metrics()` — read consolidated state  

Prefer `continuity_token` when the server indicates support; thread `client_session_id` when that is the continuity you have. Response modes like `mirror` exist so agents get **actionable** signals without drowning in raw vectors.

## Closing

Runtime governance, in this sense, is **digital proprioception** for agents: a shared language for condition that can be read by humans, services, and other agents without reverse-engineering logs. The interesting engineering lives where behavioral signals, continuity, and calibration meet — and where verdicts stay tied to the runtime that actually executes, not to the story alone.

---

*For setup, transports, and operator procedures, start with [README.md](../../README.md), [START_HERE.md](../guides/START_HERE.md), and [OPERATOR_RUNBOOK.md](../operations/OPERATOR_RUNBOOK.md).*
