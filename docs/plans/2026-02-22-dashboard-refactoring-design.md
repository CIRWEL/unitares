# Dashboard Refactoring Design

**Date:** 2026-02-22
**Status:** Approved
**Approach:** Full Quality Pass (zero-build)

---

## Overview

Comprehensive refactoring of the UNITARES governance dashboard to improve maintainability, performance, and accessibility while preserving the zero-build architecture.

## Current State

| File | Lines | Size |
|------|-------|------|
| dashboard.js | 3309 | 142KB |
| styles.css | 3132 | 66KB |
| utils.js | 669 | 22KB |
| components.js | 215 | 8KB |
| index.html | 354 | 18KB |

**Issues identified:**
- 4 of 5 classes in components.js are dead code (MetricTooltip, StatCard, AnimaGauge, EnvironmentalCard)
- Magic numbers scattered throughout dashboard.js
- Search inputs lack debouncing (causes excessive filtering on each keystroke)
- Duplicate event listener on discovery search (lines 1638 and 1640)
- CSS has repeated color values that should be variables
- No ARIA labels or keyboard navigation for interactive elements
- EISV charts update frequently - potential performance concern

---

## Design

### 1. Dead Code Removal

**components.js** - Remove unused classes:
- `MetricTooltip` (0 uses) - lines 55-103
- `StatCard` (0 uses) - lines 105-136
- `AnimaGauge` (0 uses) - lines 138-177
- `EnvironmentalCard` (0 uses) - lines 179-206

Keep only `LoadingSkeleton` (2 uses in dashboard.js).

**Result:** ~160 lines removed, file reduced to ~55 lines.

### 2. Configuration Extraction

Add CONFIG object at top of dashboard.js:

```javascript
const CONFIG = {
    // Timing
    REFRESH_INTERVAL_MS: 30000,
    COPY_FEEDBACK_MS: 1500,
    SCROLL_FEEDBACK_MS: 2000,
    DEBOUNCE_MS: 250,

    // Time ranges (ms)
    HOUR_MS: 60 * 60 * 1000,
    DAY_MS: 24 * 60 * 60 * 1000,
    WEEK_MS: 7 * 24 * 60 * 60 * 1000,
    MONTH_MS: 30 * 24 * 60 * 60 * 1000,

    // EISV
    EISV_WINDOW_MS: 30 * 60 * 1000,
    EISV_BUCKET_MS: 30000,

    // Limits
    MAX_REFRESH_FAILURES: 2,
    MAX_TIMELINE_ITEMS: 100,
    MAX_EVENTS_LOG: 20
};
```

Replace all hardcoded values with CONFIG references.

### 3. Debouncing

Add debounce utility to utils.js:

```javascript
function debounce(fn, delay) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
}
```

Apply to:
- `agentSearchInput` input handler
- `discoverySearchInput` input handler

Remove duplicate listener on line 1640.

### 4. CSS Consolidation

**New CSS variables for repeated colors:**
```css
:root {
    /* Status colors */
    --color-error: #ef4444;
    --color-warning: #f59e0b;
    --color-success: #22c55e;
    --color-info: #3b82f6;
    --color-muted: #6b7280;

    /* Drift indicators */
    --drift-positive: #ef4444;
    --drift-negative: #3b82f6;
    --drift-neutral: #6b7280;
}
```

Replace hardcoded hex values in dashboard.js and styles.css.

**CSS section headers:**
```css
/* ============================================
   1. Variables & Theming
   ============================================ */

/* ============================================
   2. Base & Reset
   ============================================ */

/* ============================================
   3. Layout (Header, Toolbar, Grid)
   ============================================ */

/* ============================================
   4. Stat Cards
   ============================================ */

/* ============================================
   5. Panels (Agents, Discoveries, Dialectic)
   ============================================ */

/* ============================================
   6. EISV Charts
   ============================================ */

/* ============================================
   7. Governance Pulse
   ============================================ */

/* ============================================
   8. Timeline
   ============================================ */

/* ============================================
   9. Modal
   ============================================ */

/* ============================================
   10. Animations & Transitions
   ============================================ */

/* ============================================
   11. Responsive / Media Queries
   ============================================ */
```

### 5. Code Organization (Revealing Module Pattern)

Reorganize dashboard.js into logical modules:

