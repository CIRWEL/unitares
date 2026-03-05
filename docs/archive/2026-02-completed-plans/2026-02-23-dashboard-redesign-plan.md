# Dashboard Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the governance dashboard from monitoring-only to a comprehensive interface serving enterprise operators, human developers, and AI agents.

**Architecture:** htmx + Alpine.js for modern DX without build step. Server returns HTML fragments via new endpoints. Existing JSON API preserved for backwards compatibility.

**Tech Stack:** Vanilla JS, htmx 2.0, Alpine.js 3.14, Chart.js 4.4 (existing), Python/Starlette backend

**Design Document:** `docs/plans/2026-02-23-dashboard-redesign-design.md`

---

## Phase 1: Foundation

### Task 1.1: Add htmx and Alpine.js to index.html

**Files:**
- Modify: `dashboard/index.html:16-21`

**Step 1: Add library script tags**

Open `dashboard/index.html` and add after the Chart.js scripts (line 17):

```html
    <!-- htmx for server-driven updates -->
    <script src="https://unpkg.com/htmx.org@2.0.0"></script>
    <!-- Alpine.js for client-side reactivity -->
    <script src="https://unpkg.com/alpinejs@3.14.0" defer></script>
```

**Step 2: Verify in browser**

Run: Open `http://localhost:8767/dashboard` in browser
Expected: No console errors, page loads normally

Open browser console and verify:
```javascript
typeof htmx !== 'undefined'  // true
typeof Alpine !== 'undefined'  // true
```

**Step 3: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(dashboard): add htmx and Alpine.js CDN scripts"
```

---

### Task 1.2: Create help.json with all terminology

**Files:**
- Create: `dashboard/help.json`

**Step 1: Create help.json file**

Create `dashboard/help.json`:

```json
{
  "eisv": {
    "energy": {
      "short": "Agent's available capacity",
      "long": "Energy represents the agent's current processing capacity. High energy means the agent can handle complex tasks. Low energy may indicate the agent is overwhelmed or needs rest.",
      "range": "0.0 to 1.0 (higher is better)",
      "thresholds": {
        "good": ">= 0.6",
        "warning": "0.3 - 0.6",
        "critical": "< 0.3"
      }
    },
    "integrity": {
      "short": "Decision consistency",
      "long": "Integrity measures how consistently the agent makes decisions aligned with its principles. High integrity means reliable, predictable behavior.",
      "range": "0.0 to 1.0 (higher is better)",
      "thresholds": {
        "good": ">= 0.7",
        "warning": "0.5 - 0.7",
        "critical": "< 0.5"
      }
    },
    "entropy": {
      "short": "Behavioral randomness",
      "long": "Entropy measures unpredictability in agent behavior. Some entropy is healthy (creativity), but too much suggests instability or confusion.",
      "range": "0.0 to 1.0 (lower is usually better)",
      "thresholds": {
        "good": "< 0.2",
        "warning": "0.2 - 0.4",
        "critical": "> 0.4"
      }
    },
    "void": {
      "short": "Unprocessed uncertainty",
      "long": "Void represents areas where the agent lacks knowledge or confidence. High void may indicate the agent is operating outside its expertise.",
      "range": "0.0 to 1.0 (lower is better)",
      "thresholds": {
        "good": "< 0.15",
        "warning": "0.15 - 0.3",
        "critical": "> 0.3"
      }
    }
  },
  "metrics": {
    "coherence": {
      "short": "Overall agent health",
      "long": "Coherence is a composite score derived from EISV values. It represents how well the agent is functioning overall. Calculated as: (Energy + Integrity) / 2 - (Entropy + Void) / 4",
      "range": "0.0 to 1.0 (higher is better)"
    },
    "risk": {
      "short": "Governance intervention likelihood",
      "long": "Risk score determines whether governance should intervene. Based on coherence, confidence, complexity, and ethical drift. Higher risk means more likely to pause or halt the agent.",
      "range": "0.0 to 1.0 (lower is better)",
      "thresholds": {
        "approve": "< 0.35 (auto-approve)",
        "proceed": "0.35 - 0.60 (proceed with monitoring)",
        "pause": "0.60 - 0.70 (pause for review)",
        "halt": "> 0.70 (halt and escalate)"
      }
    },
    "confidence": {
      "short": "Agent's self-reported certainty",
      "long": "How confident the agent is in its current task. Low confidence with high complexity may trigger governance intervention.",
      "range": "0.0 to 1.0"
    },
    "complexity": {
      "short": "Task difficulty estimate",
      "long": "How complex the current task appears. High complexity combined with low confidence increases risk.",
      "range": "0.0 to 1.0"
    }
  },
  "drift": {
    "emotional": {
      "short": "Calibration deviation",
      "long": "How far the agent's emotional responses deviate from its calibrated baseline. Positive means more reactive, negative means more suppressed.",
      "range": "-1.0 to 1.0 (closer to 0 is better)"
    },
    "epistemic": {
      "short": "Knowledge consistency",
      "long": "How consistently the agent applies its knowledge. Drift here may indicate confusion or conflicting information.",
      "range": "-1.0 to 1.0 (closer to 0 is better)"
    },
    "behavioral": {
      "short": "Action pattern stability",
      "long": "How stable the agent's action patterns are compared to baseline. High drift may indicate the agent is adapting (good) or destabilizing (bad).",
      "range": "-1.0 to 1.0 (closer to 0 is better)"
    }
  },
  "status": {
    "active": {
      "short": "Agent is running",
      "long": "The agent is actively processing tasks and checking in with governance."
    },
    "paused": {
      "short": "Temporarily stopped",
      "long": "The agent has been paused by governance or an operator. It will not process tasks until resumed."
    },
    "waiting_input": {
      "short": "Needs human input",
      "long": "The agent is waiting for human guidance before proceeding. This may be due to high-risk decisions or explicit requests for review."
    },
    "archived": {
      "short": "No longer active",
      "long": "The agent has been archived and is no longer participating in governance. Historical data is preserved."
    }
  },
  "actions": {
    "pause": {
      "short": "Stop agent temporarily",
      "long": "Pausing an agent prevents it from processing new tasks. Use this when you need to investigate issues or the agent is behaving unexpectedly.",
      "reversible": true
    },
    "resume": {
      "short": "Restart paused agent",
      "long": "Resuming returns a paused agent to active status. The agent will continue from where it left off.",
      "reversible": true
    },
    "archive": {
      "short": "Permanently deactivate",
      "long": "Archiving removes an agent from active governance. Use this for agents that are no longer needed. Can be undone by an administrator.",
      "reversible": false
    },
    "recalibrate": {
      "short": "Reset baseline metrics",
      "long": "Recalibration rebuilds the agent's baseline EISV values from recent history. Use this if the agent's environment has fundamentally changed.",
      "reversible": false
    }
  },
  "keyboard": {
    "/": "Focus search",
    "Escape": "Close panel or clear search",
    "j": "Move down in list",
    "k": "Move up in list",
    "Enter": "Open selected item",
    "?": "Show keyboard shortcuts"
  }
}
```

**Step 2: Update allowed files in server**

Open `src/mcp_server.py` and find line ~2274:

```python
allowed_files = ["utils.js", "components.js", "styles.css", "dashboard.js"]
```

Change to:

```python
allowed_files = ["utils.js", "components.js", "styles.css", "dashboard.js", "help.json"]
```

**Step 3: Verify help.json loads**

Run: Open browser console on dashboard page
```javascript
fetch('/dashboard/help.json').then(r => r.json()).then(console.log)
```
Expected: JSON object with eisv, metrics, drift, status, actions, keyboard keys

**Step 4: Commit**

```bash
git add dashboard/help.json src/mcp_server.py
git commit -m "feat(dashboard): add help.json terminology database"
```

---

### Task 1.3: Create Alpine.js help store

**Files:**
- Modify: `dashboard/dashboard.js:45-55`

**Step 1: Add help store initialization**

Open `dashboard/dashboard.js`. After line 52 (themeManager initialization), add:

```javascript
// Help system store (Alpine.js)
let helpData = null;

/**
 * Initialize Alpine stores for global state management.
 * Must be called before Alpine starts (it has defer attribute).
 */
document.addEventListener('alpine:init', () => {
    // Help content store
    Alpine.store('help', {
        data: {},
        loaded: false,

        async load() {
            if (this.loaded) return;
            try {
                const response = await fetch('/dashboard/help.json');
                if (response.ok) {
                    this.data = await response.json();
                    this.loaded = true;
                    helpData = this.data;  // Also set module-level for non-Alpine code
                }
            } catch (e) {
                console.warn('Failed to load help.json:', e);
            }
        },

        get(path) {
            // path like "eisv.energy" or "metrics.coherence"
            const parts = path.split('.');
            let result = this.data;
            for (const part of parts) {
                result = result?.[part];
            }
            return result;
        },

        short(path) {
            return this.get(path)?.short || path;
        },

        long(path) {
            return this.get(path)?.long || '';
        }
    });

    // Load help data immediately
    Alpine.store('help').load();
});
```

**Step 2: Verify in browser**

Run: Open browser console on dashboard page, wait 2 seconds:
```javascript
Alpine.store('help').loaded  // true
Alpine.store('help').short('eisv.energy')  // "Agent's available capacity"
```

**Step 3: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "feat(dashboard): add Alpine.js help store"
```

