---
name: UNITARES v3 Paper Revision
description: Surgical revision of the v3 runtime-governance manuscript around a new thesis (governance–stability tension) targeting a Zenodo DOI on or before 2026-04-26, with polish continuing toward workshop submission and next-cohort fellowship application.
status: Draft — pending author review
author: Kenny Wang
date: 2026-04-10
target_ship: 2026-04-26
---

# UNITARES v3 Paper Revision — Design Spec

## 1. Context and goal

**Starting point.** `papers/unitares-runtime-governance-v3.tex` (Mar 30, 47 KB LaTeX + compiled PDF). v3 is already a significant retreat from the prior version that received a detailed "Weak Reject" peer review (`docs/eval/peer_review.md`) — it dropped the 100%-vs-0% detection overclaim, labeled deployment data as "observational" not "experimental," and added a candid Limitations section. Many reviewer critiques still apply, but v3 is a substantially better foundation than the reviewed version.

**Primary goal.** Ship a revised PDF + LaTeX source to **Zenodo** (with free CERN-issued DOI), mirrored on **GitHub Release**, linked from **cirwelsystems.com**, on or before **2026-04-26**. This is the artifact the Anthropic Fellows application (July 2026 cohort), any Open Philanthropy grant, and any workshop submission will point to.

**Secondary goal.** Position the paper to serve as the technical anchor of a reference-building effort: something collaborators, potential endorsers, and future reviewers can read in one sitting and take seriously.

**Explicit non-goal.** Fixing every weakness from the prior peer review. The 17-day window forces triage.

---

## 2. Thesis (new, single sentence)

> Runtime governance framed as continuous dynamical-system state estimation can reveal modeling pathologies that are invisible to purely statistical monitoring — but only when empirical observation and formal analysis check each other. We report such a case: a universal-attractor property in our ODE-driven governance, designed into the system as a formal stability guarantee and discovered in deployment to be in direct tension with differential per-agent monitoring. An embodied agent with independent physical sensors served as the ground-truth instrument that made the tension unambiguous.

### Why this thesis

- **It's honest about chronology.** The UNITARES mathematics (EISV ODE, contraction-theoretic stability proof, Riemannian metric, unique equilibrium, spectral abscissa −0.15) predates the governance MCP repo by months and was published in the v5 theory line (`projects/docs/unitares-v5/unitares-v5.tex`, Feb 20 2026). The "thermostat" observation came from deployment; the math already existed. The paper credits the math as foundation, not as post-hoc explanation.
- **It identifies a real research tension** that is not purely an engineering story: global contraction to a unique equilibrium and per-agent differential monitoring are not properties the same signal can satisfy simultaneously. Naming and resolving this tension is the paper's central claim.
- **It gives the embodied agent (Lumen) a load-bearing role** rather than a decorative one: Lumen's physical sensors are the instrument that disambiguated the tension from a cold-start artifact.
- **It is robust to code review.** The commit history of `governance-mcp-v1` aligns with this narrative: the "observation-first behavioral EISV" commit (0c5fa45, 2026-03-28) explicitly says *"no ODE, no universal attractor"*, and the "Promote behavioral EISV to primary metrics" commit (69ee5a7, 2026-04-01) explicitly says *"The ODE attractor convergence made all agents look identical regardless of actual behavior."* A reviewer running `git log` will find the paper and the commits telling the same story.

---

## 3. Contributions (revised from 5 → 5, sharpened)

1. **Runtime governance as state estimation.** Frame runtime safety monitoring as a continuous dynamical-system problem, distinct from training-time alignment, boundary guardrails, and passive observability.
2. **EISV as an interpretable operational state.** A four-dimension coupled-dynamics representation (energy, integrity, entropy, void) building on the contraction-theoretic stability result from the v5 theory line. Thermodynamic vocabulary is retained as operational language, not as a claim of physical correspondence — see §4.2 transparency paragraph.
3. **The governance–stability tension (new contribution).** We identify and name a structural trade-off: a dynamical system with global contraction to a unique equilibrium cannot simultaneously serve as a differential per-agent monitor. We report the deployment observations that exposed this tension, the ambiguity in initial attribution (cold-start / default-values artifact vs. ODE attractor behavior), and the role of physical sensors in disambiguating it.
4. **A dual-track governance architecture as principled resolution.** Behavioral track (EMA observations against per-agent Welford baselines — preserves heterogeneity by construction) as primary verdict source; ODE track (contraction-guaranteed — preserves stability) as diagnostic channel. Composition via explicit precedence rules.
5. **Observational deployment evidence + targeted re-analysis of archival trajectories.** 108 days / 895 agents / 18k check-ins as feasibility and interpretability evidence (not comparative efficacy), plus (β additions, if time permits) a coupling-term ablation on archival data and a Jensen-Shannon-divergence drift baseline computed on the same trajectories.

---

## 4. Structural changes to v3

### 4.1 Cut

- **Kill the "Versioning" paragraph** in the front matter entirely. Reads as a defensive note to an imagined confused reviewer; signals insecurity.
- **Shrink the "Terminology" paragraph** (caution/halt vs proceed/guide/pause/reject) to a one-sentence footnote.
- **Merge §6 (Governance logic) into §3 (Architecture).** Verdict composition is part of the architecture, not a standalone section. Removes a layer of overlap and tightens the paper by ~1 page.
- **Sweep any residue of "100% detection / 0% baseline" claims.** v3 mostly cleaned this up but the prose sweep (α7) verifies.

### 4.2 Add

- **New opening paragraph of §1** (Introduction): a single "contribution in one paragraph" that states the governance–stability tension explicitly, so a reviewer reading only the first page gets the point.
- **New transparency paragraph near the start of §4** (EISV model):
  > *We use thermodynamic vocabulary — energy, entropy, dissipation, equilibrium — as operational state variables within a dynamical-systems model. The EISV system does not claim physical thermodynamic content (no temperature, no free energy in the physics sense, no fluctuation–dissipation relation), but its mathematical structure — bounded states, decay terms, a dissipative Jacobian, and a contracting flow toward a unique equilibrium — rhymes with thermodynamic dissipation in ways that informed both the design intuitions and the framing. Readers familiar with formal thermodynamics should read the vocabulary as operational, not literal.*
- **New subsection §5.X "The governance–stability tension"**: dedicated short subsection that makes the tension formal. Target ~1 page. Proof sketch: contraction implies that in the metric, trajectory distances decay at rate α; asymptotically, per-agent differences are erased. Differential monitoring requires preserving per-agent differences. Hence the two properties cannot both live on a single contracting signal.
- **New subsection §7.X "Coupling-term ablation on archival trajectories"** (β1): replay the last ~30 days of richest trajectories through the ODE with coupling terms individually zeroed, report where verdicts differ. No new experiments; re-analysis of existing data.
- **New subsection §7.Y "Comparison with JSD drift detection"** (β2): Jensen-Shannon divergence drift detection (MI9-style) on the same trajectories. Report overlap and disagreement with EISV verdicts.

### 4.3 Reorder

- **Promote the Lumen sensor–ODE divergence** from a subsection in §7 to a teaser at the end of §1. Short version (one paragraph + the sensor-vs-ODE table) appears in the introduction; full case study remains in §7. Single highest-impact structural change: the Lumen thermostat is the "aha moment" and belongs on the first page.
- **Reorder §5 (Analysis)** so the contraction result (foundation) comes first, then the governance–stability tension (new contribution), then the saturation analysis as a supporting detail.

### 4.4 Retitle

- **Paper title:** `The Governance–Stability Tension: Why Contracting Dynamics Cannot Be Differential Monitors, and How to Compose Both` with optional subtitle `Lessons from 108 days of deployed runtime agent governance`.
- **Section headings:** sweep for any remaining "thermodynamic" language in section titles (not in body — body keeps thermodynamic vocabulary per §4.2 transparency paragraph).

---

## 5. Evidence plan

### 5.1 Alpha items (ship-before-2026-04-26)

