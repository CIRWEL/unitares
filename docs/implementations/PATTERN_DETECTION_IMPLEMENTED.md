# Pattern Detection Implementation

**Created:** January 4, 2026  
**Last Updated:** January 4, 2026  
**Status:** Active

---

## Overview

Implemented comprehensive pattern detection to address the real problem: **cognitive loops** (agents stuck in unproductive patterns, not crashes).

## Problem Solved

**What actually happened:**
- Agent was responsive (metrics worked fine)
- Stuck in cognitive loop (grep → read → grep → read...)
- Making progress on wrong thing
- Human had to press stop (circuit breaker)

**What the code solves:**
- ✅ Loop detection: "You've grepped for similar patterns 3 times"
- ✅ Time-boxing: "10 min investigating without progress → try different approach"
- ✅ Hypothesis tracking: "You edited code, test if it's loaded before debugging further"
- ✅ Crash detection: Still handles unresponsive agents (useful for actual crashes)

## Components

### 1. Pattern Tracker (`src/pattern_tracker.py`)

Core pattern detection engine:

- **ToolCallPattern**: Tracks tool calls with normalized args (ignores timestamps, IDs)
- **InvestigationSession**: Tracks investigation time and progress
- **Hypothesis**: Tracks code changes that need testing

**Features:**
- Loop detection: Same tool + similar args within window (default: 3 calls in 30 min)
- Time-boxing: Max investigation time without progress (default: 10 min)
- Hypothesis tracking: Untested code changes (default: 5 min warning)

### 2. Pattern Helpers (`src/mcp_handlers/pattern_helpers.py`)

Integration helpers:

- **detect_code_changes()**: Detects code modification tools (search_replace, write, edit_notebook)
- **record_hypothesis_if_needed()**: Records code changes as hypotheses
- **check_untested_hypotheses()**: Warns if hypotheses untested > 5 min
- **mark_hypothesis_tested()**: Marks hypotheses as tested when testing tools are called

### 3. Integration Points

**Tool Dispatch (`src/mcp_handlers/__init__.py`):**
- Records every tool call for loop detection
- Detects code changes → records as hypotheses
- Checks for untested hypotheses → warns
- Marks hypotheses as tested when testing tools called
- Records progress → resets time-boxing timer

**Stuck Agent Detection (`src/mcp_handlers/lifecycle.py`):**
- Integrates pattern detection into `_detect_stuck_agents()`
- Detects `cognitive_loop` and `time_box_exceeded` patterns
- Adds pattern-based stuck detection alongside margin-based detection

## Detection Rules

### Loop Detection
- **Trigger**: Same tool + similar args called 3+ times in 30 minutes
- **Action**: Log warning, mark as stuck (cognitive_loop)
- **Message**: "You've called {tool} with similar arguments {count} times. Consider trying a different approach."

### Time-Boxing
- **Trigger**: Investigation session > 10 minutes without progress
- **Action**: Log warning, mark as stuck (time_box_exceeded)
- **Message**: "You've been investigating for {total} minutes without progress. Consider trying a different approach or escalating."

### Hypothesis Tracking
- **Trigger**: Code changes made but not tested > 5 minutes
- **Action**: Log warning (doesn't mark as stuck, just prompts)
- **Message**: "You made {change_type} changes {age} minutes ago but haven't tested them. Test your changes before continuing."

## Usage

### Automatic (Built-in)
Pattern detection runs automatically on every tool call:
- Loop detection: Checks for repeated patterns
- Code change detection: Records hypotheses
- Testing detection: Marks hypotheses as tested
- Progress tracking: Resets time-boxing timer

### Manual (For Testing)
```python
from src.pattern_tracker import get_pattern_tracker

tracker = get_pattern_tracker()

# Start investigation
tracker.start_investigation(agent_id, problem_description="Debugging issue")

# Record tool calls (automatic via dispatch_tool)
# ...

# Check patterns
patterns = tracker.get_patterns(agent_id)
```

## Configuration

Default thresholds (can be adjusted):
- **Loop threshold**: 3 similar calls
- **Loop window**: 30 minutes
- **Time-box limit**: 10 minutes without progress
- **Hypothesis warning**: 5 minutes untested

## Benefits

1. **Catches real problem**: Detects cognitive loops, not just crashes
2. **Proactive**: Warns before agent gets truly stuck
3. **Non-blocking**: Warnings don't stop tool calls (just logs)
4. **Actionable**: Clear messages guide agent behavior
5. **Comprehensive**: Handles loops, time-boxing, and hypothesis tracking

## Future Enhancements

- [ ] Pattern learning: Learn which patterns lead to success
- [ ] Adaptive thresholds: Adjust based on agent behavior
- [ ] Pattern suggestions: Suggest alternative approaches
- [ ] Cross-agent patterns: Detect patterns across multiple agents

---

## Related Files

- `src/pattern_tracker.py` - Core pattern detection
- `src/mcp_handlers/pattern_helpers.py` - Integration helpers
- `src/mcp_handlers/lifecycle.py` - Stuck agent detection integration
- `src/mcp_handlers/__init__.py` - Tool dispatch integration

