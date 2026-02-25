/**
 * UNITARES Governance Dashboard
 *
 * Main application logic. Depends on:
 * - utils.js (DashboardAPI, DataProcessor)
 * - components.js (ThemeManager)
 * - Chart.js (visualizations)
 */

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

// State bridges — route globals through state.js for module access
// Each property getter/setter delegates to state.get()/state.set()
// so existing code like `cachedAgents = x` still works transparently.
if (typeof state !== 'undefined') {
    ['refreshFailures', 'autoRefreshPaused', 'previousStats',
     'cachedAgents', 'cachedDiscoveries', 'cachedStuckAgents',
     'cachedDialecticSessions', 'eisvChartUpper', 'eisvChartLower',
     'eisvWebSocket', 'agentEISVHistory', 'knownAgents',
     'selectedAgentView', 'lastVitalsTimestamp', 'recentDecisions'
    ].forEach(function (key) {
        Object.defineProperty(window, key, {
            get: function () { return state.get(key); },
            set: function (v) { var u = {}; u[key] = v; state.set(u); },
            configurable: true
        });
    });
}

// ============================================================================
// MODAL FUNCTIONS
// ============================================================================
let modalTriggerElement = null;

/**
 * Expand a panel into a modal view.
 * @param {'discoveries'|'dialectic'|'stuck-agents'} panelType - Panel to expand
 */
function expandPanel(panelType) {
    modalTriggerElement = document.activeElement;
    const modal = document.getElementById('panel-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');

    if (panelType === 'discoveries') {
        modalTitle.textContent = `Recent Discoveries (${cachedDiscoveries.length})`;
        modalBody.innerHTML = renderDiscoveriesForModal(cachedDiscoveries);
    } else if (panelType === 'dialectic') {
        modalTitle.textContent = `Dialectic Sessions (${cachedDialecticSessions.length})`;
        modalBody.innerHTML = renderDialecticForModal(cachedDialecticSessions);
    } else if (panelType === 'stuck-agents') {
        modalTitle.textContent = `Stuck Agents (${cachedStuckAgents.length})`;
        modalBody.innerHTML = renderStuckAgentsForModal(cachedStuckAgents);
    }

    modal.classList.add('visible');
    document.body.style.overflow = 'hidden';

    // Focus first focusable element in modal
    const firstFocusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (firstFocusable) firstFocusable.focus();
}

/**
 * Close the modal and return focus to trigger element.
 */
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

/**
 * Trap focus within modal when open.
 * @param {KeyboardEvent} e
 */
function trapFocus(e) {
    const modal = document.getElementById('panel-modal');
    if (!modal || !modal.classList.contains('visible')) return;
    if (e.key !== 'Tab') return;

    const focusableEls = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (focusableEls.length === 0) return;

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

// Close modal on escape or click outside
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});
document.getElementById('panel-modal')?.addEventListener('click', (e) => {
    if (e.target.classList.contains('panel-modal-overlay')) closeModal();
});
// Close button handler
document.querySelector('.panel-modal-close')?.addEventListener('click', closeModal);

/**
 * Render discoveries list for modal view.
 * @param {Array<Object>} discoveries - Discovery objects from API
 * @returns {string} HTML string
 */
function renderDiscoveriesForModal(discoveries) {
    if (!discoveries || discoveries.length === 0) {
        return '<div class="loading">No discoveries found</div>';
    }

    return `<div class="discoveries-list">${discoveries.map(d => {
        const type = d.type || d.discovery_type || 'note';
        const summary = d.summary || d.title || 'Untitled';
        const content = d.content || d.details || '';
        const agent = d.agent_id || d.agent || 'Unknown';
        const time = d.timestamp || d.created_at || '';

        return `
            <div class="discovery-item">
                <div class="discovery-header">
                    <span class="discovery-type">${escapeHtml(type)}</span>
                    <span class="discovery-time">${escapeHtml(time)}</span>
                </div>
                <div class="discovery-summary">${escapeHtml(summary)}</div>
                ${content ? `<div class="discovery-content" style="margin-top: 8px; font-size: 0.9em; color: var(--text-secondary);">${escapeHtml(content)}</div>` : ''}
                <div class="discovery-meta" style="margin-top: 8px; font-size: 0.8em; color: var(--text-secondary);">
                    Agent: ${escapeHtml(agent.length > 20 ? agent.substring(0, 20) + '...' : agent)}
                </div>
            </div>
        `;
    }).join('')}</div>`;
}

function renderDialecticForModal(sessions) {
    if (!sessions || sessions.length === 0) {
        return '<div class="loading">No dialectic sessions found</div>';
    }

    return `<div class="dialectic-list">${sessions.map(session => {
        const phase = session.phase || session.status || 'unknown';
        const phaseColor = getPhaseColor(phase);
        const requestorId = session.paused_agent || session.requestor_id || 'Unknown';
        const reviewerId = session.reviewer || session.reviewer_id || 'None';
        const sessionType = session.session_type || session.type || 'verification';
        const topic = session.topic || session.reason || `${sessionType} session`;
        const created = session.created || session.created_at || '';
        const sessionId = session.session_id || 'unknown';

        return `
            <div class="dialectic-item ${phase}">
                <div class="dialectic-header">
                    <span class="dialectic-type" style="border-color: ${phaseColor}; color: ${phaseColor}">
                        ${escapeHtml(formatDialecticPhase(phase))}
                    </span>
                    <span class="dialectic-session-type">${escapeHtml(sessionType)}</span>
                    <span class="dialectic-time">${escapeHtml(created)}</span>
                </div>
                <div class="dialectic-topic">${escapeHtml(topic)}</div>
                <div class="dialectic-agents">
                    <span class="agent-label">Session:</span> ${escapeHtml(sessionId)}
                </div>
                <div class="dialectic-agents" style="margin-top: 4px;">
                    <span class="agent-label">Requestor:</span> ${escapeHtml(requestorId)}
                    ${reviewerId && reviewerId !== 'None' ? `<span class="agent-label">Reviewer:</span> ${escapeHtml(reviewerId)}` : ''}
                </div>
            </div>
        `;
    }).join('')}</div>`;
}

