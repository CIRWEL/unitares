#!/usr/bin/env bash
# Check skill freshness against source file modification times.
# Exit 0 if all fresh, exit 1 if any stale. Suitable as pre-commit hook.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECTS_ROOT="${UNITARES_PROJECTS_ROOT:-$(cd "${PLUGIN_ROOT}/.." && pwd)}"

exec python3 "${SCRIPT_DIR}/_check_freshness.py" "${PLUGIN_ROOT}" "${PROJECTS_ROOT}"