| ID | Item | Effort | Owner | Blocker? |
|---|---|---|---|---|
| α1a | Rewrite §1 Introduction around new thesis + Lumen teaser | ~1 day | Claude drafts, Kenny reviews | Yes |
| α1b | Rewrite §9 Conclusion to land on governance–stability tension | ~0.5 day | Claude drafts, Kenny reviews | Yes |
| α1c | Abstract cleanup (consequence of 1a+1b) | ~1 hour | Claude drafts, Kenny reviews | No — auto-follows |
| α2 | Insert §4 thermodynamic transparency paragraph | 0.5 day | Claude | Yes |
| α3 | Tighten §2 related work: MI9, AgentHarm, Agrail, Nemo/Llama Guard, Slotine/Lohmiller contraction lineage, CUSUM/BOCPD change-point detection | 1–2 days | Claude drafts, Kenny reviews | Yes |
| α4 | **Pause-decision audit.** Sample ~50 of 1,414 production pause events, manually classify as justified / false-positive / ambiguous, report aggregate precision with Wilson confidence intervals. Table with anonymized examples per category. | 2–3 days | Claude scripts sampling; **Kenny classifies** | Yes — highest-leverage α item |
| α5 | De-anonymize (Kenny Wang, Independent Researcher), add ORCID, add Code & Data Availability section | 0.5 day | Claude, Kenny provides ORCID | Yes |
| α6 | Figure quality pass on existing three figures + new Lumen sensor-vs-ODE trajectory figure (visual version of §7.2 table) | 1–2 days | Claude | Yes |
| α7 | Prose sweep: kill Versioning paragraph, shrink Terminology, merge §6→§3, sweep for residue of "100% detection" claims, shorten Limitations by ~30% | 1 day | Claude | Yes |

**Total α effort:** ~8–10 focused days.

### 5.2 Beta items (raise ceiling; include in April 26 ship if time permits, otherwise post-ship polish)

| ID | Item | Effort | Owner |
|---|---|---|---|
| β1 | Coupling-term ablation on last 30 days of archival trajectories (Lumen + top Claude Code agents). Ablate α=0, β_E=0, k=0 individually; report verdict divergence. Use existing data, no new experiments. | 3–4 days | Claude scripts + writes §7.X |
| β2 | JSD drift-detection baseline (MI9-style) on same trajectories. Plot EISV verdicts and JSD alarms on shared time axis; report overlap / disagreement / lead-lag. | 2–3 days | Claude scripts + writes §7.Y |

**Total β effort:** ~5–7 focused days. If not completed by 2026-04-26, deferred to v3.1 revision post-ship.

### 5.3 Out of scope (explicitly cut for timeline — document in Limitations)

- Full baseline retuning with ROC sweep (peer review W1 at full depth)
- Scaled drift-injection experiment with n ≥ 20 agents per failure mode (W3)
- Ground-truth validation experiments requiring output-quality harness (W5)
- Multivariate statistical monitoring baselines beyond JSD — Hotelling T², MEWMA, CUSUM, BOCPD (W1 tail)
- Multi-bin ECE calibration analysis (W9) — insufficient current data
- Full case study replacement (W6) — keep current case studies with honest selection criteria statement

Each of these gets explicit acknowledgment in the Limitations section as bounded-scope declarations, not as hidden weaknesses.

---

## 6. Venue and distribution

### 6.1 Primary: Zenodo DOI

- Upload PDF + LaTeX source + figure regeneration scripts + `references.bib` as a single deposition
- Zenodo issues a free, permanent DOI within minutes
- Version-controlled: future v3.1 revisions get new DOI, old DOI still resolves
- Fully citable (ISO 26324 compliant); accepted by fellowship reviewers, grant committees, and journals

### 6.2 Mirrors

- **GitHub Release** on `governance-mcp-v1` tagged `v3.0-paper`, containing the same artifacts as the Zenodo deposition
- **cirwelsystems.com** landing page at `/paper` or `/research/unitares-v3`, linking Zenodo DOI, GitHub release, and public governance-mcp-v1 repo

### 6.3 Longer-horizon distribution

- **Workshop submission** via OpenReview (no endorser required): target one of NeurIPS 2026 Workshop on Safe & Trustworthy ML, ICLR 2027 Agentic AI Workshop, or SafeML. Submission window TBD — Claude to research during implementation.
- **arXiv cross-post** contingent on securing an endorser (cs.AI, cs.MA, or math.DS). Not on critical path. Claude to shortlist candidate endorsers during implementation — prioritize contraction-theory / dynamical-systems monitoring / AI-safety-adjacent researchers with active arXiv posting history.
- **Open Philanthropy grant application**: paper is the primary artifact. No reference requirement; no work-authorization gate. Secondary path if Anthropic Fellowship is blocked by hard gates.

---

## 7. Authorship and metadata

