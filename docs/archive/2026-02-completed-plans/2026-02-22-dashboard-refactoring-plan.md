# Dashboard Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the dashboard for maintainability, performance, and accessibility while preserving zero-build architecture.

**Architecture:** Vanilla JS with revealing module pattern, CSS variables for theming, ARIA for accessibility. No bundler, no TypeScript.

**Tech Stack:** HTML5, CSS3, vanilla JavaScript (ES6+), Chart.js

---

## Phase 1: Dead Code Removal

### Task 1.1: Remove Dead Classes from components.js

**Files:**
- Modify: `dashboard/components.js:55-215`

**Step 1: Verify dead code**

Run in browser console:
```javascript
console.log('MetricTooltip used:', typeof MetricTooltip !== 'undefined');
console.log('StatCard used:', typeof StatCard !== 'undefined');
// These exist but grep shows 0 uses in dashboard.js
```

**Step 2: Remove MetricTooltip class (lines 55-103)**

Delete the entire `class MetricTooltip { ... }` block.

**Step 3: Remove StatCard class (lines 105-136)**

Delete the entire `class StatCard { ... }` block.

**Step 4: Remove AnimaGauge class (lines 138-177)**

Delete the entire `class AnimaGauge { ... }` block.

**Step 5: Remove EnvironmentalCard class (lines 179-206)**

Delete the entire `class EnvironmentalCard { ... }` block.

**Step 6: Update exports at bottom**

Change:
```javascript
if (typeof window !== 'undefined') {
    window.LoadingSkeleton = LoadingSkeleton;
    window.MetricTooltip = MetricTooltip;
    window.StatCard = StatCard;
    window.AnimaGauge = AnimaGauge;
    window.EnvironmentalCard = EnvironmentalCard;
}
```

To:
```javascript
if (typeof window !== 'undefined') {
    window.LoadingSkeleton = LoadingSkeleton;
}
```

**Step 7: Verify in browser**

- Open http://127.0.0.1:8767/dashboard
- Check console for errors
- Verify dashboard loads correctly

**Step 8: Commit**

```bash
git add dashboard/components.js
git commit -m "refactor(dashboard): remove 4 unused component classes

Remove MetricTooltip, StatCard, AnimaGauge, EnvironmentalCard.
Only LoadingSkeleton is actually used (2 references in dashboard.js)."
```

---

## Phase 2: Utility Updates

### Task 2.1: Add debounce Function to utils.js

**Files:**
- Modify: `dashboard/utils.js` (add before class definitions)

**Step 1: Add debounce function after file header**

Insert after line 6 (after the header comment):

```javascript
/**
 * Creates a debounced function that delays invoking fn until after delay ms
 * have elapsed since the last time the debounced function was invoked.
 * @param {Function} fn - Function to debounce
 * @param {number} delay - Delay in milliseconds
 * @returns {Function} Debounced function
 */
function debounce(fn, delay) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
}
```

**Step 2: Export debounce**

Add to the window exports at bottom of file:

```javascript
if (typeof window !== 'undefined') {
    window.DashboardAPI = DashboardAPI;
    window.DataProcessor = DataProcessor;
    window.ThemeManager = ThemeManager;
    window.EISVWebSocket = EISVWebSocket;
    window.debounce = debounce;  // Add this line
}
```

**Step 3: Test in browser console**

```javascript
const debouncedLog = debounce((x) => console.log('debounced:', x), 500);
debouncedLog(1); debouncedLog(2); debouncedLog(3);
// Should only log "debounced: 3" after 500ms
```

**Step 4: Commit**

```bash
git add dashboard/utils.js
git commit -m "feat(dashboard): add debounce utility function"
```

---

## Phase 3: Configuration Extraction

### Task 3.1: Add CONFIG Object to dashboard.js

**Files:**
- Modify: `dashboard/dashboard.js:11-30`

**Step 1: Add CONFIG object after header**

Replace lines 11-26 with:

```javascript
// ============================================================================
// CONFIGURATION & STATE
// ============================================================================

/**
 * Dashboard configuration constants.
 * All magic numbers should be defined here.
 */
const CONFIG = {
    // Timing (ms)
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
    EISV_MAX_POINTS: 60,

    // Limits
    MAX_REFRESH_FAILURES: 2,
    MAX_TIMELINE_ITEMS: 100,
    MAX_EVENTS_LOG: 20,

    // Coalescing
    COALESCE_WINDOW_MS: 30000
};

// Verify dependencies loaded
if (typeof DashboardAPI === 'undefined' || typeof DataProcessor === 'undefined' || typeof ThemeManager === 'undefined') {
    console.error('Dashboard utilities not loaded. Make sure utils.js and components.js are accessible.');
}

// Core instances
const api = typeof DashboardAPI !== 'undefined' ? new DashboardAPI(window.location.origin) : null;
const themeManager = typeof ThemeManager !== 'undefined' ? new ThemeManager() : null;

// Refresh settings (use CONFIG values)
let refreshFailures = 0;
let autoRefreshPaused = false;
```

**Step 2: Remove old REFRESH_INTERVAL_MS and maxRefreshFailures**

Delete the old lines:
```javascript
const REFRESH_INTERVAL_MS = 30000;
const maxRefreshFailures = 2;
```

**Step 3: Commit (partial - CONFIG added)**

```bash
git add dashboard/dashboard.js
git commit -m "refactor(dashboard): add CONFIG object with timing constants"
```

### Task 3.2: Replace Magic Numbers with CONFIG References

**Files:**
- Modify: `dashboard/dashboard.js` (multiple locations)

**Step 1: Replace timeout values**

Find and replace:
- `}, 2000);` → `}, CONFIG.SCROLL_FEEDBACK_MS);` (lines ~273, ~3103, ~3281)
- `}, 1500);` → `}, CONFIG.COPY_FEEDBACK_MS);` (lines ~301, ~1696, ~1703)

**Step 2: Replace time range calculations**

Find and replace:
- `24 * 60 * 60 * 1000` → `CONFIG.DAY_MS`
- `7 * 24 * 60 * 60 * 1000` → `CONFIG.WEEK_MS`
- `30 * 24 * 60 * 60 * 1000` → `CONFIG.MONTH_MS`

**Step 3: Replace EISV constants**

Find and replace:
- `const BUCKET_MS = 30000;` → `const BUCKET_MS = CONFIG.EISV_BUCKET_MS;`
- `const COALESCE_WINDOW_MS = 30000;` → (remove, use CONFIG.COALESCE_WINDOW_MS)
- `const EISV_WINDOW_MS = 30 * 60 * 1000;` → (remove, use CONFIG.EISV_WINDOW_MS)

**Step 4: Replace maxRefreshFailures**

Find and replace:
- `maxRefreshFailures` → `CONFIG.MAX_REFRESH_FAILURES`

**Step 5: Verify in browser**

- Dashboard should load without errors
- Auto-refresh should still work
- Copy buttons should still show feedback

**Step 6: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "refactor(dashboard): replace magic numbers with CONFIG references"
```

---

## Phase 4: Debouncing Search Inputs

### Task 4.1: Apply Debounce to Search Handlers

**Files:**
- Modify: `dashboard/dashboard.js:1595-1650`

**Step 1: Find the search input handlers**

Current code around line 1595:
```javascript
agentSearchInput.addEventListener('input', applyAgentFilters);
```

**Step 2: Wrap with debounce**

Change to:
```javascript
agentSearchInput.addEventListener('input', debounce(applyAgentFilters, CONFIG.DEBOUNCE_MS));
```

**Step 3: Fix discovery search (remove duplicate, add debounce)**

Current code around lines 1638-1640:
```javascript
discoverySearchInput.addEventListener('input', applyDiscoveryFilters);
discoverySearchInput.addEventListener('input', handleDiscoverySearch);  // DUPLICATE - remove
```

Change to:
```javascript
discoverySearchInput.addEventListener('input', debounce(applyDiscoveryFilters, CONFIG.DEBOUNCE_MS));
// Remove the duplicate handleDiscoverySearch listener
```

**Step 4: Test in browser**

- Type quickly in agent search - should not filter on every keystroke
- Type quickly in discovery search - should wait 250ms after typing stops
- Verify filtering still works correctly

**Step 5: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "perf(dashboard): debounce search inputs, remove duplicate listener"
```

