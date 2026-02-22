# UNITARES v5 Paper — Working Notes

## Status: Ready for Overleaf Upload

The LaTeX source `unitares-v5.tex` is a complete paper (1592 lines) with all sections written, production data filled in, contraction proof completed, 6 figures integrated, and all review feedback addressed. Linear I-dynamics mode has been rolled out as the production default.

## Revision Log

### Final integration (2026-02-20)
- **6 figures added** from production data (PDF + PNG at 300dpi):
  - Fig 1: E-I scatter by regime (fig1_ei_scatter.pdf)
  - Fig 2: S-V operating region (fig2_sv_scatter.pdf)
  - Fig 3: Coherence histogram (fig3_coherence_hist.pdf)
  - Fig 4: Saturation margin boxplot by regime (fig4_saturation_margin.pdf)
  - Fig 5: EISV regime profiles (fig5_regime_profiles.pdf)
  - Fig 6: Knowledge graph discovery types (fig6_discovery_types.pdf)
- **Linear I-dynamics mode** rolled out as production default in `parameters.py`
  - Auto-applies γ_I=0.169 when linear mode + default profile
  - All 65 tests passing
- **Limitations updated** to reflect logistic→linear transition
- **All cross-references verified** — no broken \Cref/\ref targets
- **Author metadata**: Kenny Wang, Independent Researcher, kenny@cirwel.com

### Review feedback addressed (2026-02-20)
1. **"Five contributions" → "six contributions"** — fixed
2. **Theorem 3.2 contraction proof** — full Gershgorin analysis in Appendix B with metric M = diag(0.1, 0.2, 1.0, 0.08), certified α_c = 0.02 (conservative lower bound)
3. **Related Work AI Safety** — positioned vs Moral Anchor System (Ravindran 2025), Control Barrier Functions (Ames 2019), NeMo Guardrails (Rebedea 2023)
4. **Stochastic extension verified** — explicit computation for G = diag(0,0,σ,0), steady-state bound = 0.01, cited Pham et al. 2009
5. **Ethical drift parameter table** — added as Table 3 in Appendix A
6. **"Honest measurements" promoted** — now §10.1 "Design Principle: Adjust Expectations, Not Measurements" with three consequences
7. **Three-tier → two-tier explanation** — Remark 5.4 explains why "revise" was ambiguous in production
8. **Boundary clamping** — new §10.3 "Boundary Clamping and Non-Smoothness" with three treatments (interior operation, projected dynamical systems, practical monitoring)
9. **Experiments section** — fully written with production data from governance.db (903 agents, 69 days, 198K audit events)
10. **Energy spike containment** — Remark 6.4 showing entropy dominates energy excitation (γ_E=0.05 < λ₁∈[0.05,0.20])
11. **Saturation margin fixed** — m_sat corrected from "≈0.2" to "-1.23" with production data

## What's Written (All Complete)

| Section | Status | Key Content |
|---------|--------|-------------|
| Abstract | ✅ | 903 agents, 69 days, V ∈ [-0.1, 0.1] in 100% of agents |
| 1. Introduction | ✅ | Six contributions, full related work (MAS, CBF, guardrails) |
| 2. EISV Dynamics | ✅ | All 4 ODEs, coherence, adaptive λ₁, Φ objective |
| 3. Contraction Analysis | ✅ | Jacobian, Theorem 3.2 (α_c = 0.02), equilibrium |
| 4. I-Channel Saturation | ✅ | Logistic vs linear, criterion, contraction implications |
| 5. Adaptive Governor | ✅ | Phase detection, PID law, wind-up, decay, verdict, Remark 5.4 |
| 6. Ethical Drift Vector | ✅ | 4 components, EMA baseline, warmup, dynamics coupling, Remark 6.4 |
| 7. Stochastic Extensions | ✅ | Itô SDE, Theorem 7.1, production noise verification |
| 8. Multi-Agent Network | ✅ | Graph coupling, Theorem 8.1 synchronization |
| 9. Experiments | ✅ | 6 subsections, 4 tables, 6 figures, 903 agents, regime analysis |
| 10. Discussion | ✅ | Honest measurements (§10.1), parameters (§10.2), clamping (§10.3), limits (§10.4), thermo (§10.5) |
| 11. Conclusion | ✅ | Impact statement included |
| App A: Parameters | ✅ | 3 tables (dynamics, governor, ethical drift) |
| App B: Contraction | ✅ | Full Gershgorin analysis, metric construction, numerical verification |
| App C: Saturation | ✅ | Saturation margin table by regime (all negative under logistic mode) |
| References | ✅ | 14 references |

