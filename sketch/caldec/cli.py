"""
Command-line interface.

Usage:
    caldec check [--path PATH]           Check calibration status
    caldec drift [--path PATH]           Check for drift
    caldec serve [--port PORT]           Run REST API server
    caldec demo                          Run demo with simulated data
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="caldec",
        description="Calibrated Decisions - confidence calibration for autonomous systems",
    )
    sub = parser.add_subparsers(dest="command", help="Commands")

    # check
    p_check = sub.add_parser("check", help="Check calibration status")
    p_check.add_argument("--path", default="data/calibration.json", help="Calibration data path")

    # drift
    p_drift = sub.add_parser("drift", help="Check for drift")
    p_drift.add_argument("--path", default="data/drift.json", help="Drift data path")

    # serve
    p_serve = sub.add_parser("serve", help="Run REST API server")
    p_serve.add_argument("--host", default="0.0.0.0", help="Host")
    p_serve.add_argument("--port", type=int, default=8080, help="Port")
    p_serve.add_argument("--data-dir", default="data", help="Data directory")

    # demo
    sub.add_parser("demo", help="Run demo with simulated data")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check(args.path)
    elif args.command == "drift":
        cmd_drift(args.path)
    elif args.command == "serve":
        cmd_serve(args.host, args.port, args.data_dir)
    elif args.command == "demo":
        cmd_demo()
    else:
        parser.print_help()


def cmd_check(path: str):
    from .calibrator import Calibrator

    p = Path(path)
    if not p.exists():
        print(f"No calibration data at {path}")
        sys.exit(1)

    cal = Calibrator(path=p)
    report = cal.check()

    print(f"Calibrated: {report.calibrated}")
    print(f"Total: {report.total}")
    print(f"Summary: {report.summary}")

    if report.issues:
        print("\nIssues:")
        for issue in report.issues:
            print(f"  - {issue}")

    if report.bins:
        print("\nBins:")
        for k, v in sorted(report.bins.items()):
            print(f"  {k}: expected {v['expected']:.0%}, actual {v['accuracy']:.0%} (n={v['count']})")

    if report.correction_factors:
        print("\nCorrection factors:")
        for k, f in sorted(report.correction_factors.items()):
            label = "overconfident" if f < 1 else "underconfident" if f > 1 else "calibrated"
            print(f"  {k}: {f:.2f} ({label})")


def cmd_drift(path: str):
    from .drift import DriftDetector

    p = Path(path)
    if not p.exists():
        print(f"No drift data at {path}")
        sys.exit(1)

    d = DriftDetector(path=p)
    report = d.check()

    print(f"Drifting: {report.drifting}")
    if report.drift_type:
        print(f"Type: {report.drift_type}")
        print(f"Direction: {report.direction}")
        print(f"Severity: {report.severity:.1%}")
    print(f"\nRecommendation: {report.recommendation}")


def cmd_serve(host: str, port: int, data_dir: str):
    from .server import serve
    print(f"Starting caldec server at http://{host}:{port}")
    serve(host, port, data_dir)


def cmd_demo():
    import random
    from .calibrator import Calibrator
    from .drift import DriftDetector

    print("=" * 50)
    print("caldec Demo - Simulated Trading Strategy")
    print("=" * 50)

    cal = Calibrator()
    drift = DriftDetector()

    print("\nSimulating 100 predictions...")

    for _ in range(100):
        # Simulate overconfident model
        conf = random.uniform(0.5, 0.95)
        # High confidence = overconfident (only 65% accurate at 90%+ confidence)
        if conf > 0.85:
            correct = random.random() < 0.65
        else:
            correct = random.random() < conf

        cal.record_with_outcome(conf, correct)
        drift.record(conf, correct)

    print("\n--- Calibration Report ---")
    report = cal.check()
    print(f"Calibrated: {report.calibrated}")
    print(f"Summary: {report.summary}")
    if report.issues:
        for issue in report.issues:
            print(f"  ! {issue}")

    print("\n--- Correction Factors ---")
    for k, f in sorted(report.correction_factors.items()):
        label = "overconfident" if f < 1 else "underconfident" if f > 1 else "ok"
        print(f"  {k}: ×{f:.2f} ({label})")

    print("\n--- Calibrated Confidence ---")
    for raw in [0.6, 0.75, 0.9]:
        adj, _ = cal.calibrate(raw)
        print(f"  {raw:.0%} raw → {adj:.0%} calibrated")

    print("\n--- Drift Check ---")
    d = drift.check()
    print(f"Drifting: {d.drifting}")
    print(f"Recommendation: {d.recommendation}")


if __name__ == "__main__":
    main()