function renderStuckAgentsForModal(agents) {
    if (!agents || agents.length === 0) {
        return '<div class="stuck-agents-empty"><span class="stuck-agents-empty-icon">✓</span>No stuck agents detected</div>';
    }

    const getAgentData = (id) => cachedAgents.find(a => a.agent_id === id);

    const formatAge = (minutes) => {
        if (minutes < 60) return `${minutes.toFixed(0)}m`;
        if (minutes < 1440) return `${(minutes / 60).toFixed(1)}h`;
        return `${(minutes / 1440).toFixed(1)}d`;
    };

    const reasonConfig = {
        'activity_timeout': { label: 'Inactive', icon: '⏸', color: 'var(--text-muted)', severity: 'low' },
        'critical_margin_timeout': { label: 'Critical', icon: '⚠', color: 'var(--color-volatility)', severity: 'high' },
        'tight_margin_timeout': { label: 'Tight Margin', icon: '◐', color: 'var(--color-entropy)', severity: 'medium' }
    };

    return `<div class="stuck-agents-list">${agents.map(stuck => {
        const agentData = getAgentData(stuck.agent_id);
        const name = agentData?.name || agentData?.label || stuck.agent_id.substring(0, 10) + '...';
        const age = formatAge(stuck.age_minutes);
        const config = reasonConfig[stuck.reason] || { label: stuck.reason, icon: '?', color: 'var(--text-muted)', severity: 'low' };

        // Get additional details from cached agent data
        const metrics = agentData?.metrics || {};
        const coherence = metrics.coherence !== undefined ? (metrics.coherence * 100).toFixed(0) + '%' : '—';
        const risk = metrics.risk_score !== undefined ? (metrics.risk_score * 100).toFixed(0) + '%' : '—';
        const updates = agentData?.total_updates || '—';
        const trustTier = agentData?.trust_tier || 0;
        const tierNames = ['Unknown', 'Emerging', 'Established', 'Verified'];
        const tierName = tierNames[trustTier] || 'Unknown';
        const lastUpdate = agentData?.last_update ? new Date(agentData.last_update).toLocaleString() : '—';
        const purpose = agentData?.purpose || '—';

        return `
            <div class="stuck-agent-card stuck-agent-${config.severity}" data-agent-id="${escapeHtml(stuck.agent_id)}">
                <div class="stuck-agent-header">
                    <div class="stuck-agent-identity">
                        <span class="stuck-agent-icon" style="color: ${config.color}">${config.icon}</span>
                        <span class="stuck-agent-name">${escapeHtml(name)}</span>
                        <span class="stuck-agent-badge" style="background: ${config.color}20; color: ${config.color}; border: 1px solid ${config.color}40">${config.label}</span>
                    </div>
                    <div class="stuck-agent-actions">
                        <button class="stuck-agent-view-btn" data-agent-id="${escapeHtml(stuck.agent_id)}" title="View agent details">
                            <span>Details</span>
                        </button>
                        <button class="stuck-agent-resume-btn" data-agent-id="${escapeHtml(stuck.agent_id)}" title="Clear stuck status and resume this agent">
                            <span>Unstick</span>
                        </button>
                        <button class="stuck-agent-archive-btn" data-agent-id="${escapeHtml(stuck.agent_id)}" title="Archive this stuck agent">
                            <span>Archive</span>
                        </button>
                    </div>
                </div>
                <div class="stuck-agent-metrics">
                    <div class="stuck-metric">
                        <span class="stuck-metric-label">Stuck</span>
                        <span class="stuck-metric-value stuck-metric-time">${age}</span>
                    </div>
                    <div class="stuck-metric">
                        <span class="stuck-metric-label">Coherence</span>
                        <span class="stuck-metric-value">${coherence}</span>
                    </div>
                    <div class="stuck-metric">
                        <span class="stuck-metric-label">Risk</span>
                        <span class="stuck-metric-value">${risk}</span>
                    </div>
                    <div class="stuck-metric">
                        <span class="stuck-metric-label">Updates</span>
                        <span class="stuck-metric-value">${updates}</span>
                    </div>
                    <div class="stuck-metric">
                        <span class="stuck-metric-label">Trust</span>
                        <span class="stuck-metric-value">${tierName}</span>
                    </div>
                </div>
                ${purpose !== '—' ? `<div class="stuck-agent-purpose">${escapeHtml(purpose)}</div>` : ''}
                <div class="stuck-agent-details">
                    <span class="stuck-agent-detail-item" title="Details">${escapeHtml(stuck.details || '')}</span>
                </div>
                <div class="stuck-agent-footer">
                    <span class="stuck-agent-id" title="Click to copy">${escapeHtml(stuck.agent_id)}</span>
                    <span class="stuck-agent-last-update">Last: ${lastUpdate}</span>
                </div>
            </div>`;
    }).join('')}</div>`;
}

// Archive stuck agent handler
async function archiveStuckAgent(agentId) {
    try {
        const result = await callTool('archive_agent', {
            agent_id: agentId,
            reason: 'Archived from dashboard - stuck agent'
        });
        if (result && result.success) {
            // Remove from cached stuck agents
            cachedStuckAgents = cachedStuckAgents.filter(a => a.agent_id !== agentId);
            // Refresh the modal
            const modalBody = document.getElementById('modal-body');
            const modalTitle = document.getElementById('modal-title');
            if (modalBody && modalTitle) {
                modalTitle.textContent = `Stuck Agents (${cachedStuckAgents.length})`;
                modalBody.innerHTML = renderStuckAgentsForModal(cachedStuckAgents);
            }
            // Refresh agents list
            loadAgents();
            loadStuckAgents();
            return true;
        }
        return false;
    } catch (error) {
        console.error('Failed to archive agent:', error);
        return false;
    }
}

// Resume/unstick stuck agent handler
async function resumeStuckAgent(agentId) {
    try {
        // Check if agent is active (stuck) vs paused — active agents need unstick flag
        const agentData = cachedAgents.find(a => a.agent_id === agentId);
        const isActive = agentData && (agentData.lifecycle_status === 'active' || agentData.status === 'active');
        const result = await callTool('agent', {
            action: 'resume',
            agent_id: agentId,
            reason: isActive ? 'Unstuck from dashboard' : 'Resumed from dashboard',
            unstick: isActive ? true : undefined
        });
        if (result && result.success) {
            // Remove from cached stuck agents
            cachedStuckAgents = cachedStuckAgents.filter(a => a.agent_id !== agentId);
            // Refresh the modal
            const modalBody = document.getElementById('modal-body');
            const modalTitle = document.getElementById('modal-title');
            if (modalBody && modalTitle) {
                modalTitle.textContent = `Stuck Agents (${cachedStuckAgents.length})`;
                modalBody.innerHTML = renderStuckAgentsForModal(cachedStuckAgents);
            }
            // Refresh agents list
            loadAgents();
            loadStuckAgents();
            return true;
        }
        return false;
    } catch (error) {
        console.error('Failed to resume agent:', error);
        return false;
    }
}

// Event delegation for stuck agents modal
document.addEventListener('click', async (event) => {
    // Handle resume button
    const resumeBtn = event.target.closest('.stuck-agent-resume-btn');
    if (resumeBtn) {
        event.stopPropagation();
        const agentId = resumeBtn.getAttribute('data-agent-id');
        if (!agentId) return;

        resumeBtn.disabled = true;
        resumeBtn.innerHTML = '<span>...</span>';

        const success = await resumeStuckAgent(agentId);
        if (!success) {
            resumeBtn.disabled = false;
            resumeBtn.innerHTML = '<span>Failed</span>';
            setTimeout(() => {
                resumeBtn.innerHTML = '<span>Resume</span>';
            }, CONFIG.SCROLL_FEEDBACK_MS);
        }
        return;
    }

    // Handle archive button
    const archiveBtn = event.target.closest('.stuck-agent-archive-btn');
    if (archiveBtn) {
        event.stopPropagation();
        const agentId = archiveBtn.getAttribute('data-agent-id');
        if (!agentId) return;

        archiveBtn.disabled = true;
        archiveBtn.innerHTML = '<span>...</span>';

        const success = await archiveStuckAgent(agentId);
        if (!success) {
            archiveBtn.disabled = false;
            archiveBtn.innerHTML = '<span>Failed</span>';
            setTimeout(() => {
                archiveBtn.innerHTML = '<span>Archive</span>';
            }, CONFIG.SCROLL_FEEDBACK_MS);
        }
        return;
    }

    // Handle view details button
    const viewBtn = event.target.closest('.stuck-agent-view-btn');
    if (viewBtn) {
        event.stopPropagation();
        const agentId = viewBtn.getAttribute('data-agent-id');
        if (!agentId) return;

        const agent = cachedAgents.find(a => a.agent_id === agentId);
        if (agent) {
            closeModal();
            setTimeout(() => showAgentDetail(agent), 100);
        }
        return;
    }

    // Handle ID copy
    const idEl = event.target.closest('.stuck-agent-id');
    if (idEl) {
        const id = idEl.textContent;
        try {
            await navigator.clipboard.writeText(id);
            const original = idEl.textContent;
            idEl.textContent = 'Copied!';
            setTimeout(() => { idEl.textContent = original; }, CONFIG.COPY_FEEDBACK_MS);
        } catch (e) {
            console.error('Copy failed:', e);
        }
        return;
    }
});

