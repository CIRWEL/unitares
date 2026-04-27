"""Install-surface guardrail.

Asserts that operator-specific values (one operator's LAN IPs, Tailscale IPs,
personal domain, absolute home paths) do not re-enter the files called out
in docs/install/cross-machine-surface.md. When a new MUST-FIX entry is added
to that doc, add a corresponding assertion here so regressions fail pre-push
instead of shipping.

Intentionally scoped NARROWLY to specific files. A repo-wide grep would
false-positive on tests, fixtures, and the audit doc itself (which cites the
bad values as examples of what to remove).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _read(relpath: str) -> str:
    p = REPO / relpath
    assert p.exists(), f"install-surface: missing file {relpath}"
    return p.read_text()


# (relpath, pattern, rationale) — each lifted directly from
# docs/install/cross-machine-surface.md § MUST-FIX.
FORBIDDEN_IN_FILE = [
    (
        "scripts/ops/start_unitares.sh",
        r"192\.168\.1\.\d+|100\.96\.201\.46",
        "operator's LAN / Tailscale IP must not appear as a default allowlist entry",
    ),
    (
        "scripts/ops/start_unitares.sh",
        r"gov\.cirwel\.org",
        "operator's domain must not be baked in (use CLOUDFLARE_TUNNEL_HOSTNAME)",
    ),
    (
        "scripts/ops/start_server.sh",
        r"gov\.cirwel\.org",
        "operator's domain must not appear in example strings",
    ),
    (
        "requirements-core.txt",
        r"gov\.cirwel\.org",
        "operator's domain must not appear in install comments",
    ),
    (
        "scripts/ops/com.unitares.ipv6-loopback-proxy.plist.template",
        r"/Users/[a-zA-Z0-9_-]+/projects/unitares",
        "plist template must use __UNITARES_ROOT__ placeholder",
    ),
]


@pytest.mark.parametrize("relpath,pattern,rationale", FORBIDDEN_IN_FILE)
def test_no_operator_specific_defaults(relpath: str, pattern: str, rationale: str) -> None:
    content = _read(relpath)
    matches = re.findall(pattern, content)
    assert not matches, (
        f"{rationale}\n"
        f"  file:     {relpath}\n"
        f"  matches:  {matches}\n"
        f"  see:      docs/install/cross-machine-surface.md"
    )


# Plist templates must use placeholder substitution, not live paths.
PLIST_TEMPLATES = [
    "scripts/ops/com.unitares.sentinel.plist.template",
    "scripts/ops/com.unitares.vigil.plist.template",
    "scripts/ops/com.unitares.gateway-mcp.plist.template",
    "scripts/ops/com.unitares.governance-backup.plist.template",
    "scripts/ops/com.unitares.ipv6-loopback-proxy.plist.template",
    "scripts/ops/com.unitares.chronicler.plist.template",
]


@pytest.mark.parametrize("relpath", PLIST_TEMPLATES)
def test_plist_template_uses_placeholders(relpath: str) -> None:
    content = _read(relpath)
    # Allow /Users/ inside HTML comments (for example "verify with" blocks)
    # but not inside <string> values.
    string_values = re.findall(r"<string>([^<]*)</string>", content)
    for value in string_values:
        assert "/Users/" not in value, (
            f"plist template has hardcoded /Users/ path in <string>: {value!r}\n"
            f"  file: {relpath}\n"
            f"  use __UNITARES_ROOT__ / __HOME__ placeholders instead"
        )
    # Must reference at least one placeholder — otherwise it's not a template.
    assert "__UNITARES_ROOT__" in content or "__HOME__" in content, (
        f"plist template has no __UNITARES_ROOT__ or __HOME__ placeholder: {relpath}"
    )
