# Validation Roadmap

Status: specialized engineering roadmap. Use this to plan empirical validation work for groundedness, predictive validity, and intervention usefulness. This is not the primary architecture overview.

## Why This Exists

UNITARES now has enough runtime plumbing that the main open question is no longer "can the system produce a state vector?" It can. The harder question is whether the state earns strong claims about agent self-regulation.

That question breaks into three narrower claims:

1. **Grounded**: the state tracks observable signals outside the agent's own narration.
2. **Predictive**: the state forecasts bad outcomes better than simple baselines.
3. **Causally useful**: interventions based on the state improve outcomes without excessive false alarms.

The repo is currently strongest on the first claim, partly equipped for the second, and only lightly prepared for the third. This roadmap exists to keep the validation work concrete and staged rather than letting the narrative outrun the evidence.

## Current Assets In The Repo

The evaluation starting point is not zero. Relevant surfaces already exist:

- `src/dual_log/continuity.py` cross-checks self-report against server-derived operational signals and tool-usage-derived complexity.
- `src/behavioral_sensor.py` computes behavioral EISV from observables such as decision history, coherence, calibration error, outcomes, and tool signals.
- `src/auto_ground_truth.py` defines what counts as exogenous evidence instead of letting calibration grade its own homework.
- `src/mcp_handlers/observability/outcome_events.py` records outcome events with EISV snapshots and state semantics.
- `src/outcome_correlation.py` computes verdict distributions, metric correlations, risk-bin bad rates, and dataset coverage.
- `scripts/analysis/analyze_drift.py` studies trajectory validation events.
- `scripts/analysis/export_outcome_dataset.py` exports flattened outcome rows for offline studies.

That means the immediate problem is not missing observability primitives. The immediate problem is turning them into a repeatable research ladder.

## Validation Ladder

| Claim | Question | Minimum evidence | Failure mode if skipped |
|------|----------|------------------|-------------------------|
| Grounded | Is the state tied to observables rather than just self-report? | High coverage of behavioral, primary, and exogenous outcome data | Introspection theater |
| Predictive | Do state and risk signals forecast bad outcomes? | Held-out correlation / ranking lift over simple baselines | Decorative monitoring |
| Causally useful | Do interventions based on the state help? | Controlled comparison of intervention policies | Expensive false-confidence |

The order matters. Do not run causal-intervention stories before the predictive layer is solid. Do not run predictive claims on a dataset with weak exogenous coverage.

## Phase 1: Groundedness

Goal: show that the dataset is meaningfully anchored in observable evidence.

Primary checks:

- Percent of outcome events with `primary_eisv`
- Percent with `behavioral_eisv`
- Percent where behavioral state is the primary source
- Percent with at least one exogenous signal
- Coverage by signal type: tests, commands, files, lint, tool observations, explicit outcome events

Run:

```bash
python3 scripts/analysis/export_outcome_dataset.py --since-hours 168
```

Success threshold:

- most outcome rows should include a snapshot
- exogenous coverage should be common enough that calibration is not dominated by internally generated labels
- behavioral primary should be common outside very-early-life agents

If those conditions fail, do not make stronger predictive claims yet. Improve capture of tests, command outcomes, file operations, and tool-result summaries first.

## Phase 2: Predictive Validity

Goal: determine whether the state predicts degradation better than simpler alternatives.

Core comparisons:

- EISV metrics vs bad outcome rate
- risk bin vs bad outcome rate
- verdict vs bad outcome rate
- behavioral-primary rows vs ODE-primary rows
- full dual-log features vs simpler baselines

Baselines to beat:

- constant global bad-rate baseline
- verdict-only baseline
- simple risk-only baseline
- self-report-only subset

Study shape:

1. Export outcome rows for a time window.
2. Split train/test by time or by agent family.
3. Compare ranking quality and calibration, not just raw correlation.
4. Report where the model fails: early-life agents, sparse-tool agents, or heavily embodied agents.

Success threshold:

- high-risk bins should show materially higher bad-outcome rates than healthy bins
- behavioral-primary rows should not underperform the simpler ODE fallback on held-out data
- the full grounded feature set should beat verdict-only and risk-only baselines

## Phase 3: Causal Usefulness

Goal: show that acting on the state improves outcomes.

Do not start here first. Once predictive validity is acceptable, run controlled comparisons:

- `control`: no governance intervention
- `observe_only`: record state but do not alter behavior
- `mirror_only`: surface guidance/question without hard intervention
- `full_intervention`: allow guide/pause/reject or restorative actions

Measure:

- task completion rate
- retry count
- rollback / failure rate
- time to recovery after degradation
- false positive intervention rate
- operator burden

Success threshold:

- interventions reduce bad outcomes or reduce recovery time
- false positives stay low enough that the system is not just freezing useful work

## Minimal Instrumentation Priorities

These are the next concrete changes worth making if the dataset is still thin:

1. Capture exogenous evidence by default on every check-in path:
   - tests
   - command exit codes
   - lint results
   - file-operation summaries
   - tool result summaries
2. Preserve signal provenance so features can be grouped by source rather than only by value.
3. Distinguish agent classes in analysis:
   - text/tool-grounded
   - sensor-grounded
   - embodied
4. Keep intervention logs explicit so causal studies can tell "state was observed" from "state changed behavior."

## Practical Operating Rule

Use the following rule of thumb when talking about the system:

- If groundedness is strong but predictive evidence is weak, say the system is **grounded but not yet validated as a predictor**.
- If predictive evidence is strong but intervention evidence is weak, say the system is **predictive but not yet proven to improve outcomes**.
- Only call the system a true self-regulation layer once the intervention step shows net benefit.

That keeps the public framing honest while still letting the engineering and research work move forward.
