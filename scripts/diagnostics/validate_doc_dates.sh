#!/bin/bash
# Documentation Date Validator
# Checks for outdated year references in documentation

PROJECT_DIR="/Users/cirwel/projects/governance-mcp-v1"
cd "$PROJECT_DIR" || exit 1

CURRENT_YEAR=$(date +%Y)
PREVIOUS_YEAR=$((CURRENT_YEAR - 1))

echo "📅 Documentation Date Validator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Current year: $CURRENT_YEAR"
echo "Checking for: $PREVIOUS_YEAR (outdated)"
echo ""

FOUND_ISSUES=0

# Check markdown files
echo "📄 Checking markdown files..."
while IFS= read -r file; do
    if grep -q "$PREVIOUS_YEAR" "$file"; then
        FOUND_ISSUES=$((FOUND_ISSUES + 1))
        echo "  ⚠️  $file"
        grep -n "$PREVIOUS_YEAR" "$file" | head -3 | while read -r line; do
            echo "      $line"
        done
    fi
done < <(find . -name "*.md" \
    -not -path "./.git/*" \
    -not -path "./node_modules/*" \
    -not -path "./__pycache__/*")

# Check Python files for date-related comments
echo ""
echo "🐍 Checking Python files..."
while IFS= read -r file; do
    # Look for comments with dates
    if grep -E "#.*$PREVIOUS_YEAR" "$file" > /dev/null; then
        matches=$(grep -c -E "#.*$PREVIOUS_YEAR" "$file")
        if [ "$matches" -gt 0 ]; then
            FOUND_ISSUES=$((FOUND_ISSUES + 1))
            echo "  ⚠️  $file ($matches occurrences)"
            grep -n -E "#.*$PREVIOUS_YEAR" "$file" | head -2 | while read -r line; do
                echo "      $line"
            done
        fi
    fi
done < <(find . -name "*.py" \
    -not -path "./.git/*" \
    -not -path "./node_modules/*" \
    -not -path "./__pycache__/*" \
    -not -path "./venv/*")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$FOUND_ISSUES" -eq 0 ]; then
    echo "✅ No outdated dates found!"
    echo ""
    echo "All documentation appears to have current dates."
    exit 0
else
    echo "❌ Found $FOUND_ISSUES file(s) with potentially outdated dates"
    echo ""
    echo "Action needed:"
    echo "  1. Review each file"
    echo "  2. Update $PREVIOUS_YEAR → $CURRENT_YEAR where appropriate"
    echo "  3. Re-run this script to verify"
    echo ""
    echo "Note: Historical references to $PREVIOUS_YEAR may be intentional."
    echo "Use judgment to determine if updates are needed."
    exit 1
fi