// ============================================================================
// API & UTILITY WRAPPERS
// ============================================================================

async function callTool(toolName, toolArguments = {}, options = {}) {
    return api.callTool(toolName, toolArguments, options);
}

// Re-export DataProcessor utilities for convenience
const escapeHtml = DataProcessor.escapeHtml;
const highlightMatch = DataProcessor.highlightMatch;
const copyToClipboard = DataProcessor.copyToClipboard;
const formatRelativeTime = DataProcessor.formatRelativeTime;
const formatTimestamp = DataProcessor.formatTimestamp;

// ============================================================================
// UI HELPERS
// ============================================================================

/** Strip dashboard-internal keys (prefixed with _) from objects before display. */
function filterInternalKeys(obj) {
    if (!obj || typeof obj !== 'object') return obj;
    return Object.fromEntries(
        Object.entries(obj).filter(([k]) => !k.startsWith('_'))
    );
}

function showError(message) {
    const container = document.getElementById('error-container');
    container.innerHTML = `<div class="error">Error: ${escapeHtml(message)}</div>`;
}

function clearError() {
    document.getElementById('error-container').innerHTML = '';
}

function formatChange(current, previous) {
    if (previous === undefined || previous === null) return '';
    const diff = current - previous;
    if (diff === 0) return '';
    const arrow = diff > 0 ? '▲' : '▼';
    const dir = diff > 0 ? 'up' : 'down';
    const sign = diff > 0 ? '+' : '';
    return `<span class="change-arrow ${dir}">${arrow}</span><span class="change-arrow ${dir}">${sign}${diff}</span>`;
}

function updateConnectionBanner(hasError) {
    const banner = document.getElementById('connection-banner');
    if (!banner) return;
    if (hasError) {
        refreshFailures += 1;
    } else {
        // Reset on success, but only if we had failures
        if (refreshFailures > 0) {
            refreshFailures = Math.max(0, refreshFailures - 1); // Decay failures gradually
        }
    }

    // Only show banner after multiple consecutive failures
    if (refreshFailures >= CONFIG.MAX_REFRESH_FAILURES) {
        banner.textContent = `Connection issues detected (${refreshFailures} failures). Check server status or network. Click "Refresh now" to retry.`;
        banner.classList.remove('hidden');
    } else {
        banner.classList.add('hidden');
    }
}

function updateRefreshStatus() {
    const status = document.getElementById('refresh-status');
    if (!status) return;
    status.textContent = autoRefreshPaused
        ? 'Auto-refresh paused'
        : `Auto-refresh every ${Math.round(CONFIG.REFRESH_INTERVAL_MS / 1000)} seconds`;
}

// Agent utilities, rendering, filtering, detail modal, and export
// are now in agents.js → AgentsModule
var getAgentStatus = AgentsModule.getAgentStatus;
var getAgentDisplayName = AgentsModule.getAgentDisplayName;
var agentHasMetrics = AgentsModule.agentHasMetrics;
var formatStatusLabel = AgentsModule.formatStatusLabel;
var updateStatusLegend = AgentsModule.updateStatusLegend;
var updateAgentFilterInfo = AgentsModule.updateAgentFilterInfo;
var applyAgentFilters = AgentsModule.applyAgentFilters;
var clearAgentFilters = AgentsModule.clearAgentFilters;
var showAgentDetail = AgentsModule.showAgentDetail;
var exportAgents = AgentsModule.exportAgents;

// Discovery utilities, rendering, filtering, detail modal, and export
// are now in discoveries.js → DiscoveriesModule
var normalizeDiscoveryType = DiscoveriesModule.normalizeDiscoveryType;
var formatDiscoveryType = DiscoveriesModule.formatDiscoveryType;
var updateDiscoveryFilterInfo = DiscoveriesModule.updateDiscoveryFilterInfo;
var updateDiscoveryLegend = DiscoveriesModule.updateDiscoveryLegend;
var applyDiscoveryFilters = DiscoveriesModule.applyDiscoveryFilters;
var clearDiscoveryFilters = DiscoveriesModule.clearDiscoveryFilters;
var showDiscoveryDetail = DiscoveriesModule.showDiscoveryDetail;
var exportDiscoveries = DiscoveriesModule.exportDiscoveries;

// ============================================================================
// DATA LOADING
// ============================================================================

/**
 * Load agents from API and render to panel.
 * Updates cachedAgents and stats.
 * @returns {Promise<void>}
 */
