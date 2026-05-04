#!/usr/bin/env python3
"""
Mechanical evaluator for Phase B promotion eligibility per
``docs/proposals/surface-lease-plane-v0.md`` §6.1.

Runs the six promotion-gate criteria against live telemetry and prints a
deterministic per-criterion verdict plus overall recommendation. Use this
instead of ad-hoc SQL when deciding whether to flip enforcement on a
surface_kind — anchors the call in audit data, not vibes.

Usage:
    python3 scripts/lease_plane/evaluate_phase_b_promotion.py <surface_kind>
    python3 scripts/lease_plane/evaluate_phase_b_promotion.py dialectic --json
    python3 scripts/lease_plane/evaluate_phase_b_promotion.py file --window-days 14

Exit codes:
    0 - All evaluable criteria PASS for the surface_kind (promotable)
    1 - One or more criteria FAIL or are NOT_YET_EVALUABLE (not promotable)
    2 - Database / connection error (cannot evaluate)
    3 - Unknown surface_kind
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2


class UnknownSurfaceKindError(ValueError):
    """Raised when an unrecognized surface_kind is passed to evaluate()."""


# Per §6.2, ordering when multiple surface_kinds are eligible.
KNOWN_SURFACE_KINDS = ("dialectic", "resident", "file", "capture", "td")

# Per §6.1: criterion 5 is N/A for non-write surface_kinds.
NON_WRITE_SURFACE_KINDS = frozenset({"dialectic", "resident"})


@dataclass
class CriterionResult:
    number: int
    name: str
    status: str  # PASS, FAIL, NOT_APPLICABLE, NOT_YET_EVALUABLE
    detail: str
    measured: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    surface_kind: str
    window_days: int
    evaluated_at: str
    criteria: list[CriterionResult]
    promotable: bool

    @property
    def summary(self) -> str:
        return (
            f"surface_kind={self.surface_kind} "
            f"window={self.window_days}d "
            f"promotable={'YES' if self.promotable else 'NO'}"
        )


def _conn(db_url: str | None):
    url = db_url or os.environ.get(
        "DB_POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/governance"
    )
    return psycopg2.connect(url)


class _DictCursor:
    """Wraps a psycopg2 cursor so fetchone() returns a column-name dict.

    Avoids the hard dependency on ``psycopg2.extras.RealDictCursor`` so the
    module loads cleanly under test environments that stub psycopg2 (see
    ``tests/test_calibrate_class_conditional.py`` — ``sys.modules.setdefault``
    installs a bare stub that lacks ``RealDictCursor``).
    """

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        self._cursor.execute(sql, params)

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None or isinstance(row, dict):
            return row
        cols = [d[0] for d in self._cursor.description]
        return dict(zip(cols, row))


def _criterion_1_advisory_window(cur, surface_kind: str, window_days: int) -> CriterionResult:
    """≥14 days of advisory-mode telemetry for that surface_kind."""
    cur.execute(
        """
        SELECT min(ts) AS earliest, max(ts) AS latest, count(*) AS n
        FROM lease_plane.lease_plane_events
        WHERE advisory_mode = true AND surface_kind = %s
        """,
        (surface_kind,),
    )
    row = cur.fetchone()
    earliest = row["earliest"]
    if earliest is None:
        return CriterionResult(
            number=1,
            name="advisory_window",
            status="FAIL",
            detail=f"no advisory traffic for surface_kind='{surface_kind}'",
            measured={"events": 0},
        )
    now = datetime.now(timezone.utc)
    days_observed = (now - earliest).total_seconds() / 86400.0
    measured = {
        "earliest": earliest.isoformat(),
        "latest": row["latest"].isoformat(),
        "events": row["n"],
        "days_observed": round(days_observed, 2),
        "days_required": window_days,
    }
    if days_observed >= window_days:
        return CriterionResult(
            number=1,
            name="advisory_window",
            status="PASS",
            detail=f"{days_observed:.1f}d ≥ {window_days}d",
            measured=measured,
        )
    return CriterionResult(
        number=1,
        name="advisory_window",
        status="FAIL",
        detail=f"only {days_observed:.1f}d of {window_days}d required "
        f"(eligible {(earliest + timedelta(days=window_days)).date().isoformat()})",
        measured=measured,
    )


def _criterion_2_uptime(cur, window_days: int) -> CriterionResult:
    """0 service-availability incidents on the lease plane (≥99.5% uptime)."""
    # Sentinel writes to audit.events. The exact event_type/agent for lease-plane
    # downtime alarms is operationally established (sentinel batched alarm rule
    # for 'conflict_held_by_other' events landed PR #310). We approximate with
    # any 'service_down' / 'lease_plane_down' style event type if present.
    cur.execute(
        """
        SELECT exists(
          SELECT 1 FROM information_schema.tables
          WHERE table_schema = 'audit' AND table_name = 'events'
        ) AS has_table
        """
    )
    has_audit_events = cur.fetchone()["has_table"]
    if not has_audit_events:
        return CriterionResult(
            number=2,
            name="lease_plane_uptime",
            status="NOT_YET_EVALUABLE",
            detail="audit.events table not present; uptime probe wiring pending",
        )
    cur.execute(
        """
        SELECT count(*) AS n
        FROM audit.events
        WHERE event_type IN ('lease_plane_down', 'service_down')
          AND ts > now() - %s::interval
        """,
        (f"{window_days} days",),
    )
    n_down = cur.fetchone()["n"]
    if n_down == 0:
        return CriterionResult(
            number=2,
            name="lease_plane_uptime",
            status="PASS",
            detail=f"0 service-availability incidents in {window_days}d window",
            measured={"down_events": 0},
        )
    return CriterionResult(
        number=2,
        name="lease_plane_uptime",
        status="FAIL",
        detail=f"{n_down} service-availability incidents in {window_days}d window",
        measured={"down_events": n_down},
    )


def _criterion_3_type_a_signal(cur, surface_kind: str, window_days: int) -> CriterionResult:
    """≥3 distinct surface_id with conflict_held_by_other in the window."""
    cur.execute(
        """
        SELECT count(DISTINCT surface_id) AS distinct_surfaces,
               count(*) AS total_conflicts
        FROM lease_plane.lease_plane_events
        WHERE event_type = 'conflict_held_by_other'
          AND advisory_mode = true
          AND surface_kind = %s
          AND ts > now() - %s::interval
        """,
        (surface_kind, f"{window_days} days"),
    )
    row = cur.fetchone()
    distinct = row["distinct_surfaces"]
    measured = {"distinct_surfaces": distinct, "total_conflicts": row["total_conflicts"]}
    if distinct >= 3:
        return CriterionResult(
            number=3,
            name="type_a_conflict_signal",
            status="PASS",
            detail=f"{distinct} distinct surface_id with conflicts ≥ 3",
            measured=measured,
        )
    return CriterionResult(
        number=3,
        name="type_a_conflict_signal",
        status="FAIL",
        detail=f"only {distinct} distinct surface_id with conflicts; need ≥ 3",
        measured=measured,
    )


def _criterion_4_incident_linkage(cur, surface_kind: str, window_days: int) -> CriterionResult:
    """Type A→incident linkage: blocked caller's audit_session joins to a KG entry within ±1h."""
    # The ±1h KG join requires (a) audit_session emitted on lease conflict events,
    # and (b) a queryable KG table with timestamps. The current
    # lease_plane.lease_plane_events schema does not carry audit_session;
    # the linkage instrumentation hasn't landed yet.
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'lease_plane'
          AND table_name = 'lease_plane_events'
          AND column_name IN ('audit_session', 'audit_session_id')
        """
    )
    has_audit_session = cur.fetchone() is not None
    if not has_audit_session:
        return CriterionResult(
            number=4,
            name="incident_kg_linkage",
            status="NOT_YET_EVALUABLE",
            detail="lease_plane_events lacks audit_session column; "
            "linkage instrumentation must land before this criterion is evaluable",
        )
    # When the column exists, evaluate the join. Schema details are deferred to
    # the implementation that lands the column; this branch will need to be
    # filled in then with the canonical KG-join SQL.
    return CriterionResult(
        number=4,
        name="incident_kg_linkage",
        status="NOT_YET_EVALUABLE",
        detail="audit_session column present but join SQL pending — "
        "fill in canonical KG-join query when instrumentation finalizes",
    )


def _criterion_5_coverage_ratio(cur, surface_kind: str, window_days: int) -> CriterionResult:
    """Coverage ratio (writes through lease plane / total writes) ≥ 0.95."""
    if surface_kind in NON_WRITE_SURFACE_KINDS:
        return CriterionResult(
            number=5,
            name="coverage_ratio",
            status="NOT_APPLICABLE",
            detail=f"surface_kind='{surface_kind}' is non-write per §6.1 carve-out",
        )
    cur.execute(
        """
        WITH writes AS (
          SELECT count(*) AS n FROM audit.tool_usage
           WHERE tool_name LIKE 'write.%%'
             AND payload->>'surface_id' LIKE %s
             AND ts > now() - %s::interval
        ), acquires AS (
          SELECT count(*) AS n FROM audit.tool_usage
           WHERE tool_name = 'lease.acquire'
             AND payload->>'surface_id' LIKE %s
             AND ts > now() - %s::interval
        )
        SELECT writes.n AS writes, acquires.n AS acquires,
               CASE WHEN writes.n = 0 THEN NULL
                    ELSE acquires.n::float / writes.n
               END AS coverage_ratio
        FROM writes, acquires
        """,
        (
            f"{surface_kind}:%",
            f"{window_days} days",
            f"{surface_kind}:%",
            f"{window_days} days",
        ),
    )
    row = cur.fetchone()
    writes = row["writes"]
    acquires = row["acquires"]
    coverage = row["coverage_ratio"]
    measured = {"writes": writes, "acquires": acquires, "coverage_ratio": coverage}
    if writes == 0:
        return CriterionResult(
            number=5,
            name="coverage_ratio",
            status="NOT_YET_EVALUABLE",
            detail="no write.* audit events with surface_id payload yet — "
            "write-class tool emission instrumentation must land before this criterion is evaluable",
            measured=measured,
        )
    if coverage is not None and coverage >= 0.95:
        return CriterionResult(
            number=5,
            name="coverage_ratio",
            status="PASS",
            detail=f"coverage_ratio={coverage:.3f} ≥ 0.95",
            measured=measured,
        )
    return CriterionResult(
        number=5,
        name="coverage_ratio",
        status="FAIL",
        detail=f"coverage_ratio={coverage:.3f} < 0.95 — unintegrated callers exist",
        measured=measured,
    )


def _criterion_6_adversarial_bypass(cur, surface_kind: str, window_days: int) -> CriterionResult:
    """Adversarial-bypass cross-check: file-mtime delta vs lease-acquired window."""
    # The adversarial cross-check requires (a) a job that records file-mtime
    # observations and (b) reconciliation against lease-acquire windows.
    # No such pipeline is wired today; mark NOT_YET_EVALUABLE rather than
    # silently passing.
    cur.execute(
        """
        SELECT exists(
          SELECT 1 FROM information_schema.tables
          WHERE table_schema = 'lease_plane'
            AND table_name IN ('mtime_observations', 'bypass_observations')
        ) AS has_table
        """
    )
    if not cur.fetchone()["has_table"]:
        return CriterionResult(
            number=6,
            name="adversarial_bypass_check",
            status="NOT_YET_EVALUABLE",
            detail="mtime/bypass observation table not present; "
            "adversarial-bypass cross-check pipeline must land before this criterion is evaluable",
        )
    return CriterionResult(
        number=6,
        name="adversarial_bypass_check",
        status="NOT_YET_EVALUABLE",
        detail="observation table exists but reconciliation SQL pending — "
        "fill in canonical mtime/lease-window join when pipeline finalizes",
    )


def evaluate(surface_kind: str, window_days: int, db_url: str | None = None) -> EvaluationReport:
    if surface_kind not in KNOWN_SURFACE_KINDS:
        raise UnknownSurfaceKindError(
            f"unknown surface_kind '{surface_kind}'. "
            f"Known: {', '.join(KNOWN_SURFACE_KINDS)}"
        )
    with _conn(db_url) as conn:
        with conn.cursor() as raw_cur:
            cur = _DictCursor(raw_cur)
            criteria = [
                _criterion_1_advisory_window(cur, surface_kind, window_days),
                _criterion_2_uptime(cur, window_days),
                _criterion_3_type_a_signal(cur, surface_kind, window_days),
                _criterion_4_incident_linkage(cur, surface_kind, window_days),
                _criterion_5_coverage_ratio(cur, surface_kind, window_days),
                _criterion_6_adversarial_bypass(cur, surface_kind, window_days),
            ]
    promotable = all(c.status in {"PASS", "NOT_APPLICABLE"} for c in criteria)
    return EvaluationReport(
        surface_kind=surface_kind,
        window_days=window_days,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        criteria=criteria,
        promotable=promotable,
    )


def _format_text(report: EvaluationReport) -> str:
    lines = [
        f"Phase B promotion evaluation — surface_kind={report.surface_kind}",
        f"  window: {report.window_days} days",
        f"  evaluated_at: {report.evaluated_at}",
        "",
    ]
    for c in report.criteria:
        marker = {
            "PASS": "✓",
            "FAIL": "✗",
            "NOT_APPLICABLE": "—",
            "NOT_YET_EVALUABLE": "?",
        }.get(c.status, " ")
        lines.append(f"  {marker} (§6.1.{c.number}) {c.name}: {c.status}")
        lines.append(f"      {c.detail}")
        if c.measured:
            for k, v in c.measured.items():
                lines.append(f"      {k}: {v}")
        lines.append("")
    lines.append(f"VERDICT: {'PROMOTABLE' if report.promotable else 'NOT PROMOTABLE'}")
    return "\n".join(lines)


def _format_json(report: EvaluationReport) -> str:
    payload = asdict(report)
    payload["criteria"] = [asdict(c) for c in report.criteria]
    return json.dumps(payload, indent=2, default=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("surface_kind", help=f"one of: {', '.join(KNOWN_SURFACE_KINDS)}")
    parser.add_argument(
        "--window-days",
        type=int,
        default=14,
        help="advisory-mode window in days (default: 14, per §6.1.1)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument("--db-url", help="override DB_POSTGRES_URL")
    args = parser.parse_args(argv)

    try:
        report = evaluate(
            surface_kind=args.surface_kind,
            window_days=args.window_days,
            db_url=args.db_url,
        )
    except UnknownSurfaceKindError as e:
        print(str(e), file=sys.stderr)
        return 3
    except psycopg2.Error as e:
        print(f"db error: {e}", file=sys.stderr)
        return 2
    print(_format_json(report) if args.json else _format_text(report))
    return 0 if report.promotable else 1


if __name__ == "__main__":
    sys.exit(main())
