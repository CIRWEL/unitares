# ROI Metrics Tool

**Created:** December 30, 2025  
**Last Updated:** December 30, 2025  
**Status:** Active

---

## Overview

The `get_roi_metrics` tool calculates value delivered by multi-agent coordination, helping customers justify pricing and track ROI.

## Features

### Time Saved Calculator
- Estimates time saved from preventing duplicate work
- Based on discovery relationships (`related_to` field)
- Assumes 0.5 hours per duplicate prevented (conservative)
- Includes: discovery time + implementation + testing

### Coordination Efficiency Score
- Measures how well agents coordinate and share knowledge
- Range: 0.0 (no coordination) to 1.0 (perfect coordination)
- Formula:
  - Base: 0.5 (some coordination happening)
  - +0.2 if cross-agent sharing > 20% of discoveries
  - +0.2 if multiple agents contributing
  - +0.1 if total discoveries > 10 (active knowledge graph)

### Knowledge Sharing Metrics
- Total discoveries in knowledge graph
- Unique agents contributing
- Average discoveries per agent

### Cost Savings Estimate
- Calculates cost savings based on time saved
- Default: $100/hour developer rate
- Customizable via `hourly_rate` parameter

## Usage

### Basic Usage

```json
{
  "hourly_rate": 100
}
```

### Response Format

```json
{
  "success": true,
  "time_saved": {
    "hours": 12.5,
    "days": 1.56,
    "description": "Estimated time saved from preventing 25 duplicate work items"
  },
  "duplicates_prevented": 25,
  "coordination_efficiency": {
    "score": 0.85,
    "percentage": 85.0,
    "description": "Measures how well agents coordinate and share knowledge"
  },
  "knowledge_sharing": {
    "total_discoveries": 150,
    "unique_agents_contributing": 12,
    "avg_discoveries_per_agent": 12.5
  },
  "cost_savings": {
    "estimated_usd": 1250.0,
    "hourly_rate_used": 100,
    "description": "Estimated cost savings at $100/hour developer rate"
  },
  "system_health": {
    "total_agents": 50,
    "active_agents": 12,
    "coordination_active": true
  }
}
```

## Calculation Methods

### Duplicates Prevented
- **Method**: Count discoveries with `related_to` relationships
- **Rationale**: If a discovery links to similar work, it means the agent found existing work before starting
- **Fallback**: If relationship data unavailable, estimate 20% of total discoveries

### Time Saved
- **Per duplicate**: 0.5 hours (conservative)
- **Includes**: Discovery time + implementation + testing
- **Formula**: `duplicates_prevented × 0.5 hours`

### Coordination Efficiency
- **Base score**: 0.5 (assumes some coordination)
- **Sharing bonus**: +0.2 if >20% of discoveries have cross-agent relationships
- **Multi-agent bonus**: +0.2 if multiple agents contributing
- **Activity bonus**: +0.1 if knowledge graph has >10 discoveries

### Cost Savings
- **Formula**: `time_saved_hours × hourly_rate`
- **Default rate**: $100/hour
- **Customizable**: Pass `hourly_rate` parameter

## Use Cases

1. **Customer Value Demonstration**
   - Show ROI to justify pricing
   - Track value over time
   - Compare coordination efficiency across deployments

2. **System Health Monitoring**
   - Monitor coordination effectiveness
   - Identify when knowledge sharing improves
   - Track agent collaboration patterns

3. **Pricing Justification**
   - Calculate cost savings vs. license cost
   - Show time saved per agent
   - Demonstrate coordination value

## Related Tools

- `aggregate_metrics()` - Fleet-wide health overview
- `get_telemetry_metrics()` - System telemetry
- `list_knowledge_graph()` - Knowledge graph stats
- `search_knowledge_graph()` - Find discoveries

## Implementation Notes

- Uses knowledge graph `query()` method for fast lookups
- Samples first 100 discoveries for efficiency
- Handles missing data gracefully with fallbacks
- Non-blocking async operations

---

**Status:** Ready for Production

