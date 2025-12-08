#!/bin/bash
# Pre-commit hook: Verify tool count in documentation matches reality
#
# Add to .git/hooks/pre-commit:
#   ./scripts/pre_commit_tool_count_check.sh || exit 1

set -e

cd "$(git rev-parse --show-toplevel)"

echo "🔍 Checking tool count synchronization..."

# Run the check
if python3 scripts/update_docs_tool_count.py --check > /dev/null 2>&1; then
    echo "✅ Tool count in sync"
    exit 0
else
    echo ""
    echo "❌ Tool count mismatch detected!"
    echo ""
    python3 scripts/update_docs_tool_count.py --check
    echo ""
    echo "Fix options:"
    echo "  1. Run: python3 scripts/update_docs_tool_count.py --update"
    echo "  2. Or manually update the documentation"
    echo ""
    exit 1
fi
