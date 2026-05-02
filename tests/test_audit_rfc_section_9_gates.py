"""Tests for `scripts/dev/audit_rfc_section_9_gates.py`.

The audit script is the architect-recommended starting move for §9
reconciliation. The reconciliation work itself depends on the audit being
trustworthy, so the parser/classifier carries its own regression tests.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts/dev/audit_rfc_section_9_gates.py"


@pytest.fixture(scope="module")
def audit_module():
    spec = importlib.util.spec_from_file_location("audit_rfc_section_9_gates", SCRIPT_PATH)
    assert spec and spec.loader, "could not load audit script as module"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --- find_section_9 --------------------------------------------------------


def test_find_section_9_extracts_only_section_9(audit_module):
    text = (
        "## 8. Other section\n"
        "irrelevant\n"
        "## 9. Pre-implementation checklist\n"
        "the meat\n"
        "Test name: `test_a`.\n"
        "## 10. Runway tradeoff\n"
        "after the cut\n"
    )
    section = audit_module.find_section_9(text)
    assert "the meat" in section
    assert "after the cut" not in section
    assert "irrelevant" not in section


def test_find_section_9_raises_when_missing(audit_module):
    with pytest.raises(SystemExit):
        audit_module.find_section_9("no section nine here")


# --- parse_gates -----------------------------------------------------------


def test_parse_gates_single_python_test_name(audit_module):
    section = "- [ ] **§7.2** — desc. Test name: `test_alpha_one`."
    py, elx = audit_module.parse_gates(section)
    assert py == ["test_alpha_one"]
    assert elx == []


def test_parse_gates_multiple_python_test_names(audit_module):
    section = (
        "- [ ] **§7.3** — desc. Test names: `test_a`, `test_b`, `test_c` (post-removal)."
    )
    py, elx = audit_module.parse_gates(section)
    assert py == ["test_a", "test_b", "test_c"]
    assert elx == []


def test_parse_gates_elixir_test_names(audit_module):
    section = (
        "- [ ] **§7.3.5** — desc. Test names (Elixir-side): "
        "`test http_router returns 409 on held_by_other`, "
        "`test http_router returns 200 on permission_denied`."
    )
    py, elx = audit_module.parse_gates(section)
    assert py == []
    assert elx == [
        "test http_router returns 409 on held_by_other",
        "test http_router returns 200 on permission_denied",
    ]


def test_parse_gates_dedupes_repeated_names(audit_module):
    section = (
        "- [ ] **§A** — desc. Test name: `test_dup`.\n"
        "- [ ] **§B** — desc. Test name: `test_dup`."
    )
    py, _ = audit_module.parse_gates(section)
    assert py == ["test_dup"]


def test_parse_gates_ignores_lines_without_test_name(audit_module):
    section = (
        "- [x] Council pass: dialectic — v0.8\n"
        "- [ ] **§A** — desc. Test name: `test_only_this_one`."
    )
    py, _ = audit_module.parse_gates(section)
    assert py == ["test_only_this_one"]


# --- collect_python_tests / collect_elixir_tests ---------------------------


def test_collect_python_tests_finds_async_and_sync_defs(audit_module, tmp_path):
    f = tmp_path / "test_demo.py"
    f.write_text(
        "def test_sync_one():\n"
        "    pass\n"
        "\n"
        "async def test_async_two():\n"
        "    pass\n"
        "\n"
        "def helper_not_a_test():\n"
        "    pass\n"
    )
    found = audit_module.collect_python_tests([tmp_path])
    assert set(found.keys()) == {"test_sync_one", "test_async_two"}
    assert found["test_sync_one"] == f


def test_collect_elixir_tests_extracts_quoted_descriptions(audit_module, tmp_path):
    f = tmp_path / "demo_test.exs"
    f.write_text(
        'defmodule Demo do\n'
        '  use ExUnit.Case\n'
        '  test "router returns 409" do\n'
        '    :ok\n'
        '  end\n'
        '\n'
        '  test "router accepts 200" do\n'
        '    :ok\n'
        '  end\n'
        'end\n'
    )
    found = audit_module.collect_elixir_tests([tmp_path])
    assert set(found.keys()) == {"test router returns 409", "test router accepts 200"}


# --- classify --------------------------------------------------------------


def test_classify_exact_match(audit_module, tmp_path):
    found = {"test_foo_bar": tmp_path / "tests/test_x.py"}
    status, evidence = audit_module.classify("test_foo_bar", found)
    assert status == "exact"
    assert "test_x.py" in evidence


def test_classify_variant_above_threshold(audit_module, tmp_path):
    # Both names share most tokens — difflib ratio comfortably above 0.75.
    found = {"test_acquire_with_retry_jittered_backoff_within_bounds": tmp_path / "x.py"}
    status, evidence = audit_module.classify(
        "test_acquire_with_retry_jittered_backoff", found
    )
    assert status == "variant"
    assert "within_bounds" in evidence
    assert "ratio" in evidence


def test_classify_missing_when_no_close_match(audit_module, tmp_path):
    found = {"test_completely_different_subject": tmp_path / "x.py"}
    status, evidence = audit_module.classify("test_phase_zero_acquire_race_blocked", found)
    assert status == "missing"
    assert evidence == ""


# --- audit() end-to-end on the live RFC -----------------------------------


def test_audit_runs_against_live_rfc_and_returns_rows(audit_module):
    """Smoke test — make sure the audit doesn't crash on the real RFC and
    that every row has the four expected keys."""
    rows = audit_module.audit()
    assert rows, "expected at least one §9 named gate"
    expected_keys = {"lang", "gate", "status", "evidence"}
    assert all(set(r) == expected_keys for r in rows)
    statuses = {r["status"] for r in rows}
    assert statuses <= {"exact", "variant", "missing"}
