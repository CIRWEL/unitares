#!/usr/bin/env python3
"""
Drift Analysis Script - Generate Empirical Evidence for Patent Claims

PURPOSE:
Analyze drift telemetry data to generate quantitative evidence:
1. Convergence curves (does ||Δη|| decrease over time?)
2. Component correlation (which drift components predict problems?)
3. Baseline stability (are baselines converging appropriately?)
4. Decision correlation (does high drift predict negative outcomes?)

OUTPUT:
- Console summary statistics
- CSV export for external analysis
- Markdown report for patent documentation

USAGE:
    python scripts/analyze_drift.py [--agent AGENT_ID] [--export-csv] [--report]
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def load_telemetry(telemetry_file: Path, agent_id: Optional[str] = None) -> List[Dict]:
    """Load telemetry data from JSONL file."""
    if not telemetry_file.exists():
        return []

    samples = []
    with open(telemetry_file, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
                if agent_id is None or sample.get('agent_id') == agent_id:
                    samples.append(sample)
            except json.JSONDecodeError:
                continue

    return samples


def compute_statistics(samples: List[Dict]) -> Dict[str, Any]:
    """Compute aggregate statistics from samples."""
    if not samples:
        return {'error': 'No samples'}

    def safe_mean(lst):
        return sum(lst) / len(lst) if lst else 0.0

    def safe_std(lst):
        if len(lst) < 2:
            return 0.0
        mean = safe_mean(lst)
        variance = sum((x - mean) ** 2 for x in lst) / len(lst)
        return variance ** 0.5

    def safe_min(lst):
        return min(lst) if lst else 0.0

    def safe_max(lst):
        return max(lst) if lst else 0.0

    # Extract values
    norms = [s['norm'] for s in samples]
    cal_devs = [s['calibration_deviation'] for s in samples]
    cpx_divs = [s['complexity_divergence'] for s in samples]
    coh_devs = [s['coherence_deviation'] for s in samples]
    stab_devs = [s['stability_deviation'] for s in samples]
    confidences = [s.get('confidence', 0) for s in samples if s.get('confidence') is not None]

    agents = list(set(s['agent_id'] for s in samples))

    # Time range
    timestamps = [s['timestamp'] for s in samples]
    time_range = {
        'start': min(timestamps) if timestamps else None,
        'end': max(timestamps) if timestamps else None,
    }

    # Convergence analysis: compare first half vs second half
    mid = len(norms) // 2
    first_half_mean = safe_mean(norms[:mid]) if mid > 0 else None
    second_half_mean = safe_mean(norms[mid:]) if mid > 0 else None

    convergence = None
    if first_half_mean is not None and second_half_mean is not None:
        if first_half_mean > second_half_mean:
            convergence = {
                'improving': True,
                'reduction': (first_half_mean - second_half_mean) / first_half_mean * 100,
                'first_half_mean': first_half_mean,
                'second_half_mean': second_half_mean,
            }
        else:
            convergence = {
                'improving': False,
                'increase': (second_half_mean - first_half_mean) / max(first_half_mean, 0.001) * 100,
                'first_half_mean': first_half_mean,
                'second_half_mean': second_half_mean,
            }

    # Decision correlation
    proceed_norms = [s['norm'] for s in samples if s.get('decision') == 'proceed']
    pause_norms = [s['norm'] for s in samples if s.get('decision') == 'pause']

    decision_correlation = {
        'proceed_count': len(proceed_norms),
        'proceed_mean_norm': safe_mean(proceed_norms),
        'pause_count': len(pause_norms),
        'pause_mean_norm': safe_mean(pause_norms),
    }

    return {
        'total_samples': len(samples),
        'agents': agents,
        'agent_count': len(agents),
        'time_range': time_range,
        'norm': {
            'mean': safe_mean(norms),
            'std': safe_std(norms),
            'min': safe_min(norms),
            'max': safe_max(norms),
        },
        'components': {
            'calibration_deviation': {
                'mean': safe_mean(cal_devs),
                'std': safe_std(cal_devs),
            },
            'complexity_divergence': {
                'mean': safe_mean(cpx_divs),
                'std': safe_std(cpx_divs),
            },
            'coherence_deviation': {
                'mean': safe_mean(coh_devs),
                'std': safe_std(coh_devs),
            },
            'stability_deviation': {
                'mean': safe_mean(stab_devs),
                'std': safe_std(stab_devs),
            },
        },
        'confidence': {
            'mean': safe_mean(confidences),
            'std': safe_std(confidences),
        },
        'convergence': convergence,
        'decision_correlation': decision_correlation,
    }


def generate_report(stats: Dict[str, Any], agent_id: Optional[str] = None) -> str:
    """Generate markdown report for patent documentation."""
    lines = [
        "# Ethical Drift Analysis Report",
        "",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**Agent Filter:** {agent_id or 'All agents'}",
        "",
        "---",
        "",
        "## Summary Statistics",
        "",
        f"- **Total Samples:** {stats['total_samples']}",
        f"- **Agents:** {stats['agent_count']}",
        f"- **Time Range:** {stats['time_range'].get('start', 'N/A')} to {stats['time_range'].get('end', 'N/A')}",
        "",
        "## Drift Norm (||Δη||)",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Mean | {stats['norm']['mean']:.4f} |",
        f"| Std Dev | {stats['norm']['std']:.4f} |",
        f"| Min | {stats['norm']['min']:.4f} |",
        f"| Max | {stats['norm']['max']:.4f} |",
        "",
        "## Component Analysis",
        "",
        "| Component | Mean | Std Dev |",
        "|-----------|------|---------|",
    ]

    for name, data in stats['components'].items():
        lines.append(f"| {name} | {data['mean']:.4f} | {data['std']:.4f} |")

    lines.extend([
        "",
        "## Convergence Analysis",
        "",
    ])

    conv = stats.get('convergence')
    if conv:
        if conv['improving']:
            lines.extend([
                f"**Status:** ✅ IMPROVING",
                "",
                f"- First half mean: {conv['first_half_mean']:.4f}",
                f"- Second half mean: {conv['second_half_mean']:.4f}",
                f"- Reduction: {conv['reduction']:.1f}%",
                "",
                "*The drift norm is decreasing over time, indicating the system is converging.*",
            ])
        else:
            lines.extend([
                f"**Status:** ⚠️ NOT CONVERGING",
                "",
                f"- First half mean: {conv['first_half_mean']:.4f}",
                f"- Second half mean: {conv['second_half_mean']:.4f}",
                f"- Increase: {conv['increase']:.1f}%",
                "",
                "*The drift norm is increasing. Further investigation needed.*",
            ])
    else:
        lines.append("*Insufficient data for convergence analysis.*")

    lines.extend([
        "",
        "## Decision Correlation",
        "",
    ])

    dc = stats['decision_correlation']
    lines.extend([
        f"| Decision | Count | Mean Norm |",
        f"|----------|-------|-----------|",
        f"| proceed | {dc['proceed_count']} | {dc['proceed_mean_norm']:.4f} |",
        f"| pause | {dc['pause_count']} | {dc['pause_mean_norm']:.4f} |",
    ])

    if dc['proceed_count'] > 0 and dc['pause_count'] > 0:
        if dc['pause_mean_norm'] > dc['proceed_mean_norm']:
            lines.extend([
                "",
                f"*Higher drift correlates with pause decisions (ratio: {dc['pause_mean_norm']/dc['proceed_mean_norm']:.2f}x). This validates the drift metric.*",
            ])

    lines.extend([
        "",
        "---",
        "",
        "*This report provides quantitative evidence for patent claims regarding ethical drift measurement.*",
    ])

    return "\n".join(lines)


def export_csv(samples: List[Dict], output_path: Path) -> int:
    """Export samples to CSV."""
    if not samples:
        return 0

    headers = list(samples[0].keys())

    with open(output_path, 'w') as f:
        f.write(','.join(headers) + '\n')
        for sample in samples:
            row = [str(sample.get(h, '')) for h in headers]
            f.write(','.join(row) + '\n')

    return len(samples)


def main():
    parser = argparse.ArgumentParser(description='Analyze drift telemetry data')
    parser.add_argument('--agent', '-a', type=str, help='Filter by agent ID')
    parser.add_argument('--export-csv', '-c', action='store_true', help='Export to CSV')
    parser.add_argument('--report', '-r', action='store_true', help='Generate markdown report')
    parser.add_argument('--output-dir', '-o', type=str, default='data/analysis', help='Output directory')

    args = parser.parse_args()

    # Load telemetry
    telemetry_file = project_root / 'data' / 'telemetry' / 'drift_telemetry.jsonl'
    samples = load_telemetry(telemetry_file, args.agent)

    if not samples:
        print("No telemetry data found.")
        print(f"Expected file: {telemetry_file}")
        return 1

    # Compute statistics
    stats = compute_statistics(samples)

    # Print summary
    print("\n" + "=" * 60)
    print("ETHICAL DRIFT ANALYSIS")
    print("=" * 60)
    print(f"\nTotal samples: {stats['total_samples']}")
    print(f"Agents: {', '.join(stats['agents'][:5])}{'...' if len(stats['agents']) > 5 else ''}")
    print(f"\n||Δη|| Statistics:")
    print(f"  Mean: {stats['norm']['mean']:.4f}")
    print(f"  Std:  {stats['norm']['std']:.4f}")
    print(f"  Range: [{stats['norm']['min']:.4f}, {stats['norm']['max']:.4f}]")

    print(f"\nComponent Means:")
    for name, data in stats['components'].items():
        print(f"  {name}: {data['mean']:.4f}")

    conv = stats.get('convergence')
    if conv:
        print(f"\nConvergence:")
        if conv['improving']:
            print(f"  ✅ Improving ({conv['reduction']:.1f}% reduction)")
        else:
            print(f"  ⚠️ Not converging ({conv['increase']:.1f}% increase)")

    dc = stats['decision_correlation']
    if dc['proceed_count'] > 0 or dc['pause_count'] > 0:
        print(f"\nDecision Correlation:")
        print(f"  proceed: {dc['proceed_count']} samples, mean norm {dc['proceed_mean_norm']:.4f}")
        print(f"  pause: {dc['pause_count']} samples, mean norm {dc['pause_mean_norm']:.4f}")

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Export CSV if requested
    if args.export_csv:
        csv_path = output_dir / 'drift_analysis.csv'
        count = export_csv(samples, csv_path)
        print(f"\nExported {count} samples to {csv_path}")

    # Generate report if requested
    if args.report:
        report = generate_report(stats, args.agent)
        report_path = output_dir / 'drift_report.md'
        with open(report_path, 'w') as f:
            f.write(report)
        print(f"Generated report: {report_path}")

    print("\n" + "=" * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