---

### Task 1.4: Add tooltip directive for Alpine

**Files:**
- Modify: `dashboard/dashboard.js` (after help store)
- Modify: `dashboard/styles.css` (add tooltip styles)

**Step 1: Add tooltip directive**

In `dashboard/dashboard.js`, add after the help store initialization (inside the `alpine:init` handler):

```javascript
    // Tooltip directive: x-tooltip="eisv.energy" or x-tooltip="'Custom text'"
    Alpine.directive('tooltip', (el, { expression }, { evaluate }) => {
        let content;

        // Check if it's a help path or direct string
        if (expression.startsWith("'") || expression.startsWith('"')) {
            content = evaluate(expression);
        } else {
            // It's a help path
            const helpItem = Alpine.store('help').get(expression);
            if (helpItem) {
                content = `<strong>${helpItem.short}</strong>`;
                if (helpItem.long) {
                    content += `<br><span class="tooltip-detail">${helpItem.long}</span>`;
                }
                if (helpItem.range) {
                    content += `<br><span class="tooltip-range">Range: ${helpItem.range}</span>`;
                }
            } else {
                content = expression;
            }
        }

        // Create tooltip element
        const tooltip = document.createElement('div');
        tooltip.className = 'tooltip';
        tooltip.innerHTML = content;
        document.body.appendChild(tooltip);

        // Position and show on hover/focus
        const show = () => {
            const rect = el.getBoundingClientRect();
            tooltip.style.left = `${rect.left + rect.width / 2}px`;
            tooltip.style.top = `${rect.bottom + 8}px`;
            tooltip.classList.add('visible');
        };

        const hide = () => {
            tooltip.classList.remove('visible');
        };

        el.addEventListener('mouseenter', show);
        el.addEventListener('mouseleave', hide);
        el.addEventListener('focus', show);
        el.addEventListener('blur', hide);

        // Cleanup on element removal
        el._tooltipCleanup = () => {
            tooltip.remove();
            el.removeEventListener('mouseenter', show);
            el.removeEventListener('mouseleave', hide);
            el.removeEventListener('focus', show);
            el.removeEventListener('blur', hide);
        };
    });
```

**Step 2: Add tooltip CSS**

Open `dashboard/styles.css` and add at the end:

```css
/* ============================================================================
   TOOLTIPS
   ============================================================================ */

.tooltip {
    position: fixed;
    z-index: 10000;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 0.85rem;
    max-width: 300px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    pointer-events: none;
    opacity: 0;
    transform: translateX(-50%) translateY(4px);
    transition: opacity 0.15s ease, transform 0.15s ease;
}

.tooltip.visible {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
}

.tooltip-detail {
    display: block;
    margin-top: 4px;
    color: var(--text-secondary);
    font-size: 0.8rem;
    line-height: 1.4;
}

.tooltip-range {
    display: block;
    margin-top: 4px;
    color: var(--text-tertiary);
    font-size: 0.75rem;
    font-family: var(--font-mono);
}

/* Help indicator on hoverable elements */
[x-tooltip] {
    cursor: help;
    border-bottom: 1px dotted var(--text-tertiary);
}
```

**Step 3: Test tooltip on a metric label**

Open `dashboard/index.html` and find line ~104:

```html
<span class="legend-item"><span class="legend-dot energy"></span>Energy</span>
```

Change to:

```html
<span class="legend-item"><span class="legend-dot energy"></span><span x-tooltip="eisv.energy">Energy</span></span>
```

**Step 4: Verify in browser**

Run: Hover over "Energy" label in EISV chart
Expected: Tooltip appears with "Agent's available capacity" and explanation

**Step 5: Commit**

```bash
git add dashboard/dashboard.js dashboard/styles.css dashboard/index.html
git commit -m "feat(dashboard): add Alpine tooltip directive with help.json integration"
```

---

### Task 1.5: Add tooltips to all EISV labels

**Files:**
- Modify: `dashboard/index.html:101-120`

**Step 1: Update all EISV legend items**

Open `dashboard/index.html` and replace the EISV chart legend section (~lines 103-117):

```html
            <div class="eisv-chart-cell">
                <div class="eisv-chart-label">
                    <span class="legend-item"><span class="legend-dot energy"></span><span x-tooltip="eisv.energy">Energy</span></span>
                    <span class="legend-item"><span class="legend-dot integrity"></span><span x-tooltip="eisv.integrity">Integrity</span></span>
                    <span class="legend-item"><span class="legend-dot legend-dot-dashed coherence"></span><span x-tooltip="metrics.coherence">Coherence</span></span>
                </div>
                <div class="eisv-chart-container">
                    <canvas id="eisv-chart-upper"></canvas>
                </div>
            </div>
            <!-- Lower chart: S, V (near zero, need own scale) -->
            <div class="eisv-chart-cell">
                <div class="eisv-chart-label">
                    <span class="legend-item"><span class="legend-dot entropy"></span><span x-tooltip="eisv.entropy">Entropy</span></span>
                    <span class="legend-item"><span class="legend-dot volatility"></span><span x-tooltip="eisv.void">Void</span></span>
                </div>
                <div class="eisv-chart-container">
                    <canvas id="eisv-chart-lower"></canvas>
                </div>
            </div>
```

**Step 2: Verify all tooltips work**

Run: Hover over each EISV label (Energy, Integrity, Coherence, Entropy, Void)
Expected: Each shows appropriate tooltip with help content

**Step 3: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(dashboard): add tooltips to all EISV chart labels"
```

---

### Task 1.6: Add tooltips to governance pulse metrics

**Files:**
- Modify: `dashboard/index.html:145-175`

**Step 1: Update pulse metric labels**

Open `dashboard/index.html` and update the pulse metrics section. Find the Risk label (~line 148):

```html
<span class="pulse-metric-label">Risk → Verdict</span>
```

Change to:

```html
<span class="pulse-metric-label"><span x-tooltip="metrics.risk">Risk</span> → Verdict</span>
```

Find Confidence (~line 162):
```html
<span class="pulse-metric-label">Confidence</span>
```

Change to:
```html
<span class="pulse-metric-label"><span x-tooltip="metrics.confidence">Confidence</span></span>
```

Find Complexity (~line 169):
```html
<span class="pulse-metric-label">Complexity</span>
```

Change to:
```html
<span class="pulse-metric-label"><span x-tooltip="metrics.complexity">Complexity</span></span>
```

**Step 2: Update drift axis labels**

Find the drift section (~lines 180-197). Update each axis label:

```html
<span class="drift-axis-label" title="Emotional drift — calibration deviation from baseline"><span x-tooltip="drift.emotional">Emotional</span></span>
```

```html
<span class="drift-axis-label" title="Epistemic drift — coherence deviation from baseline"><span x-tooltip="drift.epistemic">Epistemic</span></span>
```

```html
<span class="drift-axis-label" title="Behavioral drift — stability deviation from baseline"><span x-tooltip="drift.behavioral">Behavioral</span></span>
```

**Step 3: Verify in browser**

Run: Hover over Risk, Confidence, Complexity, and drift axis labels
Expected: Each shows appropriate tooltip

**Step 4: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(dashboard): add tooltips to governance pulse metrics"
```

---

### Task 1.7: Implement keyboard shortcut handler

**Files:**
- Modify: `dashboard/dashboard.js` (after Alpine init)

**Step 1: Add keyboard shortcut handler**

In `dashboard/dashboard.js`, add after the Alpine `alpine:init` block:

```javascript
// ============================================================================
// KEYBOARD SHORTCUTS
// ============================================================================

/**
 * Global keyboard shortcut handler.
 * Shortcuts are ignored when focus is in an input/textarea.
 */
document.addEventListener('keydown', (e) => {
    // Ignore if in input field
    const activeTag = document.activeElement?.tagName?.toLowerCase();
    if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select') {
        // But allow Escape to blur
        if (e.key === 'Escape') {
            document.activeElement.blur();
            e.preventDefault();
        }
        return;
    }

    // Don't intercept if modifier keys are held (except shift for ?)
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    switch (e.key) {
        case '/':
            // Focus search
            e.preventDefault();
            const searchInput = document.getElementById('agent-search');
            if (searchInput) {
                searchInput.focus();
                searchInput.select();
            }
            break;

        case 'Escape':
            // Close panel or clear search
            e.preventDefault();
            const panel = document.querySelector('.slide-panel.open');
            if (panel) {
                closeSlidePanel();
            } else {
                // Clear search if there's content
                const search = document.getElementById('agent-search');
                if (search && search.value) {
                    search.value = '';
                    search.dispatchEvent(new Event('input'));
                }
            }
            break;

        case '?':
            // Show keyboard shortcuts (when shift+/ pressed)
            e.preventDefault();
            showKeyboardShortcuts();
            break;

        case 'j':
            // Move down in agent list
            e.preventDefault();
            navigateAgentList(1);
            break;

        case 'k':
            // Move up in agent list
            e.preventDefault();
            navigateAgentList(-1);
            break;

        case 'Enter':
            // Open selected agent
            e.preventDefault();
            openSelectedAgent();
            break;
    }
});

// Track which agent card is "selected" for keyboard navigation
let selectedAgentIndex = -1;

/**
 * Navigate agent list with j/k keys.
 * @param {number} direction - 1 for down, -1 for up
 */
function navigateAgentList(direction) {
    const agentCards = document.querySelectorAll('.agent-card');
    if (!agentCards.length) return;

    // Remove previous selection
    agentCards.forEach(card => card.classList.remove('keyboard-selected'));

    // Update index
    selectedAgentIndex += direction;
    if (selectedAgentIndex < 0) selectedAgentIndex = agentCards.length - 1;
    if (selectedAgentIndex >= agentCards.length) selectedAgentIndex = 0;

    // Apply selection
    const selected = agentCards[selectedAgentIndex];
    selected.classList.add('keyboard-selected');
    selected.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Open the currently selected agent (Enter key).
 */
function openSelectedAgent() {
    const selected = document.querySelector('.agent-card.keyboard-selected');
    if (selected) {
        // For now, just click it (later this will open slide panel)
        selected.click();
    }
}

/**
 * Show keyboard shortcuts help modal.
 */
function showKeyboardShortcuts() {
    const shortcuts = helpData?.keyboard || {
        '/': 'Focus search',
        'Escape': 'Close panel or clear search',
        'j': 'Move down in list',
        'k': 'Move up in list',
        'Enter': 'Open selected item',
        '?': 'Show this help'
    };

    let html = '<div class="keyboard-shortcuts-list">';
    for (const [key, description] of Object.entries(shortcuts)) {
        html += `<div class="shortcut-row">
            <kbd>${key}</kbd>
            <span>${description}</span>
        </div>`;
    }
    html += '</div>';

    // Use existing modal
    const modal = document.getElementById('panel-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');

    modalTitle.textContent = 'Keyboard Shortcuts';
    modalBody.innerHTML = html;

    modal.classList.add('visible');
    document.body.style.overflow = 'hidden';
}
```

**Step 2: Add keyboard selection styles**

In `dashboard/styles.css`, add:

```css
/* Keyboard navigation selection */
.agent-card.keyboard-selected {
    outline: 2px solid var(--accent-color);
    outline-offset: 2px;
}

/* Keyboard shortcuts modal */
.keyboard-shortcuts-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.shortcut-row {
    display: flex;
    align-items: center;
    gap: 16px;
}

.shortcut-row kbd {
    display: inline-block;
    min-width: 32px;
    padding: 4px 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    font-family: var(--font-mono);
    font-size: 0.85rem;
    text-align: center;
}
```

**Step 3: Verify keyboard shortcuts**

Run:
1. Press `/` - should focus agent search
2. Press `Escape` - should blur search
3. Press `j` - should select first agent card
4. Press `k` - should move selection up
5. Press `?` - should show shortcuts modal

**Step 4: Commit**

```bash
git add dashboard/dashboard.js dashboard/styles.css
git commit -m "feat(dashboard): add keyboard shortcut handler (/, Esc, j, k, Enter, ?)"
```

---

## Phase 2: Navigation

### Task 2.1: Add hash-based routing

**Files:**
- Modify: `dashboard/dashboard.js`

**Step 1: Add router module**

In `dashboard/dashboard.js`, add after the keyboard shortcuts section:

```javascript
// ============================================================================
// HASH-BASED ROUTING
// ============================================================================

/**
 * Simple hash router for deep-linking.
 * Routes:
 *   #agent/{uuid}      - Open agent detail panel
 *   #discovery/{id}    - Open discovery detail
 *   #search?q={query}  - Set search query
 */
const Router = {
    routes: {},

    /**
     * Register a route handler.
     * @param {string} pattern - Route pattern (e.g., 'agent/:id')
     * @param {Function} handler - Function to call with params
     */
    on(pattern, handler) {
        this.routes[pattern] = handler;
    },

    /**
     * Navigate to a route.
     * @param {string} hash - Hash without # prefix
     */
    navigate(hash) {
        window.location.hash = hash;
    },

    /**
     * Parse current hash and call matching handler.
     */
    handleRoute() {
        const hash = window.location.hash.slice(1);  // Remove #
        if (!hash) return;

        // Try each route pattern
        for (const [pattern, handler] of Object.entries(this.routes)) {
            const match = this.matchRoute(pattern, hash);
            if (match) {
                handler(match.params, match.query);
                return;
            }
        }

        console.warn('No route matched:', hash);
    },

    /**
     * Match a route pattern against a hash.
     * @param {string} pattern - Pattern like 'agent/:id'
     * @param {string} hash - Hash like 'agent/abc-123?foo=bar'
     * @returns {Object|null} - {params: {id: 'abc-123'}, query: {foo: 'bar'}} or null
     */
    matchRoute(pattern, hash) {
        // Split hash into path and query
        const [path, queryString] = hash.split('?');
        const query = queryString ? Object.fromEntries(new URLSearchParams(queryString)) : {};

        // Split pattern and path into segments
        const patternParts = pattern.split('/');
        const pathParts = path.split('/');

        if (patternParts.length !== pathParts.length) return null;

        const params = {};
        for (let i = 0; i < patternParts.length; i++) {
            if (patternParts[i].startsWith(':')) {
                // This is a parameter
                params[patternParts[i].slice(1)] = pathParts[i];
            } else if (patternParts[i] !== pathParts[i]) {
                // Literal mismatch
                return null;
            }
        }

        return { params, query };
    },

    /**
     * Initialize router and listen for hash changes.
     */
    init() {
        window.addEventListener('hashchange', () => this.handleRoute());
        // Handle initial hash on page load
        if (window.location.hash) {
            this.handleRoute();
        }
    }
};

// Register routes (handlers will be added as features are built)
Router.on('agent/:id', (params) => {
    console.log('Route: agent', params.id);
    // TODO: openAgentPanel(params.id)
});

Router.on('discovery/:id', (params) => {
    console.log('Route: discovery', params.id);
    // TODO: openDiscoveryPanel(params.id)
});

Router.on('search', (params, query) => {
    console.log('Route: search', query.q);
    const searchInput = document.getElementById('agent-search');
    if (searchInput && query.q) {
        searchInput.value = query.q;
        searchInput.dispatchEvent(new Event('input'));
    }
});

// Initialize router when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    Router.init();
});
```

**Step 2: Verify routing**

Run in browser:
1. Navigate to `http://localhost:8767/dashboard#agent/test-id`
   - Console should log: "Route: agent test-id"
2. Navigate to `http://localhost:8767/dashboard#search?q=claude`
   - Search input should populate with "claude"

**Step 3: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "feat(dashboard): add hash-based router for deep-linking"
```

---

### Task 2.2: Create slide panel component

**Files:**
- Modify: `dashboard/index.html`
- Modify: `dashboard/styles.css`
- Modify: `dashboard/dashboard.js`

**Step 1: Add slide panel HTML structure**

In `dashboard/index.html`, add before the closing `</body>` tag (after the modal):

```html
    <!-- Slide Panel for detail views -->
    <aside id="slide-panel" class="slide-panel" role="complementary" aria-labelledby="panel-title">
        <div class="slide-panel-header">
            <h2 id="panel-title">Details</h2>
            <button class="slide-panel-close" type="button" aria-label="Close panel">&times;</button>
        </div>
        <div class="slide-panel-body" id="panel-body">
            <!-- Content loaded dynamically -->
        </div>
    </aside>
```

**Step 2: Add slide panel styles**

In `dashboard/styles.css`, add:

```css
/* ============================================================================
   SLIDE PANEL
   ============================================================================ */

.slide-panel {
    position: fixed;
    top: 0;
    right: 0;
    width: 50%;
    max-width: 600px;
    height: 100vh;
    background: var(--bg-primary);
    border-left: 1px solid var(--border-color);
    box-shadow: -4px 0 20px rgba(0, 0, 0, 0.1);
    transform: translateX(100%);
    transition: transform 0.25s ease;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.slide-panel.open {
    transform: translateX(0);
}

/* Push main content when panel is open */
body.panel-open main {
    margin-right: 50%;
    max-width: calc(100% - 50%);
    transition: margin-right 0.25s ease, max-width 0.25s ease;
}

@media (max-width: 1024px) {
    .slide-panel {
        width: 80%;
        max-width: none;
    }

    body.panel-open main {
        margin-right: 0;
        max-width: 100%;
    }
}

@media (max-width: 640px) {
    .slide-panel {
        width: 100%;
    }
}

.slide-panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-secondary);
    flex-shrink: 0;
}

.slide-panel-header h2 {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 600;
}

.slide-panel-close {
    background: none;
    border: none;
    font-size: 1.5rem;
    color: var(--text-secondary);
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background 0.15s ease;
}

.slide-panel-close:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
}

.slide-panel-body {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
}

/* Loading state for panel */
.slide-panel-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--text-secondary);
}
```

**Step 3: Add panel control functions**

In `dashboard/dashboard.js`, add after the Router section:

```javascript
// ============================================================================
// SLIDE PANEL
// ============================================================================

let panelTriggerElement = null;

/**
 * Open the slide panel with content.
 * @param {string} title - Panel title
 * @param {string} content - HTML content for panel body
 */
function openSlidePanel(title, content) {
    panelTriggerElement = document.activeElement;

    const panel = document.getElementById('slide-panel');
    const panelTitle = document.getElementById('panel-title');
    const panelBody = document.getElementById('panel-body');

    panelTitle.textContent = title;
    panelBody.innerHTML = content;

    panel.classList.add('open');
    document.body.classList.add('panel-open');

    // Focus first focusable element
    const firstFocusable = panelBody.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (firstFocusable) {
        firstFocusable.focus();
    } else {
        panel.querySelector('.slide-panel-close').focus();
    }
}

/**
 * Close the slide panel.
 */
function closeSlidePanel() {
    const panel = document.getElementById('slide-panel');
    panel.classList.remove('open');
    document.body.classList.remove('panel-open');

    // Clear hash if it was a panel route
    if (window.location.hash.match(/^#(agent|discovery)\//)) {
        history.pushState(null, '', window.location.pathname);
    }

    // Return focus
    if (panelTriggerElement) {
        panelTriggerElement.focus();
        panelTriggerElement = null;
    }
}

// Wire up close button
document.addEventListener('DOMContentLoaded', () => {
    const closeBtn = document.querySelector('.slide-panel-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', closeSlidePanel);
    }
});
```

**Step 4: Verify panel works**

Run in browser console:
```javascript
openSlidePanel('Test Panel', '<p>Hello World</p>')
```
Expected: Panel slides in from right with title "Test Panel"

Press Escape or click X to close.

**Step 5: Commit**

```bash
git add dashboard/index.html dashboard/styles.css dashboard/dashboard.js
git commit -m "feat(dashboard): add slide panel component"
```

---

### Task 2.3: Implement scoped search

**Files:**
- Modify: `dashboard/index.html`
- Modify: `dashboard/dashboard.js`
- Modify: `dashboard/styles.css`

**Step 1: Update search input with scope indicator**

In `dashboard/index.html`, find the agent search input (~line 234):

```html
<input id="agent-search" type="text" placeholder="Search agents" aria-label="Search agents by name or ID">
```

Replace with:

```html
<div class="search-wrapper">
    <span class="search-scope" id="search-scope" title="Search scope">Agents</span>
    <input id="agent-search" type="text" placeholder="Search agents..." aria-label="Search agents by name or ID">
    <button id="search-scope-toggle" class="search-scope-btn" type="button" title="Expand search scope">
        <span class="scope-expand-icon">▼</span>
    </button>
</div>
```

**Step 2: Add search wrapper styles**

In `dashboard/styles.css`, add:

```css
/* ============================================================================
   SCOPED SEARCH
   ============================================================================ */

.search-wrapper {
    display: flex;
    align-items: center;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    overflow: hidden;
}

.search-wrapper:focus-within {
    border-color: var(--accent-color);
    box-shadow: 0 0 0 2px rgba(var(--accent-rgb), 0.2);
}

.search-scope {
    padding: 6px 10px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-right: 1px solid var(--border-color);
    white-space: nowrap;
}

.search-wrapper input {
    flex: 1;
    border: none;
    background: transparent;
    padding: 6px 10px;
    font-size: 0.9rem;
    min-width: 120px;
}

.search-wrapper input:focus {
    outline: none;
}

.search-scope-btn {
    background: none;
    border: none;
    padding: 6px 10px;
    color: var(--text-tertiary);
    cursor: pointer;
    transition: color 0.15s ease;
}

.search-scope-btn:hover {
    color: var(--text-primary);
}

.scope-expand-icon {
    font-size: 0.7rem;
}

/* Search scope dropdown (future enhancement) */
.search-scope-menu {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    z-index: 100;
}

.search-scope-menu.visible {
    display: block;
}

.search-scope-option {
    padding: 8px 16px;
    cursor: pointer;
}

.search-scope-option:hover {
    background: var(--bg-hover);
}
```

**Step 3: Update search handler to use scope**

In `dashboard/dashboard.js`, find the existing search handling (or add if not present):

```javascript
// ============================================================================
// SCOPED SEARCH
// ============================================================================

const SearchScope = {
    current: 'agents',

    scopes: {
        agents: {
            label: 'Agents',
            placeholder: 'Search agents...',
            filter: (query, data) => {
                if (!query) return data;
                const q = query.toLowerCase();
                return data.filter(a =>
                    a.label?.toLowerCase().includes(q) ||
                    a.agent_id?.toLowerCase().includes(q) ||
                    a.tags?.some(t => t.toLowerCase().includes(q))
                );
            }
        },
        all: {
            label: 'All',
            placeholder: 'Search everything...',
            filter: (query, data) => {
                // TODO: Search across agents, discoveries, sessions
                return data;
            }
        }
    },

    setScope(scope) {
        if (!this.scopes[scope]) return;
        this.current = scope;

        const scopeLabel = document.getElementById('search-scope');
        const searchInput = document.getElementById('agent-search');

        if (scopeLabel) scopeLabel.textContent = this.scopes[scope].label;
        if (searchInput) searchInput.placeholder = this.scopes[scope].placeholder;
    },

    filter(query, data) {
        return this.scopes[this.current].filter(query, data);
    }
};

// Initialize search scope toggle
document.addEventListener('DOMContentLoaded', () => {
    const toggleBtn = document.getElementById('search-scope-toggle');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            // Toggle between agents and all
            const next = SearchScope.current === 'agents' ? 'all' : 'agents';
            SearchScope.setScope(next);
            // Re-trigger search
            const searchInput = document.getElementById('agent-search');
            if (searchInput) searchInput.dispatchEvent(new Event('input'));
        });
    }
});
```

**Step 4: Verify scoped search**

Run in browser:
1. Type in search box - should filter agents
2. Click dropdown button - scope should toggle to "All"
3. Press `/` - should focus search

**Step 5: Commit**

```bash
git add dashboard/index.html dashboard/styles.css dashboard/dashboard.js
git commit -m "feat(dashboard): implement scoped search with agents/all toggle"
```

---

### Task 2.4: Wire agent cards to open slide panel

**Files:**
- Modify: `dashboard/dashboard.js`

**Step 1: Update Router to open agent panel**

In `dashboard/dashboard.js`, find the Router agent route and update:

```javascript
Router.on('agent/:id', (params) => {
    openAgentDetailPanel(params.id);
});
```

**Step 2: Add agent detail panel function**

Add after the slide panel functions:

```javascript
/**
 * Open agent detail panel.
 * @param {string} agentId - Agent UUID
 */
function openAgentDetailPanel(agentId) {
    // Find agent in cached data
    const agent = cachedAgents.find(a => a.agent_id === agentId);

    if (!agent) {
        openSlidePanel('Agent Not Found', `
            <div class="empty-state">
                <p>Agent ${agentId} not found.</p>
                <p class="help-text">This agent may have been archived or the ID is invalid.</p>
            </div>
        `);
        return;
    }

    const content = renderAgentDetailContent(agent);
    openSlidePanel(agent.label || agent.agent_id, content);
}

/**
 * Render agent detail panel content.
 * @param {Object} agent - Agent data
 * @returns {string} HTML content
 */
function renderAgentDetailContent(agent) {
    const status = agent.status || 'unknown';
    const coherence = typeof agent.coherence === 'number' ? (agent.coherence * 100).toFixed(1) + '%' : 'N/A';
    const risk = typeof agent.risk === 'number' ? (agent.risk * 100).toFixed(1) + '%' : 'N/A';
    const lastSeen = agent.last_seen ? formatRelativeTime(new Date(agent.last_seen)) : 'Never';

    return `
        <div class="agent-detail">
            <div class="agent-detail-status status-${status}">${status}</div>

            <div class="agent-detail-section">
                <h3>Current Metrics</h3>
                <div class="agent-detail-metrics">
                    <div class="metric-row">
                        <span class="metric-label" x-tooltip="metrics.coherence">Coherence</span>
                        <span class="metric-value">${coherence}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label" x-tooltip="metrics.risk">Risk</span>
                        <span class="metric-value">${risk}</span>
                    </div>
                </div>
            </div>

            <div class="agent-detail-section">
                <h3>EISV Values</h3>
                <div class="agent-detail-eisv">
                    <div class="eisv-bar">
                        <span class="eisv-label">E</span>
                        <div class="eisv-bar-track"><div class="eisv-bar-fill energy" style="width:${(agent.eisv?.E || 0) * 100}%"></div></div>
                        <span class="eisv-value">${((agent.eisv?.E || 0) * 100).toFixed(0)}%</span>
                    </div>
                    <div class="eisv-bar">
                        <span class="eisv-label">I</span>
                        <div class="eisv-bar-track"><div class="eisv-bar-fill integrity" style="width:${(agent.eisv?.I || 0) * 100}%"></div></div>
                        <span class="eisv-value">${((agent.eisv?.I || 0) * 100).toFixed(0)}%</span>
                    </div>
                    <div class="eisv-bar">
                        <span class="eisv-label">S</span>
                        <div class="eisv-bar-track"><div class="eisv-bar-fill entropy" style="width:${(agent.eisv?.S || 0) * 100}%"></div></div>
                        <span class="eisv-value">${((agent.eisv?.S || 0) * 100).toFixed(0)}%</span>
                    </div>
                    <div class="eisv-bar">
                        <span class="eisv-label">V</span>
                        <div class="eisv-bar-track"><div class="eisv-bar-fill volatility" style="width:${(agent.eisv?.V || 0) * 100}%"></div></div>
                        <span class="eisv-value">${((agent.eisv?.V || 0) * 100).toFixed(0)}%</span>
                    </div>
                </div>
            </div>

            <div class="agent-detail-section">
                <h3>Info</h3>
                <dl class="agent-detail-info">
                    <dt>ID</dt>
                    <dd><code>${agent.agent_id}</code></dd>
                    <dt>Last Seen</dt>
                    <dd>${lastSeen}</dd>
                    <dt>Total Updates</dt>
                    <dd>${agent.total_updates || 0}</dd>
                    ${agent.tags?.length ? `<dt>Tags</dt><dd>${agent.tags.map(t => `<span class="tag">${t}</span>`).join(' ')}</dd>` : ''}
                </dl>
            </div>

            <div class="agent-detail-actions">
                <!-- Quick actions will be added in Phase 4 -->
            </div>
        </div>
    `;
}
```

**Step 3: Add agent detail styles**

In `dashboard/styles.css`, add:

```css
/* ============================================================================
   AGENT DETAIL PANEL
   ============================================================================ */

.agent-detail {
    display: flex;
    flex-direction: column;
    gap: 24px;
}

.agent-detail-status {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 0.85rem;
    font-weight: 500;
    text-transform: capitalize;
}

.agent-detail-status.status-active { background: var(--status-active-bg); color: var(--status-active); }
.agent-detail-status.status-paused { background: var(--status-paused-bg); color: var(--status-paused); }
.agent-detail-status.status-waiting_input { background: var(--status-waiting-bg); color: var(--status-waiting); }
.agent-detail-status.status-archived { background: var(--status-archived-bg); color: var(--status-archived); }

.agent-detail-section h3 {
    margin: 0 0 12px 0;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.agent-detail-metrics {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.metric-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 6px;
}

.metric-label {
    color: var(--text-secondary);
}

.metric-value {
    font-family: var(--font-mono);
    font-weight: 500;
}

.agent-detail-eisv {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.eisv-bar {
    display: flex;
    align-items: center;
    gap: 8px;
}

.eisv-label {
    width: 16px;
    font-family: var(--font-mono);
    font-weight: 600;
    color: var(--text-secondary);
}

.eisv-bar-track {
    flex: 1;
    height: 8px;
    background: var(--bg-secondary);
    border-radius: 4px;
    overflow: hidden;
}

.eisv-bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s ease;
}

.eisv-bar-fill.energy { background: var(--color-energy); }
.eisv-bar-fill.integrity { background: var(--color-integrity); }
.eisv-bar-fill.entropy { background: var(--color-entropy); }
.eisv-bar-fill.volatility { background: var(--color-void); }

.eisv-value {
    width: 40px;
    text-align: right;
    font-family: var(--font-mono);
    font-size: 0.85rem;
    color: var(--text-secondary);
}

.agent-detail-info {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px 16px;
    margin: 0;
}

.agent-detail-info dt {
    color: var(--text-secondary);
    font-size: 0.85rem;
}

.agent-detail-info dd {
    margin: 0;
}

.agent-detail-info code {
    font-size: 0.8rem;
    word-break: break-all;
}

.agent-detail-actions {
    display: flex;
    gap: 12px;
    padding-top: 16px;
    border-top: 1px solid var(--border-color);
}
```

**Step 4: Make agent cards clickable**

Find the agent card rendering function in `dashboard/dashboard.js` and ensure cards have onclick handlers. In the `renderAgentCard` or equivalent function, the card should have:

```javascript
onclick="Router.navigate('agent/${agent.agent_id}')"
```

Or add a click handler after rendering:

```javascript
// After rendering agent cards, wire up click handlers
document.querySelectorAll('.agent-card').forEach(card => {
    const agentId = card.dataset.agentId;
    if (agentId) {
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => Router.navigate(`agent/${agentId}`));
    }
});
```

**Step 5: Verify agent detail panel**

Run:
1. Click on an agent card
2. Panel should slide in with agent details
3. URL should update to `#agent/{uuid}`
4. Press Escape to close
5. Navigate directly to `#agent/{uuid}` - should open panel

**Step 6: Commit**

```bash
git add dashboard/dashboard.js dashboard/styles.css
git commit -m "feat(dashboard): wire agent cards to open detail slide panel"
```

---

## Phase 3: Agent Detail (Server-Side)

### Task 3.1: Add EISV history endpoint

**Files:**
- Create: `src/mcp_handlers/dashboard_fragments.py`
- Modify: `src/mcp_server.py`

**Step 1: Create dashboard fragments handler module**

Create `src/mcp_handlers/dashboard_fragments.py`:

```python
"""
Dashboard HTML Fragment Handlers

Serves HTML fragments for htmx-powered dashboard updates.
"""

from datetime import datetime, timedelta
from typing import Optional
import html

# Import database and utilities
from src.db.postgres_backend import PostgresBackend
from src.logging_utils import get_logger

logger = get_logger(__name__)


async def get_eisv_history_fragment(
    db: PostgresBackend,
    agent_id: str,
    range_str: str = "24h"
) -> str:
    """
    Get EISV history data as JSON for Chart.js.

    Args:
        db: Database backend
        agent_id: Agent UUID
        range_str: Time range (1h, 24h, 7d, 30d)

    Returns:
        JSON string with chart data
    """
    # Parse range
    range_hours = {
        "1h": 1,
        "24h": 24,
        "7d": 24 * 7,
        "30d": 24 * 30
    }.get(range_str, 24)

    since = datetime.utcnow() - timedelta(hours=range_hours)

    try:
        # Query audit events for this agent
        events = await db.query_audit_events(
            agent_id=agent_id,
            event_type="checkin",
            since=since,
            limit=500
        )

        # Transform to chart data
        labels = []
        energy = []
        integrity = []
        entropy = []
        void_values = []
        coherence = []

        for event in events:
            data = event.get("data", {})
            eisv = data.get("eisv", {})

            labels.append(event.get("timestamp", ""))
            energy.append(eisv.get("E", 0))
            integrity.append(eisv.get("I", 0))
            entropy.append(eisv.get("S", 0))
            void_values.append(eisv.get("V", 0))

            # Calculate coherence: (E + I) / 2 - (S + V) / 4
            e, i, s, v = eisv.get("E", 0), eisv.get("I", 0), eisv.get("S", 0), eisv.get("V", 0)
            coh = (e + i) / 2 - (s + v) / 4
            coherence.append(max(0, min(1, coh)))

        import json
        return json.dumps({
            "labels": labels,
            "datasets": {
                "energy": energy,
                "integrity": integrity,
                "entropy": entropy,
                "void": void_values,
                "coherence": coherence
            }
        })

    except Exception as e:
        logger.error(f"Failed to get EISV history: {e}")
        return '{"error": "Failed to load history"}'


async def get_agent_incidents_fragment(
    db: PostgresBackend,
    agent_id: str,
    limit: int = 20
) -> str:
    """
    Get recent incidents for an agent as HTML.

    Args:
        db: Database backend
        agent_id: Agent UUID
        limit: Max incidents to return

    Returns:
        HTML fragment with incident list
    """
    try:
        # Query significant events
        events = await db.query_audit_events(
            agent_id=agent_id,
            event_type=None,  # All types
            limit=limit
        )

        # Filter to significant events
        significant = []
        for event in events:
            event_type = event.get("event_type", "")
            if event_type in ["governance_decision", "risk_threshold", "pause", "resume", "calibration"]:
                significant.append(event)

        if not significant:
            return '<div class="empty-state"><p>No incidents recorded</p></div>'

        html_parts = ['<div class="incident-list">']
        for event in significant[:10]:
            ts = event.get("timestamp", "")
            event_type = html.escape(event.get("event_type", "unknown"))
            data = event.get("data", {})
            summary = html.escape(data.get("summary", event_type))

            html_parts.append(f'''
                <div class="incident-item incident-{event_type}">
                    <span class="incident-time">{ts}</span>
                    <span class="incident-type">{event_type}</span>
                    <span class="incident-summary">{summary}</span>
                </div>
            ''')
        html_parts.append('</div>')

        return ''.join(html_parts)

    except Exception as e:
        logger.error(f"Failed to get agent incidents: {e}")
        return '<div class="error">Failed to load incidents</div>'
```

**Step 2: Add fragment routes to server**

In `src/mcp_server.py`, find where routes are added (~line 2301) and add:

```python
        # Dashboard fragment routes (for htmx)
        async def http_dashboard_eisv_history(request):
            """Get EISV history data for an agent"""
            agent_id = request.path_params.get("agent_id", "")
            range_str = request.query_params.get("range", "24h")

            from src.mcp_handlers.dashboard_fragments import get_eisv_history_fragment
            data = await get_eisv_history_fragment(db, agent_id, range_str)

            return Response(content=data, media_type="application/json")

        async def http_dashboard_incidents(request):
            """Get incident history for an agent"""
            agent_id = request.path_params.get("agent_id", "")

            from src.mcp_handlers.dashboard_fragments import get_agent_incidents_fragment
            html_content = await get_agent_incidents_fragment(db, agent_id)

            return Response(content=html_content, media_type="text/html")

        # Add routes before the main dashboard routes
        app.routes.append(Route("/dashboard/fragments/eisv-history/{agent_id}", http_dashboard_eisv_history, methods=["GET"]))
        app.routes.append(Route("/dashboard/fragments/incidents/{agent_id}", http_dashboard_incidents, methods=["GET"]))
```

**Step 3: Verify endpoint**

Run:
```bash
curl "http://localhost:8767/dashboard/fragments/eisv-history/test-agent-id?range=24h"
```
Expected: JSON with labels and datasets (may be empty if no data)

**Step 4: Commit**

```bash
git add src/mcp_handlers/dashboard_fragments.py src/mcp_server.py
git commit -m "feat(dashboard): add EISV history and incidents fragment endpoints"
```

---

### Task 3.2: Add EISV trend chart to agent detail panel

**Files:**
- Modify: `dashboard/dashboard.js`

**Step 1: Update renderAgentDetailContent to include chart container**

Find `renderAgentDetailContent` in `dashboard/dashboard.js` and add a chart section:

```javascript
// Add after the EISV Values section in renderAgentDetailContent:

            <div class="agent-detail-section">
                <h3>EISV Trend</h3>
                <div class="eisv-trend-controls">
                    <select id="eisv-trend-range" class="trend-range-select">
                        <option value="1h">Last hour</option>
                        <option value="24h" selected>Last 24h</option>
                        <option value="7d">Last 7 days</option>
                        <option value="30d">Last 30 days</option>
                    </select>
                </div>
                <div class="eisv-trend-chart-container">
                    <canvas id="agent-eisv-trend-chart"></canvas>
                </div>
            </div>
```

**Step 2: Add chart initialization function**

Add to `dashboard/dashboard.js`:

```javascript
let agentTrendChart = null;

/**
 * Load and render EISV trend chart for an agent.
 * @param {string} agentId - Agent UUID
 * @param {string} range - Time range (1h, 24h, 7d, 30d)
 */
async function loadAgentEisvTrend(agentId, range = '24h') {
    try {
        const response = await fetch(`/dashboard/fragments/eisv-history/${agentId}?range=${range}`);
        if (!response.ok) throw new Error('Failed to load EISV history');

        const data = await response.json();
        if (data.error) throw new Error(data.error);

        renderAgentTrendChart(data);
    } catch (e) {
        console.error('Failed to load EISV trend:', e);
        const container = document.querySelector('.eisv-trend-chart-container');
        if (container) {
            container.innerHTML = '<div class="empty-state"><p>Failed to load trend data</p></div>';
        }
    }
}

/**
 * Render the EISV trend chart with Chart.js.
 * @param {Object} data - Chart data from server
 */
function renderAgentTrendChart(data) {
    const canvas = document.getElementById('agent-eisv-trend-chart');
    if (!canvas) return;

    // Destroy existing chart
    if (agentTrendChart) {
        agentTrendChart.destroy();
        agentTrendChart = null;
    }

    const ctx = canvas.getContext('2d');

    // Parse timestamps
    const labels = data.labels.map(ts => new Date(ts));

    agentTrendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Energy',
                    data: data.datasets.energy,
                    borderColor: getComputedStyle(document.documentElement).getPropertyValue('--color-energy').trim(),
                    backgroundColor: 'transparent',
                    tension: 0.3,
                    pointRadius: 0
                },
                {
                    label: 'Integrity',
                    data: data.datasets.integrity,
                    borderColor: getComputedStyle(document.documentElement).getPropertyValue('--color-integrity').trim(),
                    backgroundColor: 'transparent',
                    tension: 0.3,
                    pointRadius: 0
                },
                {
                    label: 'Coherence',
                    data: data.datasets.coherence,
                    borderColor: getComputedStyle(document.documentElement).getPropertyValue('--color-coherence').trim(),
                    backgroundColor: 'transparent',
                    borderDash: [5, 5],
                    tension: 0.3,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        displayFormats: {
                            hour: 'HH:mm',
                            day: 'MMM d'
                        }
                    },
                    grid: { display: false }
                },
                y: {
                    min: 0,
                    max: 1,
                    grid: { color: 'rgba(128,128,128,0.1)' }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}
```

**Step 3: Wire up chart loading when panel opens**

Update `openAgentDetailPanel` to load the chart:

```javascript
function openAgentDetailPanel(agentId) {
    // ... existing code ...

    const content = renderAgentDetailContent(agent);
    openSlidePanel(agent.label || agent.agent_id, content);

    // Load trend chart after panel opens
    setTimeout(() => {
        loadAgentEisvTrend(agentId, '24h');

        // Wire up range selector
        const rangeSelect = document.getElementById('eisv-trend-range');
        if (rangeSelect) {
            rangeSelect.addEventListener('change', (e) => {
                loadAgentEisvTrend(agentId, e.target.value);
            });
        }
    }, 100);
}
```

**Step 4: Add chart container styles**

In `dashboard/styles.css`, add:

```css
.eisv-trend-controls {
    margin-bottom: 12px;
}

.trend-range-select {
    padding: 6px 10px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.85rem;
}

.eisv-trend-chart-container {
    height: 200px;
    position: relative;
}
```

**Step 5: Verify trend chart**

Run:
1. Click on an agent card
2. Panel should show EISV trend chart (may be empty if no historical data)
3. Change range selector - chart should reload

**Step 6: Commit**

```bash
git add dashboard/dashboard.js dashboard/styles.css
git commit -m "feat(dashboard): add EISV trend chart to agent detail panel"
```

---

## Phase 4: Quick Actions

### Task 4.1: Add action buttons to agent detail panel

**Files:**
- Modify: `dashboard/dashboard.js`
- Modify: `dashboard/styles.css`

**Step 1: Update renderAgentDetailContent with action buttons**

In `renderAgentDetailContent`, update the actions section:

```javascript
            <div class="agent-detail-actions">
                ${status === 'active' ? `
                    <button class="action-btn action-pause"
                            onclick="confirmAgentAction('${agent.agent_id}', 'pause')"
                            title="Pause this agent">
                        ⏸ Pause
                    </button>
                ` : ''}
                ${status === 'paused' ? `
                    <button class="action-btn action-resume"
                            onclick="executeAgentAction('${agent.agent_id}', 'resume')"
                            title="Resume this agent">
                        ▶ Resume
                    </button>
                ` : ''}
                ${status !== 'archived' ? `
                    <button class="action-btn action-archive"
                            onclick="confirmAgentAction('${agent.agent_id}', 'archive')"
                            title="Archive this agent">
                        📦 Archive
                    </button>
                ` : ''}
                <button class="action-btn action-secondary"
                        onclick="confirmAgentAction('${agent.agent_id}', 'recalibrate')"
                        title="Recalibrate baseline metrics">
                    🔄 Recalibrate
                </button>
            </div>
```

**Step 2: Add action button styles**

In `dashboard/styles.css`, add:

```css
/* ============================================================================
   QUICK ACTIONS
   ============================================================================ */

.agent-detail-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    padding-top: 16px;
    border-top: 1px solid var(--border-color);
}

.action-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.9rem;
    cursor: pointer;
    transition: all 0.15s ease;
}

.action-btn:hover {
    background: var(--bg-hover);
    border-color: var(--text-tertiary);
}

.action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.action-btn.action-pause {
    border-color: var(--status-paused);
    color: var(--status-paused);
}

.action-btn.action-pause:hover {
    background: var(--status-paused-bg);
}

.action-btn.action-resume {
    border-color: var(--status-active);
    color: var(--status-active);
}

.action-btn.action-resume:hover {
    background: var(--status-active-bg);
}

.action-btn.action-archive {
    border-color: var(--status-archived);
    color: var(--status-archived);
}

.action-btn.action-archive:hover {
    background: var(--status-archived-bg);
}

.action-btn.action-secondary {
    color: var(--text-secondary);
}

/* Loading state */
.action-btn.loading {
    position: relative;
    color: transparent;
}

.action-btn.loading::after {
    content: '';
    position: absolute;
    width: 16px;
    height: 16px;
    border: 2px solid var(--border-color);
    border-top-color: var(--accent-color);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}
```

**Step 3: Add action execution functions**

In `dashboard/dashboard.js`, add:

```javascript
// ============================================================================
// QUICK ACTIONS
// ============================================================================

/**
 * Show confirmation dialog for an agent action.
 * @param {string} agentId - Agent UUID
 * @param {string} action - Action type (pause, archive, recalibrate)
 */
function confirmAgentAction(agentId, action) {
    const messages = {
        pause: 'Pause this agent? It will stop processing tasks until resumed.',
        archive: 'Archive this agent? It will be removed from active governance.',
        recalibrate: 'Recalibrate this agent? This will rebuild baseline metrics from recent history.'
    };

    if (confirm(messages[action] || `Execute ${action}?`)) {
        executeAgentAction(agentId, action);
    }
}

/**
 * Execute an agent action via API.
 * @param {string} agentId - Agent UUID
 * @param {string} action - Action type
 */
async function executeAgentAction(agentId, action) {
    // Find and disable the button
    const btn = document.querySelector(`.action-btn.action-${action}`);
    if (btn) {
        btn.disabled = true;
        btn.classList.add('loading');
    }

    try {
        let toolName, toolArgs;

        switch (action) {
            case 'pause':
                toolName = 'agent';
                toolArgs = { action: 'update', agent_id: agentId, status: 'paused' };
                break;
            case 'resume':
                toolName = 'agent';
                toolArgs = { action: 'update', agent_id: agentId, status: 'active' };
                break;
            case 'archive':
                toolName = 'agent';
                toolArgs = { action: 'archive', agent_id: agentId };
                break;
            case 'recalibrate':
                toolName = 'calibration';
                toolArgs = { action: 'rebuild', agent_id: agentId };
                break;
            default:
                throw new Error(`Unknown action: ${action}`);
        }

        const result = await api.callTool(toolName, toolArgs);

        if (result.error) {
            throw new Error(result.error);
        }

        // Refresh data and re-render panel
        await loadAgents();

        // Re-open panel with updated data
        openAgentDetailPanel(agentId);

        // Show success feedback
        showToast(`Agent ${action} successful`, 'success');

    } catch (e) {
        console.error(`Failed to ${action} agent:`, e);
        showToast(`Failed to ${action}: ${e.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('loading');
        }
    }
}

/**
 * Show a toast notification.
 * @param {string} message - Message to show
 * @param {string} type - 'success' or 'error'
 */
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => toast.classList.add('visible'));

    // Remove after delay
    setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
```

**Step 4: Add toast styles**

In `dashboard/styles.css`, add:

```css
/* Toast notifications */
.toast {
    position: fixed;
    bottom: 20px;
    right: 20px;
    padding: 12px 20px;
    border-radius: 6px;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    transform: translateY(100px);
    opacity: 0;
    transition: transform 0.3s ease, opacity 0.3s ease;
    z-index: 10001;
}

.toast.visible {
    transform: translateY(0);
    opacity: 1;
}

.toast-success {
    border-color: var(--status-active);
    background: var(--status-active-bg);
}

.toast-error {
    border-color: var(--status-error);
    background: var(--status-error-bg);
}
```

**Step 5: Verify actions work**

Run:
1. Open agent detail panel
2. Click Pause button - should show confirmation, then update status
3. Click Resume button - should immediately resume
4. Verify toast notifications appear

**Step 6: Commit**

```bash
git add dashboard/dashboard.js dashboard/styles.css
git commit -m "feat(dashboard): add quick action buttons with confirmation dialogs"
```

---

## Phase 5: Me Mode

### Task 5.1: Add identity detection middleware

**Files:**
- Modify: `src/mcp_server.py`

**Step 1: Add identity extraction to dashboard routes**

In `src/mcp_server.py`, update the dashboard handler to extract agent identity:

```python
        async def http_dashboard(request):
            """Serve the web dashboard with identity context"""
            # Extract agent identity from headers
            agent_name = request.headers.get("X-Agent-Name", "")
            agent_id = request.headers.get("X-Agent-ID", "")

            dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"
            if dashboard_path.exists():
                content = dashboard_path.read_text()

                # Inject identity context into the page
                identity_script = f'''
                <script>
                    window.DASHBOARD_IDENTITY = {{
                        agentName: {json.dumps(agent_name)},
                        agentId: {json.dumps(agent_id)},
                        isAgent: {json.dumps(bool(agent_name or agent_id))}
                    }};
                </script>
                '''

                # Insert before closing </head>
                content = content.replace('</head>', identity_script + '</head>')

                return Response(
                    content=content,
                    media_type="text/html"
                )
            return JSONResponse({
                "error": "Dashboard not found",
                "path": str(dashboard_path)
            }, status_code=404)
```

**Step 2: Commit**

```bash
git add src/mcp_server.py
git commit -m "feat(dashboard): add identity detection from X-Agent-Name header"
```

---

### Task 5.2: Add Alpine identity store and Me mode UI

**Files:**
- Modify: `dashboard/dashboard.js`
- Modify: `dashboard/index.html`
- Modify: `dashboard/styles.css`

**Step 1: Add identity store**

In `dashboard/dashboard.js`, add to the `alpine:init` handler:

```javascript
    // Identity store for Me mode
    Alpine.store('identity', {
        name: window.DASHBOARD_IDENTITY?.agentName || '',
        id: window.DASHBOARD_IDENTITY?.agentId || '',
        isAgent: window.DASHBOARD_IDENTITY?.isAgent || false,
        meMode: false,

        toggleMeMode() {
            this.meMode = !this.meMode;
            // Trigger re-filter of agents
            document.getElementById('agent-search')?.dispatchEvent(new Event('input'));
        },

        // Try to find our agent in the list
        findMyAgent() {
            if (!this.name && !this.id) return null;
            return cachedAgents.find(a =>
                a.agent_id === this.id ||
                a.label?.toLowerCase() === this.name?.toLowerCase()
            );
        }
    });
```

**Step 2: Add Me mode toggle to toolbar**

In `dashboard/index.html`, find the toolbar (~line 32) and add after the theme toggle:

```html
            <div class="me-mode-toggle" x-data x-show="$store.identity.isAgent">
                <button id="me-mode-btn"
                        class="toolbar-button"
                        :class="{ 'active': $store.identity.meMode }"
                        @click="$store.identity.toggleMeMode()"
                        type="button">
                    <span x-text="$store.identity.meMode ? '👤 Me' : '👥 All'"></span>
                </button>
                <span class="me-mode-name" x-show="$store.identity.meMode" x-text="$store.identity.name"></span>
            </div>
```

**Step 3: Add Me mode styles**

In `dashboard/styles.css`, add:

```css
/* ============================================================================
   ME MODE
   ============================================================================ */

.me-mode-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
}

.me-mode-toggle .toolbar-button.active {
    background: var(--accent-color);
    color: white;
    border-color: var(--accent-color);
}

.me-mode-name {
    font-size: 0.85rem;
    color: var(--text-secondary);
    font-weight: 500;
}

/* Highlight own agent card in Me mode */
.agent-card.is-me {
    border-color: var(--accent-color);
    box-shadow: 0 0 0 2px rgba(var(--accent-rgb), 0.2);
}

.agent-card.is-me::before {
    content: '👤 You';
    position: absolute;
    top: -10px;
    right: 12px;
    padding: 2px 8px;
    background: var(--accent-color);
    color: white;
    font-size: 0.75rem;
    border-radius: 4px;
}

/* In Me mode, dim other agents */
body.me-mode-active .agent-card:not(.is-me) {
    opacity: 0.5;
}

body.me-mode-active .agent-card.is-me {
    opacity: 1;
}
```

**Step 4: Update agent card rendering to mark own card**

In the agent card rendering logic, add the `is-me` class when appropriate:

```javascript
// When rendering agent cards, check if it's the current agent
const isMe = Alpine.store('identity').isAgent && (
    agent.agent_id === Alpine.store('identity').id ||
    agent.label?.toLowerCase() === Alpine.store('identity').name?.toLowerCase()
);

// Add to card class
const cardClass = `agent-card ${isMe ? 'is-me' : ''}`;
```

**Step 5: Update body class when Me mode is toggled**

Add to the identity store's `toggleMeMode`:

```javascript
toggleMeMode() {
    this.meMode = !this.meMode;
    document.body.classList.toggle('me-mode-active', this.meMode);
    // Trigger re-filter of agents
    document.getElementById('agent-search')?.dispatchEvent(new Event('input'));
}
```

**Step 6: Verify Me mode**

Run:
1. Add `X-Agent-Name: Test-Agent` header when accessing dashboard
2. Toggle should appear in toolbar
3. Click toggle - should highlight matching agent card
4. Other cards should dim

**Step 7: Commit**

```bash
git add dashboard/dashboard.js dashboard/index.html dashboard/styles.css
git commit -m "feat(dashboard): add Me mode for agent self-view"
```

---

## Phase 6: Polish

### Task 6.1: Add smart empty states

**Files:**
- Modify: `dashboard/dashboard.js`
- Modify: `dashboard/styles.css`

**Step 1: Create empty state renderer**

In `dashboard/dashboard.js`, add:

```javascript
/**
 * Render an empty state with helpful context.
 * @param {string} type - Type of empty state
 * @param {Object} context - Additional context
 * @returns {string} HTML
 */
function renderEmptyState(type, context = {}) {
    const states = {
        'no-agents': {
            icon: '🤖',
            title: 'No agents yet',
            description: 'Agents will appear here when they connect to governance.',
            hint: 'Agents check in when they start processing tasks.'
        },
        'no-agents-filtered': {
            icon: '🔍',
            title: 'No matching agents',
            description: `No agents match "${context.query || 'your search'}".`,
            hint: 'Try a different search term or clear filters.',
            action: '<button onclick="clearAgentFilters()" class="empty-state-action">Clear filters</button>'
        },
        'no-discoveries': {
            icon: '💡',
            title: 'No discoveries yet',
            description: 'Knowledge discoveries appear when agents learn something new.',
            hint: helpData?.status?.discovery?.long || 'Discoveries include insights, patterns, and questions.'
        },
        'no-stuck-agents': {
            icon: '✅',
            title: 'No stuck agents',
            description: 'All agents are checking in normally.',
            hint: 'Agents are considered "stuck" if they haven\'t checked in for 30+ minutes.'
        },
        'chart-no-data': {
            icon: '📊',
            title: 'No data yet',
            description: 'Chart data will appear after the first agent check-in.',
            hint: 'EISV metrics are recorded with each governance check-in.'
        },
        'panel-loading': {
            icon: '⏳',
            title: 'Loading...',
            description: 'Fetching data from the server.',
            hint: ''
        },
        'panel-error': {
            icon: '⚠️',
            title: 'Failed to load',
            description: context.error || 'An error occurred.',
            hint: 'Try refreshing the page or check the server connection.',
            action: '<button onclick="location.reload()" class="empty-state-action">Refresh</button>'
        }
    };

    const state = states[type] || {
        icon: '📭',
        title: 'Nothing here',
        description: '',
        hint: ''
    };

    return `
        <div class="empty-state">
            <div class="empty-state-icon">${state.icon}</div>
            <div class="empty-state-title">${state.title}</div>
            ${state.description ? `<div class="empty-state-description">${state.description}</div>` : ''}
            ${state.hint ? `<div class="empty-state-hint">${state.hint}</div>` : ''}
            ${state.action || ''}
        </div>
    `;
}
```

**Step 2: Add empty state styles**

In `dashboard/styles.css`, add:

```css
/* ============================================================================
   EMPTY STATES
   ============================================================================ */

.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 40px 20px;
    text-align: center;
    color: var(--text-secondary);
}

.empty-state-icon {
    font-size: 2.5rem;
    margin-bottom: 12px;
    opacity: 0.7;
}

.empty-state-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 8px;
}

.empty-state-description {
    font-size: 0.9rem;
    max-width: 300px;
    line-height: 1.5;
}

.empty-state-hint {
    margin-top: 12px;
    font-size: 0.8rem;
    color: var(--text-tertiary);
    max-width: 280px;
}

.empty-state-action {
    margin-top: 16px;
    padding: 8px 16px;
    background: var(--accent-color);
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 0.9rem;
    cursor: pointer;
    transition: background 0.15s ease;
}

.empty-state-action:hover {
    background: var(--accent-hover);
}
```

**Step 3: Use empty states in agent list rendering**

Update the agent list rendering to use the empty state:

```javascript
// When no agents match filters:
if (filteredAgents.length === 0) {
    const searchQuery = document.getElementById('agent-search')?.value;
    if (searchQuery || hasActiveFilters()) {
        container.innerHTML = renderEmptyState('no-agents-filtered', { query: searchQuery });
    } else {
        container.innerHTML = renderEmptyState('no-agents');
    }
    return;
}
```

**Step 4: Commit**

```bash
git add dashboard/dashboard.js dashboard/styles.css
git commit -m "feat(dashboard): add smart empty states with helpful context"
```

---

### Task 6.2: Add loading skeletons

**Files:**
- Modify: `dashboard/styles.css`
- Modify: `dashboard/dashboard.js`

**Step 1: Add skeleton styles**

In `dashboard/styles.css`, add:

```css
/* ============================================================================
   LOADING SKELETONS
   ============================================================================ */

.skeleton {
    background: linear-gradient(
        90deg,
        var(--bg-secondary) 25%,
        var(--bg-hover) 50%,
        var(--bg-secondary) 75%
    );
    background-size: 200% 100%;
    animation: skeleton-shimmer 1.5s infinite;
    border-radius: 4px;
}

@keyframes skeleton-shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

.skeleton-card {
    height: 120px;
    border-radius: 8px;
}

.skeleton-row {
    height: 20px;
    margin-bottom: 8px;
}

.skeleton-row:last-child {
    margin-bottom: 0;
    width: 60%;
}

.skeleton-chart {
    height: 200px;
    border-radius: 8px;
}

.skeleton-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
}
```

**Step 2: Add skeleton rendering function**

In `dashboard/dashboard.js`, add:

```javascript
/**
 * Render loading skeletons.
 * @param {string} type - Type of skeleton (card, list, chart)
 * @param {number} count - Number of items for list type
 * @returns {string} HTML
 */
function renderSkeleton(type, count = 3) {
    switch (type) {
        case 'card':
            return '<div class="skeleton skeleton-card"></div>';
        case 'list':
            return `<div class="skeleton-list">
                ${Array(count).fill('<div class="skeleton skeleton-card"></div>').join('')}
            </div>`;
        case 'chart':
            return '<div class="skeleton skeleton-chart"></div>';
        case 'rows':
            return `<div>
                ${Array(count).fill('<div class="skeleton skeleton-row"></div>').join('')}
            </div>`;
        default:
            return '<div class="skeleton skeleton-card"></div>';
    }
}
```

**Step 3: Use skeletons during loading**

Update loading states to show skeletons:

```javascript
// Example: Before loading agents
document.getElementById('agents-container').innerHTML = renderSkeleton('list', 5);

// Example: In slide panel before content loads
panelBody.innerHTML = renderSkeleton('rows', 8);
```

**Step 4: Commit**

```bash
git add dashboard/styles.css dashboard/dashboard.js
git commit -m "feat(dashboard): add loading skeleton animations"
```

---

### Task 6.3: Add error handling for failed actions

**Files:**
- Modify: `dashboard/dashboard.js`

**Step 1: Enhance error handling in API calls**

Update the `DashboardAPI` class in `utils.js` or add to `dashboard.js`:

```javascript
/**
 * Wrap API calls with error handling and retry logic.
 * @param {Function} fn - Async function to wrap
 * @param {Object} options - Options (retries, onError)
 * @returns {Function} Wrapped function
 */
function withErrorHandling(fn, options = {}) {
    const { retries = 2, onError } = options;

    return async function(...args) {
        let lastError;

        for (let attempt = 0; attempt <= retries; attempt++) {
            try {
                return await fn.apply(this, args);
            } catch (e) {
                lastError = e;

                // Don't retry on 4xx errors
                if (e.status >= 400 && e.status < 500) {
                    break;
                }

                // Wait before retry
                if (attempt < retries) {
                    await new Promise(r => setTimeout(r, Math.pow(2, attempt) * 500));
                }
            }
        }

        // All retries failed
        if (onError) {
            onError(lastError);
        } else {
            showToast(`Operation failed: ${lastError.message}`, 'error');
        }

        throw lastError;
    };
}
```

**Step 2: Add connection status indicator update**

```javascript
/**
 * Update connection status indicator based on API health.
 */
async function checkConnectionHealth() {
    const statusEl = document.getElementById('ws-status');
    const dotEl = statusEl?.querySelector('.ws-dot');
    const labelEl = statusEl?.querySelector('.ws-label');

    try {
        const response = await fetch('/health', { timeout: 5000 });
        if (response.ok) {
            dotEl?.classList.remove('disconnected');
            dotEl?.classList.add('connected');
            labelEl.textContent = 'Online';
            statusEl.title = 'Connected to server';
        } else {
            throw new Error('Health check failed');
        }
    } catch (e) {
        dotEl?.classList.remove('connected');
        dotEl?.classList.add('disconnected');
        labelEl.textContent = 'Offline';
        statusEl.title = 'Connection lost — retrying...';
    }
}

// Check connection periodically
setInterval(checkConnectionHealth, 30000);
```

**Step 3: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "feat(dashboard): enhance error handling with retries and status indicator"
```

---

## Verification Checklist

After completing all tasks, verify:

- [ ] htmx and Alpine.js load without errors
- [ ] Tooltips appear on hover for all EISV/metric labels
- [ ] Keyboard shortcuts work (/, Esc, j, k, Enter, ?)
- [ ] Hash routing works (#agent/uuid opens panel)
- [ ] Slide panel opens and closes smoothly
- [ ] Scoped search filters agents correctly
- [ ] Agent detail panel shows EISV trend chart
- [ ] Quick actions (pause/resume/archive) work with confirmations
- [ ] Me mode toggle appears for agents and highlights their card
- [ ] Empty states show helpful messages
- [ ] Loading skeletons appear during data fetches
- [ ] Error toasts appear on failures
- [ ] Mobile responsive behavior works

---

## Total Implementation Scope

- **Phase 1: Foundation** - 7 tasks
- **Phase 2: Navigation** - 4 tasks
- **Phase 3: Agent Detail** - 2 tasks
- **Phase 4: Quick Actions** - 1 task
- **Phase 5: Me Mode** - 2 tasks
- **Phase 6: Polish** - 3 tasks

**Total: 19 tasks**