```javascript
// ============================================
// MODULES
// ============================================

const ModalManager = (function() {
    function expand(panelType) { ... }
    function close() { ... }
    function renderDiscoveries(discoveries) { ... }
    function renderDialectic(sessions) { ... }
    function renderStuckAgents(agents) { ... }

    return { expand, close };
})();

const AgentPanel = (function() {
    let cached = [];
    let searchTerm = '';
    let statusFilter = 'all';
    let sortBy = 'recent';

    function load() { ... }
    function render() { ... }
    function applyFilters() { ... }
    function clearFilters() { ... }
    function exportCSV() { ... }
    function exportJSON() { ... }

    return { load, render, applyFilters, clearFilters, exportCSV, exportJSON };
})();

const DiscoveryPanel = (function() { ... })();
const DialecticPanel = (function() { ... })();
const EISVCharts = (function() { ... })();
const GovernancePulse = (function() { ... })();
const Timeline = (function() { ... })();
```

### 6. JSDoc Documentation

Add JSDoc to all public functions. Example:

```javascript
/**
 * Render an agent card with EISV metrics and status indicators.
 * @param {Object} agent - Agent data from API
 * @param {string} agent.id - Agent UUID
 * @param {string} agent.label - Display name
 * @param {Object} agent.eisv - EISV metrics {E, I, S, V, C}
 * @param {string} agent.status - active|paused|archived|deleted
 * @param {string} [searchTerm] - Optional term to highlight
 * @returns {string} HTML string for agent card
 */
function renderAgentCard(agent, searchTerm) { ... }
```

### 7. Accessibility

**ARIA labels:**
```html
<input id="agent-search" type="text" placeholder="Search agents"
       aria-label="Search agents by name or ID">

<select id="agent-status-filter" aria-label="Filter agents by status">

<button id="refresh-now" aria-label="Refresh dashboard data">
```

**Focus management:**
- Trap focus in modal when open
- Return focus to trigger element on modal close
- Add `role="dialog"` and `aria-modal="true"` to modal

**Keyboard navigation:**
- Agent cards: focusable with Enter/Space to expand
- Modal: Escape to close (already implemented)
- Add skip link for screen readers

### 8. Performance Optimization

**CSS containment:**
```css
.agent-item,
.discovery-item,
.dialectic-item {
    contain: layout style;
}

.eisv-chart-container {
    contain: strict;
}
```

**Chart optimization:**
- Limit EISV data points to last 60 (30 min at 30s intervals)
- Use `requestAnimationFrame` for chart updates
- Batch DOM updates in render functions

**Lazy rendering:**
- Only render visible items in long lists
- Add intersection observer for scroll-based loading

---

## Files Changed

| File | Changes |
|------|---------|
| components.js | Remove 4 unused classes (~160 lines) |
| utils.js | Add debounce function |
| dashboard.js | CONFIG extraction, module pattern, debouncing, JSDoc, a11y |
| styles.css | New variables, section headers, containment |
| index.html | ARIA labels, focus management attributes |

---

## Success Criteria

1. All dead code removed
2. No magic numbers in dashboard.js (all in CONFIG)
3. Search inputs debounced (250ms)
4. All public functions have JSDoc
5. ARIA labels on all interactive elements
6. Modal has proper focus management
7. CSS organized with section headers
8. No duplicate event listeners
9. Charts limited to 60 data points
10. Lighthouse accessibility score > 90

---

## Non-Goals

- TypeScript (keeping zero-build)
- ES modules requiring bundler
- Major UI/UX redesign
- New features

---

## Appendix: Decisions Log Improvement

### Problem

The current Events log in the Governance Pulse panel:
1. Shows generic events (verdict_change, drift_alert) without decision context
2. Gets repetitive when same agent checks in repeatedly
3. Truncates useful info - operators need quick visibility into recent decisions
4. Current format: `icon | time | message` - missing risk/verdict/agent context

### Design

Replace/enhance the Events log with a **Recent Decisions** log:

- **Coalesce repeated check-ins**: `Tessera (x3)` instead of 3 entries
- **Compact verdict badges**: `[A]` Approve (green), `[P]` Proceed (amber), `[!]` Pause (red), `[X]` Critical (red, pulsing)
- **Smart agent name truncation**: Full name up to 15 chars, hover shows full
- **Inline risk score**: `(0.28)` compact decimal
- **Relative time**: `2s`, `1m`, `5m` compact format

Example: `[A] Lumen (0.12) 2s | [P] Tessera (0.42) x2 15s | [!] cursor_autono... (0.65) 1m`

### Hybrid EISV Chart

Dropdown selector with three modes:
1. **Fleet Average** (default) - Rolling average bucketed by 30s intervals
2. **All (raw)** - Original behavior, all data points
3. **[Agent name]** - Single agent's trajectory

Per-agent history tracking with 30-minute window auto-cleanup.