async function loadAgents() {
    try {
        console.log('Loading agents...');
        // Use unified agent() tool with action='list'
        const result = await callTool('agent', {
            action: 'list',
            include_metrics: true,
            recent_days: 30,
            limit: 100,
            min_updates: 0
        });

        console.log('Agents loaded:', result ? (result.summary?.total || 'ok') : 'null');

        // Handle null/undefined result
        if (!result) {
            throw new Error('No response from server');
        }

        // Handle rate limit errors gracefully - don't count as failure
        if (result.error && result.error.includes('rate limit')) {
            console.warn('Rate limit hit, will retry on next refresh');
            // Keep existing data, don't clear cache
            return true; // Return true to not trigger connection banner
        }

        // Check for error response
        if (result.error) {
            throw new Error(result.error);
        }

        // Handle case where result might be an array (unexpected format)
        if (Array.isArray(result)) {
            console.warn('Unexpected array response, converting to expected format');
            const agentsObj = {
                active: result.filter(a => (a.lifecycle_status || a.status) === 'active'),
                waiting_input: result.filter(a => (a.lifecycle_status || a.status) === 'waiting_input'),
                paused: result.filter(a => (a.lifecycle_status || a.status) === 'paused'),
                archived: result.filter(a => (a.lifecycle_status || a.status) === 'archived'),
                deleted: result.filter(a => (a.lifecycle_status || a.status) === 'deleted'),
                unknown: result.filter(a => !['active', 'waiting_input', 'paused', 'archived', 'deleted'].includes(a.lifecycle_status || a.status))
            };
            const summary = {
                total: result.length,
                by_status: {
                    active: agentsObj.active.length,
                    waiting_input: agentsObj.waiting_input.length,
                    paused: agentsObj.paused.length,
                    archived: agentsObj.archived.length,
                    deleted: agentsObj.deleted.length,
                    unknown: agentsObj.unknown.length
                }
            };
            result = { agents: agentsObj, summary: summary };
        }

        // Parse the actual API response format
        // list_agents returns: { agents: { active: [], waiting_input: [], ... }, summary: { total: N, ... } }
        const agentsObj = result.agents || {};
        const summary = result.summary || {};
        const byStatus = summary.by_status || {};

        // Use summary counts (accurate) not array lengths (limited by pagination)
        const total = summary.total || 0;
        const active = (byStatus.active || 0) + (byStatus.waiting_input || 0);
        const paused = byStatus.paused || 0;
        const archived = byStatus.archived || 0;
        const deleted = byStatus.deleted || 0;
        const unknown = byStatus.unknown || 0;

        updateStatusLegend({
            active: byStatus.active || 0,
            waiting_input: byStatus.waiting_input || 0,
            paused,
            archived,
            deleted,
            unknown
        });

        // Flatten agents from all status categories (for display only)
        const allAgents = [
            ...(agentsObj.active || []),
            ...(agentsObj.waiting_input || []),
            ...(agentsObj.paused || []),
            ...(agentsObj.archived || []),
            ...(agentsObj.deleted || []),
            ...(agentsObj.unknown || [])
        ];

        // Update stats with animated counters
        animateValue(document.getElementById('total-agents'), total);
        animateValue(document.getElementById('active-agents'), active);

        const agentsChange = formatChange(total, previousStats.totalAgents);
        // Show breakdown: active, paused, archived, deleted, unknown
        const breakdown = [];
        if (active > 0) breakdown.push(`${active} active`);
        if (paused > 0) breakdown.push(`${paused} paused`);
        if (archived > 0) breakdown.push(`${archived} archived`);
        if (deleted > 0) breakdown.push(`${deleted} deleted`);
        if (unknown > 0) breakdown.push(`${unknown} unknown`);
        document.getElementById('agents-change').innerHTML = agentsChange || (total > 0 ? breakdown.join(', ') || 'All agents' : 'No agents yet');

        const activeChange = formatChange(active, previousStats.activeAgents);
        // Show what's not active
        const inactiveBreakdown = [];
        if (paused > 0) inactiveBreakdown.push(`${paused} paused`);
        if (archived > 0) inactiveBreakdown.push(`${archived} archived`);
        if (deleted > 0) inactiveBreakdown.push(`${deleted} deleted`);
        document.getElementById('active-change').innerHTML = activeChange || (total > 0 ? (inactiveBreakdown.join(', ') || 'All active') : 'Start by calling onboard()');

        previousStats.totalAgents = total;
        previousStats.activeAgents = active;

        // Fleet health stat card — computed from loaded agent data
        const fleetCoherenceEl = document.getElementById('fleet-coherence');
        const fleetDetailEl = document.getElementById('fleet-health-detail');
        if (fleetCoherenceEl && fleetDetailEl) {
            const agentsWithMetrics = allAgents.filter(a => {
                const m = a.metrics || {};
                return m.coherence !== undefined && m.coherence !== null;
            });
            if (agentsWithMetrics.length > 0) {
                const avgCoherence = agentsWithMetrics.reduce((sum, a) => sum + Number(a.metrics.coherence), 0) / agentsWithMetrics.length;
                animateValue(fleetCoherenceEl, avgCoherence, { decimals: 3 });
                const criticalCount = allAgents.filter(a => a.health_status === 'critical').length;
                const highRiskCount = allAgents.filter(a => {
                    const rs = a.metrics && a.metrics.risk_score;
                    return rs !== undefined && rs !== null && Number(rs) > 0.6;
                }).length;
                const parts = [];
                if (criticalCount > 0) parts.push(`${criticalCount} critical`);
                if (highRiskCount > 0) parts.push(`${highRiskCount} high-risk`);
                fleetDetailEl.innerHTML = parts.length > 0 ? parts.join(', ') : `${agentsWithMetrics.length} agents tracked`;
            } else {
                fleetCoherenceEl.textContent = '-';
                fleetDetailEl.innerHTML = 'No metrics data';
            }
        }

        // Sort by last update (most recent first)
        allAgents.sort((a, b) => {
            const aTime = new Date(a.last_update || a.created_at || 0);
            const bTime = new Date(b.last_update || b.created_at || 0);
            return bTime - aTime;
        });

        cachedAgents = allAgents;
        applyAgentFilters();
        return true;

    } catch (error) {
        console.error('Error loading agents:', error);
        const errorMsg = error.message || 'Unknown error';
        showError(`Failed to load agents: ${errorMsg}`);
        cachedAgents = [];
        const container = document.getElementById('agents-container');
        if (container) {
            container.innerHTML = `<div class="loading">Error loading agents: ${escapeHtml(errorMsg)}</div>`;
        }
        updateAgentFilterInfo(0);
        updateStatusLegend(null);
        return false;
    }
}

// Stuck agents monitoring
// cachedStuckAgents managed by state.js bridge

async function loadStuckAgents() {
    try {
        const result = await callTool('detect_stuck_agents', {});
        const countEl = document.getElementById('stuck-agents-count');
        const detailEl = document.getElementById('stuck-agents-detail');
        const cardEl = document.getElementById('stuck-agents-card');

        if (!countEl || !detailEl || !cardEl) return;

        if (result && result.success) {
            const stuck = result.stuck_agents || [];
            cachedStuckAgents = stuck;
            const count = stuck.length;
            animateValue(countEl, count);

            // Cross-reference: mark stuck agents in cachedAgents so agent cards show stuck badge
            const stuckIds = new Set(stuck.map(s => s.agent_id));
            const stuckMap = {};
            stuck.forEach(s => { stuckMap[s.agent_id] = s; });
            cachedAgents.forEach(a => {
                a._stuck = stuckIds.has(a.agent_id);
                a._stuckInfo = stuckMap[a.agent_id] || null;
            });
            // Re-render agent list to show stuck badges
            if (stuckIds.size > 0 && typeof applyAgentFilters === 'function') {
                applyAgentFilters();
            }

            // Style card based on count
            cardEl.classList.remove('stat-warning', 'stat-critical');
            if (count > 10) {
                cardEl.classList.add('stat-critical');
            } else if (count > 0) {
                cardEl.classList.add('stat-warning');
            }

            // Show breakdown by reason
            const byReason = result.summary?.by_reason || {};
            const parts = [];
            if (byReason.critical_margin_timeout > 0) parts.push(`${byReason.critical_margin_timeout} critical`);
            if (byReason.tight_margin_timeout > 0) parts.push(`${byReason.tight_margin_timeout} tight`);
            if (byReason.activity_timeout > 0) parts.push(`${byReason.activity_timeout} inactive`);
            detailEl.innerHTML = count > 0 ? parts.join(', ') : 'All agents healthy';
        } else {
            countEl.textContent = '-';
            detailEl.innerHTML = 'Could not check';
        }
    } catch (e) {
        console.debug('Could not load stuck agents:', e);
    }
}