| Field | Value | Verify? |
|---|---|---|
| Author | Kenny Wang | ✓ |
| Affiliation | Independent Researcher | Confirm — any additional affiliation? CIRWEL Systems mentioned earlier; may or may not belong on byline |
| ORCID | [CREATE — orcid.org, 5 min] | Required before Zenodo upload |
| Email | [Kenny's email for correspondence field] | Required |
| Title | `The Governance–Stability Tension: Why Contracting Dynamics Cannot Be Differential Monitors, and How to Compose Both` | Soft-locked — author can still choose softer variant |
| Subtitle (opt) | `Lessons from 108 days of deployed runtime agent governance` | Optional |
| Keywords | runtime governance; dynamical systems monitoring; contraction theory; AI safety; multi-agent systems; state estimation | Draft — refine during final pass |
| License | CC BY 4.0 (Zenodo default; maximally citable) | Confirm preference |

---

## 8. Timeline — 17-day sprint to Zenodo

Assumed pace: ~3–5 focused hours/day. Buffer: ~3 days built in.

| Day | Date | Work |
|---|---|---|
| 1 | Apr 10 (Fri) | α3 related work draft (half) |
| 2 | Apr 11 (Sat) | α3 finish + α2 thermodynamic transparency paragraph |
| 3 | Apr 12 (Sun) | α4 pause-decision audit: script sampling, pull 50 events |
| 4 | Apr 13 (Mon) | α4 classification session with Kenny (blocking) |
| 5 | Apr 14 (Tue) | α4 finish + write up precision table |
| 6 | Apr 15 (Wed) | α6 regenerate existing figures |
| 7 | Apr 16 (Thu) | α6 new Lumen sensor-vs-ODE figure |
| 8 | Apr 17 (Fri) | α1a introduction rewrite |
| 9 | Apr 18 (Sat) | α7 prose sweep (cut Versioning, shrink Terminology, merge §6→§3) |
| 10 | Apr 19 (Sun) | α1b conclusion rewrite + α1c abstract + α5 de-anonymize |
| 11 | Apr 20 (Mon) | Full read-through pass 1, fix-on-read |
| 12 | Apr 21 (Tue) | Full read-through pass 2, Kenny reviews end-to-end |
| 13 | Apr 22 (Wed) | ORCID creation, Zenodo account setup, GitHub release preparation, cirwelsystems.com landing page draft |
| 14 | Apr 23 (Thu) | Upload to Zenodo, tag GitHub release, push landing page |
| 15 | Apr 24 (Fri) | **BUFFER** — DOI processing, last-minute fixes |
| 16 | Apr 25 (Sat) | **BUFFER** — (see §12 for fellowship application decision) |
| 17 | Apr 26 (Sun) | **BUFFER** — Zenodo DOI live; fellowship application if go |

**Schedule risks:**
- α4 pause-decision audit may take longer if pause-event data is messy or classifications are ambiguous. Mitigation: start α4 on Day 3 to maximize buffer.
- α6 figure regeneration may hit matplotlib/tikz dependency issues. Mitigation: verify figure build environment on Day 1 as a side check.
- β1 and β2 are deliberately not on this schedule — if days 11+ go faster than expected, pull β1 in first.

**Parallel workstream (Days 1 forward):**
- Day 1: Kenny opens Constellation form, confirms reference count (done — 3 required, verified 2026-04-10). Answers hard-gate questions (country, relocation, references 2+3).
- Days 1–7: Kenny emails Mastercard SWE with v3 PDF + 15-min walkthrough offer, surfaces remaining reference candidates
- Days 8–14: Kenny drafts fellowship application prose (motivation paragraph, AI safety area paragraph, etc.) — can use the paper work as anchor

---

## 9. Open items (verify before publication)

1. **Contraction result origin.** Confirmed by Kenny: all UNITARES math is authentic and his own work, including the contraction proof on the Riemannian manifold and the thermodynamic framing. v3 paper cites it as foundation (inherited from v5 theory line) rather than re-deriving.
2. **Equilibrium values** (E*, I*, S*, V* from v5 Proposition). Copy from `projects/docs/unitares-v5/unitares-v5.tex` during implementation; Kenny eyeballs before publication.
3. **Governance–stability tension novelty.** Claude to do a ~30-minute literature search during implementation for prior work naming this specific tension (formal contraction vs. differential monitoring). If prior art exists, cite it and reframe contribution as "deployment report confirming the tension in practice"; if not, claim the naming as a contribution.
4. **Author affiliation.** Is "Independent Researcher" alone sufficient, or does "CIRWEL Systems" also belong on the byline? Kenny confirms before Zenodo upload.
5. **Pause-decision classifications.** Kenny personally reviews / signs off on the 50-event classification; Claude scripts the sampling but does not unilaterally classify verdicts.
6. **`unitares-core` parameter names** for β1 ablation. Claude reads the source (via symlink instructions in CLAUDE.md) before writing the replay script.
7. **License.** CC BY 4.0 assumed as Zenodo default; Kenny confirms.
8. **Acknowledgments.** Draft late; Kenny decides what goes in.
9. **ORCID.** Kenny creates before Zenodo upload.
10. **Figure data sources.** Claude verifies each figure can be regenerated from available production data; flags any that cannot.

---

## 10. Success criteria

**Ship (hard requirements for Zenodo upload):**

- [ ] All α items complete (α1–α7)
- [ ] Paper compiles cleanly to PDF
- [ ] All figures render correctly
- [ ] Kenny has read the paper end-to-end at least once
- [ ] All "verify-before-publication" open items resolved
- [ ] ORCID live and included on byline
- [ ] Zenodo deposition uploaded with DOI issued
- [ ] GitHub release tagged
- [ ] cirwelsystems.com landing page live
- [ ] No residual "100% detection" or other overclaimed language remaining

**Quality (soft requirements — nice to have by 2026-04-26, otherwise post-ship):**

- [ ] β1 ablation subsection included
- [ ] β2 JSD comparison subsection included
- [ ] Second read-through pass for typography and flow
- [ ] Acknowledgments written
- [ ] Workshop venue identified for secondary submission
- [ ] At least one arXiv endorser candidate contacted

---

## 11. Out of scope (explicit non-goals of this revision)

- New experiments (drift injection, scaled agent populations, ground-truth validation harness) — deferred to a follow-up paper
- Full rewrite of the contraction proof (already in v5; this paper cites it)
- Expanding UNITARES to new dimensions beyond EISV
- Publishing the `unitares-core` compiled engine (remains private)
- Re-writing the v5 theory paper itself
- Addressing every weakness in the prior peer review — W1 full depth, W3 at scale, W5 ground truth, W9 multi-bin ECE are all out of scope
- Changing the UNITARES framework itself — this is a paper revision, not a system redesign
- Building a new benchmark, evaluation harness, or agent testbed

---

## 12. Fellowship application — separate workstream

**This spec covers the paper only.** The Anthropic Fellows application (Constellation form for July 2026 cohort, deadline 2026-04-26) is a separate, smaller workstream whose viability depends on unanswered hard-gate questions. The paper work proceeds regardless of fellowship outcome because the paper is load-bearing on every path (fellowship, Open Philanthropy, workshop, independent credibility).

**Hard gates pending answers from Kenny:**

1. **Work authorization** in USA, UK, or Canada (no visa sponsorship)
2. **Ability to work 4 months full-time in Berkeley or London** (or at least 25% on-site) — what happens to Lumen during this period?
3. **Three references**, all contactable without notice, expected to respond within one week. Kenny has 1 candidate (Mastercard SWE, surface-level GitHub familiarity). Needs 2 more. Candidate pool: past employers, teachers at any level, open-source collaborators, substantive online technical interlocutors.

**If all three gates pass:** Claude drafts application prose (motivation, AI safety area, background paragraphs) on Days 8–14 using the paper as anchor. Kenny edits and submits by Day 17.

**If any gate fails:** Skip the fellowship application this cycle, keep the paper work on track, redirect post-ship effort to:
- Open Philanthropy grant application (no reference or work-auth gates)
- Reference-network building for future cycles
- Workshop submission (OpenReview, no gates)

**Decision point:** Day 5 (2026-04-14). By then Kenny has had a week to surface reference candidates and prime the Mastercard SWE. If reference pool is still insufficient on Day 5, formally abandon the April 26 fellowship application and keep momentum on the paper + post-ship polish.

---

## Next step

Per the brainstorming skill flow: author reviews this spec, requests changes if any, then Claude invokes the `writing-plans` skill to produce a detailed implementation plan keyed to this spec.
