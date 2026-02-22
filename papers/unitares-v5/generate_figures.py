#!/usr/bin/env python3
"""Generate figures for UNITARES v5 paper from production data."""

import sqlite3
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "governance.db"
OUT_DIR = Path(__file__).parent / "figures"
OUT_DIR.mkdir(exist_ok=True)

plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 10,
    'axes.labelsize': 11,
    'figure.figsize': (3.4, 2.6),  # Single column width for two-column paper
    'figure.dpi': 300,
    'savefig.bbox': 'tight',
    'savefig.pad_inches': 0.05,
})


def get_active_agents(conn, min_updates=5):
    """Get EISV data for agents with sufficient history."""
    return conn.execute("""
        SELECT agent_id, E, I, S, V, coherence, regime, update_count
        FROM agent_state WHERE update_count > ?
        ORDER BY update_count DESC
    """, (min_updates,)).fetchall()


def fig1_eisv_scatter(conn):
    """Figure 1: E-I scatter colored by regime."""
    agents = get_active_agents(conn)

    colors = {
        'CONVERGENCE': '#2ca02c',
        'EXPLORATION': '#1f77b4',
        'DIVERGENCE': '#d62728',
    }

    fig, ax = plt.subplots()
    for a in agents:
        _, E, I, S, V, C, regime, n = a
        ax.scatter(E, I, c=colors.get(regime, '#999'),
                   s=min(np.log(n+1)*8, 80), alpha=0.7, edgecolors='white', linewidths=0.3)

    # Add diagonal I=E line
    ax.plot([0.5, 1.0], [0.5, 1.0], 'k--', alpha=0.3, linewidth=0.8, label='$I = E$')

    # Legend
    for regime, color in colors.items():
        ax.scatter([], [], c=color, s=30, label=regime.capitalize())
    ax.legend(fontsize=8, loc='lower right')

    ax.set_xlabel('Energy $E$')
    ax.set_ylabel('Integrity $I$')
    ax.set_xlim(0.55, 1.02)
    ax.set_ylim(0.55, 1.02)
    ax.set_aspect('equal')

    fig.savefig(OUT_DIR / 'fig1_ei_scatter.pdf')
    fig.savefig(OUT_DIR / 'fig1_ei_scatter.png')
    plt.close(fig)
    print("  fig1_ei_scatter: E-I scatter by regime")


def fig2_sv_scatter(conn):
    """Figure 2: S-V scatter showing operating region."""
    agents = get_active_agents(conn)

    fig, ax = plt.subplots()

    S_vals = [a[3] for a in agents]
    V_vals = [a[4] for a in agents]

    ax.scatter(V_vals, S_vals, c='#1f77b4', s=25, alpha=0.7, edgecolors='white', linewidths=0.3)

    # Show theoretical bounds
    ax.axvline(x=-0.1, color='gray', linestyle=':', alpha=0.5, linewidth=0.8)
    ax.axvline(x=0.1, color='gray', linestyle=':', alpha=0.5, linewidth=0.8)
    ax.axhline(y=0.001, color='gray', linestyle=':', alpha=0.5, linewidth=0.8)

    # Annotate operating region
    ax.annotate('$V \\in [-0.1, 0.1]$', xy=(0.0, 0.19), fontsize=8, ha='center', color='gray')

    ax.set_xlabel('Void $V$')
    ax.set_ylabel('Entropy $S$')

    fig.savefig(OUT_DIR / 'fig2_sv_scatter.pdf')
    fig.savefig(OUT_DIR / 'fig2_sv_scatter.png')
    plt.close(fig)
    print("  fig2_sv_scatter: S-V operating region")


def fig3_coherence_hist(conn):
    """Figure 3: Coherence histogram showing C ≈ 0.49."""
    agents = get_active_agents(conn)
    C_vals = [a[5] for a in agents]

    fig, ax = plt.subplots()
    ax.hist(C_vals, bins=20, color='#1f77b4', alpha=0.8, edgecolor='white', linewidth=0.5)
    ax.axvline(x=0.5, color='#d62728', linestyle='--', linewidth=1, label='$C = 0.5$ (midpoint)')
    ax.axvline(x=np.mean(C_vals), color='#2ca02c', linestyle='-', linewidth=1,
               label=f'$\\bar{{C}} = {np.mean(C_vals):.3f}$')

    ax.set_xlabel('Coherence $C(V)$')
    ax.set_ylabel('Count')
    ax.legend(fontsize=8)

    fig.savefig(OUT_DIR / 'fig3_coherence_hist.pdf')
    fig.savefig(OUT_DIR / 'fig3_coherence_hist.png')
    plt.close(fig)
    print("  fig3_coherence_hist: coherence distribution")