// System health — fetches /health for DB pool, uptime, server status
async function loadSystemHealth() {
    try {
        const resp = await authFetch('/health');
        const data = await resp.json();
        const valueEl = document.getElementById('system-health-value');
        const detailEl = document.getElementById('system-health-detail');
        const cardEl = document.getElementById('system-health-card');
        if (!valueEl || !detailEl || !cardEl) return;

        const db = data.database || {};
        const uptime = data.uptime?.formatted || '?';

        cardEl.classList.remove('stat-warning', 'stat-critical');

        if (db.status === 'connected') {
            const idle = db.pool_idle ?? 0;
            const total = db.pool_size ?? 0;
            const max = db.pool_max ?? 0;
            const usage = total > 0 ? ((total - idle) / max * 100).toFixed(0) : 0;

            if (usage > 90) {
                valueEl.textContent = '⚠ DB';
                cardEl.classList.add('stat-critical');
            } else if (usage > 70) {
                valueEl.textContent = 'OK';
                cardEl.classList.add('stat-warning');
            } else {
                valueEl.textContent = 'OK';
            }
            detailEl.innerHTML = `DB pool ${total - idle}/${max} active · Up ${uptime}`;
        } else if (db.status === 'no_pool') {
            valueEl.textContent = '⚠';
            cardEl.classList.add('stat-warning');
            detailEl.innerHTML = `DB pool not initialized · Up ${uptime}`;
        } else {
            valueEl.textContent = '✗';
            cardEl.classList.add('stat-critical');
            detailEl.innerHTML = `DB ${db.status}: ${db.error || 'unknown'} · Up ${uptime}`;
        }
    } catch (e) {
        const valueEl = document.getElementById('system-health-value');
        const cardEl = document.getElementById('system-health-card');
        if (valueEl) valueEl.textContent = '✗';
        if (cardEl) cardEl.classList.add('stat-critical');
        const detailEl = document.getElementById('system-health-detail');
        if (detailEl) detailEl.innerHTML = 'Server unreachable';
    }
}

/**
 * Load discoveries from API and render to panel.
 * Updates cachedDiscoveries and stats.
 * @returns {Promise<void>}
 */
async function loadDiscoveries(searchQuery = '') {
    try {
        console.log('Loading discoveries...', searchQuery ? `(search: ${searchQuery})` : '');

        // Single API call — get discoveries and derive count from results
        const toolArgs = {
            limit: 50,
            include_details: true,
        };

        if (searchQuery) {
            toolArgs.query = searchQuery;
        }

        const searchResult = await callTool('search_knowledge_graph', toolArgs);

        // Handle null/undefined result
        if (!searchResult) {
            throw new Error('No response from server');
        }

        // Check for error in response
        if (searchResult.error || searchResult.success === false) {
            const errorMsg = searchResult.error || searchResult.message || 'Unknown error';
            // Don't throw for empty results - that's valid
            if (errorMsg.includes('too many clients') || errorMsg.includes('connection')) {
                throw new Error(`Database connection issue: ${errorMsg}. The server may have too many connections open.`);
            }
            if (errorMsg.includes('fetch failed')) {
                throw new Error(`Database query failed: ${errorMsg}. This may indicate connection pool exhaustion.`);
            }
            // For other errors, log but continue with empty results
            console.warn('Knowledge graph search error:', errorMsg);
            cachedDiscoveries = [];
            updateDiscoveryFilterInfo(0);
            updateDiscoveryLegend([]);
            return false;
        }
        
        // Handle both array and object response formats
        let discoveries = [];
        if (Array.isArray(searchResult)) {
            discoveries = searchResult;
            console.log('Got array response with', discoveries.length, 'discoveries');
        } else if (searchResult.discoveries) {
            discoveries = searchResult.discoveries;
            console.log('Got discoveries array with', discoveries.length, 'items');
        } else if (searchResult.results) {
            discoveries = searchResult.results;
            console.log('Got results array with', discoveries.length, 'items');
        } else {
            // Unexpected format - log and try to continue
            console.warn('Unexpected response format:', searchResult);
            discoveries = [];
        }

        // Sort by ID (which contains ISO timestamp) descending to get most recent first
        // ID format: "2025-12-29T08:34:42.201273" - lexicographically sortable
        discoveries.sort((a, b) => {
            const aId = (a.id || '').trim();
            const bId = (b.id || '').trim();
            if (!aId && !bId) return 0;
            if (!aId) return 1;  // No ID goes to end
            if (!bId) return -1; // No ID goes to end
            return bId.localeCompare(aId);
        });

        const enrichedDiscoveries = discoveries.map(d => {
            // Parse date from id (format: "2025-12-29T08:34:42.201273" or "2026-01-01T23:40:53.202482")
            // IDs use ISO timestamps - parse correctly
            let dateStr = 'Unknown';
            let dateObj = null;
            if (d.id) {
                try {
                    const isoStr = d.id.substring(0, 19);
                    const [datePart, timePart] = isoStr.split('T');
                    const [year, month, day] = datePart.split('-').map(Number);
                    const [hour, minute, second] = timePart.split(':').map(Number);
                    dateObj = new Date(year, month - 1, day, hour, minute, second || 0);

                    if (!isNaN(dateObj.getTime())) {
                        const now = new Date();
                        const diffMs = now - dateObj;
                        const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                        const month = monthNames[dateObj.getMonth()];
                        const day = dateObj.getDate();
                        const time = dateObj.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
                        dateStr = `${month} ${day}, ${time}`;
                    } else {
                        dateStr = isoStr.replace('T', ' ');
                    }
                } catch (e) {
                    dateStr = d.id.substring(0, 19).replace('T', ' ');
                }
            } else if (d.created_at) {
                dateObj = new Date(d.created_at);
                dateStr = !isNaN(dateObj.getTime()) ? dateObj.toLocaleString() : d.created_at;
            } else if (d.timestamp) {
                dateObj = new Date(d.timestamp);
                dateStr = !isNaN(dateObj.getTime()) ? dateObj.toLocaleString() : d.timestamp;
            }

            const timestampMs = dateObj ? dateObj.getTime() : null;
            return {
                ...d,
                _displayDate: dateStr,
                _timestampMs: timestampMs,
                _relativeTime: timestampMs ? formatRelativeTime(timestampMs) : null
            };
        });

        cachedDiscoveries = enrichedDiscoveries;

        // Update stat card — fetch real total from knowledge stats
        const loadedCount = enrichedDiscoveries.length;
        let totalDiscoveries = loadedCount;
        try {
            const stats = await callTool('knowledge', { action: 'stats' });
            if (stats && stats.stats && stats.stats.total_discoveries !== undefined) {
                totalDiscoveries = stats.stats.total_discoveries;
            }
        } catch (e) {
            console.debug('Could not fetch knowledge stats, using loaded count');
        }
        const countEl = document.getElementById('discoveries-count');
        if (countEl) animateValue(countEl, totalDiscoveries);
        const discoveriesChange = formatChange(totalDiscoveries, previousStats.discoveries);
        const changeEl = document.getElementById('discoveries-change');
        if (changeEl) {
            const parts = [];
            if (totalDiscoveries > loadedCount) parts.push(`Showing ${loadedCount}`);
            if (discoveriesChange) parts.push(discoveriesChange);
            changeEl.innerHTML = parts.join(' · ') || (totalDiscoveries > 0 ? 'Recent discoveries' : 'No discoveries yet');
        }
        previousStats.discoveries = totalDiscoveries;

        updateDiscoveryLegend(cachedDiscoveries);
        // Re-apply local filters (type/time) to the new search results
        applyDiscoveryFilters();
        return true;

    } catch (error) {
        const errorMsg = error.message || 'Unknown error';
        console.error('Failed to load discoveries:', error);
        
        // Show helpful error message
        let userMessage = `Failed to load discoveries: ${errorMsg}`;
        let isRetryable = false;
        
        if (errorMsg.includes('too many clients') || errorMsg.includes('connection pool') || errorMsg.includes('connection issue')) {
            userMessage = 'Database connection pool exhausted. The server has too many open connections. Try refreshing in a moment or restart the server.';
            isRetryable = true;
        } else if (errorMsg.includes('fetch failed') || errorMsg.includes('timeout')) {
            userMessage = 'Database query timed out or failed. This may indicate connection issues. Try refreshing.';
            isRetryable = true;
        } else if (errorMsg.includes('401') || errorMsg.includes('Authentication')) {
            userMessage = 'Authentication required. Check if the server needs an API token.';
        } else if (errorMsg.includes('PostgreSQL') || errorMsg.includes('database')) {
            userMessage = 'Database error. Check server logs for details.';
            isRetryable = true;
        }
        
        // Show error banner if retryable
        if (isRetryable) {
            updateConnectionBanner(true);
        }
        
        showError(userMessage);
        document.getElementById('discoveries-container').innerHTML =
            `<div class="loading">${escapeHtml(userMessage)}<br><small>You can try refreshing or check the server status.</small></div>`;
        cachedDiscoveries = [];
        updateDiscoveryFilterInfo(0);
        updateDiscoveryLegend([]);
        
        // Still update count to show error state
        document.getElementById('discoveries-count').textContent = '?';
        document.getElementById('discoveries-change').innerHTML = 'Error loading';
        
        return false;
    }
}

// ============================================================================
// DIALECTIC SESSIONS
// ============================================================================

// cachedDialecticSessions managed by state.js bridge

async function loadDialecticSessions() {
    try {
        console.log('Loading dialectic sessions...');
        const result = await callTool('list_dialectic_sessions', {
            limit: 50,
            include_transcript: false
        });

        console.log('Dialectic sessions result:', result);

        // Handle null/undefined result
        if (!result) {
            throw new Error('No response from server');
        }

        // Check for error
        if (result.error || result.success === false) {
            console.warn('Dialectic sessions error:', result.error || result.message);
            updateDialecticDisplay([], 'Error loading');
            return false;
        }

        // Extract sessions - minimal filtering, sort by date
        const rawSessions = result.sessions || [];
        const sessions = rawSessions
            .sort((a, b) => {
                // Sort by date descending (most recent first)
                const dateA = new Date(a.created || 0);
                const dateB = new Date(b.created || 0);
                return dateB - dateA;
            });
        cachedDialecticSessions = sessions;

        // Update stat card
        const sessionsEl = document.getElementById('dialectic-sessions');
        const changeEl = document.getElementById('dialectic-change');
        if (sessionsEl) {
            animateValue(sessionsEl, sessions.length);
        }
        if (changeEl) {
            const resolved = sessions.filter(s => s.phase === 'resolved' || s.status === 'resolved').length;
            const active = sessions.filter(s => !['resolved', 'failed'].includes(s.phase || s.status)).length;
            changeEl.innerHTML = `${resolved} resolved, ${active} active`;
        }

        // Apply current filter (respects user's active filter selection)
        applyDialecticFilters();

        return true;
    } catch (error) {
        console.error('Error loading dialectic sessions:', error);
        updateDialecticDisplay([], 'Error loading');
        return false;
    }
}

// Dialectic utilities, rendering, filtering, detail modal
// are now in dialectic.js → DialecticModule
var getPhaseColor = DialecticModule.getPhaseColor;
var formatDialecticPhase = DialecticModule.formatDialecticPhase;
var updateDialecticDisplay = DialecticModule.updateDialecticDisplay;
var updateDialecticFilterInfo = DialecticModule.updateDialecticFilterInfo;
var renderDialecticList = DialecticModule.renderDialecticList;
var applyDialecticFilters = DialecticModule.applyDialecticFilters;
var showDialecticDetail = DialecticModule.showDialecticDetail;

// ============================================================================
// MAIN REFRESH & INITIALIZATION
// ============================================================================

/**
 * Main refresh function - loads all dashboard data.
 * @param {Object} [options]
 * @param {boolean} [options.force=false] - Force refresh even if paused
 * @returns {Promise<void>}
 */
async function refresh(options = {}) {
    const force = options.force === true;
    if (autoRefreshPaused && !force) {
        return;
    }

    console.log('Refreshing dashboard...', { force, paused: autoRefreshPaused });

    // Don't auto-refresh if valid search text exists (to prevent overwriting search results)
    const searchInput = document.getElementById('discovery-search');
    if (searchInput && searchInput.value.trim().length > 0 && !force) {
        // Only refresh agents
        console.log('Search active, skipping discovery refresh');
        await loadAgents();
        await loadDialecticSessions();
        return;
    }

    clearError();
    const lastUpdateEl = document.getElementById('last-update');
    if (lastUpdateEl) {
        lastUpdateEl.textContent = new Date().toLocaleTimeString();
    }

    try {
        console.log('Starting parallel load...');
        const results = await Promise.allSettled([
            loadAgents(),
            loadDiscoveries(),
            loadDialecticSessions(),
            loadStuckAgents(),
            loadSystemHealth()
        ]);
        console.log('Load results:', results);

        // Check if critical operations failed (agents and discoveries)
        const agentsResult = results[0];
        const discoveriesResult = results[1];
        const dialecticResult = results[2];
        // results[3] is loadStuckAgents - non-critical
        
        const criticalFailures = [
            agentsResult.status === 'rejected' || (agentsResult.status === 'fulfilled' && agentsResult.value === false),
            discoveriesResult.status === 'rejected' || (discoveriesResult.status === 'fulfilled' && discoveriesResult.value === false)
        ].filter(Boolean).length;
        
        // Only show connection banner if BOTH critical operations failed
        // This prevents false positives from transient errors
        if (criticalFailures >= 2) {
            updateConnectionBanner(true);
            console.warn('Critical operations failed:', {
                agents: agentsResult.status,
                discoveries: discoveriesResult.status
            });
        } else {
            updateConnectionBanner(false);
        }
        
        // Log any individual failures
        results.forEach((result, index) => {
            if (result.status === 'rejected') {
                console.error(`Load operation ${index} failed:`, result.reason);
            }
        });
    } catch (error) {
        // This should rarely happen since we're using Promise.allSettled
        updateConnectionBanner(true);
        console.error('Refresh error:', error);
        showError(`Refresh failed: ${error.message}`);
    }
}

