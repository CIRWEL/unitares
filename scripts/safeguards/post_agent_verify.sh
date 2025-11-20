#!/bin/bash
# Post-Agent Verification Script
# Checks for suspicious changes after agent session

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "🔍 Post-Agent Verification Script"
echo "================================="
echo ""

# Check git status
echo "Checking for changes..."
echo ""

if git diff --quiet && git diff --cached --quiet; then
    echo "✅ No changes detected"
    exit 0
fi

# Show what changed
echo "📝 Changed files:"
git status --short
echo ""

# Check for deletions
DELETIONS=$(git status --short | grep "^ D" | wc -l | xargs)

if [ "$DELETIONS" -gt 0 ]; then
    echo "⚠️  WARNING: $DELETIONS file(s) deleted!"
    echo ""
    echo "Deleted files:"
    git status --short | grep "^ D"
    echo ""
    echo "To restore deleted files:"
    echo "  git checkout -- <file>"
    echo "  or"
    echo "  git reset --hard HEAD  # Restore everything"
    echo ""
fi

# Show diff summary
echo "Change summary:"
git diff --stat
echo ""

# Ask user what to do
echo "What would you like to do?"
echo "  1) Review changes (git diff)"
echo "  2) Commit changes"
echo "  3) Discard all changes (restore previous state)"
echo "  4) Exit (do nothing)"
echo ""
read -p "Choice (1-4): " choice

case $choice in
    1)
        git diff
        ;;
    2)
        read -p "Commit message: " msg
        git add .
        git commit -m "$msg"
        echo "✅ Changes committed"
        ;;
    3)
        git reset --hard HEAD
        git clean -fd
        echo "✅ All changes discarded"
        ;;
    4)
        echo "Exiting..."
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac
