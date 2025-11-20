#!/bin/bash
# File Protection Script
# Makes critical files read-only to prevent accidental deletion

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "🔒 File Protection Script"
echo "========================"
echo ""

# Function to make files read-only
protect_files() {
    echo "Making source files read-only..."
    find src -name "*.py" -exec chmod a-w {} \;
    find config -name "*.py" -exec chmod a-w {} \;
    echo "✅ Source files protected (read-only)"
}

# Function to make files writable
unprotect_files() {
    echo "Restoring write permissions..."
    find src -name "*.py" -exec chmod u+w {} \;
    find config -name "*.py" -exec chmod u+w {} \;
    echo "✅ Write permissions restored"
}

# Function to show protection status
show_status() {
    echo "Protection Status:"
    echo ""
    echo "Source files (src/):"
    ls -l src/*.py | head -5
    echo ""
    echo "Config files (config/):"
    ls -l config/*.py
}

# Parse command
case "${1:-}" in
    protect)
        protect_files
        ;;
    unprotect)
        unprotect_files
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {protect|unprotect|status}"
        echo ""
        echo "Commands:"
        echo "  protect    - Make all .py files read-only"
        echo "  unprotect  - Restore write permissions"
        echo "  status     - Show current protection status"
        echo ""
        echo "Example workflow:"
        echo "  $0 protect        # Before agent session"
        echo "  # ... agent works ..."
        echo "  $0 unprotect      # After agent session"
        exit 1
        ;;
esac