const agentSearchInput = document.getElementById('agent-search');
const agentStatusFilterInput = document.getElementById('agent-status-filter');
const agentMetricsOnlyInput = document.getElementById('agent-metrics-only');
if (agentSearchInput) {
    agentSearchInput.addEventListener('input', debounce(applyAgentFilters, CONFIG.DEBOUNCE_MS));
}
if (agentStatusFilterInput) {
    agentStatusFilterInput.addEventListener('change', applyAgentFilters);
}
if (agentMetricsOnlyInput) {
    agentMetricsOnlyInput.addEventListener('change', applyAgentFilters);
}
const agentSortInput = document.getElementById('agent-sort');
if (agentSortInput) {
    agentSortInput.addEventListener('change', applyAgentFilters);
}
const agentClearFiltersButton = document.getElementById('agent-clear-filters');
if (agentClearFiltersButton) {
    agentClearFiltersButton.addEventListener('click', clearAgentFilters);
}

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

const discoverySearchInput = document.getElementById('discovery-search');
const discoveryTypeFilterInput = document.getElementById('discovery-type-filter');
const discoveryTimeFilterInput = document.getElementById('discovery-time-filter');

if (discoverySearchInput) {
    discoverySearchInput.addEventListener('input', debounce(applyDiscoveryFilters, CONFIG.DEBOUNCE_MS));
}
if (discoveryTypeFilterInput) {
    discoveryTypeFilterInput.addEventListener('change', applyDiscoveryFilters);
}
if (discoveryTimeFilterInput) {
    discoveryTimeFilterInput.addEventListener('change', applyDiscoveryFilters);
}
const discoveryClearFiltersButton = document.getElementById('discovery-clear-filters');
if (discoveryClearFiltersButton) {
    discoveryClearFiltersButton.addEventListener('click', () => {
        clearDiscoveryFilters();
        // Reset to full list from server
        loadDiscoveries('');
    });
}
const discoveryLegend = document.getElementById('discoveries-type-legend');
if (discoveryLegend && discoveryTypeFilterInput) {
    discoveryLegend.addEventListener('click', event => {
        const chip = event.target.closest('.discovery-type');
        if (!chip) return;
        const type = chip.getAttribute('data-type');
        if (!type) return;
        discoveryTypeFilterInput.value = type;
        applyDiscoveryFilters();
    });
}

const refreshNowButton = document.getElementById('refresh-now');
const pauseRefreshInput = document.getElementById('pause-refresh');
if (refreshNowButton) {
    refreshNowButton.addEventListener('click', () => refresh({ force: true }));
}
if (pauseRefreshInput) {
    pauseRefreshInput.addEventListener('change', event => {
        autoRefreshPaused = event.target.checked;
        updateRefreshStatus();
    });
}
updateRefreshStatus();

const agentsContainer = document.getElementById('agents-container');
if (agentsContainer) {
    agentsContainer.addEventListener('click', event => {
        // Handle copy-id button click (don't bubble to agent detail)
        const button = event.target.closest('button[data-action="copy-id"]');
        if (button) {
            event.stopPropagation();
            const agentId = button.getAttribute('data-agent-id');
            if (!agentId) return;
            copyToClipboard(agentId)
                .then(() => {
                    const originalLabel = button.textContent;
                    button.textContent = 'Copied';
                    setTimeout(() => {
                        button.textContent = originalLabel;
                    }, CONFIG.COPY_FEEDBACK_MS);
                })
                .catch(() => {
                    const originalLabel = button.textContent;
                    button.textContent = 'Copy failed';
                    setTimeout(() => {
                        button.textContent = originalLabel;
                    }, CONFIG.COPY_FEEDBACK_MS);
                });
            return;
        }

        // Handle agent card click → open detail modal
        const agentItem = event.target.closest('.agent-item');
        if (!agentItem) return;
        const agentUuid = agentItem.getAttribute('data-agent-uuid');
        if (!agentUuid) return;
        const agent = cachedAgents.find(a => (a.agent_id || '') === agentUuid);
        if (agent) showAgentDetail(agent);
    });
}

const agentsLegend = document.getElementById('agents-status-legend');
if (agentsLegend && agentStatusFilterInput) {
    agentsLegend.addEventListener('click', event => {
        const chip = event.target.closest('.status-chip');
        if (!chip) return;
        const status = chip.getAttribute('data-status');
        if (!status) return;
        agentStatusFilterInput.value = status;
        applyAgentFilters();
    });
}

// Dialectic sessions event listeners
const dialecticStatusFilter = document.getElementById('dialectic-status-filter');
const dialecticRefreshButton = document.getElementById('dialectic-refresh');
if (dialecticStatusFilter) {
    dialecticStatusFilter.addEventListener('change', applyDialecticFilters);
}
if (dialecticRefreshButton) {
    dialecticRefreshButton.addEventListener('click', async () => {
        dialecticRefreshButton.disabled = true;
        dialecticRefreshButton.textContent = 'Loading...';
        try {
            await loadDialecticSessions();
        } finally {
            dialecticRefreshButton.disabled = false;
            dialecticRefreshButton.textContent = 'Refresh';
        }
    });
}

// Click handler for dialectic items to show full details
const dialecticContainer = document.getElementById('dialectic-container');
if (dialecticContainer) {
    dialecticContainer.addEventListener('click', (event) => {
        const item = event.target.closest('.dialectic-item');
        if (!item) return;
        const sessionId = item.getAttribute('data-session-id');
        if (!sessionId) return;

        const session = cachedDialecticSessions.find(s => s.session_id === sessionId);
        if (!session) return;
        showDialecticDetail(session);
    });
}

// Click handler for tags — sets them as the search term in the relevant panel
document.addEventListener('click', (event) => {
    const tag = event.target.closest('.clickable-tag');
    if (!tag) return;
    event.stopPropagation(); // Don't trigger parent click (e.g. discovery detail modal)
    const tagText = tag.getAttribute('data-tag') || tag.textContent.trim();
    if (!tagText) return;

    // Figure out which search to populate: discovery or agent
    const inDiscovery = tag.closest('.discoveries-list, .discovery-detail');
    const inAgent = tag.closest('.agents-panel, .agent-detail');

    if (inDiscovery || (!inAgent)) {
        // Default: search discoveries
        const searchInput = document.getElementById('discovery-search');
        if (searchInput) {
            searchInput.value = tagText;
            applyDiscoveryFilters();
            searchInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
            searchInput.focus();
        }
    } else {
        // Agent panel
        const searchInput = document.getElementById('agent-search');
        if (searchInput) {
            searchInput.value = tagText;
            applyAgentFilters();
            searchInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
            searchInput.focus();
        }
    }

    // Close modal if open (tag was clicked inside a detail view)
    const modal = document.getElementById('panel-modal');
    if (modal && modal.classList.contains('visible')) {
        modal.classList.remove('visible');
        document.body.style.overflow = '';
    }
});

// Click handler for discovery items to show full details
const discoveriesContainer = document.getElementById('discoveries-container');
if (discoveriesContainer) {
    discoveriesContainer.addEventListener('click', (event) => {
        const item = event.target.closest('.discovery-item');
        if (!item) return;
        const index = parseInt(item.getAttribute('data-discovery-index'), 10);
        if (isNaN(index) || index < 0 || index >= cachedDiscoveries.length) return;

        const discovery = cachedDiscoveries[index];
        showDiscoveryDetail(discovery);
    });
}

// Click handler for stuck agents card to expand
const stuckAgentsCard = document.getElementById('stuck-agents-card');
if (stuckAgentsCard) {
    stuckAgentsCard.style.cursor = 'pointer';
    stuckAgentsCard.addEventListener('click', () => {
        if (cachedStuckAgents.length > 0) {
            expandPanel('stuck-agents');
        }
    });
}