---

## Phase 5: CSS Consolidation

### Task 5.1: Add Status Color Variables

**Files:**
- Modify: `dashboard/styles.css:3-60` (in :root)

**Step 1: Add new color variables after existing ones**

Add after line ~30 (after existing color variables):

```css
    /* Status colors (semantic) */
    --color-error: #ef4444;
    --color-warning: #f59e0b;
    --color-success: #22c55e;
    --color-info: #3b82f6;
    --color-muted: #6b7280;

    /* Drift indicators */
    --drift-positive: #ef4444;
    --drift-negative: #3b82f6;
    --drift-neutral: #6b7280;
```

**Step 2: Commit (variables added)**

```bash
git add dashboard/styles.css
git commit -m "refactor(dashboard): add semantic color CSS variables"
```

### Task 5.2: Add CSS Section Headers

**Files:**
- Modify: `dashboard/styles.css` (reorganize with headers)

**Step 1: Add section headers throughout file**

Insert these headers at appropriate locations:

After :root and [data-theme] blocks (~line 75):
```css
/* ============================================
   2. Base & Reset
   ============================================ */
```

Before .header (~line 150):
```css
/* ============================================
   3. Layout (Header, Toolbar, Grid)
   ============================================ */
```

Before .stat-card (~line 590):
```css
/* ============================================
   4. Stat Cards
   ============================================ */
```

Before .panel (~line 700):
```css
/* ============================================
   5. Panels (Agents, Discoveries, Dialectic)
   ============================================ */
```

Before .live-chart-panel (~line 1400):
```css
/* ============================================
   6. EISV Charts
   ============================================ */
```

Before .governance-pulse or #governance-pulse-panel (~line 1800):
```css
/* ============================================
   7. Governance Pulse
   ============================================ */
```

Before .timeline-panel (~line 2200):
```css
/* ============================================
   8. Timeline
   ============================================ */
```

Before .panel-modal (~line 1600):
```css
/* ============================================
   9. Modal
   ============================================ */
```

Before @keyframes (~line 2650):
```css
/* ============================================
   10. Animations & Transitions
   ============================================ */
```

Before @media (~line 2900):
```css
/* ============================================
   11. Responsive / Media Queries
   ============================================ */
```

**Step 2: Commit**

```bash
git add dashboard/styles.css
git commit -m "refactor(dashboard): add section headers to CSS for navigation"
```

### Task 5.3: Add CSS Containment for Performance

**Files:**
- Modify: `dashboard/styles.css`

**Step 1: Add containment rules**

Find `.agent-item` and add:
```css
.agent-item {
    /* existing styles */
    contain: layout style;
}
```

Find `.discovery-item` and add:
```css
.discovery-item {
    /* existing styles */
    contain: layout style;
}
```

Find `.dialectic-item` and add:
```css
.dialectic-item {
    /* existing styles */
    contain: layout style;
}
```

Find `.eisv-chart-container` and add:
```css
.eisv-chart-container {
    /* existing styles */
    contain: strict;
}
```

**Step 2: Test in browser**

- Dashboard should render correctly
- Scrolling in panels should feel smooth

**Step 3: Commit**

```bash
git add dashboard/styles.css
git commit -m "perf(dashboard): add CSS containment for render optimization"
```

---

## Phase 6: Accessibility Improvements

### Task 6.1: Add ARIA Labels to index.html

**Files:**
- Modify: `dashboard/index.html`

**Step 1: Add ARIA labels to inputs**

Find and update:

```html
<input id="agent-search" type="text" placeholder="Search agents"
       aria-label="Search agents by name or ID">

<select id="agent-status-filter" aria-label="Filter agents by status">

<select id="agent-sort" aria-label="Sort agents">

<input id="discovery-search" type="text" placeholder="Search"
       aria-label="Search discoveries">

<select id="discovery-type-filter" aria-label="Filter discoveries by type">

<select id="discovery-time-filter" aria-label="Filter discoveries by time">

<select id="dialectic-status-filter" aria-label="Filter dialectic sessions">

<select id="timeline-range" aria-label="Select timeline range">

<select id="eisv-agent-select" aria-label="Select agent for EISV view">
```

**Step 2: Add ARIA labels to buttons**

```html
<button id="refresh-now" class="toolbar-button" type="button"
        aria-label="Refresh dashboard data now">Refresh now</button>

<button id="eisv-chart-clear" class="panel-button" type="button"
        aria-label="Clear EISV chart data">Clear</button>

<button id="agent-clear-filters" class="panel-button" type="button"
        aria-label="Clear agent filters">Clear</button>

<button id="discovery-clear-filters" class="panel-button" type="button"
        aria-label="Clear discovery filters">Clear</button>

<button id="dialectic-refresh" class="panel-button" type="button"
        aria-label="Refresh dialectic sessions">Refresh</button>
```

**Step 3: Add modal accessibility attributes**

Find the modal div and update:

```html
<div id="panel-modal" class="panel-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="modal-title">
```

**Step 4: Add skip link for screen readers**

Add after opening `<body>` tag:

```html
<a href="#agents-container" class="skip-link">Skip to agents</a>
```

**Step 5: Add skip-link CSS to styles.css**

```css
.skip-link {
    position: absolute;
    top: -40px;
    left: 0;
    background: var(--accent-cyan);
    color: var(--bg-color);
    padding: 8px 16px;
    z-index: 9999;
    transition: top 0.2s;
}

.skip-link:focus {
    top: 0;
}
```

**Step 6: Commit**

```bash
git add dashboard/index.html dashboard/styles.css
git commit -m "a11y(dashboard): add ARIA labels, modal roles, skip link"
```

### Task 6.2: Add Focus Management for Modal

**Files:**
- Modify: `dashboard/dashboard.js`

**Step 1: Track trigger element and add focus trap**

Find the modal functions and update:

```javascript
let modalTriggerElement = null;

function expandPanel(panelType, triggerEl = null) {
    modalTriggerElement = triggerEl || document.activeElement;
    const modal = document.getElementById('panel-modal');
    // ... existing code ...
    modal.classList.add('visible');
    document.body.style.overflow = 'hidden';

    // Focus first focusable element in modal
    const firstFocusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (firstFocusable) firstFocusable.focus();
}

function closeModal() {
    const modal = document.getElementById('panel-modal');
    if (!modal) return;
    modal.classList.remove('visible');
    document.body.style.overflow = '';

    // Return focus to trigger element
    if (modalTriggerElement) {
        modalTriggerElement.focus();
        modalTriggerElement = null;
    }
}
```

**Step 2: Add focus trap**

Add after closeModal:

```javascript
/**
 * Trap focus within modal when open.
 * @param {KeyboardEvent} e
 */
function trapFocus(e) {
    const modal = document.getElementById('panel-modal');
    if (!modal.classList.contains('visible')) return;
    if (e.key !== 'Tab') return;

    const focusableEls = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    const firstEl = focusableEls[0];
    const lastEl = focusableEls[focusableEls.length - 1];

    if (e.shiftKey && document.activeElement === firstEl) {
        lastEl.focus();
        e.preventDefault();
    } else if (!e.shiftKey && document.activeElement === lastEl) {
        firstEl.focus();
        e.preventDefault();
    }
}

document.addEventListener('keydown', trapFocus);
```

**Step 3: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "a11y(dashboard): add modal focus management and focus trap"
```

---

## Phase 7: JSDoc Documentation

### Task 7.1: Add JSDoc to Core Functions

**Files:**
- Modify: `dashboard/dashboard.js`

**Step 1: Document modal functions**

```javascript
/**
 * Expand a panel into a modal view.
 * @param {'discoveries'|'dialectic'|'stuck-agents'} panelType - Panel to expand
 * @param {HTMLElement} [triggerEl] - Element that triggered the modal (for focus return)
 */
function expandPanel(panelType, triggerEl = null) { ... }

/**
 * Close the modal and return focus to trigger element.
 */
function closeModal() { ... }
```

**Step 2: Document render functions**

```javascript
/**
 * Render discoveries list for modal view.
 * @param {Array<Object>} discoveries - Discovery objects from API
 * @returns {string} HTML string
 */
function renderDiscoveriesForModal(discoveries) { ... }

