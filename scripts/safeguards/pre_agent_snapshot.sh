#!/bin/bash
# Pre-Agent Snapshot Script
# Creates a git snapshot before letting an agent modify files

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "📸 Pre-Agent Snapshot Script"
echo "============================"
echo ""

# Check if git is initialized
if [ ! -d .git ]; then
    echo "❌ Error: Git repository not initialized"
    echo "Run: git init"
    exit 1
fi

# Get agent description
AGENT_DESC="${1:-unknown-agent}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
TAG_NAME="pre-agent-${TIMESTAMP}"

echo "Agent: $AGENT_DESC"
echo "Timestamp: $TIMESTAMP"
echo ""

# Stage all changes
echo "Staging current state..."
git add .

# Check if there are changes to commit
if git diff --cached --quiet; then
    echo "ℹ️  No changes to commit (working directory clean)"
else
    # Commit changes
    echo "Creating snapshot commit..."
    git commit -m "Pre-agent snapshot: $AGENT_DESC

Timestamp: $TIMESTAMP
Purpose: Backup before agent session

This commit can be used to restore state if agent causes issues."
    
    echo "✅ Snapshot commit created"
fi

# Create tag
echo "Creating tag: $TAG_NAME"
git tag "$TAG_NAME"

echo ""
echo "✅ Pre-agent snapshot complete!"
echo ""
echo "Recovery commands:"
echo "  View tags:     git tag -l 'pre-agent-*'"
echo "  Restore state: git reset --hard $TAG_NAME"
echo "  Compare:       git diff $TAG_NAME"
echo ""
