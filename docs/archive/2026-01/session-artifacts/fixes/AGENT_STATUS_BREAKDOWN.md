# Agent Status Breakdown Explanation

**Created:** January 2, 2026  
**Last Updated:** January 2, 2026  
**Status:** Analysis

---

## Current Situation

**Dashboard shows:**
- Total: 719 agents (excluding test agents)
- Active: 2
- Archived: 48
- Waiting Input: 0
- Paused: 0
- Deleted: 0
- **Unaccounted: 669 agents**

## The Problem

The 669 "unaccounted" agents are agents that:
1. **Don't have a recognized status** - Their `meta.status` is not one of: `active`, `waiting_input`, `paused`, `archived`, `deleted`
2. **May have `None` status** - Created but never had status set
3. **May have empty string `""` status** - Status was cleared/reset
4. **May have other values** - Legacy status values or corrupted data

## Why This Happens

Agents are created with `status="active"` by default, but:
- Older agents may have been created before status tracking
- Agents may have had status cleared/reset
- Database migrations may have left some agents without status
- Test agents (filtered out) may have different status patterns

## Solution Options

### Option 1: Default Missing Status to "active"
Treat agents with `None` or unrecognized status as "active"

### Option 2: Add "unknown" Status Category
Create a new status category for agents without recognized status

### Option 3: Clean Up Old Agents
Archive or delete agents with missing status if they're old/inactive

### Option 4: Migration Script
Run a migration to set default status for all agents without status

---

## Recommendation

**Option 1 + Option 4**: 
- Add "unknown" status to the breakdown
- Show it in dashboard
- Provide migration tool to fix old agents

---

**Status:** Needs implementation

