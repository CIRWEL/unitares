"""Pins the dashboard static-file allowlist against silent regression.

Each JS module listed in dashboard/index.html's <script src> tags must be
in the allowlist, else the browser gets a 404 and the feature silently
breaks (seen with fleet-metrics.js on initial ship). This test reads the
HTML, pulls every /dashboard/*.js reference, and asserts each one is
allowed.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest


def _load_allowlist() -> list[str]:
    """Extract the `allowed_files` list from http_dashboard_static's source.

    We parse the source instead of calling the function because extracting
    the list is structurally simpler than constructing a Starlette request
    and inspecting the mocked response — and parsing is exactly what
    regressions would fool.
    """
    from src.http_api import http_dashboard_static

    src = inspect.getsource(http_dashboard_static)
    # Find the assignment block `allowed_files = [ ... ]`
    match = re.search(r"allowed_files\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert match, "http_dashboard_static no longer defines `allowed_files = [...]`"
    body = match.group(1)
    # Extract quoted strings inside the list
    return re.findall(r'"([^"]+)"', body)


def _scripts_referenced_by_index_html() -> list[str]:
    """Return every basename referenced via /dashboard/... in index.html."""
    html_path = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"
    text = html_path.read_text()
    # Match href or src attributes pointing at /dashboard/<file>
    hits = re.findall(r'(?:href|src)="/dashboard/([^"?]+)"', text)
    return sorted(set(hits))


class TestDashboardStaticAllowlist:
    def test_fleet_metrics_is_allowed(self):
        assert "fleet-metrics.js" in _load_allowlist()

    def test_sentinel_is_allowed(self):
        assert "sentinel.js" in _load_allowlist()

    def test_vigil_is_allowed(self):
        assert "vigil.js" in _load_allowlist()

    def test_every_index_html_reference_is_allowed(self):
        referenced = _scripts_referenced_by_index_html()
        allowed = set(_load_allowlist())
        missing = [f for f in referenced if f not in allowed]
        assert missing == [], (
            f"These files are referenced in dashboard/index.html but missing from "
            f"http_dashboard_static's allowlist — browser will 404 them silently: {missing}"
        )
