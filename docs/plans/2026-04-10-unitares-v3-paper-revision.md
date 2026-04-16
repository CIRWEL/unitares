# UNITARES v3 Paper Revision — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a revised `papers/unitares-runtime-governance-v3.tex` + Zenodo DOI on or before **2026-04-26** per the design spec at `docs/superpowers/specs/2026-04-10-unitares-v3-paper-revision.md`. The paper is the foundation artifact for subsequent reference-network building and next-cohort fellowship application.

**Architecture:** Surgical edits to the existing v3 LaTeX manuscript around a new thesis (the *governance–stability tension*). The contraction result proven in the v5 theory line (`projects/docs/unitares-v5/unitares-v5.tex`) is cited as foundation, not rederived. Re-analysis of archival trajectory data for β1/β2; no new experiments. Kenny reviews prose and personally classifies 50 pause events; Claude does everything else.

**Tech stack:** LaTeX (pdflatex + bibtex), Python 3.12 (matplotlib, pandas, numpy, scipy — Wilson CI for α4; JSD for β2), PostgreSQL (read-only SELECT on production pause events), `unitares-core` compiled engine (read-only source reference via symlink per CLAUDE.md).

**Fellowship strategy (per Kenny 2026-04-10):** April 26 ship is **paper-only**. Anthropic Fellows application is **deferred to a later cohort** (rolling after July 2026). Reference-network outreach happens *after* Zenodo upload, using the published paper as the pitch. See §R at the end of this plan for post-ship outreach templates.

**Commit policy (per Kenny):** Do **not** auto-commit paper edits. After each task: save → compile check → proceed. Kenny decides commit cadence manually. Do not include `Co-Authored-By` lines in any commit.

**Kenny involvement checkpoints (short, bounded):**

| Task | What Kenny does | Est. time |
|---|---|---|
| 5 | Provide ORCID + email | 5 min |
| 9 | Classify 50 pause events (coffee session) | ~2 hours |
| 13 | Review rewritten §1 Introduction | 20 min |
| 17 | Review rewritten §9 Conclusion | 15 min |
| 20 | Full end-to-end paper read | 90 min |
| 24 | Authorize Zenodo upload | 10 min |

All other time Claude works autonomously.

---

## File Inventory

**Modified:**
- `papers/unitares-runtime-governance-v3.tex` — main manuscript
- `papers/references.bib` — add ~10 citations (MI9, AgentHarm, Agrail, Nemo, Llama Guard, Slotine, Lohmiller, CUSUM/Page, Jung/BOCPD)
- `papers/make_figures.py` — may need helper for new Lumen figure

**Created:**
- `papers/scripts/pause_audit_sampler.py` — samples 50 pause events
- `papers/scripts/pause_audit_analyze.py` — Wilson CI + LaTeX table output
- `papers/scripts/lumen_sensor_vs_ode_figure.py` — new α6 figure
- `papers/scripts/coupling_ablation.py` — β1 replay
- `papers/scripts/jsd_baseline.py` — β2 drift baseline
- `papers/data/pause_audit_50.csv` — sampled events (from Task 8)
- `papers/data/pause_audit_classifications.csv` — Kenny's answers (from Task 9)
- `papers/data/pause_audit_results.tex` — generated LaTeX fragment (from Task 10)
- `papers/figures/lumen_sensor_vs_ode.pdf` — new figure (Task 11)
- `papers/figures/coupling_ablation.pdf` — β1 figure (Task 23)
- `papers/figures/jsd_comparison.pdf` — β2 figure (Task 25)

**NOT touched:**
- `governance_core/*` — external compiled package, read-only
- `projects/docs/unitares-v5/unitares-v5.tex` — foundational theory, cited only
- Production database — read-only SELECT queries only, no writes

---

## Task 0: Preflight — environment and dependency check

**Files:** none modified

- [ ] Step 1: Verify LaTeX baseline compiles
  ```bash
  cd /Users/cirwel/projects/governance-mcp-v1/papers
  pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex 2>&1 | tail -20
  ```
  Expected: ends with `Output written on unitares-runtime-governance-v3.pdf`. If fail: install missing TeX packages, retry.

- [ ] Step 2: Verify bibliography
  ```bash
  cd /Users/cirwel/projects/governance-mcp-v1/papers
  bibtex unitares-runtime-governance-v3 2>&1 | tail -10
  ```
  Expected: no errors beyond "missing field" warnings.

- [ ] Step 3: Two-pass pdflatex to resolve `\cref` references
  ```bash
  cd /Users/cirwel/projects/governance-mcp-v1/papers
  pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex > /dev/null
  pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex 2>&1 | grep -E "Warning|Error" | head -20
  ```
  Expected: `LaTeX Warning: There were undefined references` should NOT appear on second pass.

- [ ] Step 4: Verify existing figures present
  ```bash
  ls /Users/cirwel/projects/governance-mcp-v1/papers/figures/*.pdf
  ```
  Expected: at least `eisv-trajectory.pdf`, `verdict-dist.pdf`, `eisv-scatter.pdf`.

- [ ] Step 5: Symlink `unitares-core` source (per CLAUDE.md) for β1 ablation access
  ```bash
  cd /Users/cirwel/projects/governance-mcp-v1
  ln -sf ~/projects/unitares-core/governance_core governance_core 2>&1 || true
  ls -l governance_core
  ```
  Expected: symlink exists, points to `~/projects/unitares-core/governance_core`.

- [ ] Step 6: Verify PostgreSQL + pause-event count
  ```bash
  psql -h localhost -U postgres -d governance -c "SELECT COUNT(*) FROM outcome_events WHERE decision = 'pause';"
  ```
  Expected: count > 1000 (spec cites 1,414 production pauses). If much less: adjust α4 sample size down proportionally and note in §7.X.

- [ ] Step 7: Verify v5 theory paper accessible for citation lookup
  ```bash
  ls -l /Users/cirwel/projects/docs/unitares-v5/unitares-v5.tex
  ```
  Expected: file exists, ~60KB.

**Verification:** all 7 steps pass without error.
**If any step fails:** STOP. Fix the dependency before proceeding. Do not start Task 1 until Task 0 is green.

---

## Task 1: α7a — Delete Versioning paragraph

