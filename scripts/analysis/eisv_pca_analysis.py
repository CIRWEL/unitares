#!/usr/bin/env python3
"""
EISV Dimensionality Analysis

Question: Is EISV the right basis, or is the data trying to tell us something different?

Two analyses:
1. PCA on EISV state histories — are the 4 dimensions redundant? correlated?
2. PCA on raw check-in signals — what are the natural axes of behavioral variation?
"""

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

DB_PATH = Path(__file__).parent.parent / "data" / "governance.db"


def load_eisv_histories(conn, min_updates=15, max_updates=5000):
    """Extract per-timepoint EISV vectors from state_json histories."""
    cursor = conn.execute(
        "SELECT agent_id, state_json FROM agent_state "
        "WHERE update_count >= ? AND update_count <= ?",
        (min_updates, max_updates),
    )

    rows = []
    agent_ids = []
    for agent_id, state_json_str in cursor:
        state = json.loads(state_json_str)
        n = len(state.get("E_history", []))
        if n < min_updates:
            continue

        E_hist = state["E_history"]
        I_hist = state["I_history"]
        S_hist = state["S_history"]
        V_hist = state["V_history"]
        coh_hist = state.get("coherence_history", [0.5] * n)
        risk_hist = state.get("risk_history", [0.5] * n)
        lam_hist = state.get("lambda1_history", [0.125] * n)

        length = min(len(E_hist), len(I_hist), len(S_hist), len(V_hist),
                     len(coh_hist), len(risk_hist), len(lam_hist))

        for i in range(length):
            rows.append([
                E_hist[i], I_hist[i], S_hist[i], V_hist[i],
                coh_hist[i], risk_hist[i], lam_hist[i],
            ])
            agent_ids.append(agent_id)

    return np.array(rows), agent_ids


def load_complexity_signals(conn):
    """Extract raw dual-log signals from complexity_derivation audit events."""
    cursor = conn.execute(
        "SELECT agent_id, details_json FROM audit_events "
        "WHERE event_type = 'complexity_derivation'"
    )

    rows = []
    for agent_id, details_str in cursor:
        d = json.loads(details_str)
        reported = d.get("reported_complexity")
        derived = d.get("derived_complexity")
        discrepancy = d.get("discrepancy")
        resp_len = d.get("response_length")

        if None in (reported, derived, discrepancy, resp_len):
            continue

        rows.append([
            float(reported),
            float(derived),
            float(discrepancy),
            float(resp_len),
        ])

    return np.array(rows) if rows else np.empty((0, 4))


def run_pca(X, feature_names, label=""):
    """Run PCA and print results."""
    # Standardize
    mu = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-10] = 1.0
    Z = (X - mu) / std

    # Covariance & eigen decomposition
    cov = np.cov(Z, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)

    # Sort descending
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    total_var = eigenvalues.sum()
    explained = eigenvalues / total_var
    cumulative = np.cumsum(explained)

    print(f"\n{'='*70}")
    print(f"PCA: {label}")
    print(f"{'='*70}")
    print(f"Observations: {X.shape[0]:,}  Features: {X.shape[1]}")

    # Explained variance
    print(f"\n--- Explained Variance ---")
    for i, (ev, ex, cum) in enumerate(zip(eigenvalues, explained, cumulative)):
        bar = "#" * int(ex * 50)
        print(f"  PC{i+1}: {ex:6.1%}  (cumul: {cum:6.1%})  {bar}")

    # How many for 90%?
    n90 = np.searchsorted(cumulative, 0.90) + 1
    n95 = np.searchsorted(cumulative, 0.95) + 1
    print(f"\n  Components for 90% variance: {n90}")
    print(f"  Components for 95% variance: {n95}")

    # Loadings (top components)
    n_show = min(4, len(eigenvalues))
    print(f"\n--- Loadings (top {n_show} components) ---")
    header = "  Feature" + "".join(f"{'PC'+str(i+1):>10}" for i in range(n_show))
    print(header)
    print("  " + "-" * (len(header) - 2))

    for j, name in enumerate(feature_names):
        vals = "".join(f"{eigenvectors[j, i]:10.3f}" for i in range(n_show))
        # Mark dominant loadings
        dominant = [i for i in range(n_show) if abs(eigenvectors[j, i]) > 0.45]
        marker = f"  <-- dominant in PC{','.join(str(d+1) for d in dominant)}" if dominant else ""
        print(f"  {name:<18}{vals}{marker}")

    # Correlation matrix
    print(f"\n--- Correlation Matrix ---")
    corr = np.corrcoef(Z, rowvar=False)
    header = "  " + "".join(f"{n[:7]:>8}" for n in feature_names)
    print(header)
    for i, name in enumerate(feature_names):
        vals = "".join(f"{corr[i, j]:8.3f}" for j in range(len(feature_names)))
        print(f"  {name[:7]:<8}{vals}")

    # Flag high correlations
    print(f"\n--- High Correlations (|r| > 0.5) ---")
    found = False
    for i in range(len(feature_names)):
        for j in range(i + 1, len(feature_names)):
            r = corr[i, j]
            if abs(r) > 0.5:
                print(f"  {feature_names[i]} <-> {feature_names[j]}: r = {r:.3f}")
                found = True
    if not found:
        print("  None found.")

    # Per-agent variance analysis (if agent_ids provided)
    return eigenvalues, eigenvectors, explained, cumulative