// showAgentDetail is now in agents.js → AgentsModule.showAgentDetail

// showDiscoveryDetail is now in discoveries.js → DiscoveriesModule.showDiscoveryDetail

// showDialecticDetail is now in dialectic.js → DialecticModule.showDialecticDetail

// renderDialecticDetailContent is now in dialectic.js → DialecticModule.renderDialecticDetailContent

// Theme toggle
const themeToggle = document.getElementById('theme-toggle');
const themeIcon = document.getElementById('theme-icon');
const themeLabel = document.getElementById('theme-label');
if (themeToggle && themeManager) {
    themeToggle.addEventListener('click', () => {
        const newTheme = themeManager.toggle();
        if (themeIcon) themeIcon.textContent = newTheme === 'dark' ? '🌙' : '☀️';
        if (themeLabel) themeLabel.textContent = newTheme === 'dark' ? 'Dark' : 'Light';
    });
    // Set initial icon
    const currentTheme = themeManager.getTheme();
    if (themeIcon) themeIcon.textContent = currentTheme === 'dark' ? '🌙' : '☀️';
    if (themeLabel) themeLabel.textContent = currentTheme === 'dark' ? 'Dark' : 'Light';
} else if (themeToggle) {
    // Hide theme toggle if themeManager not available
    themeToggle.style.display = 'none';
}


// exportAgents is now in agents.js → AgentsModule.exportAgents

// exportDiscoveries is now in discoveries.js → DiscoveriesModule.exportDiscoveries

const exportAgentsCsv = document.getElementById('export-agents-csv');
const exportAgentsJson = document.getElementById('export-agents-json');
const exportDiscoveriesCsv = document.getElementById('export-discoveries-csv');
const exportDiscoveriesJson = document.getElementById('export-discoveries-json');

if (exportAgentsCsv) exportAgentsCsv.addEventListener('click', () => exportAgents('csv'));
if (exportAgentsJson) exportAgentsJson.addEventListener('click', () => exportAgents('json'));
if (exportDiscoveriesCsv) exportDiscoveriesCsv.addEventListener('click', () => exportDiscoveries('csv'));
if (exportDiscoveriesJson) exportDiscoveriesJson.addEventListener('click', () => exportDiscoveries('json'));

// ========================================
// EISV Charts Module (eisv-charts.js)
// ========================================
// Chart init, WebSocket, governance pulse, decisions log, drift gauges,
// and value animations are now in EISVChartsModule.
var animateValue = EISVChartsModule.animateValue;
var updateValueWithGlow = EISVChartsModule.updateValueWithGlow;
var addEISVDataPoint = EISVChartsModule.addEISVDataPoint;
var addDecision = EISVChartsModule.addDecision;
var addEventEntry = EISVChartsModule.addEventEntry;
var fetchInitialEvents = EISVChartsModule.fetchInitialEvents;
var getVerdictBadge = EISVChartsModule.getVerdictBadge;
var renderDecisionsLog = EISVChartsModule.renderDecisionsLog;
var rebuildChartFromSelection = EISVChartsModule.rebuildChartFromSelection;
var updateAgentDropdown = EISVChartsModule.updateAgentDropdown;
var initEISVChart = EISVChartsModule.initEISVChart;
var initWebSocket = EISVChartsModule.initWebSocket;
var updateGovernancePulse = EISVChartsModule.updateGovernancePulse;
var updateAgentCardFromWS = EISVChartsModule.updateAgentCardFromWS;

// EISV functions removed — see eisv-charts.js
// (computeFleetAverage, rebuildChartFromSelection, makeChartOptions, equilibriumPlugin,
//  initEISVChart, addEISVDataPoint, drift gauges, governance verdict/pulse,
//  decisions log, events log, value animations, WebSocket init)
// Module self-initializes chart + WebSocket on DOMContentLoaded.
// ============================================
// Timeline Module (timeline.js)
// ============================================
// Skeletons, timeline rendering, WS status label now in TimelineModule.
// Module self-initializes skeletons, range filter, and click handlers.
var renderTimeline = TimelineModule.renderTimeline;
var updateWSStatusLabel = TimelineModule.updateWSStatusLabel;

// Hook timeline into refresh cycle — update after agents load
const originalLoadAgents = loadAgents;
loadAgents = async function() {
    const result = await originalLoadAgents();
    renderTimeline();
    return result;
};

// Patch EISV WebSocket to update status label
if (typeof EISVWebSocket !== 'undefined') {
    const origInitWS = initWebSocket;
    initWebSocket = function() {
        origInitWS();
        const checkInterval = setInterval(() => {
            const wsEl = document.querySelector('#ws-status .ws-dot');
            if (!wsEl) return;
            const currentClass = wsEl.className;
            if (currentClass.includes('connected')) updateWSStatusLabel('connected');
            else if (currentClass.includes('polling')) updateWSStatusLabel('polling');
            else if (currentClass.includes('reconnecting')) updateWSStatusLabel('reconnecting');
            else updateWSStatusLabel('disconnected');
        }, CONFIG.SCROLL_FEEDBACK_MS);
    };
}

// ============================================
// Fleet Heatmap Toggle
// ============================================
(function initHeatmap() {
    const toggleBtn = document.getElementById('heatmap-toggle');
    const closeBtn = document.getElementById('heatmap-close');
    const panel = document.getElementById('heatmap-panel');
    if (!toggleBtn || !panel) return;

    function renderHeatmap() {
        if (typeof FleetHeatmap === 'undefined') return;
        const agentsWithMetrics = cachedAgents.filter(a => agentHasMetrics(a)).slice(0, 30);
        if (agentsWithMetrics.length === 0) return;
        const heatmap = new FleetHeatmap('fleet-heatmap');
        heatmap.render(agentsWithMetrics);
    }

    function toggleHeatmap() {
        const isVisible = panel.style.display !== 'none';
        panel.style.display = isVisible ? 'none' : '';
        if (!isVisible) renderHeatmap();
    }

    toggleBtn.addEventListener('click', toggleHeatmap);
    if (closeBtn) closeBtn.addEventListener('click', () => { panel.style.display = 'none'; });

    // Re-render on each refresh if visible
    const origRefresh = refresh;
    refresh = async function() {
        const result = await origRefresh();
        if (panel.style.display !== 'none') renderHeatmap();
        return result;
    };
})();

// Initial load
console.log('Dashboard initializing...');
console.log('API available:', typeof api !== 'undefined' && api !== null);
console.log('DataProcessor available:', typeof DataProcessor !== 'undefined');
console.log('ThemeManager available:', typeof themeManager !== 'undefined' && themeManager !== null);

// Wait for DOM to be ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        console.log('DOM ready, starting initial load');
        setTimeout(() => { refresh(); }, 100);
        fetchInitialEvents();  // Load recent events
    });
} else {
    console.log('DOM already ready, starting initial load');
    setTimeout(() => { refresh(); }, 100);
    fetchInitialEvents();  // Load recent events
}

// Auto-refresh every 30 seconds
setInterval(() => {
    if (!autoRefreshPaused) {
        refresh();
    }
}, CONFIG.REFRESH_INTERVAL_MS);
