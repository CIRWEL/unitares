#!/bin/bash
# Pre-commit hook for documentation validation
# - Prevents markdown proliferation
# - Validates tool count synchronization
# - Checks version consistency
# Usage: Add to .git/hooks/pre-commit or run manually before committing

# Tool count validation
echo "🔍 Checking tool count synchronization..."
if ! python3 scripts/update_docs_tool_count.py --check > /dev/null 2>&1; then
    echo "❌ Tool count mismatch detected!"
    python3 scripts/update_docs_tool_count.py --check
    echo ""
    echo "Fix: python3 scripts/update_docs_tool_count.py --update"
    exit 1
fi
echo "✅ Tool count in sync"

# Version validation
echo "🔍 Checking version consistency..."
if ! python3 scripts/version_manager.py --check > /dev/null 2>&1; then
    echo "❌ Version mismatch detected!"
    python3 scripts/version_manager.py --check
    echo ""
    echo "Fix: python3 scripts/version_manager.py --update"
    exit 1
fi
echo "✅ Version consistent"

# Markdown proliferation check
echo "🔍 Checking for new markdown files..."

NEW_MARKDOWN_FILES=$(git diff --cached --name-only --diff-filter=A | grep '\.md$')

if [ -z "$NEW_MARKDOWN_FILES" ]; then
    echo "✅ No new markdown files"
    exit 0
fi

VIOLATIONS=0

for file in $NEW_MARKDOWN_FILES; do
    # Skip approved files
    if [[ "$file" == "README.md" ]] || \
       [[ "$file" == "CHANGELOG.md" ]] || \
       [[ "$file" == "tools/README.md" ]] || \
       [[ "$file" == "docs/README.md" ]] || \
       [[ "$file" == "docs/QUICK_REFERENCE.md" ]] || \
       [[ "$file" == "docs/DOC_MAP.md" ]] || \
       [[ "$file" == "docs/DOCUMENTATION_GUIDELINES.md" ]] || \
       [[ "$file" == "docs/MARKDOWN_PROLIFERATION_POLICY.md" ]] || \
       [[ "$file" == docs/guides/*.md ]] || \
       [[ "$file" == docs/architecture/*.md ]]; then
        echo "✅ $file - Approved file"
        continue
    fi
    
    # Check file size
    WORD_COUNT=$(wc -w < "$file" 2>/dev/null || echo "0")
    
    if [ "$WORD_COUNT" -lt 500 ]; then
        echo "❌ $file - Too small ($WORD_COUNT words, need 500+)"
        echo "   → Consolidate into existing doc or use knowledge graph"
        VIOLATIONS=$((VIOLATIONS + 1))
    elif [ "$WORD_COUNT" -lt 1000 ]; then
        echo "⚠️  $file - Small ($WORD_COUNT words, recommend 1000+)"
        echo "   → Consider consolidating into existing doc"
    else
        echo "✅ $file - Size OK ($WORD_COUNT words)"
    fi
    
    # Check if it's a fix summary (should go in FIXES_LOG.md)
    if [[ "$file" == docs/fixes/*.md ]] && [[ "$file" != "docs/fixes/FIXES_LOG.md" ]]; then
        echo "❌ $file - Fix summary should go in docs/fixes/FIXES_LOG.md"
        VIOLATIONS=$((VIOLATIONS + 1))
    fi
    
    # Check if it's a small analysis (should consolidate)
    if [[ "$file" == docs/analysis/*.md ]] && [ "$WORD_COUNT" -lt 1000 ]; then
        echo "⚠️  $file - Small analysis, consider consolidating"
    fi
done

if [ $VIOLATIONS -gt 0 ]; then
    echo ""
    echo "❌ Found $VIOLATIONS markdown policy violations"
    echo "See docs/MARKDOWN_PROLIFERATION_POLICY.md for guidelines"
    echo ""
    echo "Alternatives:"
    echo "  - Consolidate into existing docs"
    echo "  - Use knowledge graph: store_knowledge_graph()"
    echo "  - Use agent metadata: update_agent_metadata(notes=...)"
    echo ""
    exit 1
fi

echo "✅ All markdown files comply with policy"
exit 0