def analyze_per_agent_variance(X, agent_ids, feature_names):
    """Check if variance is between-agent or within-agent."""
    agents = defaultdict(list)
    for i, aid in enumerate(agent_ids):
        agents[aid].append(X[i])

    within_var = np.zeros(X.shape[1])
    between_var = np.zeros(X.shape[1])
    grand_mean = X.mean(axis=0)
    total_n = 0

    for aid, rows in agents.items():
        arr = np.array(rows)
        n = len(arr)
        if n < 2:
            continue
        agent_mean = arr.mean(axis=0)
        within_var += arr.var(axis=0) * n
        between_var += n * (agent_mean - grand_mean) ** 2
        total_n += n

    if total_n == 0:
        return

    within_var /= total_n
    between_var /= total_n

    print(f"\n--- Variance Decomposition (between vs within agent) ---")
    print(f"  {'Feature':<18} {'Between':>10} {'Within':>10} {'Ratio B/W':>10} {'Interpretation'}")
    print("  " + "-" * 65)
    for j, name in enumerate(feature_names):
        total = within_var[j] + between_var[j]
        if total < 1e-10:
            continue
        ratio = between_var[j] / within_var[j] if within_var[j] > 1e-10 else float('inf')
        interp = "IDENTITY" if ratio > 2.0 else "BEHAVIOR" if ratio < 0.5 else "mixed"
        print(f"  {name:<18} {between_var[j]:10.6f} {within_var[j]:10.6f} {ratio:10.2f} {interp}")

    print(f"\n  IDENTITY = mostly varies between agents (fingerprint)")
    print(f"  BEHAVIOR = mostly varies within agents (state changes)")


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))

    # --- Analysis 1: EISV State Space ---
    eisv_features = ["E", "I", "S", "V", "coherence", "risk", "lambda1"]

    print("\nLoading EISV histories...")
    X_eisv, agent_ids = load_eisv_histories(conn, min_updates=15, max_updates=5000)
    if X_eisv.shape[0] > 0:
        print(f"Loaded {X_eisv.shape[0]:,} observations from {len(set(agent_ids))} agents")
        run_pca(X_eisv, eisv_features, "EISV + Derived Signals (state_json histories)")
        analyze_per_agent_variance(X_eisv, agent_ids, eisv_features)

        # Also run PCA on just E, I, S, V (the core 4)
        run_pca(X_eisv[:, :4], ["E", "I", "S", "V"], "Core EISV Only (4 dimensions)")
    else:
        print("No EISV history data found with sufficient updates.")

    # --- Analysis 2: Raw Input Signals ---
    print("\n\nLoading complexity signals...")
    X_complexity = load_complexity_signals(conn)
    complexity_features = ["reported_cx", "derived_cx", "discrepancy", "resp_length"]
    if X_complexity.shape[0] > 0:
        print(f"Loaded {X_complexity.shape[0]:,} complexity observations")
        run_pca(X_complexity, complexity_features, "Raw Dual-Log Signals (complexity_derivation)")
    else:
        print("No complexity data found.")

    # --- Analysis 3: Combined (EISV final state + complexity, where joinable) ---
    # Use agent-level aggregates
    print("\n\nBuilding per-agent profiles...")
    cursor = conn.execute(
        "SELECT agent_id, E, I, S, V, coherence, update_count "
        "FROM agent_state WHERE update_count >= 10"
    )
    agent_profiles = {}
    for aid, E, I, S, V, coh, uc in cursor:
        agent_profiles[aid] = {"E": E, "I": I, "S": S, "V": V,
                               "coherence": coh, "update_count": uc}

    # Add complexity stats per agent
    cursor = conn.execute(
        "SELECT agent_id, details_json FROM audit_events "
        "WHERE event_type = 'complexity_derivation'"
    )
    agent_cx = defaultdict(list)
    for aid, details_str in cursor:
        d = json.loads(details_str)
        if d.get("derived_complexity") is not None:
            agent_cx[aid].append({
                "reported": d.get("reported_complexity", 0.5),
                "derived": d["derived_complexity"],
                "discrepancy": d.get("discrepancy", 0),
                "resp_len": d.get("response_length", 0),
            })

    # Build combined profiles
    combined_rows = []
    combined_names = ["E", "I", "S", "V", "coherence",
                      "mean_reported", "mean_derived", "mean_discrep",
                      "mean_resp_len", "update_count"]
    for aid, profile in agent_profiles.items():
        cx_list = agent_cx.get(aid, [])
        if len(cx_list) < 3:
            continue
        combined_rows.append([
            profile["E"], profile["I"], profile["S"], profile["V"],
            profile["coherence"],
            np.mean([c["reported"] for c in cx_list]),
            np.mean([c["derived"] for c in cx_list]),
            np.mean([c["discrepancy"] for c in cx_list]),
            np.mean([c["resp_len"] for c in cx_list]),
            profile["update_count"],
        ])

    if combined_rows:
        X_combined = np.array(combined_rows)
        print(f"Built {X_combined.shape[0]} agent profiles with both EISV and complexity data")
        run_pca(X_combined, combined_names, "Per-Agent Combined Profiles")

    conn.close()
    print(f"\n{'='*70}")
    print("Done.")


if __name__ == "__main__":
    main()