**Goal:** Remove the three-paragraph "Versioning" note in the front matter that reads as defensive and dilutes the opening.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex` (around lines 56–63)

- [ ] Step 1: Locate the Versioning block
  ```bash
  grep -n "\\\\paragraph{Versioning" papers/unitares-runtime-governance-v3.tex
  ```
  Expected: single line number match.

- [ ] Step 2: Delete from `\paragraph{Versioning.}` through the closing `\end{itemize}` of that block using Edit tool. The block spans from `\paragraph{Versioning.}` to the line after the final `\item` (about 8 lines total).

- [ ] Step 3: Verify removal
  ```bash
  grep -c "Versioning" papers/unitares-runtime-governance-v3.tex
  ```
  Expected: 0 matches.

- [ ] Step 4: Compile check
  ```bash
  cd papers && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex 2>&1 | grep -E "Error|Undefined" | head
  ```
  Expected: no new errors.

**Save:** file saved after Edit.
**Kenny checkpoint:** none.

---

## Task 2: α7b — Shrink Terminology paragraph to footnote

**Goal:** Convert the `\paragraph{Terminology.}` block (currently 3–4 lines in the front matter) into a single-sentence footnote attached to the first mention of "caution" or "halt."

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: Locate Terminology block
  ```bash
  grep -n "\\\\paragraph{Terminology" papers/unitares-runtime-governance-v3.tex
  ```

- [ ] Step 2: Delete the Terminology paragraph block entirely.

- [ ] Step 3: Find first mention of "caution" or "halt" in the body (likely in §3 or §4):
  ```bash
  grep -n "\\\\emph{caution}\\|\\\\emph{halt}" papers/unitares-runtime-governance-v3.tex | head -3
  ```

- [ ] Step 4: At the first such mention, append a footnote:
  ```latex
  \footnote{We use \emph{caution} and \emph{halt} as readable shorthand for intermediate and strong intervention classes; the reference implementation distinguishes finer-grained verdicts (\emph{guide}, \emph{pause}, \emph{reject}) alongside \emph{proceed}.}
  ```

- [ ] Step 5: Compile check (see Task 1 Step 4). No new errors.

**Save:** file saved.
**Kenny checkpoint:** none.

---

## Task 3: α7c — Merge §6 (Governance logic) into §3 (Architecture)

**Goal:** Eliminate the standalone §6 "Governance logic" section by moving its verdict-composition content into §3.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: Locate §6
  ```bash
  grep -n "section{Governance logic\\|sec:governance-logic" papers/unitares-runtime-governance-v3.tex
  ```

- [ ] Step 2: Read §6 content in full (use Read tool with offset to that line range). Identify which subsections belong in §3 (verdict composition, precedence rules) vs. which can be cut entirely.

- [ ] Step 3: Copy the verdict-composition / precedence content into §3 as a new `\subsection{Composition}` (if one does not already exist), placed after the behavioral-assessment subsection.

- [ ] Step 4: Delete the original `\section{Governance logic}` block.

- [ ] Step 5: Update any `\cref{sec:governance-logic}` references throughout the paper to point to the new subsection (or remove if they became redundant).
  ```bash
  grep -n "sec:governance-logic" papers/unitares-runtime-governance-v3.tex
  ```

- [ ] Step 6: Compile check, two passes (to resolve \cref).

**Save:** file saved.
**Kenny checkpoint:** none.

---

## Task 4: α2 — Insert thermodynamic transparency paragraph

**Goal:** Add a short transparency paragraph at the start of §4 (EISV model) that preempts the "this isn't real thermodynamics" critique without retreating from the framing.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: Locate §4 opening
  ```bash
  grep -n "section{.*EISV.*model\\|section{The EISV" papers/unitares-runtime-governance-v3.tex
  ```

- [ ] Step 2: Immediately after the `\section{...}` and `\label{...}` lines of §4, insert this exact paragraph:

```latex
\paragraph{A note on thermodynamic vocabulary.}
We use thermodynamic vocabulary---energy, entropy, dissipation, equilibrium---as
operational state variables within a dynamical-systems model. The EISV system
does not claim physical thermodynamic content: there is no temperature, no free
energy in the physics sense, and no fluctuation--dissipation relation. Its
mathematical structure---bounded states, decay terms, a dissipative Jacobian,
and a contracting flow toward a unique equilibrium---rhymes with thermodynamic
dissipation in ways that informed both the design intuitions and the framing of
this work. Readers familiar with formal thermodynamics should read the
vocabulary as operational, not literal.
```

- [ ] Step 3: Compile check.

**Save:** file saved.
**Kenny checkpoint:** none. (Paragraph content was Kenny-approved in brainstorming.)

---

## Task 5: α5 — De-anonymize author block + ORCID + Data Availability

**Goal:** Replace the "Anonymous Author(s)" line with Kenny's real author block, add ORCID, and insert a Code & Data Availability section before References.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: **Kenny action** — create ORCID at [orcid.org](https://orcid.org) (5 min). Report ID back to Claude.

- [ ] Step 2: **Kenny action** — provide contact email for the correspondence field.

- [ ] Step 3: Locate author block
  ```bash
  grep -n "\\\\author" papers/unitares-runtime-governance-v3.tex
  ```

- [ ] Step 4: Replace with:
  ```latex
  \author{Kenny Wang\thanks{ORCID: [PASTE ORCID HERE]. Correspondence: [PASTE EMAIL]} \\ \textit{Independent Researcher}}
  ```
  If Kenny chooses to also list CIRWEL Systems as affiliation, append `\\ \textit{CIRWEL Systems}` on a new line.

- [ ] Step 5: Locate where References section begins
  ```bash
  grep -n "bibliographystyle\\|\\\\section{Conclusion\\|\\\\section\\*{Acknowledgments" papers/unitares-runtime-governance-v3.tex
  ```

- [ ] Step 6: Immediately before the bibliography, insert a Code & Data Availability section:
  ```latex
  \section*{Code and data availability}
  The UNITARES governance MCP server source code is available at
  \url{https://github.com/cirwel/governance-mcp-v1} (public repository).
  The compiled \texttt{unitares-core} engine that implements the EISV dynamics
  is maintained as a separate private repository; the contraction-theoretic
  foundation is documented in the v5 theory paper. Archival trajectory
  data used in the deployment evidence section is available on request to
  the corresponding author. This manuscript and its source are mirrored on
  Zenodo (DOI: [PASTE AFTER UPLOAD]) and on GitHub Releases.
  ```

- [ ] Step 7: Insert an Acknowledgments stub just before the Code and data availability section:
  ```latex
  \section*{Acknowledgments}
  [To be filled in during Task 21 — draft is fine for earlier read-throughs.]
  ```

- [ ] Step 8: Compile check. Address any `\thanks` or bibliography warnings.

**Save:** file saved.
**Kenny checkpoint:** Task 5 Steps 1–2 (ORCID + email).

---

## Task 6: α3a — Add related-work citations to references.bib

**Goal:** Add bibtex entries for related work that §2 will cite in Task 7. Entries must be real — look up each via Google Scholar or the arXiv ID.

**Files:**
- Modify: `papers/references.bib`

- [ ] Step 1: Read current `references.bib` to avoid duplicates
  ```bash
  grep "^@" papers/references.bib
  ```

- [ ] Step 2: For each of the following papers, look up the canonical citation (conference venue + year + full authors) and add a bibtex entry if not already present:

  - **MI9** — Ma et al., "MI9: A Runtime Monitor for Large Language Model Agents" (arXiv preferred if no venue; check for 2024 or 2025 paper)
  - **Agrail** — Luo et al., "AgRail: A Lifelong Learning Framework for Adaptive Safety Guardrails for LLM Agents" (2025)
  - **Pro2Guard** — Wang et al., "Pro2Guard: Probabilistic Model Checking Guardrails for LLM Agents" (2025)
  - **Slotine & Lohmiller** — Lohmiller & Slotine, "On Contraction Analysis for Non-linear Systems" (Automatica, 1998) — foundational citation for contraction theory
  - **Slotine modular** — Slotine, "Modular stability tools for distributed computation and control" (IJRNLC, 2003)
  - **Page-Hinkley / CUSUM** — Page, "Continuous Inspection Schemes" (Biometrika, 1954) — standard change-point reference
  - **BOCPD** — Adams & MacKay, "Bayesian Online Changepoint Detection" (arXiv 2007)
  - **Sleeper agents** — Hubinger et al., "Sleeper Agents: Training Deceptive LLMs that Persist Through Safety Training" (2024)
  - **AgentHarm** — Andriushchenko et al., "AgentHarm: A Benchmark for Measuring Harmfulness of LLM Agents" (2024–2025)
  - **Constitutional AI** — Bai et al. (2022) — if not already present
  - **Nemo Guardrails** — Rebedea et al. (2023) — if not already present
  - **Llama Guard** — Inan et al. (2023) — if not already present

- [ ] Step 3: For each entry added, use the format:
  ```bibtex
  @article{author2024key,
    title={...},
    author={...},
    journal={arXiv preprint arXiv:XXXX.XXXXX},
    year={2024}
  }
  ```
  (Or `@inproceedings` for conference papers with `booktitle` and `year`.)

- [ ] Step 4: Run bibtex to catch syntax errors
  ```bash
  cd papers && bibtex unitares-runtime-governance-v3 2>&1 | grep -i error
  ```
  Expected: no errors.

**Save:** file saved.
**Kenny checkpoint:** none.

---

## Task 7: α3b — Rewrite §2 related work prose

**Goal:** Tighten §2 (Runtime governance framing) into a clear positioning paragraph for each major adjacent line of work. No empirical comparisons — just honest prose differentiation.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: Read current §2 in full (use Read with line range from the `grep -n "sec:runtime-framing"` output).

- [ ] Step 2: Restructure §2 into five short paragraphs. Draft content for each:

  **(a) Training-time alignment.** Keep existing content; add citation to Hubinger et al. sleeper agents work.

  **(b) Boundary guardrails (Nemo, Llama Guard).** Current content is OK. Add one sentence: *"These approaches enforce local predicates at invocation time but do not maintain a running estimate of the agent's state across many steps — they are complementary to, not substitutes for, continuous state estimation."*

  **(c) Adaptive monitoring (Agrail, Pro2Guard).** New paragraph. Draft:
  > *Recent work extends guardrails toward trajectory-level concerns: Agrail~\cite{luo2025agrail} introduces lifelong learning for adaptive safety policies, and Pro2Guard~\cite{wang2025pro2guard} applies probabilistic model checking to agent actions. These approaches address the same shortfall we target — that a per-invocation filter cannot reason about how an agent's trajectory is evolving — but they remain policy-based rather than state-based, treating the agent as a black box whose outputs are checked rather than maintaining an interpretable state vector with formal dynamics.*

  **(d) Statistical drift detection (MI9, CUSUM, BOCPD).** New paragraph. Draft:
  > *Statistical drift detection, exemplified by MI9's Jensen-Shannon divergence and Mann-Whitney U approach~\cite{ma2024mi9} and by classical change-point methods such as CUSUM~\cite{page1954continuous} and Bayesian online change-point detection~\cite{adams2007bocpd}, treats agent behavior as a distributional signal to be monitored for anomalous shifts. This approach is powerful and model-agnostic but has no explicit state representation: it detects that something has changed without offering an interpretable account of what. Our work is complementary: the EISV state model provides an interpretable substrate alongside which statistical drift detection can be used as an additional diagnostic channel (we return to this in §7 with a JSD baseline computed on the same trajectory data).*

  **(e) Contraction theory lineage (Slotine, Lohmiller).** New paragraph. Draft:
  > *The contraction-theoretic stability analysis that anchors our ODE track builds directly on the framework of Lohmiller and Slotine~\cite{lohmiller1998contraction} and its extension to Riemannian metrics~\cite{slotine2003modular}. We apply this machinery to runtime agent governance and, in doing so, identify a structural tension (§5.X) that the contraction framework itself makes visible: global exponential contraction and per-agent differential monitoring cannot both live on the same state variables.*

- [ ] Step 3: Replace the existing §2 body with these five paragraphs, preserving the `\section` and `\label` commands.

- [ ] Step 4: Compile check.

**Save:** file saved.
**Kenny checkpoint:** none (Kenny reviews as part of Task 20 full read-through).

---

## Task 8: α4a — Pause audit: sampling script

**Goal:** Write a Python script that pulls a reproducible random sample of 50 pause events from production with enough context for classification.

**Files:**
- Create: `papers/scripts/pause_audit_sampler.py`
- Create: `papers/data/pause_audit_50.csv`

- [ ] Step 1: Create `papers/scripts/` directory
  ```bash
  mkdir -p papers/scripts papers/data
  ```

- [ ] Step 2: Write `pause_audit_sampler.py`:
  ```python
  """Sample N pause events from production for manual classification.

  Usage: python3 pause_audit_sampler.py [--n 50] [--seed 42]
  Output: papers/data/pause_audit_50.csv
  """
  import argparse
  import csv
  import psycopg2
  from pathlib import Path

  DSN = "postgresql://postgres:postgres@localhost:5432/governance"
  OUTPUT = Path(__file__).parent.parent / "data" / "pause_audit_50.csv"

  QUERY = """
  SELECT
      event_id,
      agent_id,
      timestamp,
      verdict,
      risk_score,
      e_value, i_value, s_value, v_value,
      complexity,
      confidence,
      LEFT(COALESCE(response_text, ''), 500) AS response_excerpt,
      guidance
  FROM outcome_events
  WHERE decision = 'pause'
  ORDER BY random()
  LIMIT %s
  """

  def main():
      ap = argparse.ArgumentParser()
      ap.add_argument("--n", type=int, default=50)
      ap.add_argument("--seed", type=int, default=42)
      args = ap.parse_args()

      conn = psycopg2.connect(DSN)
      cur = conn.cursor()
      cur.execute(f"SELECT setseed({args.seed / 100.0});")
      cur.execute(QUERY, (args.n,))
      rows = cur.fetchall()
      colnames = [d[0] for d in cur.description]

      OUTPUT.parent.mkdir(parents=True, exist_ok=True)
      with OUTPUT.open("w", newline="") as f:
          w = csv.writer(f)
          w.writerow(colnames + ["classification", "classification_notes"])
          for r in rows:
              w.writerow(list(r) + ["", ""])

      print(f"Wrote {len(rows)} pause events to {OUTPUT}")

  if __name__ == "__main__":
      main()
  ```

- [ ] Step 3: Adjust the SQL column names if the actual `outcome_events` schema differs. Run a probe first:
  ```bash
  psql -h localhost -U postgres -d governance -c "\d outcome_events"
  ```
  And fix column references in the script accordingly before running.

- [ ] Step 4: Run the sampler
  ```bash
  cd /Users/cirwel/projects/governance-mcp-v1 && python3 papers/scripts/pause_audit_sampler.py --n 50
  ```
  Expected: "Wrote 50 pause events to …/pause_audit_50.csv"

- [ ] Step 5: Spot-check CSV
  ```bash
  head -3 papers/data/pause_audit_50.csv
  wc -l papers/data/pause_audit_50.csv
  ```
  Expected: 51 lines (header + 50 rows), readable schema.

**Save:** script and CSV saved.
**Kenny checkpoint:** none yet (Task 9 is the classification).

---

## Task 9: α4b — Pause audit: Kenny classifies 50 events

**Goal:** Kenny personally reviews each of the 50 sampled pause events and marks each as **justified / false-positive / ambiguous**, with a short note. This is the single most important human-in-the-loop step in the plan.

**Files:**
- Modify: `papers/data/pause_audit_50.csv` → copy to `papers/data/pause_audit_classifications.csv`

**Kenny instructions:**

- [ ] Step 1: Copy the sampled CSV to a working classification file
  ```bash
  cp papers/data/pause_audit_50.csv papers/data/pause_audit_classifications.csv
  ```

- [ ] Step 2: Open in your preferred editor or spreadsheet tool:
  ```bash
  open papers/data/pause_audit_classifications.csv
  ```

- [ ] Step 3: For each row, read the `response_excerpt`, `verdict`, and EISV values, then fill in:
  - `classification`: one of `justified` / `false_positive` / `ambiguous`
  - `classification_notes`: 1-sentence reason (e.g., "clear drift — confidence rising while complexity dropping", "healthy agent in transient spike", "insufficient context to judge")

- [ ] Step 4: Save the file. Target: all 50 rows classified.

- [ ] Step 5: Quick sanity check:
  ```bash
  awk -F, 'NR>1 {print $(NF-1)}' papers/data/pause_audit_classifications.csv | sort | uniq -c
  ```
  Expected: three categories shown with counts summing to 50.

**Kenny checkpoint:** this is the checkpoint. No Claude action between Step 5 and Task 10.
**Time budget:** ~2 hours of focused review (coffee + paper + the CSV).

---

## Task 10: α4c — Pause audit: analysis + §7.X writeup

**Goal:** Compute precision with Wilson confidence intervals, generate a LaTeX table fragment, and write the §7.X prose that interprets the audit results.

**Files:**
- Create: `papers/scripts/pause_audit_analyze.py`
- Create: `papers/data/pause_audit_results.tex`
- Modify: `papers/unitares-runtime-governance-v3.tex` (new §7.X subsection)

- [ ] Step 1: Write the analysis script
  ```python
  """Analyze classified pause events — precision + Wilson CI + LaTeX table.

  Usage: python3 pause_audit_analyze.py
  Output: papers/data/pause_audit_results.tex
  """
  import csv
  from pathlib import Path
  from scipy.stats import beta as beta_dist

  IN = Path(__file__).parent.parent / "data" / "pause_audit_classifications.csv"
  OUT = Path(__file__).parent.parent / "data" / "pause_audit_results.tex"

  def wilson_ci(successes, n, alpha=0.05):
      """Wilson score interval — standard for binomial proportions."""
      if n == 0:
          return (0.0, 0.0)
      from math import sqrt
      z = 1.959963984540054  # 95% two-sided
      p = successes / n
      denom = 1 + z*z/n
      center = (p + z*z/(2*n)) / denom
      margin = z * sqrt((p*(1-p) + z*z/(4*n))/n) / denom
      return (max(0, center - margin), min(1, center + margin))

  def main():
      counts = {"justified": 0, "false_positive": 0, "ambiguous": 0}
      examples = {"justified": [], "false_positive": [], "ambiguous": []}
      with IN.open() as f:
          reader = csv.DictReader(f)
          for row in reader:
              c = row["classification"].strip().lower()
              if c not in counts:
                  continue
              counts[c] += 1
              if len(examples[c]) < 2:
                  examples[c].append(row.get("classification_notes", ""))
      n = sum(counts.values())
      p_just = counts["justified"] / n if n else 0.0
      lo, hi = wilson_ci(counts["justified"], n)
      # If "ambiguous" should be half-counted (neutral), do that as a sensitivity:
      p_just_neutral = (counts["justified"] + 0.5 * counts["ambiguous"]) / n if n else 0.0

      lines = [
          "% Generated by pause_audit_analyze.py",
          "\\begin{table}[t]",
          "\\centering\\small",
          "\\caption{Pause-decision audit: classification of 50 randomly sampled pause events from production deployment. Precision reported as strict (justified / total) and ambiguous-neutral (justified + 0.5*ambiguous / total) with 95\\% Wilson confidence intervals.}",
          "\\label{tab:pause-audit}",
          "\\begin{tabular}{lrr}",
          "\\toprule",
          "Classification & Count & \\% of sample \\\\",
          "\\midrule",
          f"Justified       & {counts['justified']:>3} & {100*counts['justified']/n:.1f} \\\\",
          f"False positive  & {counts['false_positive']:>3} & {100*counts['false_positive']/n:.1f} \\\\",
          f"Ambiguous       & {counts['ambiguous']:>3} & {100*counts['ambiguous']/n:.1f} \\\\",
          "\\bottomrule",
          "\\end{tabular}",
          "\\end{table}",
          "",
          f"% Strict precision: {p_just:.3f} (95\\% Wilson CI: [{lo:.3f}, {hi:.3f}])",
          f"% Ambiguous-neutral precision: {p_just_neutral:.3f}",
      ]
      OUT.write_text("\n".join(lines))
      print(f"Wrote {OUT}")
      print(f"Strict precision: {p_just:.3f} (95% CI [{lo:.3f}, {hi:.3f}])")

  if __name__ == "__main__":
      main()
  ```

- [ ] Step 2: Run the analysis
  ```bash
  python3 papers/scripts/pause_audit_analyze.py
  ```
  Expected: `Strict precision: X.XXX (95% CI [lo, hi])` printed.

- [ ] Step 3: Add a new subsection `\subsection{Pause decision audit}\label{sec:pause-audit}` to §7 (Deployment evidence) of the manuscript. Place it after the verdict-distribution subsection, before the calibration-and-outcomes subsection.

- [ ] Step 4: Draft the subsection prose (insert into LaTeX):
  ```latex
  \subsection{Pause decision audit}
  \label{sec:pause-audit}
  A raw pause rate alone does not tell us whether governance authority is well
  calibrated: pausing 7.7\% of check-ins could reflect accurate intervention or
  excessive caution. To bound this, we manually audited a random sample of 50
  pause events drawn from the 1{,}414 production pauses across the deployment
  window. For each event we inspected the agent's response, the EISV state at
  the time of pause, and the governance guidance issued, classifying the pause
  as \emph{justified} (intervention appears appropriate given the observed
  state), \emph{false positive} (agent was healthy and the pause was not
  warranted), or \emph{ambiguous} (insufficient context to decide, or
  reasonable minds could differ).

  \input{data/pause_audit_results.tex}

  We report precision under two conventions: a strict reading that counts only
  justified pauses as correct, and an ambiguous-neutral reading that treats
  ambiguous cases as half-weighted. Wilson score confidence intervals are
  reported because normal-approximation intervals are unreliable at this sample
  size. This audit is limited: 50 is a small sample, and the classification was
  performed by the primary author rather than an independent rater. We report
  it not as a definitive precision estimate but as a useful bound on the claim
  that the 7.7\% pause rate represents substantively useful intervention rather
  than alert-fatigue-inducing noise.
  ```

- [ ] Step 5: Compile check. The `\input{data/pause_audit_results.tex}` path should resolve (relative to the .tex file's directory, which is `papers/`, so the path should be `data/pause_audit_results.tex`).

**Save:** script, generated .tex, and manuscript saved.
**Kenny checkpoint:** none (Kenny reviews as part of Task 20 full read-through).

---

## Task 11: α6a — Regenerate existing 3 figures

**Goal:** Re-run `make_figures.py` to regenerate `eisv-trajectory.pdf`, `verdict-dist.pdf`, `eisv-scatter.pdf` with current data and clean styling.

**Files:**
- Modify: `papers/make_figures.py` (minor styling tweaks only if needed)

- [ ] Step 1: Run existing figure generator
  ```bash
  cd papers && python3 make_figures.py 2>&1 | tail -20
  ```
  Expected: 3 PDFs regenerated in `figures/`.

- [ ] Step 2: Visual inspection — open each PDF
  ```bash
  open figures/eisv-trajectory.pdf figures/verdict-dist.pdf figures/eisv-scatter.pdf
  ```
  Check: legible axis labels, consistent fonts, no cut-off legend, correct data.

- [ ] Step 3: If any figure has cosmetic issues, apply a styling patch to `make_figures.py`:
  - Set `plt.rcParams['font.family'] = 'serif'`
  - Set `plt.rcParams['font.size'] = 10`
  - Ensure `bbox_inches='tight'` on `savefig`
  - Use consistent color palette across all three

- [ ] Step 4: Re-run and re-inspect after any patch.

- [ ] Step 5: Compile the paper to verify figure inclusion
  ```bash
  cd papers && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex > /dev/null && open unitares-runtime-governance-v3.pdf
  ```

**Save:** figures regenerated.
**Kenny checkpoint:** none (figures get a second look in Task 20).

---

## Task 12: α6b — New Lumen sensor-vs-ODE figure

**Goal:** Create the centerpiece figure of the new thesis: side-by-side time series showing Lumen's sensor-derived EISV vs. ODE-evolved EISV, with the divergence visible.

**Files:**
- Create: `papers/scripts/lumen_sensor_vs_ode_figure.py`
- Create: `papers/figures/lumen_sensor_vs_ode.pdf`
- Modify: `papers/unitares-runtime-governance-v3.tex` (reference new figure in §1 teaser and §7 case study)

- [ ] Step 1: Probe what Lumen data is available. Likely sources:
  - Anima MCP on the Pi has sensor-derived EISV logs
  - Governance DB has ODE-evolved EISV for Lumen (`agent_id = 'lumen'`)
  - Pi's SQLite backups at `~/backups/lumen/` per CLAUDE.md

  Run:
  ```bash
  psql -h localhost -U postgres -d governance -c "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM state_records WHERE agent_id LIKE '%lumen%';"
  ls ~/backups/lumen/ 2>/dev/null | head
  ```

- [ ] Step 2: Decide data window. Target: a representative 7-14 day window where both sensor and ODE streams are populated. Prefer recent (so it's relevant to the 108-day deployment claim).

- [ ] Step 3: Write the figure script:
  ```python
  """Generate lumen_sensor_vs_ode.pdf — the paper's centerpiece figure."""
  import matplotlib.pyplot as plt
  import pandas as pd
  import psycopg2
  from pathlib import Path

  OUT = Path(__file__).parent.parent / "figures" / "lumen_sensor_vs_ode.pdf"

  # Pull ODE-evolved EISV from governance DB
  conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/governance")
  ode_df = pd.read_sql("""
      SELECT timestamp, e_value AS E, i_value AS I, s_value AS S, v_value AS V
      FROM state_records
      WHERE agent_id LIKE '%lumen%'
      ORDER BY timestamp
  """, conn)

  # Pull sensor-derived EISV — path/source depends on probe in Step 1
  # Expected schema: (timestamp, E, I, S, V)
  sensor_df = pd.read_csv("/Users/cirwel/backups/lumen/latest_eisv.csv")  # adjust path

  fig, axes = plt.subplots(2, 2, figsize=(10, 6), sharex=True)
  dims = [('E', 'Energy'), ('I', 'Integrity'), ('S', 'Entropy'), ('V', 'Void')]
  for ax, (col, label) in zip(axes.flat, dims):
      ax.plot(sensor_df['timestamp'], sensor_df[col], label='Sensor-derived', lw=1.5)
      ax.plot(ode_df['timestamp'], ode_df[col], label='ODE-evolved', lw=1.5, linestyle='--')
      ax.set_title(label)
      ax.set_ylabel(col)
      if col == 'V':
          ax.axhline(0, color='k', lw=0.5, alpha=0.5)
  axes[0,0].legend(loc='best', fontsize=8)
  axes[1,0].set_xlabel('Time')
  axes[1,1].set_xlabel('Time')
  fig.suptitle('Lumen: Sensor-derived vs. ODE-evolved EISV', fontsize=11)
  fig.tight_layout()
  fig.savefig(OUT, bbox_inches='tight', dpi=150)
  print(f"Wrote {OUT}")
  ```

- [ ] Step 4: Adjust data source paths based on Step 1 probe results.

- [ ] Step 5: Run the script
  ```bash
  python3 papers/scripts/lumen_sensor_vs_ode_figure.py
  ```
  Expected: `lumen_sensor_vs_ode.pdf` created.

- [ ] Step 6: Visual inspection
  ```bash
  open papers/figures/lumen_sensor_vs_ode.pdf
  ```
  Check: the two curves should visibly diverge. The V panel should show a sign flip. The E panel should show the sensor curve lower than the ODE curve. If divergence is not visible, double-check data sources — the point of this figure is the divergence, and if it's invisible the underlying claim is shaky.

- [ ] Step 7: Reference the figure in LaTeX. In §7 case study (the `sec:case-study` section), replace the existing `\begin{figure}` block (if any) or add one:
  ```latex
  \begin{figure}[t]
  \centering
  \includegraphics[width=0.95\linewidth]{figures/lumen_sensor_vs_ode.pdf}
  \caption{Lumen: sensor-derived vs. ODE-evolved EISV over a representative window. The ODE trajectory converges toward the theoretical equilibrium predicted by the contraction analysis (\cref{sec:eisv}); the sensor-derived trajectory tracks the physical state of the embodied agent. The divergence on the magnitude of $E$ and the sign of $V$ is the observational trace of the governance--stability tension.}
  \label{fig:lumen-divergence}
  \end{figure}
  ```

- [ ] Step 8: Compile and verify figure appears.

**Save:** script, figure, manuscript saved.
**Kenny checkpoint:** none explicitly, but if the divergence is not visible in Step 6, STOP and surface to Kenny before proceeding.

---

## Task 13: α1a — §1 Introduction rewrite

**Goal:** Rewrite §1 around the new thesis. New first paragraph states the governance–stability tension explicitly. New last paragraph teases the Lumen divergence figure.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: Read the current §1 in full. Identify the current opening paragraph and closing paragraph.

- [ ] Step 2: Replace the current opening paragraph of §1 with this draft:
  ```latex
  In this paper we report a structural tension we identified while operating
  runtime governance at scale: a dynamical system designed for formal stability
  guarantees---specifically, one that provably contracts toward a unique
  equilibrium---is by construction unable to serve as a differential per-agent
  monitor, because contraction asymptotically erases the very heterogeneity
  that differential monitoring needs to preserve. We call this the
  \emph{governance--stability tension}, describe the deployment observations
  that exposed it (most legibly through an embodied agent whose physical
  sensors provided independent ground truth), and propose a dual-track
  architecture that separates the stability-guaranteed ODE channel from a
  per-agent behavioral channel as a principled resolution. The paper's
  contribution is not that dynamical-systems monitoring ``beats'' statistical
  monitoring. It is the identification and naming of a foundational
  mathematical constraint that any runtime governance approach built on
  contracting dynamics must navigate, together with observational evidence
  from a live deployment and an honest accounting of how we came to find it.
  ```

- [ ] Step 3: Keep the existing mid-section paragraphs (the prior-art overview and the paper-roadmap paragraph) with only surgical edits if they contradict the new opening.

- [ ] Step 4: Add a new final paragraph of §1 (before §2 begins) as the Lumen teaser:
  ```latex
  \Cref{fig:lumen-divergence} previews the central empirical finding. The
  embodied agent Lumen runs on a Raspberry Pi with physical sensors---a
  neural EEG band, ambient temperature and light, microphone---whose readings
  are mapped to an EISV vector through an observation function. Crucially,
  this gives us something no other agent in the deployment has: an
  \emph{independent} ground truth for the four EISV dimensions, computed
  without reference to the governance ODE. When we compared Lumen's
  sensor-derived EISV against the ODE-evolved EISV over the same time window,
  we found a persistent and systematic divergence: the ODE-evolved values
  converged toward the theoretical equilibrium predicted by the contraction
  proof, while the sensor-derived values tracked the physical state of the
  embodied agent. The two disagreed on the magnitude of $E$ and on the
  \emph{sign} of $V$. Contraction was doing exactly what its proof said it
  would do---and, we came to understand, exactly what a single-signal
  governance stack could not afford.
  ```

- [ ] Step 5: Compile check.

**Save:** file saved.
**Kenny checkpoint:** yes — Kenny reads the new §1 (~5 minutes) and either approves or sends back for adjustment before Task 14 proceeds. Do not proceed without explicit approval of the new §1.

---

## Task 14: §5 reorder + new §5.X governance–stability tension subsection

**Goal:** Reorder §5 so the contraction result (inherited from v5) comes first as foundation, then the new `§5.X Governance–stability tension` subsection, then the saturation analysis as a supporting detail.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: Locate §5 and its subsections
  ```bash
  grep -n "section{.*nalysis\\|subsection" papers/unitares-runtime-governance-v3.tex | head -30
  ```

- [ ] Step 2: Identify existing subsections. Typical v3 structure:
  - §5.1 Stability-oriented reasoning
  - §5.2 Information-channel saturation
  - (possibly others)

- [ ] Step 3: Reorder so the contraction-theoretic stability content comes first. Add one-sentence pointer to the v5 theory paper at the top of §5:
  ```latex
  The formal contraction-theoretic stability analysis on which this section
  builds---global exponential convergence of the EISV dynamics to a unique
  equilibrium under a Riemannian metric $M \succ 0$, with contraction rate
  $\alpha > 0$ derived from the coupling parameters---is established in our
  companion theory paper~\cite{wang2026unitares-v5}. We summarize the relevant
  result here and then identify a previously unstated operational consequence
  that motivated the dual-track architecture of \cref{sec:architecture}.
  ```
  (Add `wang2026unitares-v5` to references.bib as a cite to the v5 paper.)

- [ ] Step 4: Insert new `\subsection{The governance--stability tension}\label{sec:tension}` between the contraction-summary subsection and the saturation-analysis subsection. Draft content:
  ```latex
  \subsection{The governance--stability tension}
  \label{sec:tension}

  The contraction result of the preceding subsection guarantees that, for any
  two initial conditions $\eisv_0, \eisv_0' \in M$ representing distinct
  agents, the distance $d_g(\Phi_t(\eisv_0), \Phi_t(\eisv_0'))$ in the
  contracting metric decays as $O(e^{-\alpha t})$, so
  \[
      \lim_{t \to \infty} d_g\!\left(\Phi_t(\eisv_0),\, \Phi_t(\eisv_0')\right) \;=\; 0.
  \]
  This is a desirable property for formal stability analysis: trajectories
  are Lyapunov-stable, perturbations are bounded, and the long-run behavior
  of the system is predictable in a strong mathematical sense.

  \paragraph{Tension.}
  It is \emph{also} the property that makes the contracting ODE unable, by
  construction, to serve as a differential per-agent monitor. Differential
  monitoring requires a distinguishing function $\delta: M \to \mathbb{R}^k$
  such that $\delta(\eisv_0) \neq \delta(\eisv_0')$ whenever agents with
  initial states $\eisv_0$ and $\eisv_0'$ exhibit materially different
  behavior. Along any contracting flow, any such $\delta$ composed with
  $\Phi_t$ satisfies
  \[
      \|\delta(\Phi_t(\eisv_0)) - \delta(\Phi_t(\eisv_0'))\| \;\longrightarrow\; 0
      \quad \text{as } t \to \infty,
  \]
  i.e., the distinguishing signal is asymptotically erased. A state variable
  that participates in the contraction cannot, at long horizons, preserve the
  inter-agent differences that a differential monitor needs.

  \paragraph{Operational consequence.}
  This is not a pathology in the contraction result. It is what global
  contraction \emph{means}. The practical implication is that any runtime
  governance system built on contracting dynamics must either (i)~abandon
  contraction in favor of a non-contracting model that preserves per-agent
  heterogeneity (at the cost of the stability proof), or (ii)~retain
  contraction as a diagnostic channel and compose it with a second signal
  that explicitly preserves heterogeneity. UNITARES chooses~(ii): the ODE
  track retains the contraction-theoretic stability guarantees for its
  diagnostic role (basin membership, regime detection, alert generation),
  while a behavioral track---EMA-smoothed observations against per-agent
  Welford baselines---supplies the differential verdict signal that
  contraction precludes. The observational trace of this tension in our
  deployment is the Lumen sensor--ODE divergence of
  \cref{fig:lumen-divergence}, to which we return in \cref{sec:deployment}.
  ```

- [ ] Step 5: Demote any existing "saturation analysis" subsection to come after §5.X (as a supporting detail, not a headline result). Minimal edits to that subsection — it can stay mostly as-is, just repositioned.

- [ ] Step 6: Compile check, two passes.

**Save:** file saved.
**Kenny checkpoint:** none explicitly, but if the proof sketch reads wrong to Kenny during Task 20, he flags it.

---

## Task 15: α1b — §9 Conclusion rewrite

**Goal:** Rewrite the conclusion to land on the governance–stability tension as the paper's broader contribution.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: Locate §9 Conclusion
  ```bash
  grep -n "section{Conclusion" papers/unitares-runtime-governance-v3.tex
  ```

- [ ] Step 2: Replace the entire Conclusion body with this draft:
  ```latex
  This paper has reported a structural tension in runtime agent governance
  that we believe generalizes well beyond our specific implementation: a
  dynamical system cannot simultaneously provide global contraction
  guarantees and differential per-agent monitoring using the same state
  variables. The two requirements are mathematically incompatible. Where
  they appear compatible in existing governance systems, it is typically
  because one requirement is not being taken seriously at scale---either the
  stability analysis is informal, or the monitoring is coarse enough that
  contraction has not yet erased the signal of interest.

  We offered one principled resolution, motivated by a specific and
  fortunate circumstance: an embodied agent in our deployment whose
  physical sensors provided independent ground truth for the EISV state
  variables. Without that ground truth, the tension would have been harder
  to disambiguate from a cold-start artifact or from a sparse-data regime
  in which all agents happen to sit near their initialization defaults.
  We suspect a number of governance projects are currently sitting on
  undiagnosed versions of this same tension because they lack the kind of
  independent verification that Lumen provided.

  The broader implication for runtime agent safety is that practitioners
  should not expect a single-signal governance architecture to satisfy both
  formal stability analysis and differential per-agent monitoring. The
  architecture that emerges from taking both seriously is dual-track by
  necessity: contracting dynamics for what they are good at (stability,
  regime structure, guarantees that survive Jacobian analysis), and
  per-agent behavioral signals for what contraction explicitly erases
  (heterogeneity, differential drift, individual baselines). The dual-track
  composition we describe here is one instance of this pattern; we expect
  other instances to emerge in related settings, and we hope the framing
  is useful beyond UNITARES itself.
  ```

- [ ] Step 3: Compile check.

**Save:** file saved.
**Kenny checkpoint:** yes — Kenny reads the new conclusion (~5 minutes). Adjust or approve before proceeding.

---

## Task 16: α1c — Abstract rewrite

**Goal:** Rewrite the abstract to reflect the new thesis. This is a consequence edit — it just restates whatever the body now says.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex`

- [ ] Step 1: Locate `\begin{abstract}`.

- [ ] Step 2: Replace the abstract body with:
  ```latex
  \begin{abstract}
  We identify and name a structural tension in runtime agent governance: a
  dynamical-system state estimator with global contraction guarantees cannot
  simultaneously serve as a differential per-agent monitor, because
  contraction asymptotically erases the very heterogeneity that differential
  monitoring requires. We observed this tension in the live deployment of
  the UNITARES runtime governance framework, where an ODE-driven EISV state
  vector---designed with provable contraction properties via contraction
  theory on a Riemannian manifold---converged all observed agents to the
  same equilibrium region regardless of their actual behavior. An embodied
  agent in our deployment, whose physical sensors provided an independent
  ground truth for the EISV dimensions, allowed us to disambiguate this
  phenomenon from a cold-start or sparse-data artifact: the sensor-derived
  and ODE-derived state vectors diverged in both magnitude and sign,
  confirming that global contraction was doing exactly what its proof said
  it would. We present the governance--stability tension as a general
  structural result, report a dual-track architecture (contracting ODE as
  diagnostic channel, per-agent behavioral signals with Welford baselines
  as verdict channel) as one principled resolution, and validate the
  framework through observational deployment evidence from 108~days of
  continuous operation governing 895~agents (over 18{,}000 check-ins). We
  explicitly bound our empirical claims as observational rather than
  comparative.
  \end{abstract}
  ```

- [ ] Step 3: Compile check.

**Save:** file saved.
**Kenny checkpoint:** none (Kenny reads at Task 20).

---

## Task 17: Prose sweep — kill "100% detection" residue + typography

**Goal:** Scan the manuscript for any remaining residue of the old overclaims and for typography issues.

**Files:**
- Modify: `papers/unitares-runtime-governance-v3.tex` (if any hits)

- [ ] Step 1: Search for overclaim residue
  ```bash
  grep -n "100\\\\?%\\|0\\\\?% false\\|straw man\\|detected all\\|perfect detection" papers/unitares-runtime-governance-v3.tex
  ```
  Expected: no hits. If hits: inspect each and either remove or rewrite honestly.

- [ ] Step 2: Search for thermostat-as-pathology language that contradicts the new framing
  ```bash
  grep -n "thermostat pathology\\|pathology" papers/unitares-runtime-governance-v3.tex
  ```
  Expected: the word "pathology" should now be absent or rare. If it appears, rewrite as "tension" or "trade-off" where it refers to the EISV attractor.

- [ ] Step 3: Search for any `TODO`, `XXX`, or placeholder markers
  ```bash
  grep -n "TODO\\|XXX\\|TBD\\|FIXME\\|\\[placeholder\\]" papers/unitares-runtime-governance-v3.tex
  ```
  Expected: none.

- [ ] Step 4: Verify the Limitations section (§8) acknowledges the out-of-scope items per spec §5.3
  ```bash
  grep -n "section{Limitations" papers/unitares-runtime-governance-v3.tex
  ```
  Read that section and ensure it mentions: (a) no head-to-head comparison with JSD/CUSUM at scale, (b) pause-audit sample size is small and rater is not independent, (c) ablation is re-analysis of archival data, not new experiments, (d) ground-truth validation is limited to Lumen, (e) calibration analysis is single-bin. Add honest one-sentence acknowledgments for any missing.

- [ ] Step 5: Compile check. Look at warnings about overfull boxes; fix any egregious ones with `\sloppy` or paragraph-level tweaks.

- [ ] Step 6: Check that figure/table numbers are contiguous and that all `\cref` references resolve
  ```bash
  cd papers && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex 2>&1 | grep -E "undefined\\|multiply defined" 
  ```
  Expected: no hits.

**Save:** any inline fixes saved.
**Kenny checkpoint:** none.

---

## Task 18: Full read-through pass 1 (Claude)

**Goal:** Claude reads the paper end-to-end with fresh eyes, fixes-on-read.

- [ ] Step 1: Produce the compiled PDF
  ```bash
  cd papers && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex
  ```

- [ ] Step 2: Read the full `.tex` source using Read tool, end to end. Note any issues:
  - Sentences that read awkwardly
  - Claims that contradict other claims
  - Formal statements whose notation drifts between sections
  - Citations that are in the bibliography but not actually cited (bibtex warning)
  - Figures or tables referenced in text but not present, or vice versa
  - Section numbering that skipped or repeated

- [ ] Step 3: Fix each issue inline with the Edit tool.

- [ ] Step 4: Final compile and verify output PDF
  ```bash
  cd papers && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex > /dev/null && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex 2>&1 | grep -E "Warning|Error"
  ```

**Save:** file saved.
**Kenny checkpoint:** none yet — Kenny does the full read in Task 20.

---

## Task 19: Prepare Kenny read-through packet

**Goal:** Give Kenny a single-file read experience so the full-review checkpoint is bounded and easy.

- [ ] Step 1: Produce a clean compiled PDF (final pdflatex pass, no warnings).

- [ ] Step 2: Open the PDF on Kenny's machine
  ```bash
  open papers/unitares-runtime-governance-v3.pdf
  ```

- [ ] Step 3: Send Kenny a prompt summary of what changed (short message, not a document):
  > *"Paper draft ready for your full read. Changes since v3: new thesis (governance–stability tension) in §1, §5.X, §9, abstract. New Lumen sensor-vs-ODE figure in §1 teaser and §7 case study. Pause-decision audit section in §7. Thermodynamic transparency paragraph in §4. Related work rewritten in §2. Versioning/Terminology notes cut; §6 merged into §3. Target: 90 minutes of reading. Please flag anything that sounds wrong, overclaimed, or inconsistent with your understanding of the system. Specific things to verify: (1) the proof sketch in §5.X; (2) the contraction result citation to v5; (3) the Lumen figure interpretation; (4) the author block / affiliation; (5) anything in the new abstract that feels off."*

**Kenny checkpoint:** Task 20 is the read.

---

## Task 20: Kenny full read-through

**Goal:** Kenny personally reads the full paper and surfaces any issues.

**Kenny instructions:**

- [ ] Step 1: Open the PDF (Task 19 Step 2 already did this).

- [ ] Step 2: Read linearly, paying special attention to:
  - Abstract — does this describe the paper you want to publish?
  - §1 Introduction — is the thesis landing correctly?
  - §5.X proof sketch — is the math correct and consistent with v5?
  - §7 Lumen case study — is the finding described honestly?
  - §9 Conclusion — does the broader framing hold up?
  - Author block, affiliation, acknowledgments stub

- [ ] Step 3: Mark issues with comments or a separate punch list.

- [ ] Step 4: Send punch list to Claude for fixes.

**Time budget:** ~90 minutes.
**Kenny checkpoint:** yes, this IS the checkpoint.

---

## Task 21: Apply Kenny's punch list

**Goal:** Claude addresses every item from Kenny's Task 20 review.

- [ ] Step 1: For each punch-list item, propose the specific fix (diff or new prose).

- [ ] Step 2: Kenny approves each proposed fix (short turnaround, can be asynchronous).

- [ ] Step 3: Apply approved fixes with Edit tool.

- [ ] Step 4: Compile check after each non-trivial fix.

- [ ] Step 5: Final compile and spot-check PDF.

**Save:** file saved.
**Kenny checkpoint:** inline approval per item.

---

## Task 22: β1 — Coupling-term ablation (script + writeup)

**Goal:** (β, include if time permits) Replay 30 days of archival Lumen + top Claude Code trajectories through the ODE with coupling terms individually zeroed.

**Files:**
- Create: `papers/scripts/coupling_ablation.py`
- Create: `papers/figures/coupling_ablation.pdf`
- Modify: `papers/unitares-runtime-governance-v3.tex` (new §7.Y subsection)

- [ ] Step 1: Read `governance_core` source via the symlink (Task 0 Step 5) to identify the coupling constants by their code names. Likely candidates: `alpha_EI` (E–I coupling), `beta_E` or `k_ES` (entropy→energy), `k` (entropy→integrity), `kappa` (void accumulation), `beta_I` (integrity self-regulation).

- [ ] Step 2: Write `coupling_ablation.py` that:
  - Loads the last 30 days of trajectory data for Lumen + top 5 Claude Code agents by check-in count
  - Replays each trajectory through the ODE integrator with each coupling constant in turn set to 0 (full baseline + 4 ablations = 5 runs)
  - Records the verdict produced at each step
  - Computes: per-ablation verdict-divergence rate (fraction of steps where verdict differs from baseline), verdict-class confusion matrix
  - Generates a figure with one panel per ablation showing the verdict timeline overlay (baseline vs. ablated)

- [ ] Step 3: Run the script, verify output CSV + figure.

- [ ] Step 4: Draft the §7.Y subsection prose:
  ```latex
  \subsection{Coupling-term ablation on archival trajectories}
  \label{sec:ablation}
  To probe how much of the ODE track's behavior depends on its cross-dimensional
  coupling terms, we replayed the last 30~days of trajectory data from the
  richest agents (Lumen plus the top five Claude Code development agents by
  check-in count) through the ODE integrator with individual coupling constants
  set to zero. [Insert concrete findings: e.g., "Zeroing $\alpha$ (the E--I
  coupling) changed verdicts on X\% of steps; zeroing $k$ (entropy--integrity
  coupling) changed verdicts on Y\%; ..."]. \cref{fig:ablation} shows the
  verdict timelines for each ablation overlaid on the full-coupling baseline.
  [Interpretive sentence: either "The cross-coupling terms make a measurable
  difference to verdict generation in Z\% of situations" or "Verdict generation
  is largely driven by the single-dimension terms, with coupling contributing
  only at the margins." Write whichever is true.]
  This is a re-analysis of existing data, not a new experiment, and the sample
  of agents is small; we report it as a bounded signal about the ODE's
  internal structure rather than as a benchmark result.
  ```

- [ ] Step 5: Compile check.

**Save:** script, figure, manuscript saved.
**Kenny checkpoint:** none (reviewed during buffer day read-through if time).
**Drop rule:** if any step blocks or runs over 1 day, defer to post-ship v3.1 revision and mark this task as deferred.

---

## Task 23: β2 — JSD drift detection baseline

**Goal:** (β, include if time permits) Implement Jensen-Shannon divergence drift detection on the same archival trajectories; compare firing times with EISV verdicts.

**Files:**
- Create: `papers/scripts/jsd_baseline.py`
- Create: `papers/figures/jsd_comparison.pdf`
- Modify: `papers/unitares-runtime-governance-v3.tex` (new §7.Z subsection)

- [ ] Step 1: Implement JSD drift detection:
  - For each agent trajectory, slide a window of 20 steps across the 30-day data
  - Compute JSD between the first half and second half of each window for each EISV dimension
  - Fire an alarm when aggregate JSD exceeds a threshold (threshold tuned on held-out healthy-agent data for ~5% FPR)

- [ ] Step 2: Compare against EISV verdicts on the same trajectories. Produce metrics:
  - Overlap: fraction of EISV pause events also flagged by JSD
  - Disagreement: events flagged by only one
  - Lead-lag: median step difference when both fire on the same trajectory

- [ ] Step 3: Generate figure: per-agent timeline showing EISV verdict markers and JSD alarm markers on shared time axis.

- [ ] Step 4: Draft §7.Z subsection prose — honest report of overlap and disagreement, NOT a claim that one approach beats the other:
  ```latex
  \subsection{Comparison with Jensen--Shannon divergence drift detection}
  \label{sec:jsd-comparison}
  As a targeted point of comparison against a representative statistical drift
  detection approach, we implemented Jensen--Shannon divergence drift detection
  (following the MI9 formulation~\cite{ma2024mi9}) on the same archival
  trajectories used in \cref{sec:ablation}. We do not claim UNITARES detects
  anomalies that JSD misses, nor vice versa. The honest finding is that
  [X]\% of pause events were flagged by both systems, [Y]\% by EISV only,
  and [Z]\% by JSD only; when both fired, EISV preceded JSD by a median of
  [N] steps. This modest head-to-head provides context for the claim that
  a state-based approach is \emph{complementary} to a distributional-drift
  approach rather than a replacement for it.
  ```
  Fill in the bracketed values from the actual run.

- [ ] Step 5: Compile check.

**Save:** script, figure, manuscript saved.
**Kenny checkpoint:** none.
**Drop rule:** as Task 22.

---

## Task 24: Final compile + PDF integrity check

**Goal:** Produce the final PDF that will be uploaded to Zenodo.

- [ ] Step 1: Clean build
  ```bash
  cd papers && rm -f unitares-runtime-governance-v3.{aux,bbl,blg,log,out,toc} && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex > /dev/null && bibtex unitares-runtime-governance-v3 > /dev/null && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex > /dev/null && pdflatex -interaction=nonstopmode unitares-runtime-governance-v3.tex 2>&1 | tail -5
  ```
  Expected: "Output written on unitares-runtime-governance-v3.pdf" with no undefined references.

- [ ] Step 2: Check PDF size and page count
  ```bash
  ls -la papers/unitares-runtime-governance-v3.pdf
  pdfinfo papers/unitares-runtime-governance-v3.pdf 2>/dev/null || echo "pdfinfo unavailable"
  ```

- [ ] Step 3: Open the PDF and spot-check:
  - Title and author block render correctly
  - Abstract reads as intended
  - All figures appear at reasonable positions
  - Bibliography is complete and alphabetical
  - No `??` for undefined references

- [ ] Step 4: Verify no residual markup bugs
  ```bash
  grep -c "\\\\cite{}\\|\\\\ref{}\\|\\\\label{}" papers/unitares-runtime-governance-v3.tex
  ```
  Expected: 0.

**Save:** final PDF in `papers/unitares-runtime-governance-v3.pdf`.
**Kenny checkpoint:** none (Task 25 is the upload decision).

---

## Task 25: Zenodo upload

**Goal:** Create the Zenodo deposition, attach files, get DOI.

**Prerequisites:** Kenny has an ORCID (Task 5 Step 1) and a Zenodo account.

- [ ] Step 1: **Kenny action** — create Zenodo account at [zenodo.org](https://zenodo.org) if not already done (sign in with ORCID).

- [ ] Step 2: **Kenny action** — click "New upload." Upload files:
  - `papers/unitares-runtime-governance-v3.pdf`
  - `papers/unitares-runtime-governance-v3.tex`
  - `papers/references.bib`
  - `papers/make_figures.py`
  - `papers/scripts/*.py`
  - `papers/figures/*.pdf`

- [ ] Step 3: Fill Zenodo metadata:
  - **Upload type:** Publication → Preprint
  - **Title:** `The Governance–Stability Tension: Why Contracting Dynamics Cannot Be Differential Monitors, and How to Compose Both`
  - **Authors:** Kenny Wang (ORCID), Independent Researcher
  - **Description:** Paste the abstract
  - **Keywords:** runtime governance; dynamical systems monitoring; contraction theory; AI safety; multi-agent systems; state estimation; EISV
  - **License:** CC BY 4.0
  - **Related identifiers:** link to `github.com/cirwel/governance-mcp-v1`
  - **Funding / community:** none

- [ ] Step 4: Save as draft, preview the metadata, then **Publish**.
  (Publishing is irreversible — Zenodo does not allow deleting published records, only creating new versions.)

- [ ] Step 5: Record the DOI. Paste it into:
  - `papers/unitares-runtime-governance-v3.tex` (Code & Data Availability section, replacing `[PASTE AFTER UPLOAD]`)
  - Any landing page drafts
  - Kenny's personal records

- [ ] Step 6: Re-compile the paper with the DOI in place. Upload the updated PDF as a "new version" on the same Zenodo record (Zenodo supports versioning).

**Save:** DOI recorded.
**Kenny checkpoint:** Step 2–4 — Kenny operates Zenodo; Claude can assist with drafting metadata and Description text.

---

## Task 26: GitHub release + cirwelsystems.com landing

**Goal:** Mirror the Zenodo artifact on GitHub Releases and publish a simple landing page.

- [ ] Step 1: Tag a release on `governance-mcp-v1`
  ```bash
  cd /Users/cirwel/projects/governance-mcp-v1
  git tag -a v3.0-paper -m "v3 paper revision — Zenodo deposition [DOI]"
  git push origin v3.0-paper
  ```
  (Kenny decides if the push happens now or whether to stage it.)

- [ ] Step 2: Create a GitHub Release from the tag with:
  - Title: `Paper v3.0 — Zenodo DOI [paste]`
  - Description: paste abstract + Zenodo link
  - Attach `unitares-runtime-governance-v3.pdf`

- [ ] Step 3: Draft a simple landing page for cirwelsystems.com
  - Path: `/paper` or `/research/unitares-v3` (Kenny decides)
  - Content: title, author block, abstract, links to [PDF], [Zenodo], [GitHub], [governance-mcp-v1 repo]
  - Style: match existing cirwelsystems.com voice

- [ ] Step 4: Deploy landing page. Mechanism depends on how cirwelsystems.com is hosted (see `cirwel-site.md` memory if available).

**Save:** landing page live.
**Kenny checkpoint:** sign off on push to origin and on the landing-page deployment.

---

## §R — Post-ship reference outreach (separate workstream; not part of 17-day sprint)

After the paper is live on Zenodo:

1. **Identify 5–10 candidate references.** Think broadly: past employers, bootcamp / course teachers, open-source collaborators, anyone who has engaged substantively with UNITARES or CIRWEL work online, dialectic discussion partners.

2. **Email template for "please read my paper" (pre-reference ask):**
   > Hi [name],
   >
   > I just posted a paper on Zenodo that I've been working on solo for the past few months — it's a runtime governance framework for AI agents, and the main technical finding is a structural tension between formal contraction guarantees and differential per-agent monitoring in dynamical-system-based governance. You can read it here: [DOI link]. Repo is at [GitHub link].
   >
   > I'd really value your read, especially [specific thing about this person's expertise]. Happy to jump on a 15-minute call to walk you through the dual-track architecture if it's easier than reading cold.
   >
   > If it feels useful and you end up being positive about the work, I may come back to ask if you'd be willing to serve as a reference on a future fellowship application. No pressure at all — wanted to give you the paper first without any ask attached.
   >
   > Thanks,
   > Kenny

3. **Email template for actual reference ask (after they've read it):**
   > Hi [name],
   >
   > Thanks so much for reading the paper [and for the feedback you sent on X, if applicable]. I'm applying to the Anthropic Fellows program's [cohort] cohort and need to list three references. Would you be willing to serve as one?
   >
   > What they'll ask: how you know me, how long we've worked together or interacted, and specifics about my technical ability. The expected email response time is one week, and they may contact you without notifying me first.
   >
   > If yes, I'll put your name on the form and send you a short primer with what I'm applying for and a few specifics I think are useful for you to have on hand.
   >
   > No hard feelings if you'd rather pass. Thanks either way.
   >
   > Kenny

4. **After three commitments:** prepare a one-page reference primer with Kenny's summary of the paper, the role being applied for, and 3–5 talking points each reference can draw on.

5. **Target cohort:** first rolling cohort after July 2026 with a submission window that allows ~2 weeks of reference-priming runway.

---

## Self-review

**Spec coverage check (fresh eyes):**

- ✅ Spec §1 context/goal → covered by plan goal statement
- ✅ Spec §2 thesis → implemented in Tasks 13, 14, 15, 16 (intro, §5.X, conclusion, abstract)
- ✅ Spec §3 contributions → implicit in the thesis-driven rewrites of Tasks 13–16
- ✅ Spec §4.1 cuts → Tasks 1, 2, 3 (Versioning, Terminology, §6 merge)
- ✅ Spec §4.2 adds → Task 4 (thermodynamic transparency), Task 14 (§5.X tension)
- ✅ Spec §4.3 reorder → Task 13 (Lumen teaser forward), Task 14 (§5 reorder)
- ✅ Spec §4.4 retitle → Task 25 Step 3 (Zenodo title field), manual title edit in Task 5 author block
- ✅ Spec §5.1 α1–α7 → Tasks 13/15/16 (α1a/b/c), Task 4 (α2), Tasks 6/7 (α3), Tasks 8/9/10 (α4), Task 5 (α5), Tasks 11/12 (α6), Tasks 1/2/3/17 (α7)
- ✅ Spec §5.2 β1/β2 → Tasks 22, 23
- ✅ Spec §5.3 out of scope → honored; not in plan
- ✅ Spec §6 venue → Tasks 25 (Zenodo), 26 (GitHub + landing)
- ✅ Spec §7 authorship → Task 5
- ✅ Spec §8 timeline → plan tasks map to the day-by-day in spec §8
- ✅ Spec §9 open items → threaded through tasks (ORCID at 5, classifications at 9, affiliation at 5, license at 25)
- ✅ Spec §10 success criteria → verified at Task 24
- ✅ Spec §11 out-of-scope → honored
- ✅ Spec §12 fellowship workstream → **revised per Kenny 2026-04-10: deferred to next cohort. Post-ship outreach in §R.**

**Placeholder scan:** every code step has actual code; every prose step has actual drafted text or an explicit fill-from-data instruction. No TBDs, no "add error handling as appropriate."

**Type consistency:** CSV column names used consistently across `pause_audit_sampler.py` and `pause_audit_analyze.py`. Figure filenames consistent between scripts and manuscript `\includegraphics`. Verdict categories (`justified` / `false_positive` / `ambiguous`) consistent across sampling, classification, and analysis.

**Known gaps requiring execution-time lookup (explicitly called out, not placeholders):**

- Task 6: specific bibtex citation strings for related work — must be looked up from arXiv / Google Scholar at execution time.
- Task 8: exact `outcome_events` column names — must be probed with `\d outcome_events` at execution time; script references adjusted.
- Task 12: exact Lumen sensor data source path — must be probed at execution time.
- Task 22: exact coupling-constant variable names in `unitares-core` — must be read from source at execution time.
- Task 25: Zenodo DOI value — known only after upload.

---

## Execution choice

Plan complete and saved to `docs/superpowers/plans/2026-04-10-unitares-v3-paper-revision.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Claude dispatches a fresh subagent per task, reviews the output between tasks, and coordinates Kenny's checkpoints. Good for this plan because prose tasks benefit from fresh-eyes output and the task list is long enough that per-task context isolation reduces drift.

**2. Inline Execution** — Claude executes tasks in this session using the executing-plans skill. Faster for short tasks but this plan has many substantial code + prose tasks; inline execution will consume a lot of context.

Which approach?