def fig4_saturation_margin(conn):
    """Figure 4: Saturation margin by regime."""
    agents = get_active_agents(conn)

    # Production params
    k = 0.10
    beta_I = 0.30
    gamma_I = 0.25

    regimes = {'CONVERGENCE': [], 'EXPLORATION': [], 'DIVERGENCE': []}

    for a in agents:
        _, E, I, S, V, C, regime, n = a
        A = beta_I * C - k * S
        m_sat = 1.0 - (4.0 * A / gamma_I)
        if regime in regimes:
            regimes[regime].append(m_sat)

    fig, ax = plt.subplots()
    positions = [1, 2, 3]
    labels = ['Convergence', 'Exploration', 'Divergence']
    colors = ['#2ca02c', '#1f77b4', '#d62728']

    data = [regimes['CONVERGENCE'], regimes['EXPLORATION'], regimes['DIVERGENCE']]
    bp = ax.boxplot(data, positions=positions, patch_artist=True, widths=0.6)

    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    ax.axhline(y=0, color='black', linestyle='-', linewidth=1.5, label='Saturation boundary')
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel('Saturation margin $m_{\\mathrm{sat}}$')
    ax.legend(fontsize=8)

    # Annotate
    ax.annotate('All agents saturated\n(logistic mode)',
                xy=(2, -0.3), fontsize=7, ha='center', color='#d62728', style='italic')

    fig.savefig(OUT_DIR / 'fig4_saturation_margin.pdf')
    fig.savefig(OUT_DIR / 'fig4_saturation_margin.png')
    plt.close(fig)
    print("  fig4_saturation_margin: saturation margin boxplot by regime")


def fig5_regime_profiles(conn):
    """Figure 5: EISV bar chart by regime."""
    agents = get_active_agents(conn)

    regimes = {'CONVERGENCE': [], 'EXPLORATION': [], 'DIVERGENCE': []}
    for a in agents:
        _, E, I, S, V, C, regime, n = a
        if regime in regimes:
            regimes[regime].append((E, I, S, abs(V)))

    fig, ax = plt.subplots(figsize=(3.4, 2.2))

    x = np.arange(4)  # E, I, S, |V|
    width = 0.25

    labels = ['$E$', '$I$', '$S$', '$|V|$']
    colors = ['#2ca02c', '#1f77b4', '#d62728']
    regime_names = ['Convergence', 'Exploration', 'Divergence']

    for i, (rname, color) in enumerate(zip(['CONVERGENCE', 'EXPLORATION', 'DIVERGENCE'], colors)):
        data = regimes[rname]
        if data:
            means = [np.mean([d[j] for d in data]) for j in range(4)]
            ax.bar(x + i*width, means, width, color=color, alpha=0.8, label=regime_names[i])

    ax.set_xticks(x + width)
    ax.set_xticklabels(labels)
    ax.set_ylabel('Mean Value')
    ax.legend(fontsize=7, loc='upper right')

    fig.savefig(OUT_DIR / 'fig5_regime_profiles.pdf')
    fig.savefig(OUT_DIR / 'fig5_regime_profiles.png')
    plt.close(fig)
    print("  fig5_regime_profiles: EISV by regime")


def fig6_discovery_types(conn):
    """Figure 6: Knowledge graph discovery types."""
    rows = conn.execute("""
        SELECT type, COUNT(*) as cnt FROM discoveries
        GROUP BY type ORDER BY cnt DESC LIMIT 6
    """).fetchall()

    types = [r[0] for r in rows]
    counts = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(3.4, 2.0))
    ax.barh(range(len(types)), counts, color='#1f77b4', alpha=0.8, edgecolor='white')
    ax.set_yticks(range(len(types)))
    ax.set_yticklabels([t.replace('_', ' ').capitalize() for t in types], fontsize=9)
    ax.set_xlabel('Count')
    ax.invert_yaxis()

    fig.savefig(OUT_DIR / 'fig6_discovery_types.pdf')
    fig.savefig(OUT_DIR / 'fig6_discovery_types.png')
    plt.close(fig)
    print("  fig6_discovery_types: knowledge graph breakdown")


if __name__ == "__main__":
    print(f"Connecting to: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)

    print("Generating figures...")
    fig1_eisv_scatter(conn)
    fig2_sv_scatter(conn)
    fig3_coherence_hist(conn)
    fig4_saturation_margin(conn)
    fig5_regime_profiles(conn)
    fig6_discovery_types(conn)

    conn.close()
    print(f"\nDone. Figures saved to: {OUT_DIR}")