/**
 * Render an agent card with EISV metrics and status indicators.
 * @param {Object} agent - Agent data from API
 * @param {string} agent.id - Agent UUID
 * @param {string} [agent.label] - Display name
 * @param {Object} [agent.eisv] - EISV metrics {E, I, S, V, C}
 * @param {string} [agent.status] - active|paused|archived|deleted
 * @param {string} [searchTerm] - Optional term to highlight
 * @returns {string} HTML string for agent card
 */
function renderAgent(agent, searchTerm) { ... }
```

**Step 3: Document filter functions**

```javascript
/**
 * Apply all active filters to the agent list and re-render.
 * Reads filter state from DOM inputs.
 */
function applyAgentFilters() { ... }

/**
 * Apply all active filters to discoveries and re-render.
 * Reads filter state from DOM inputs.
 */
function applyDiscoveryFilters() { ... }
```

**Step 4: Document data loading functions**

```javascript
/**
 * Load agents from API and render to panel.
 * Updates cachedAgents and stats.
 * @returns {Promise<void>}
 */
async function loadAgents() { ... }

/**
 * Load discoveries from API and render to panel.
 * Updates cachedDiscoveries and stats.
 * @returns {Promise<void>}
 */
async function loadDiscoveries() { ... }

/**
 * Main refresh function - loads all dashboard data.
 * @param {Object} [options]
 * @param {boolean} [options.force=false] - Force refresh even if paused
 * @returns {Promise<void>}
 */
async function refresh(options = {}) { ... }
```

**Step 5: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "docs(dashboard): add JSDoc to core functions"
```

---

## Phase 8: Performance Optimization

### Task 8.1: Limit EISV Chart Data Points

**Files:**
- Modify: `dashboard/dashboard.js`

**Step 1: Find EISV data management**

Look for where EISV data is pushed to chart datasets.

**Step 2: Add data point limiting**

After pushing new data point, add:

```javascript
// Limit to CONFIG.EISV_MAX_POINTS to prevent memory growth
if (dataset.data.length > CONFIG.EISV_MAX_POINTS) {
    dataset.data.shift();
}
```

**Step 3: Test in browser**

- Leave dashboard open for extended period
- Verify chart doesn't grow unbounded
- Verify oldest points are removed

**Step 4: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "perf(dashboard): limit EISV chart to 60 data points"
```

### Task 8.2: Use requestAnimationFrame for Chart Updates

**Files:**
- Modify: `dashboard/dashboard.js`

**Step 1: Find chart.update() calls**

Look for direct `chart.update()` calls.

**Step 2: Wrap in requestAnimationFrame**

Change:
```javascript
chart.update();
```

To:
```javascript
requestAnimationFrame(() => chart.update());
```

**Step 3: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "perf(dashboard): use requestAnimationFrame for chart updates"
```

---

## Phase 9: Final Verification

### Task 9.1: Run Lighthouse Accessibility Audit

**Step 1: Open Chrome DevTools**

- Open dashboard in Chrome
- Open DevTools (F12)
- Go to Lighthouse tab

**Step 2: Run audit**

- Select "Accessibility" category
- Click "Analyze page load"

**Step 3: Fix any issues**

Target: Score > 90

**Step 4: Final commit**

```bash
git add -A
git commit -m "refactor(dashboard): complete quality pass

- Remove dead code from components.js
- Extract magic numbers to CONFIG
- Add debouncing to search inputs
- Add CSS variables and section headers
- Add JSDoc documentation
- Add ARIA labels and focus management
- Add CSS containment
- Limit EISV chart data points

Closes dashboard refactoring design."
```

---

## Summary

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| 1. Dead Code | 1 task | 5 min |
| 2. Utils | 1 task | 5 min |
| 3. Config | 2 tasks | 15 min |
| 4. Debouncing | 1 task | 5 min |
| 5. CSS | 3 tasks | 20 min |
| 6. Accessibility | 2 tasks | 15 min |
| 7. JSDoc | 1 task | 20 min |
| 8. Performance | 2 tasks | 10 min |
| 9. Verification | 1 task | 10 min |
| **Total** | **14 tasks** | **~105 min** |

---

**Plan complete and saved to `docs/plans/2026-02-22-dashboard-refactoring-plan.md`.**

**Two execution options:**

1. **Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

2. **Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