## Figures (6 total)

| Figure | File | Section | Description |
|--------|------|---------|-------------|
| Fig 1 | fig1_ei_scatter.pdf | §9.2 | E-I scatter by regime, I > E diagonal |
| Fig 2 | fig2_sv_scatter.pdf | §9.2 | S-V operating region, V ∈ [-0.1, 0.1] |
| Fig 3 | fig3_coherence_hist.pdf | §9.2 | Coherence distribution, C̅ = 0.483 |
| Fig 4 | fig4_saturation_margin.pdf | §9.3 | Saturation margin, all negative |
| Fig 5 | fig5_regime_profiles.pdf | §9.4 | EISV by regime (convergence/exploration/divergence) |
| Fig 6 | fig6_discovery_types.pdf | §9.5 | Knowledge graph discovery types |

## Production Data Summary

From `governance.db` (queried 2026-02-20):
- **903 total agents**, 75 with >5 updates, 5 with >1000 updates
- **EISV equilibrium**: E̅=0.766, I̅=0.877, S̅=0.082, V̅=-0.033
- **Coherence**: C̅=0.483, range [0.455, 0.503]
- **V range**: [-0.089, 0.007] — 100% within [-0.1, 0.1]
- **19 agents** at I≥0.999 boundary (logistic mode saturation)
- **Saturation margin**: m_sat = -1.28 mean (all negative under logistic mode)
- **Regimes**: 24 convergence, 22 exploration, 29 divergence (active agents)
- **198,333 audit events**, 500 knowledge discoveries, 66 dialectic sessions
- **Deployment**: Dec 13, 2025 – Feb 20, 2026 (69 days)

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Production parameters as primary | α=0.42, β_I=0.30 — what actually runs |
| Contraction rate α_c = 0.02 | Conservative Gershgorin bound; actual convergence faster |
| Linear I-mode as default | 100% saturation under logistic mode; linear gives I*≈0.80 |
| Two-tier verdict | "Revise" caused oscillation in practice |
| D-term dominant (K_d=0.10) | D-term IS the damping — no separate oscillation detector needed |

## Overleaf Upload Checklist

1. Create new Overleaf project
2. Upload `unitares-v5.tex` as main document
3. Create `figures/` directory and upload all 6 PDF files
4. Compile with pdfLaTeX (all packages are standard)
5. The paper uses: amsmath, graphicx, booktabs, algorithm, algorithmic, hyperref, cleveref, natbib, xcolor, thmtools, caption

## Remaining Work (Optional)

### Before Submission
1. **Target venue** — recommend arXiv-first, then workshop submission (SafeAI, NeurIPS Safety)
2. **Final proofread** — one pass for typos and minor phrasing

### Optional Improvements
- Non-diagonal metric for tighter contraction bound (could improve α_c from 0.02 to ~0.05)
- A/B comparison of logistic vs linear mode in production
- Before/after CIRS v2 comparison once sufficient post-deployment data exists
- Eigenvalue computation of the actual Jacobian at observed equilibrium

## Source Files (Code → Paper Mapping)

| Code File | Paper Section |
|-----------|---------------|
| `governance_core/dynamics.py` | §2 (Dynamics), §4 (Saturation) |
| `governance_core/coherence.py` | §2.3 (Coherence) |
| `governance_core/parameters.py` | Appendix A |
| `governance_core/scoring.py` | §2.5 (Objective) |
| `governance_core/ethical_drift.py` | §6 (Ethical Drift) |
| `governance_core/adaptive_governor.py` | §5 (Governor) |
| `governance_core/phase_aware.py` | §5.2 (Phase Detection) |
| `papers/unitares-v5/generate_figures.py` | §9 (Experiments) |
| `data/governance.db` | §9 (Experiments) |
