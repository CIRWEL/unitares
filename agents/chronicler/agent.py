#!/usr/bin/env python3
"""Chronicler — daily scraper of fleet metrics into `metrics.series`.

Intentionally lightweight: one-shot invocation (launchd drives cadence),
no own identity, no EISV check-ins. Runs each scraper in `scrapers.py`,
POSTs the value to the governance server, emits a `.error` metric on
failure so silent breakage stays visible.

Environment:
    UNITARES_METRICS_URL        base URL (default http://127.0.0.1:8767)
    UNITARES_HTTP_API_TOKEN     bearer token; optional if running locally
                                (trusted-network bypass handles 127.0.0.1)
    CHRONICLER_REPO_ROOT        repo to scrape (default: working directory)

Usage:
    python3 agents/chronicler/agent.py          # run all scrapers once
    python3 agents/chronicler/agent.py --dry    # no POSTs, print to stdout
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx

# Make sibling package importable when invoked via launchd (no sys.path magic
# otherwise; the launchd plist sets PYTHONPATH to the repo root).
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agents.chronicler.scrapers import SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s chronicler: %(message)s",
)
log = logging.getLogger("chronicler")


DEFAULT_URL = "http://127.0.0.1:8767"


def post_metric(
    client: httpx.Client,
    base_url: str,
    token: str | None,
    name: str,
    value: float,
) -> None:
    """POST one `(name, value)` point. Raises on HTTP error."""
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    resp = client.post(
        f"{base_url}/v1/metrics",
        headers=headers,
        content=json.dumps({"name": name, "value": value}),
        timeout=10.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"POST /v1/metrics failed for {name}: "
            f"{resp.status_code} {resp.text[:200]}"
        )


def run(
    base_url: str,
    token: str | None,
    repo_root: Path,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Run every registered scraper. Returns (successes, failures)."""
    successes = 0
    failures = 0

    with httpx.Client() as client:
        for name, scraper in sorted(SCRAPERS.items()):
            try:
                value = float(scraper(repo_root))
            except Exception as exc:
                failures += 1
                log.warning("scraper %s failed: %s", name, exc)
                if not dry_run:
                    # Best-effort: the error metric may itself fail if the
                    # server is unreachable; swallow silently in that case,
                    # there's nothing useful to do with the inner error.
                    try:
                        post_metric(client, base_url, token, f"{name}.error", 1.0)
                    except Exception as inner:
                        log.warning("could not post error metric for %s: %s", name, inner)
                continue

            if dry_run:
                log.info("DRY %s = %s", name, value)
                successes += 1
                continue

            try:
                post_metric(client, base_url, token, name, value)
                successes += 1
                log.info("recorded %s = %s", name, value)
            except Exception as exc:
                failures += 1
                log.warning("could not post %s: %s", name, exc)

    return successes, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chronicler metrics scraper.")
    parser.add_argument("--dry", action="store_true", help="print metrics without posting")
    args = parser.parse_args(argv)

    base_url = os.environ.get("UNITARES_METRICS_URL", DEFAULT_URL).rstrip("/")
    token = os.environ.get("UNITARES_HTTP_API_TOKEN") or None
    repo_root = Path(os.environ.get("CHRONICLER_REPO_ROOT", os.getcwd())).resolve()

    log.info("chronicler start: url=%s repo=%s scrapers=%d", base_url, repo_root, len(SCRAPERS))
    successes, failures = run(base_url, token, repo_root, dry_run=args.dry)
    log.info("chronicler done: success=%d fail=%d", successes, failures)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
