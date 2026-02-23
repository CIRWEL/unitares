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

// Refresh state
let refreshFailures = 0;
let autoRefreshPaused = false;

// Cached data
let previousStats = {};
let cachedAgents = [];
let cachedDiscoveries = [];

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

// Event delegation for stuck agents modal
document.addEventListener('click', async (event) => {
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
    const sign = diff > 0 ? '+' : '';
    const color = diff > 0 ? '#4ade80' : '#ff6b6b';
    return `<span style="color: ${color}">${sign}${diff}</span>`;
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

function getAgentStatus(agent) {
    return agent.lifecycle_status || agent.status || 'unknown';
}

function getAgentDisplayName(agent) {
    return agent.label || agent.display_name || agent.name || agent.agent_id || 'Unknown';
}

function agentHasMetrics(agent) {
    const metrics = agent.metrics || {};
    return metrics && (metrics.E !== undefined || metrics.I !== undefined || metrics.S !== undefined);
}

function formatStatusLabel(status) {
    const normalized = String(status || 'unknown').toLowerCase();
    const labels = {
        active: 'Active',
        waiting_input: 'Waiting',
        paused: 'Paused',
        archived: 'Archived',
        deleted: 'Deleted',
        unknown: 'Unknown'
    };
    return labels[normalized] || normalized.replace(/_/g, ' ');
}

// formatTimestamp and formatRelativeTime are already defined above as const variables
// These duplicate definitions are removed to avoid conflicts

function formatAgentTimestamp(agent) {
    const lastUpdateDate = agent.last_update ? new Date(agent.last_update) : null;
    if (lastUpdateDate && !isNaN(lastUpdateDate.getTime())) {
        const lastUpdate = lastUpdateDate.toLocaleString();
        const relative = formatRelativeTime(lastUpdateDate.getTime());
        return relative ? `Updated ${lastUpdate} (${relative})` : `Updated ${lastUpdate}`;
    }
    const createdDate = agent.created_at ? new Date(agent.created_at) : null;
    if (createdDate && !isNaN(createdDate.getTime())) {
        const created = createdDate.toLocaleString();
        const relative = formatRelativeTime(createdDate.getTime());
        return relative ? `Created ${created} (${relative})` : `Created ${created}`;
    }
    return null;
}

function updateStatusLegend(statusCounts) {
    const container = document.getElementById('agents-status-legend');
    if (!container) return;
    if (!statusCounts) {
        container.textContent = '';
        return;
    }

    const entries = [
        { key: 'active', label: 'Active', count: statusCounts.active || 0 },
        { key: 'waiting_input', label: 'Waiting', count: statusCounts.waiting_input || 0 },
        { key: 'paused', label: 'Paused', count: statusCounts.paused || 0 },
        { key: 'archived', label: 'Archived', count: statusCounts.archived || 0 },
        { key: 'deleted', label: 'Deleted', count: statusCounts.deleted || 0 },
        { key: 'unknown', label: 'Unknown', count: statusCounts.unknown || 0 }
    ];

    const chips = entries
        .filter(entry => entry.count > 0)
        .map(entry => `<button class="status-chip ${entry.key}" data-status="${entry.key}" type="button">${entry.label} ${entry.count}</button>`)
        .join(' ');

    container.innerHTML = chips || '';
}

function updateAgentFilterInfo(filteredCount) {
    const info = document.getElementById('agents-filter-info');
    if (!info) return;
    const total = cachedAgents.length;
    if (!total) {
        info.textContent = '';
        return;
    }
    if (filteredCount === 0) {
        info.textContent = `No agents match filters (${total} loaded)`;
        return;
    }
    const showingCount = Math.min(filteredCount, 20);
    info.textContent = `Showing ${showingCount} of ${filteredCount} filtered (${total} loaded)`;
}

// ============================================================================
// AGENT RENDERING & FILTERING
// ============================================================================

/**
 * Render a list of agent cards with EISV metrics and status indicators.
 * @param {Array<Object>} agents - Agent data from API
 * @param {string} [searchTerm] - Optional term to highlight in results
 */
function renderAgentsList(agents, searchTerm = '') {
    const container = document.getElementById('agents-container');
    if (cachedAgents.length === 0) {
        container.innerHTML = '<div class="loading">No agents found. Agents will appear here after calling onboard() or any tool.</div>';
        updateAgentFilterInfo(0);
        return;
    }

    if (agents.length === 0) {
        container.innerHTML = '<div class="loading">No agents match the current filters.</div>';
        updateAgentFilterInfo(0);
        return;
    }

    updateAgentFilterInfo(agents.length);
    container.innerHTML = agents.slice(0, 20).map(agent => {
        // Use lifecycle_status from agent object (more reliable than array membership)
        const status = getAgentStatus(agent);
        const statusClass = status === 'paused' ? 'paused' :
            status === 'archived' ? 'archived' :
                status === 'deleted' ? 'archived' : '';  // Deleted agents styled like archived
        const statusIndicator = `<span class="status-indicator ${status}"></span>`;
        const statusLabel = escapeHtml(formatStatusLabel(status));

        const metrics = agent.metrics || {};
        const eValue = metrics.E !== undefined && metrics.E !== null ? Number(metrics.E) : null;
        const iValue = metrics.I !== undefined && metrics.I !== null ? Number(metrics.I) : null;
        const sValue = metrics.S !== undefined && metrics.S !== null ? Number(metrics.S) : null;
        const vValue = metrics.V !== undefined && metrics.V !== null ? Number(metrics.V) : null;
        const cValue = metrics.coherence !== undefined && metrics.coherence !== null ? Number(metrics.coherence) : null;
        // EISV metrics - show all four core metrics
        const e = eValue !== null && !Number.isNaN(eValue) ? eValue.toFixed(6) : '-';
        const i = iValue !== null && !Number.isNaN(iValue) ? iValue.toFixed(6) : '-';
        const s = sValue !== null && !Number.isNaN(sValue) ? sValue.toFixed(6) : '-';
        const v = vValue !== null && !Number.isNaN(vValue) ? vValue.toFixed(6) : '-';
        const coherence = cValue !== null && !Number.isNaN(cValue) ? cValue.toFixed(6) : '-';
        const clampPercent = value => {
            if (value === null || Number.isNaN(value)) return 0;
            return Math.max(0, Math.min(100, value * 100));
        };
        const ePct = clampPercent(eValue);
        const iPct = clampPercent(iValue);
        const sPct = clampPercent(sValue);
        // Void can be negative (I>E); bar shows |V| rescaled from effective range
        const vPct = vValue !== null && !Number.isNaN(vValue)
            ? Math.max(0, Math.min(100, (Math.abs(vValue) / 0.3) * 100))
            : 0;
        const cPct = clampPercent(cValue);
        const displayName = getAgentDisplayName(agent);
        const agentId = agent.agent_id || '';
        const timestampLabel = formatAgentTimestamp(agent);
        const nameHtml = highlightMatch(displayName, searchTerm);
        const idHtml = searchTerm ? highlightMatch(agentId, searchTerm) : escapeHtml(agentId);
        const subtitleParts = [];
        if (timestampLabel) {
            subtitleParts.push(escapeHtml(timestampLabel));
        }
        const totalUpdates = agent.total_updates || 0;
        if (totalUpdates > 0) {
            subtitleParts.push(`${totalUpdates} update${totalUpdates !== 1 ? 's' : ''}`);
        }
        const subtitleHtml = subtitleParts.length ? `<div class="agent-subtitle">${subtitleParts.join(' &bull; ')}</div>` : '';

        // Purpose line
        const purpose = agent.purpose ? escapeHtml(agent.purpose) : '';
        const purposeHtml = purpose ? `<div class="agent-purpose" title="${purpose}">${purpose}</div>` : '';

        // Trust tier badge — API returns string names: "unknown", "emerging", "established", "verified"
        const tierRaw = agent.trust_tier;
        const tierNameToNum = { unknown: 0, emerging: 1, established: 2, verified: 3 };
        const tierNames = { 0: 'unknown', 1: 'emerging', 2: 'established', 3: 'verified' };
        const tierNum = tierRaw !== undefined && tierRaw !== null
            ? (typeof tierRaw === 'number' ? tierRaw : (tierNameToNum[String(tierRaw).toLowerCase()] ?? 0))
            : 0;
        const tierDisplayNames = { 0: 'T0', 1: 'T1', 2: 'T2', 3: 'T3' };
        const trustTierHtml = `<span class="trust-tier tier-${tierNum}" title="Trust Tier ${tierNum}: ${tierNames[tierNum] || 'unknown'}">${tierDisplayNames[tierNum]}</span>`;

        // Show metrics only if we have at least one metric value
        const hasMetrics = agentHasMetrics(agent);

        const actionsHtml = agentId
            ? `<div class="agent-actions"><button class="agent-action" type="button" data-action="copy-id" data-agent-id="${escapeHtml(agentId)}">Copy ID</button></div>`
            : '';

        // Contextual metric bar colors: E/I high=green, S/V low=green
        const metricColor = (val, inverted) => {
            if (val === null || Number.isNaN(val)) return '';
            if (inverted) {
                return val < 0.3 ? 'var(--accent-green)' : val < 0.6 ? 'var(--accent-yellow)' : 'var(--accent-orange)';
            }
            return val > 0.6 ? 'var(--accent-green)' : val > 0.3 ? 'var(--accent-yellow)' : 'var(--accent-orange)';
        };
        const eColor = metricColor(eValue, false);
        const iColor = metricColor(iValue, false);
        const sColor = metricColor(sValue, true);
        const vColor = metricColor(vValue, true);
        const cColor = metricColor(cValue, false);

        return `
            <div class="agent-item ${statusClass}" data-agent-uuid="${escapeHtml(agentId)}" style="cursor: pointer;" title="Click to view details">
                <div class="agent-meta">
                    <div class="agent-title">
                        ${statusIndicator}
                        <span class="agent-name">${nameHtml}</span>
                        <span class="status-chip ${status}">${statusLabel}</span>
                        ${trustTierHtml}
                        ${actionsHtml}
                    </div>
                    ${subtitleHtml}
                    ${purposeHtml}
                </div>
                ${hasMetrics ? `
                    <div class="agent-metrics">
                        <div class="metric e" title="Energy (divergence/productive capacity)">
                            <div class="label">E</div>
                            <div class="val">${e}</div>
                            <div class="metric-bar"><div class="metric-bar-fill" style="width: ${ePct}%; ${eColor ? `background: ${eColor}` : ''}"></div></div>
                        </div>
                        <div class="metric i" title="Information Integrity">
                            <div class="label">I</div>
                            <div class="val">${i}</div>
                            <div class="metric-bar"><div class="metric-bar-fill" style="width: ${iPct}%; ${iColor ? `background: ${iColor}` : ''}"></div></div>
                        </div>
                        <div class="metric s" title="Entropy (disorder/uncertainty)">
                            <div class="label">S</div>
                            <div class="val">${s}</div>
                            <div class="metric-bar"><div class="metric-bar-fill" style="width: ${sPct}%; ${sColor ? `background: ${sColor}` : ''}"></div></div>
                        </div>
                        <div class="metric v" title="Void Integral (E-I imbalance)">
                            <div class="label">V</div>
                            <div class="val">${v}</div>
                            <div class="metric-bar"><div class="metric-bar-fill" style="width: ${vPct}%; ${vColor ? `background: ${vColor}` : ''}"></div></div>
                        </div>
                        <div class="metric c" title="Coherence">
                            <div class="label">C</div>
                            <div class="val">${coherence}</div>
                            <div class="metric-bar"><div class="metric-bar-fill" style="width: ${cPct}%; ${cColor ? `background: ${cColor}` : ''}"></div></div>
                        </div>
                    </div>
                ` : '<div class="agent-metrics"><span style="color: #8a9ba8; font-size: 0.9em;">No metrics yet</span></div>'}
            </div>
        `;
    }).join('');
}

/**
 * Apply all active filters to the agent list and re-render.
 * Reads filter state from DOM inputs.
 */
function applyAgentFilters() {
    const searchInput = document.getElementById('agent-search');
    const statusFilterInput = document.getElementById('agent-status-filter');
    const metricsOnlyInput = document.getElementById('agent-metrics-only');
    const sortInput = document.getElementById('agent-sort');

    const searchTerm = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const statusFilter = statusFilterInput ? statusFilterInput.value : 'all';
    const metricsOnly = metricsOnlyInput ? metricsOnlyInput.checked : false;
    const sortBy = sortInput ? sortInput.value : 'recent';

    let filteredAgents = cachedAgents.filter(agent => {
        const status = getAgentStatus(agent);
        if (statusFilter !== 'all' && status !== statusFilter) {
            return false;
        }

        if (metricsOnly && !agentHasMetrics(agent)) {
            return false;
        }

        if (searchTerm) {
            const displayName = getAgentDisplayName(agent);
            const agentId = agent.agent_id || '';
            const purpose = agent.purpose || '';
            const haystack = `${displayName} ${agentId} ${purpose}`.toLowerCase();
            if (!haystack.includes(searchTerm)) {
                return false;
            }
        }

        return true;
    });

    // Sort
    filteredAgents = [...filteredAgents].sort((a, b) => {
        switch (sortBy) {
            case 'name':
                return getAgentDisplayName(a).localeCompare(getAgentDisplayName(b));
            case 'coherence': {
                const aC = (a.metrics || {}).coherence ?? -1;
                const bC = (b.metrics || {}).coherence ?? -1;
                return bC - aC; // high first
            }
            case 'risk': {
                const aR = (a.metrics || {}).risk_score ?? -1;
                const bR = (b.metrics || {}).risk_score ?? -1;
                return bR - aR; // high first
            }
            case 'updates':
                return (b.total_updates || 0) - (a.total_updates || 0);
            case 'recent':
            default: {
                const aTime = new Date(a.last_update || a.created_at || 0);
                const bTime = new Date(b.last_update || b.created_at || 0);
                return bTime - aTime;
            }
        }
    });

    renderAgentsList(filteredAgents, searchTerm);
}

function clearAgentFilters() {
    const searchInput = document.getElementById('agent-search');
    const statusFilterInput = document.getElementById('agent-status-filter');
    const metricsOnlyInput = document.getElementById('agent-metrics-only');
    const sortInput = document.getElementById('agent-sort');
    if (searchInput) searchInput.value = '';
    if (statusFilterInput) statusFilterInput.value = 'all';
    if (metricsOnlyInput) metricsOnlyInput.checked = false;
    if (sortInput) sortInput.value = 'recent';
    applyAgentFilters();
}

// ============================================================================
// DISCOVERY RENDERING & FILTERING
// ============================================================================

function normalizeDiscoveryType(type) {
    if (!type) return 'note';
    return String(type).trim().toLowerCase();
}

function formatDiscoveryType(type) {
    const value = normalizeDiscoveryType(type);
    const labelMap = {
        bug_found: 'Bug',
        improvement: 'Improvement',
        insight: 'Insight',
        pattern: 'Pattern',
        question: 'Question',
        answer: 'Answer',
        note: 'Note',
        exploration: 'Exploration',
        analysis: 'Analysis'
    };
    return labelMap[value] || value.replace(/_/g, ' ');
}

function updateDiscoveryFilterInfo(filteredCount) {
    const info = document.getElementById('discoveries-filter-info');
    if (!info) return;
    const total = cachedDiscoveries.length;
    if (!total) {
        info.textContent = '';
        return;
    }
    if (filteredCount === 0) {
        info.textContent = `No discoveries match filters (${total} loaded)`;
        return;
    }
    const showingCount = Math.min(filteredCount, 10);
    info.textContent = `Showing ${showingCount} of ${filteredCount} filtered (${total} loaded)`;
}

function updateDiscoveryLegend(discoveries) {
    const container = document.getElementById('discoveries-type-legend');
    if (!container) return;
    if (!discoveries || discoveries.length === 0) {
        container.textContent = '';
        return;
    }

    const counts = {};
    discoveries.forEach(d => {
        const type = normalizeDiscoveryType(d.type || d.discovery_type || 'note');
        counts[type] = (counts[type] || 0) + 1;
    });

    const total = discoveries.length;
    const chips = [];
    chips.push(`<button class="discovery-type" data-type="all" type="button">All ${total}</button>`);

    const orderedTypes = ['insight', 'improvement', 'bug_found', 'pattern', 'question', 'answer', 'analysis', 'note', 'exploration'];
    orderedTypes.forEach(type => {
        if (!counts[type]) return;
        const label = escapeHtml(formatDiscoveryType(type));
        const count = counts[type];
        chips.push(`<button class="discovery-type ${type}" data-type="${type}" type="button">${label} ${count}</button>`);
        delete counts[type];
    });

    Object.keys(counts).sort().forEach(type => {
        const label = escapeHtml(formatDiscoveryType(type));
        const count = counts[type];
        chips.push(`<button class="discovery-type ${type}" data-type="${type}" type="button">${label} ${count}</button>`);
    });

    container.innerHTML = chips.join(' ');
}

function renderDiscoveriesList(discoveries, searchTerm = '') {
    const container = document.getElementById('discoveries-container');
    if (cachedDiscoveries.length === 0) {
        container.innerHTML = '<div class="loading">No recent discoveries. Use store_knowledge_graph() to add discoveries.</div>';
        updateDiscoveryFilterInfo(0);
        return;
    }

    if (discoveries.length === 0) {
        container.innerHTML = '<div class="loading">No discoveries match the current filters.</div>';
        updateDiscoveryFilterInfo(0);
        return;
    }

    updateDiscoveryFilterInfo(discoveries.length);
    const displayDiscoveries = discoveries.slice(0, 10);
    container.innerHTML = displayDiscoveries.map((d, idx) => {
        const type = normalizeDiscoveryType(d.type || d.discovery_type || 'note');
        const typeLabel = escapeHtml(formatDiscoveryType(type));
        const agent = escapeHtml(d.by || d.agent_id || d._agent_id || 'Unknown');
        const details = String(d.details || d.content || d.discovery || '');
        const summaryText = d.summary || 'Untitled';
        const summaryHtml = highlightMatch(summaryText, searchTerm);
        const relative = d._relativeTime ? ` (${d._relativeTime})` : '';
        const displayDate = escapeHtml(`${d._displayDate || 'Unknown'}${relative}`);
        const tags = (d.tags || []).slice(0, 5).map(t => `<span class="discovery-tag">${escapeHtml(t)}</span>`).join('');

        return `
            <div class="discovery-item" data-discovery-index="${idx}" style="cursor: pointer;" title="Click to view full details">
                <div class="discoveries-meta-line">
                    <span class="discovery-type ${type}">${typeLabel}</span>
                    <span class="meta-item">By: ${agent}</span>
                    <span class="meta-item">${displayDate}</span>
                </div>
                <div class="discovery-summary">${summaryHtml}</div>
                ${tags ? `<div class="discovery-tags">${tags}</div>` : ''}
            </div>
        `;
    }).join('');
}

/**
 * Apply all active filters to discoveries and re-render.
 * Reads filter state from DOM inputs.
 */
function applyDiscoveryFilters() {
    const searchInput = document.getElementById('discovery-search');
    const typeFilterInput = document.getElementById('discovery-type-filter');
    const timeFilterInput = document.getElementById('discovery-time-filter');
    const searchTerm = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const typeFilter = typeFilterInput ? typeFilterInput.value : 'all';
    const timeFilter = timeFilterInput ? timeFilterInput.value : 'all';
    let cutoff = null;
    if (timeFilter === '24h') {
        cutoff = Date.now() - CONFIG.DAY_MS;
    } else if (timeFilter === '7d') {
        cutoff = Date.now() - CONFIG.WEEK_MS;
    } else if (timeFilter === '30d') {
        cutoff = Date.now() - CONFIG.MONTH_MS;
    }

    const filtered = cachedDiscoveries.filter(d => {
        const type = normalizeDiscoveryType(d.type || d.discovery_type || 'note');
        if (typeFilter !== 'all' && type !== typeFilter) {
            return false;
        }

        if (cutoff !== null) {
            if (!d._timestampMs || d._timestampMs < cutoff) {
                return false;
            }
        }

        if (searchTerm) {
            const haystack = `${d.summary || ''} ${d.details || ''} ${d.content || ''} ${d.discovery || ''}`.toLowerCase();
            if (!haystack.includes(searchTerm)) {
                return false;
            }
        }

        return true;
    });

    renderDiscoveriesList(filtered, searchTerm);
}

function clearDiscoveryFilters() {
    const searchInput = document.getElementById('discovery-search');
    const typeFilterInput = document.getElementById('discovery-type-filter');
    const timeFilterInput = document.getElementById('discovery-time-filter');
    if (searchInput) searchInput.value = '';
    if (typeFilterInput) typeFilterInput.value = 'all';
    if (timeFilterInput) timeFilterInput.value = 'all';
    applyDiscoveryFilters();
}

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

        // Update stats
        document.getElementById('total-agents').textContent = total;
        document.getElementById('active-agents').textContent = active;

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
                fleetCoherenceEl.textContent = avgCoherence.toFixed(3);
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
let cachedStuckAgents = [];

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
            countEl.textContent = count;

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
        const resp = await fetch('/health');
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
        if (countEl) countEl.textContent = totalDiscoveries;
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

let cachedDialecticSessions = [];

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
            sessionsEl.textContent = sessions.length;
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

function updateDialecticDisplay(sessions, message) {
    const sessionsEl = document.getElementById('dialectic-sessions');
    const changeEl = document.getElementById('dialectic-change');
    if (sessionsEl) {
        sessionsEl.textContent = sessions.length || '?';
    }
    if (changeEl) {
        changeEl.innerHTML = message || '';
    }
}

function updateDialecticFilterInfo(count) {
    const filterInfo = document.getElementById('dialectic-filter-info');
    if (filterInfo) {
        filterInfo.textContent = `Showing ${count} session${count !== 1 ? 's' : ''}`;
    }
}

function getPhaseColor(phase) {
    const colors = {
        'resolved': 'var(--accent-green)',
        'failed': 'var(--accent-orange)',
        'thesis': 'var(--accent-cyan)',
        'antithesis': 'var(--accent-purple)',
        'synthesis': 'var(--accent-yellow)'
    };
    return colors[phase] || 'var(--text-secondary)';
}

function formatDialecticPhase(phase) {
    const labels = {
        'resolved': 'Resolved',
        'failed': 'Failed',
        'thesis': 'Thesis',
        'antithesis': 'Antithesis',
        'synthesis': 'Synthesis'
    };
    return labels[phase] || phase || 'Unknown';
}

function renderDialecticList(sessions) {
    const container = document.getElementById('dialectic-container');
    if (!container) return;

    if (!sessions || sessions.length === 0) {
        container.innerHTML = `
            <div class="dialectic-empty">
                <div class="dialectic-empty-icon">🔄</div>
                <div>No active dialectic sessions</div>
                <div style="font-size: 0.85em; margin-top: 5px; opacity: 0.7">
                    Sessions appear when agents request recovery reviews
                </div>
            </div>`;
        return;
    }


    // Limit to 25 sessions for display
    const displaySessions = sessions.slice(0, 25);
    const hasMore = sessions.length > 25;

    container.innerHTML = displaySessions.map(session => {
        const phase = session.phase || session.status || 'unknown';
        const phaseColor = getPhaseColor(phase);
        const requestorId = session.paused_agent || session.requestor_id || session.agent_id || 'Unknown';
        const reviewerId = session.reviewer || session.reviewer_id || 'None';
        const sessionType = session.session_type || session.type || 'verification';
        const topic = session.topic || session.reason || `${sessionType} session`;
        const created = session.created || session.created_at || session.timestamp || '';

        // Format timestamp
        let timeAgo = '';
        if (created) {
            try {
                const date = new Date(created);
                const now = new Date();
                const diffMs = now - date;
                const diffMins = Math.floor(diffMs / 60000);
                const diffHours = Math.floor(diffMins / 60);
                const diffDays = Math.floor(diffHours / 24);

                if (diffDays > 0) {
                    timeAgo = `${diffDays}d ago`;
                } else if (diffHours > 0) {
                    timeAgo = `${diffHours}h ago`;
                } else if (diffMins > 0) {
                    timeAgo = `${diffMins}m ago`;
                } else {
                    timeAgo = 'Just now';
                }
            } catch (e) {
                timeAgo = created;
            }
        }

        // Resolution info
        let resolutionInfo = '';
        if (session.resolution) {
            const res = session.resolution;
            resolutionInfo = `<div class="dialectic-resolution">
                Resolution: ${escapeHtml(res.action || res.type || 'Unknown')}
                ${res.confidence ? ` (${(res.confidence * 100).toFixed(0)}% conf)` : ''}
            </div>`;
        }

        return `
            <div class="dialectic-item ${phase}" data-session-id="${session.session_id || ''}" style="cursor: pointer;" title="Click to view details">
                <div class="dialectic-header">
                    <span class="dialectic-type" style="border-color: ${phaseColor}; color: ${phaseColor}">
                        ${escapeHtml(formatDialecticPhase(phase))}
                    </span>
                    <span class="dialectic-session-type">${escapeHtml(sessionType)}</span>
                    <span class="dialectic-time">${escapeHtml(timeAgo)}</span>
                </div>
                <div class="dialectic-topic">${escapeHtml(topic)}</div>
                <div class="dialectic-agents">
                    <span class="agent-label">Requestor:</span> ${escapeHtml(requestorId.length > 15 ? requestorId.substring(0, 12) + '...' : requestorId)}
                    ${reviewerId && reviewerId !== 'None' ? `<span class="agent-label" style="margin-left: 10px;">Reviewer:</span> ${escapeHtml(reviewerId.length > 15 ? reviewerId.substring(0, 12) + '...' : reviewerId)}` : ''}
                    <span class="agent-label" style="margin-left: 10px; color: var(--accent-cyan);">📝 ${session.message_count || 0} messages</span>
                </div>
                ${resolutionInfo}
            </div>
        `;
    }).join('');

    // Add "more" indicator if truncated
    if (hasMore) {
        container.innerHTML += `<div class="loading" style="text-align: center; padding: 10px;">
            ...and ${sessions.length - 25} more sessions (use filter to narrow down)
        </div>`;
    }
}

function applyDialecticFilters() {
    const statusFilter = document.getElementById('dialectic-status-filter');
    const filter = statusFilter ? statusFilter.value : 'substantive';

    let filtered = cachedDialecticSessions;
    if (filter === 'substantive') {
        // Only sessions with real dialectic content (thesis+antithesis+synthesis = 3+ messages)
        filtered = cachedDialecticSessions.filter(s => (s.message_count || 0) >= 3);
    } else if (filter !== 'all') {
        filtered = cachedDialecticSessions.filter(s => {
            const phase = s.phase || s.status || '';
            if (filter === 'active') {
                return ['thesis', 'antithesis', 'synthesis'].includes(phase);
            }
            return phase === filter;
        });
    }

    updateDialecticFilterInfo(filtered.length);
    renderDialecticList(filtered);
}

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

function showAgentDetail(agent) {
    const modal = document.getElementById('panel-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    if (!modal || !modalTitle || !modalBody) return;

    const displayName = getAgentDisplayName(agent);
    const status = getAgentStatus(agent);
    const agentId = agent.agent_id || 'Unknown';
    const metrics = agent.metrics || {};
    const tierNameToNum = { unknown: 0, emerging: 1, established: 2, verified: 3 };
    const tierRaw = agent.trust_tier;
    const trustTier = tierRaw !== undefined && tierRaw !== null
        ? (typeof tierRaw === 'number' ? tierRaw : (tierNameToNum[String(tierRaw).toLowerCase()] ?? 0))
        : 0;
    const tierNames = { 0: 'Unknown', 1: 'Emerging', 2: 'Established', 3: 'Verified' };
    const tierDescriptions = {
        0: 'New agent, no trajectory history. +5% risk adjustment.',
        1: 'Some history, building consistency. +5% risk adjustment.',
        2: 'Consistent behavioral trajectory. No risk adjustment.',
        3: 'Strong trajectory match + operator endorsement. -5% risk reduction.'
    };

    // EISV with interpretations using DataProcessor
    const eisvMetrics = ['E', 'I', 'S', 'V', 'C'];
    const metricValues = {
        E: metrics.E, I: metrics.I, S: metrics.S, V: metrics.V,
        C: metrics.coherence
    };
    const eisvHtml = eisvMetrics.map(name => {
        const val = metricValues[name];
        if (val === undefined || val === null) return '';
        const formatted = typeof DataProcessor !== 'undefined'
            ? DataProcessor.formatEISVMetric(Number(val), name)
            : { display: Number(val).toFixed(6), interpretation: '', color: 'var(--text-primary)' };
        return `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border-color);">
                <div>
                    <strong style="color: ${formatted.color}; font-family: var(--font-mono);">${name}</strong>
                    <span style="color: var(--text-secondary); font-size: 0.85em; margin-left: 8px;">${escapeHtml(formatted.interpretation)}</span>
                </div>
                <span style="font-family: var(--font-mono); font-weight: 600; color: ${formatted.color};">${formatted.display}</span>
            </div>`;
    }).filter(Boolean).join('');

    // Governance section
    const healthStatus = agent.health_status || 'unknown';
    const verdict = metrics.verdict || '-';
    const riskScore = metrics.risk_score !== undefined && metrics.risk_score !== null ? (Number(metrics.risk_score) * 100).toFixed(1) + '%' : '-';
    const phi = metrics.phi !== undefined && metrics.phi !== null ? Number(metrics.phi).toFixed(4) : '-';
    const meanRisk = metrics.mean_risk !== undefined && metrics.mean_risk !== null ? (Number(metrics.mean_risk) * 100).toFixed(1) + '%' : '-';

    // Tags and notes
    const tags = agent.tags && agent.tags.length > 0 ? agent.tags.map(t => `<span style="background: rgba(0,255,255,0.1); color: var(--accent-cyan); padding: 2px 8px; border-radius: 3px; font-size: 0.85em;">${escapeHtml(t)}</span>`).join(' ') : '<span style="color: var(--text-secondary);">None</span>';
    const notes = agent.notes ? escapeHtml(agent.notes) : '';
    const purpose = agent.purpose ? escapeHtml(agent.purpose) : '';

    let html = `
        <div class="agent-detail">
            <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 15px; flex-wrap: wrap;">
                <span class="status-indicator ${status}" style="width: 10px; height: 10px;"></span>
                <span style="font-size: 1.2em; font-weight: 600;">${escapeHtml(displayName)}</span>
                <span class="status-chip ${status}">${escapeHtml(formatStatusLabel(status))}</span>
                ${trustTier !== null ? `<span class="trust-tier tier-${trustTier}">Tier ${trustTier}: ${tierNames[trustTier] || 'Unknown'}</span>` : ''}
            </div>

            ${purpose ? `<div style="color: var(--text-secondary); font-style: italic; margin-bottom: 15px;">${purpose}</div>` : ''}

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
                <div>
                    <strong style="color: var(--text-secondary);">Agent ID:</strong><br>
                    <code style="font-size: 0.85em; word-break: break-all;">${escapeHtml(agentId)}</code>
                </div>
                <div>
                    <strong style="color: var(--text-secondary);">Total Updates:</strong><br>
                    ${agent.total_updates || 0}
                </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
                <div>
                    <strong style="color: var(--text-secondary);">Created:</strong><br>
                    ${agent.created_at || agent.created || '-'}
                </div>
                <div>
                    <strong style="color: var(--text-secondary);">Last Update:</strong><br>
                    ${agent.last_update || '-'}
                </div>
            </div>

            ${trustTier !== null ? `
                <div style="margin-bottom: 15px; padding: 10px; background: rgba(0,255,255,0.05); border-radius: 6px; border-left: 3px solid var(--accent-cyan);">
                    <strong style="color: var(--accent-cyan);">Trust Tier ${trustTier}: ${tierNames[trustTier] || 'Unknown'}</strong><br>
                    <span style="color: var(--text-secondary); font-size: 0.9em;">${tierDescriptions[trustTier] || ''}</span>
                </div>
            ` : ''}

            ${eisvHtml ? `
                <div style="margin-bottom: 15px;">
                    <strong style="color: var(--accent-cyan);">EISV Metrics:</strong>
                    <div style="margin-top: 8px;">${eisvHtml}</div>
                </div>
            ` : ''}

            <div style="margin-bottom: 15px;">
                <strong style="color: var(--accent-cyan);">Governance:</strong>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-top: 8px;">
                    <div style="padding: 10px; background: rgba(0,0,0,0.2); border-radius: 6px; text-align: center;">
                        <div style="font-size: 0.75em; color: var(--text-secondary); text-transform: uppercase;">Health</div>
                        <div class="health-badge ${healthStatus}" style="font-size: 1.1em; font-weight: 600;">${escapeHtml(healthStatus)}</div>
                    </div>
                    <div style="padding: 10px; background: rgba(0,0,0,0.2); border-radius: 6px; text-align: center;">
                        <div style="font-size: 0.75em; color: var(--text-secondary); text-transform: uppercase;">Verdict</div>
                        <div style="font-size: 1.1em; font-weight: 600;">${escapeHtml(verdict)}</div>
                    </div>
                    <div style="padding: 10px; background: rgba(0,0,0,0.2); border-radius: 6px; text-align: center;">
                        <div style="font-size: 0.75em; color: var(--text-secondary); text-transform: uppercase;">Risk</div>
                        <div style="font-size: 1.1em; font-weight: 600;">${riskScore}</div>
                    </div>
                    <div style="padding: 10px; background: rgba(0,0,0,0.2); border-radius: 6px; text-align: center;">
                        <div style="font-size: 0.75em; color: var(--text-secondary); text-transform: uppercase;">Phi</div>
                        <div style="font-size: 1.1em; font-weight: 600; font-family: var(--font-mono);">${phi}</div>
                    </div>
                    <div style="padding: 10px; background: rgba(0,0,0,0.2); border-radius: 6px; text-align: center;">
                        <div style="font-size: 0.75em; color: var(--text-secondary); text-transform: uppercase;">Mean Risk</div>
                        <div style="font-size: 1.1em; font-weight: 600;">${meanRisk}</div>
                    </div>
                </div>
            </div>

            <div style="margin-bottom: 15px;">
                <strong style="color: var(--text-secondary);">Tags:</strong>
                <div style="margin-top: 5px;">${tags}</div>
            </div>

            ${notes ? `
                <div style="margin-bottom: 15px;">
                    <strong style="color: var(--text-secondary);">Notes:</strong>
                    <div style="margin-top: 5px; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 6px; white-space: pre-wrap;">${notes}</div>
                </div>
            ` : ''}

            <details style="margin-top: 15px;">
                <summary style="cursor: pointer; color: var(--text-secondary);">Raw data</summary>
                <pre style="font-size: 0.75em; max-height: 200px; overflow: auto; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 4px; margin-top: 8px;">${escapeHtml(JSON.stringify(agent, null, 2))}</pre>
            </details>
        </div>`;

    modalTitle.textContent = `Agent: ${displayName}`;
    modalBody.innerHTML = html;
    modal.classList.add('visible');
    document.body.style.overflow = 'hidden';
}

function showDiscoveryDetail(discovery) {
    const modal = document.getElementById('panel-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    if (!modal || !modalTitle || !modalBody) return;

    const type = normalizeDiscoveryType(discovery.type || discovery.discovery_type || 'note');
    const typeLabel = formatDiscoveryType(type);
    const agent = discovery.by || discovery.agent_id || discovery._agent_id || 'Unknown';
    const summary = discovery.summary || 'Untitled';
    const details = discovery.details || discovery.content || discovery.discovery || '';
    const displayDate = discovery._displayDate || 'Unknown';
    const relativeTime = discovery._relativeTime || '';

    let html = `
        <div class="discovery-detail">
            <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 15px;">
                <span class="discovery-type ${type}" style="font-size: 1em;">${escapeHtml(typeLabel)}</span>
                <span style="color: var(--text-secondary);">${escapeHtml(displayDate)}${relativeTime ? ` (${relativeTime})` : ''}</span>
            </div>

            <div style="margin-bottom: 15px;">
                <strong style="color: var(--text-secondary);">Summary:</strong><br>
                <span style="font-size: 1.1em;">${escapeHtml(summary)}</span>
            </div>

            ${details ? `
                <div style="margin-bottom: 15px;">
                    <strong style="color: var(--text-secondary);">Details:</strong>
                    <div style="margin-top: 8px; padding: 12px; background: rgba(0,0,0,0.2); border-radius: 6px; white-space: pre-wrap; word-wrap: break-word; font-size: 0.95em; max-height: 300px; overflow-y: auto;">
${escapeHtml(details)}</div>
                </div>
            ` : ''}

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0;">
                <div>
                    <strong style="color: var(--text-secondary);">Agent:</strong><br>
                    <code style="font-size: 0.9em; word-break: break-all;">${escapeHtml(agent)}</code>
                </div>
                ${discovery.id ? `
                    <div>
                        <strong style="color: var(--text-secondary);">ID:</strong><br>
                        <code style="font-size: 0.85em; word-break: break-all;">${escapeHtml(discovery.id)}</code>
                    </div>
                ` : ''}
            </div>

            <details style="margin-top: 15px;">
                <summary style="cursor: pointer; color: var(--text-secondary);">Raw data</summary>
                <pre style="font-size: 0.75em; max-height: 200px; overflow: auto; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 4px; margin-top: 8px;">${escapeHtml(JSON.stringify(discovery, null, 2))}</pre>
            </details>
        </div>`;

    modalTitle.textContent = `Discovery: ${typeLabel}`;
    modalBody.innerHTML = html;
    modal.classList.add('visible');
    document.body.style.overflow = 'hidden';
}

async function showDialecticDetail(session) {
    const modal = document.getElementById('panel-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    if (!modal || !modalTitle || !modalBody) return;

    const sessionId = session.session_id || 'Unknown';
    const phase = session.phase || session.status || 'unknown';

    // Show modal with loading state
    modalTitle.textContent = `Dialectic Session: ${formatDialecticPhase(phase)}`;
    modalBody.innerHTML = `<div class="loading">Loading full session details...</div>`;
    modal.classList.add('visible');
    document.body.style.overflow = 'hidden';

    // Try to fetch full session with transcript
    let fullSession = session;
    if (sessionId && sessionId !== 'Unknown') {
        try {
            const result = await callTool('get_dialectic_session', {
                session_id: sessionId,
                check_timeout: false
            });
            if (result && result.session) {
                fullSession = result.session;
            } else if (result && !result.error) {
                fullSession = result;
            }
        } catch (e) {
            console.warn('Failed to fetch full session, using cached:', e);
        }
    }

    // Render with potentially full data
    renderDialecticDetailContent(modalBody, fullSession);
}

function renderDialecticDetailContent(container, session) {
    const phase = session.phase || session.status || 'unknown';
    const phaseColor = getPhaseColor(phase);
    const requestorId = session.paused_agent || session.requestor_id || session.agent_id || 'Unknown';
    const reviewerId = session.reviewer || session.reviewer_id || 'None';
    const sessionType = session.session_type || session.type || 'verification';
    const topic = session.topic || session.reason || `${sessionType} session`;
    const sessionId = session.session_id || 'Unknown';
    const created = session.created || session.created_at || session.timestamp || '';

    // Build full details HTML
    let html = `
        <div class="dialectic-detail">
            <div class="dialectic-detail-header">
                <span class="dialectic-type" style="border-color: ${phaseColor}; color: ${phaseColor}; font-size: 1.1em;">
                    ${escapeHtml(formatDialecticPhase(phase))}
                </span>
                <span class="dialectic-session-type" style="font-size: 1em;">${escapeHtml(sessionType)}</span>
            </div>

            <div style="margin: 15px 0;">
                <strong style="color: var(--text-secondary);">Topic:</strong><br>
                <span style="font-size: 1.1em;">${escapeHtml(topic)}</span>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0;">
                <div>
                    <strong style="color: var(--text-secondary);">Session ID:</strong><br>
                    <code style="font-size: 0.85em; word-break: break-all;">${escapeHtml(sessionId)}</code>
                </div>
                <div>
                    <strong style="color: var(--text-secondary);">Created:</strong><br>
                    ${escapeHtml(created)}
                </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0;">
                <div>
                    <strong style="color: var(--text-secondary);">Requestor:</strong><br>
                    <code style="font-size: 0.9em; word-break: break-all;">${escapeHtml(requestorId)}</code>
                </div>
                <div>
                    <strong style="color: var(--text-secondary);">Reviewer:</strong><br>
                    ${reviewerId !== 'None' ? `<code style="font-size: 0.9em; word-break: break-all;">${escapeHtml(reviewerId)}</code>` : '<span style="color: var(--text-secondary);">Not assigned</span>'}
                </div>
            </div>`;

    // Add resolution if present
    if (session.resolution) {
        const res = session.resolution;
        html += `
            <div style="margin: 15px 0; padding: 10px; background: rgba(0,100,0,0.2); border-radius: 6px; border-left: 3px solid var(--accent-green);">
                <strong style="color: var(--accent-green);">Resolution:</strong><br>
                <span>Action: ${escapeHtml(res.action || res.type || 'Unknown')}</span>
                ${res.confidence ? `<br>Confidence: ${(res.confidence * 100).toFixed(0)}%` : ''}
                ${res.reason ? `<br>Reason: ${escapeHtml(res.reason)}` : ''}
            </div>`;
    }

    // Add transcript - this is the key data we want to show
    const transcript = session.transcript || [];
    if (transcript.length > 0) {
        html += `
            <div style="margin: 15px 0;">
                <strong style="color: var(--accent-cyan);">Discussion Transcript (${transcript.length} messages):</strong>
                <div style="margin-top: 10px; max-height: 350px; overflow-y: auto;">
                    ${transcript.map((entry, idx) => {
                        const role = entry.role || entry.agent_id || entry.phase || 'system';
                        const content = entry.content || entry.reasoning || entry.message || '';
                        const timestamp = entry.timestamp || '';
                        const isSystem = role === 'system' || role === 'synthesis';
                        const roleColor = isSystem ? 'var(--accent-yellow)' : 'var(--accent-cyan)';

                        return `
                            <div style="margin-bottom: 12px; padding: 10px 12px; background: rgba(0,0,0,0.25); border-radius: 6px; border-left: 2px solid ${roleColor};">
                                <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                                    <strong style="color: ${roleColor}; text-transform: uppercase; font-size: 0.8em;">${escapeHtml(role)}</strong>
                                    ${timestamp ? `<span style="color: var(--text-secondary); font-size: 0.75em;">${escapeHtml(timestamp)}</span>` : ''}
                                </div>
                                <div style="color: var(--text-primary); white-space: pre-wrap; word-wrap: break-word; font-size: 0.9em; line-height: 1.5;">${escapeHtml(content)}</div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>`;
    } else {
        html += `
            <div style="margin: 15px 0; padding: 20px; background: rgba(0,0,0,0.15); border-radius: 6px; text-align: center; color: var(--text-secondary);">
                <div style="font-size: 1.5em; margin-bottom: 8px;">📭</div>
                No transcript recorded for this session.<br>
                <small>This may be an auto-resolved or system-generated session.</small>
            </div>`;
    }

    // Show raw JSON for debugging
    html += `
        <details style="margin-top: 15px;">
            <summary style="cursor: pointer; color: var(--text-secondary);">Raw session data</summary>
            <pre style="font-size: 0.75em; max-height: 200px; overflow: auto; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 4px; margin-top: 8px;">${escapeHtml(JSON.stringify(session, null, 2))}</pre>
        </details>
        </div>`;

    container.innerHTML = html;
}

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


// Export functionality
function exportAgents(format) {
    if (cachedAgents.length === 0) {
        showError('No agents to export');
        return;
    }

    const exportData = cachedAgents.map(agent => ({
        agent_id: agent.agent_id || '',
        name: getAgentDisplayName(agent),
        status: getAgentStatus(agent),
        E: agent.metrics?.E || null,
        I: agent.metrics?.I || null,
        S: agent.metrics?.S || null,
        V: agent.metrics?.V || null,
        coherence: agent.metrics?.coherence || null,
        last_update: agent.last_update || '',
        created_at: agent.created_at || ''
    }));

    if (format === 'csv') {
        if (typeof DataProcessor !== 'undefined' && DataProcessor.exportToCSV) {
            DataProcessor.exportToCSV(exportData, `agents_${new Date().toISOString().split('T')[0]}.csv`);
        } else {
            // Fallback CSV export
            const headers = Object.keys(exportData[0]);
            const csv = [
                headers.join(','),
                ...exportData.map(row => headers.map(h => {
                    const v = row[h];
                    return v === null || v === undefined ? '' : String(v).replace(/"/g, '""');
                }).join(','))
            ].join('\n');
            const blob = new Blob([csv], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `agents_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            URL.revokeObjectURL(url);
        }
    } else {
        if (typeof DataProcessor !== 'undefined' && DataProcessor.exportToJSON) {
            DataProcessor.exportToJSON(exportData, `agents_${new Date().toISOString().split('T')[0]}.json`);
        } else {
            // Fallback JSON export
            const json = JSON.stringify(exportData, null, 2);
            const blob = new Blob([json], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `agents_${new Date().toISOString().split('T')[0]}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }
    }
}

function exportDiscoveries(format) {
    if (cachedDiscoveries.length === 0) {
        showError('No discoveries to export');
        return;
    }

    const exportData = cachedDiscoveries.map(d => ({
        id: d.id || '',
        type: d.type || d.discovery_type || 'note',
        summary: d.summary || '',
        content: d.details || d.content || d.discovery || '',
        agent: d.by || d.agent_id || d._agent_id || '',
        timestamp: d._timestampMs ? new Date(d._timestampMs).toISOString() : ''
    }));

    if (format === 'csv') {
        if (typeof DataProcessor !== 'undefined' && DataProcessor.exportToCSV) {
            DataProcessor.exportToCSV(exportData, `discoveries_${new Date().toISOString().split('T')[0]}.csv`);
        } else {
            // Fallback CSV export
            const headers = Object.keys(exportData[0]);
            const csv = [
                headers.join(','),
                ...exportData.map(row => headers.map(h => {
                    const v = row[h];
                    return v === null || v === undefined ? '' : String(v).replace(/"/g, '""');
                }).join(','))
            ].join('\n');
            const blob = new Blob([csv], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `discoveries_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            URL.revokeObjectURL(url);
        }
    } else {
        if (typeof DataProcessor !== 'undefined' && DataProcessor.exportToJSON) {
            DataProcessor.exportToJSON(exportData, `discoveries_${new Date().toISOString().split('T')[0]}.json`);
        } else {
            // Fallback JSON export
            const json = JSON.stringify(exportData, null, 2);
            const blob = new Blob([json], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `discoveries_${new Date().toISOString().split('T')[0]}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }
    }
}

const exportAgentsCsv = document.getElementById('export-agents-csv');
const exportAgentsJson = document.getElementById('export-agents-json');
const exportDiscoveriesCsv = document.getElementById('export-discoveries-csv');
const exportDiscoveriesJson = document.getElementById('export-discoveries-json');

if (exportAgentsCsv) exportAgentsCsv.addEventListener('click', () => exportAgents('csv'));
if (exportAgentsJson) exportAgentsJson.addEventListener('click', () => exportAgents('json'));
if (exportDiscoveriesCsv) exportDiscoveriesCsv.addEventListener('click', () => exportDiscoveries('csv'));
if (exportDiscoveriesJson) exportDiscoveriesJson.addEventListener('click', () => exportDiscoveries('json'));

// ========================================
// Live EISV Chart + WebSocket
// ========================================
let eisvChartUpper = null;  // E, I, Coherence
let eisvChartLower = null;  // S, V
let eisvWebSocket = null;
// Per-agent EISV tracking for hybrid view
const agentEISVHistory = {}; // { agent_id: [{ts, E, I, S, V, coherence}, ...] }
const knownAgents = new Set(); // For dropdown population
let selectedAgentView = '__fleet__'; // '__fleet__', '__all__', or agent_id

function updateAgentDropdown() {
    const select = document.getElementById('eisv-agent-select');
    if (!select) return;
    const currentValue = select.value;

    // Preserve special options, add agents
    const specialOpts = ['__fleet__', '__all__'];
    const agentOpts = Array.from(knownAgents).sort();

    // Only update if agents changed
    const existingAgents = Array.from(select.options)
        .filter(o => !specialOpts.includes(o.value))
        .map(o => o.value);

    if (JSON.stringify(existingAgents) === JSON.stringify(agentOpts)) return;

    // Rebuild options
    select.innerHTML = '';
    select.add(new Option('Fleet Average', '__fleet__'));
    select.add(new Option('All (raw)', '__all__'));

    if (agentOpts.length > 0) {
        const sep = new Option('───────────', '');
        sep.disabled = true;
        select.add(sep);
        agentOpts.forEach(agentId => {
            // Use short display name
            const history = agentEISVHistory[agentId];
            const name = history?.[0]?.name || agentId;
            const shortName = name.length > 20 ? name.substring(0, 17) + '...' : name;
            select.add(new Option(shortName, agentId));
        });
    }

    // Restore selection if still valid
    if (Array.from(select.options).some(o => o.value === currentValue)) {
        select.value = currentValue;
    }
}

function computeFleetAverage() {
    const now = Date.now();
    const cutoff = now - CONFIG.EISV_WINDOW_MS;

    // Collect all recent data points
    const allPoints = [];
    for (const agentId of Object.keys(agentEISVHistory)) {
        const history = agentEISVHistory[agentId];
        for (const pt of history) {
            if (pt.ts >= cutoff) {
                allPoints.push(pt);
            }
        }
    }

    if (allPoints.length === 0) return null;

    // Group by time buckets (30 second intervals)
    const buckets = {};
    for (const pt of allPoints) {
        const bucket = Math.floor(pt.ts / CONFIG.EISV_BUCKET_MS) * CONFIG.EISV_BUCKET_MS;
        if (!buckets[bucket]) {
            buckets[bucket] = { E: [], I: [], S: [], V: [], coherence: [] };
        }
        buckets[bucket].E.push(pt.E);
        buckets[bucket].I.push(pt.I);
        buckets[bucket].S.push(pt.S);
        buckets[bucket].V.push(pt.V);
        buckets[bucket].coherence.push(pt.coherence);
    }

    // Compute averages per bucket
    const result = [];
    for (const [ts, vals] of Object.entries(buckets).sort((a,b) => a[0] - b[0])) {
        const avg = (arr) => arr.reduce((a,b) => a+b, 0) / arr.length;
        result.push({
            x: new Date(parseInt(ts)),
            E: avg(vals.E),
            I: avg(vals.I),
            S: avg(vals.S),
            V: avg(vals.V),
            coherence: avg(vals.coherence)
        });
    }
    return result;
}

function rebuildChartFromSelection() {
    if (!eisvChartUpper || !eisvChartLower) return;

    // Clear existing data
    eisvChartUpper.data.datasets.forEach(ds => ds.data = []);
    eisvChartLower.data.datasets.forEach(ds => ds.data = []);

    const now = Date.now();
    const cutoff = now - CONFIG.EISV_WINDOW_MS;

    if (selectedAgentView === '__fleet__') {
        // Fleet average
        const avgData = computeFleetAverage();
        if (avgData) {
            avgData.forEach(pt => {
                eisvChartUpper.data.datasets[0].data.push({ x: pt.x, y: pt.E });
                eisvChartUpper.data.datasets[1].data.push({ x: pt.x, y: pt.I });
                eisvChartUpper.data.datasets[2].data.push({ x: pt.x, y: pt.coherence });
                eisvChartLower.data.datasets[0].data.push({ x: pt.x, y: pt.S });
                eisvChartLower.data.datasets[1].data.push({ x: pt.x, y: pt.V });
            });
        }
    } else if (selectedAgentView === '__all__') {
        // All raw data (original behavior)
        for (const history of Object.values(agentEISVHistory)) {
            for (const pt of history) {
                if (pt.ts >= cutoff) {
                    const x = new Date(pt.ts);
                    eisvChartUpper.data.datasets[0].data.push({ x, y: pt.E });
                    eisvChartUpper.data.datasets[1].data.push({ x, y: pt.I });
                    eisvChartUpper.data.datasets[2].data.push({ x, y: pt.coherence });
                    eisvChartLower.data.datasets[0].data.push({ x, y: pt.S });
                    eisvChartLower.data.datasets[1].data.push({ x, y: pt.V });
                }
            }
        }
        // Sort by time
        [eisvChartUpper, eisvChartLower].forEach(chart => {
            chart.data.datasets.forEach(ds => {
                ds.data.sort((a, b) => a.x - b.x);
            });
        });
    } else {
        // Specific agent
        const history = agentEISVHistory[selectedAgentView] || [];
        for (const pt of history) {
            if (pt.ts >= cutoff) {
                const x = new Date(pt.ts);
                eisvChartUpper.data.datasets[0].data.push({ x, y: pt.E });
                eisvChartUpper.data.datasets[1].data.push({ x, y: pt.I });
                eisvChartUpper.data.datasets[2].data.push({ x, y: pt.coherence });
                eisvChartLower.data.datasets[0].data.push({ x, y: pt.S });
                eisvChartLower.data.datasets[1].data.push({ x, y: pt.V });
            }
        }
    }

    // Limit chart data to CONFIG.EISV_MAX_POINTS to prevent unbounded memory growth
    [eisvChartUpper, eisvChartLower].forEach(chart => {
        chart.data.datasets.forEach(ds => {
            while (ds.data.length > CONFIG.EISV_MAX_POINTS) {
                ds.data.shift();  // Remove oldest point
            }
        });
    });

    requestAnimationFrame(() => {
        eisvChartUpper.update('none');
        eisvChartLower.update('none');
    });
}

// Wire up dropdown and drift toggle
document.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('eisv-agent-select');
    if (select) {
        select.addEventListener('change', (e) => {
            selectedAgentView = e.target.value;
            rebuildChartFromSelection();
        });
    }

});

function makeChartOptions(extraYOpts) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: 'rgba(13,13,18,0.9)',
                titleFont: { family: "'Inter', sans-serif" },
                bodyFont: { family: "'JetBrains Mono', monospace", size: 12 },
                padding: 10,
                borderColor: '#333',
                borderWidth: 1,
                callbacks: {
                    label: function(ctx) {
                        return `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(4)}`;
                    }
                }
            }
        },
        scales: {
            x: {
                type: 'time',
                time: { unit: 'minute', displayFormats: { minute: 'HH:mm' }, tooltipFormat: 'HH:mm:ss' },
                grid: { color: 'rgba(255,255,255,0.05)' },
                ticks: { color: '#a0a0b0', font: { size: 11 }, maxRotation: 0 }
            },
            y: Object.assign({
                grid: { color: 'rgba(255,255,255,0.05)' },
                ticks: {
                    color: '#a0a0b0',
                    font: { family: "'JetBrains Mono', monospace", size: 11 },
                    callback: function(v) { return v.toFixed(3); }
                }
            }, extraYOpts)
        }
    };
}

// Inline Chart.js plugin: draws horizontal equilibrium reference lines
const equilibriumPlugin = {
    id: 'equilibriumLines',
    afterDraw(chart) {
        const lines = chart.options.plugins?.equilibriumLines;
        if (!lines || !lines.length) return;
        const { ctx } = chart;
        const yScale = chart.scales.y;
        const xStart = chart.chartArea.left;
        const xEnd = chart.chartArea.right;

        lines.forEach(line => {
            const y = yScale.getPixelForValue(line.value);
            if (y < chart.chartArea.top || y > chart.chartArea.bottom) return;

            ctx.save();
            ctx.beginPath();
            ctx.strokeStyle = line.color || 'rgba(255,255,255,0.15)';
            ctx.lineWidth = 1;
            ctx.setLineDash(line.dash || [4, 4]);
            ctx.moveTo(xStart, y);
            ctx.lineTo(xEnd, y);
            ctx.stroke();

            if (line.label) {
                ctx.font = '10px Inter, sans-serif';
                ctx.fillStyle = line.color || 'rgba(255,255,255,0.3)';
                ctx.textAlign = 'right';
                ctx.fillText(line.label, xEnd - 4, y - 4);
            }
            ctx.restore();
        });
    }
};
Chart.register(equilibriumPlugin);

function initEISVChart() {
    const upperCtx = document.getElementById('eisv-chart-upper');
    const lowerCtx = document.getElementById('eisv-chart-lower');
    if (!upperCtx || !lowerCtx) return;

    // Upper chart: E, I, Coherence — these cluster around 0.5-0.6
    const upperOpts = makeChartOptions({ grace: '5%' });
    upperOpts.plugins.equilibriumLines = [
        { value: 0.593, label: 'E eq ≈0.593', color: 'rgba(124,58,237,0.3)', dash: [3, 6] },
        { value: 0.595, label: 'I eq ≈0.595', color: 'rgba(16,185,129,0.3)', dash: [3, 6] },
        { value: 0.499, label: 'Coh eq ≈0.50', color: 'rgba(6,182,212,0.3)', dash: [3, 6] }
    ];

    eisvChartUpper = new Chart(upperCtx, {
        type: 'line',
        data: {
            datasets: [
                { label: 'Energy (E)', borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.08)', fill: true, data: [], tension: 0.3, pointRadius: 3, pointHoverRadius: 5, borderWidth: 2 },
                { label: 'Integrity (I)', borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.08)', fill: true, data: [], tension: 0.3, pointRadius: 3, pointHoverRadius: 5, borderWidth: 2 },
                { label: 'Coherence', borderColor: '#06b6d4', backgroundColor: 'transparent', data: [], tension: 0.3, pointRadius: 0, borderWidth: 2, borderDash: [6, 3] }
            ]
        },
        options: upperOpts
    });

    // Lower chart: S, V — near zero, need their own scale
    const lowerOpts = makeChartOptions({ grace: '10%' });
    lowerOpts.plugins.equilibriumLines = [
        { value: 0.012, label: 'S eq ≈0.012', color: 'rgba(245,158,11,0.3)', dash: [3, 6] },
        { value: 0.0, label: 'zero', color: 'rgba(255,255,255,0.1)', dash: [2, 4] }
    ];

    eisvChartLower = new Chart(lowerCtx, {
        type: 'line',
        data: {
            datasets: [
                { label: 'Entropy (S)', borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.08)', fill: true, data: [], tension: 0.3, pointRadius: 3, pointHoverRadius: 5, borderWidth: 2 },
                { label: 'Void (V)', borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.08)', fill: true, data: [], tension: 0.3, pointRadius: 3, pointHoverRadius: 5, borderWidth: 2 }
            ]
        },
        options: lowerOpts
    });
}

function addEISVDataPoint(data) {
    if (!eisvChartUpper || !eisvChartLower) return;
    const ts = new Date(data.timestamp);
    const tsMs = ts.getTime();
    const eisv = data.eisv || {};
    const agentId = data.agent_id || 'unknown';
    const agentName = data.agent_name || agentId;

    // Store in per-agent history
    if (!agentEISVHistory[agentId]) {
        agentEISVHistory[agentId] = [];
    }
    agentEISVHistory[agentId].push({
        ts: tsMs,
        name: agentName,
        E: eisv.E ?? 0,
        I: eisv.I ?? 0,
        S: eisv.S ?? 0,
        V: eisv.V ?? 0,
        coherence: data.coherence ?? 0
    });

    // Track known agents for dropdown
    if (!knownAgents.has(agentId)) {
        knownAgents.add(agentId);
        updateAgentDropdown();
    }

    // Trim old data from all agent histories
    const cutoff = tsMs - CONFIG.EISV_WINDOW_MS;
    for (const aid of Object.keys(agentEISVHistory)) {
        agentEISVHistory[aid] = agentEISVHistory[aid].filter(pt => pt.ts >= cutoff);
        if (agentEISVHistory[aid].length === 0) {
            delete agentEISVHistory[aid];
            knownAgents.delete(aid);
        }
    }

    // Update chart based on selected view
    if (selectedAgentView === '__fleet__') {
        // Rebuild with fleet average (includes new data point)
        rebuildChartFromSelection();
    } else if (selectedAgentView === '__all__' || selectedAgentView === agentId) {
        // Add point directly to chart
        eisvChartUpper.data.datasets[0].data.push({ x: ts, y: eisv.E ?? 0 });
        eisvChartUpper.data.datasets[1].data.push({ x: ts, y: eisv.I ?? 0 });
        eisvChartUpper.data.datasets[2].data.push({ x: ts, y: data.coherence ?? 0 });
        eisvChartLower.data.datasets[0].data.push({ x: ts, y: eisv.S ?? 0 });
        eisvChartLower.data.datasets[1].data.push({ x: ts, y: eisv.V ?? 0 });

        // Trim chart data by time and point count
        const cutoffDate = new Date(cutoff);
        [eisvChartUpper, eisvChartLower].forEach(chart => {
            chart.data.datasets.forEach(ds => {
                // Remove old data points by time
                while (ds.data.length > 0 && ds.data[0].x < cutoffDate) {
                    ds.data.shift();
                }
                // Limit to max points to prevent unbounded memory growth
                while (ds.data.length > CONFIG.EISV_MAX_POINTS) {
                    ds.data.shift();
                }
            });
        });
        requestAnimationFrame(() => {
            eisvChartUpper.update('none');
            eisvChartLower.update('none');
        });
    }
    // If viewing a different specific agent, don't update chart

    // Update info label with latest values
    const info = document.getElementById('eisv-chart-info');
    if (info) {
        const shortName = agentName.length > 16 ? agentName.substring(0, 16) + '...' : agentName;
        const viewLabel = selectedAgentView === '__fleet__' ? '(fleet avg)' :
                          selectedAgentView === '__all__' ? '(all)' : '';
        info.innerHTML = `<span class="eisv-agent-label">${escapeHtml(shortName)} ${viewLabel}</span>` +
            ` <span class="eisv-value" style="color:#7c3aed">E ${(eisv.E ?? 0).toFixed(3)}</span>` +
            ` <span class="eisv-value" style="color:#10b981">I ${(eisv.I ?? 0).toFixed(3)}</span>` +
            ` <span class="eisv-value" style="color:#f59e0b">S ${(eisv.S ?? 0).toFixed(4)}</span>` +
            ` <span class="eisv-value" style="color:#ef4444">V ${(eisv.V ?? 0).toFixed(5)}</span>`;
    }

    // Hide empty message
    const emptyMsg = document.getElementById('eisv-chart-empty');
    if (emptyMsg) emptyMsg.style.display = 'none';

    // Update Governance Pulse panel
    updateGovernancePulse(data);
}

let lastVitalsTimestamp = null;
const MAX_LOG_ENTRIES = 8;

const DRIFT_AXES = ['emotional', 'epistemic', 'behavioral'];
const TREND_ICONS = {
    stable: '',
    oscillating: '~',
    drifting_up: '\u2197',   // ↗
    drifting_down: '\u2198'  // ↘
};
const TREND_COLORS = {
    stable: '#6b7280',
    oscillating: '#06b6d4',
    drifting_up: '#ef4444',
    drifting_down: '#3b82f6'
};

function updateDriftGauge(index, value, trendInfo) {
    const fill = document.getElementById('drift-g-' + index);
    const valEl = document.getElementById('drift-v-' + index);
    const trendEl = document.getElementById('drift-trend-' + index);
    if (!fill) return;

    const clamped = Math.max(-0.5, Math.min(0.5, value));
    const pct = Math.abs(clamped) / 0.5 * 50;

    if (clamped >= 0) {
        fill.style.left = '50%';
        fill.style.width = pct + '%';
        fill.style.background = pct > 20 ? '#ef4444' : pct > 5 ? '#f59e0b' : '#6b7280';
    } else {
        fill.style.left = (50 - pct) + '%';
        fill.style.width = pct + '%';
        fill.style.background = pct > 20 ? '#3b82f6' : pct > 5 ? '#06b6d4' : '#6b7280';
    }

    if (valEl) {
        valEl.textContent = (clamped >= 0 ? '+' : '') + clamped.toFixed(3);
        valEl.style.color = Math.abs(clamped) < 0.005 ? '' :
            clamped > 0 ? '#ef4444' : '#3b82f6';
    }

    // Update trend indicator
    if (trendEl && trendInfo) {
        const trend = trendInfo.trend || 'stable';
        const strength = trendInfo.strength || 0;
        trendEl.textContent = TREND_ICONS[trend] || '';
        trendEl.style.color = TREND_COLORS[trend] || '#6b7280';
        trendEl.style.opacity = 0.5 + (strength * 0.5);  // Scale opacity by confidence
        trendEl.title = trend.replace('_', ' ') + (strength > 0.5 ? ' (strong)' : '');
    } else if (trendEl) {
        trendEl.textContent = '';
    }
}

function updateGovernanceVerdict(data) {
    const verdict = document.getElementById('gov-verdict');
    if (!verdict) return;
    const label = verdict.querySelector('.verdict-label');

    const risk = data.risk;
    if (risk == null) return;

    let text, cls;
    if (risk < 0.35) {
        text = 'Approve'; cls = '';
    } else if (risk < 0.60) {
        text = 'Proceed'; cls = 'risk-elevated';
    } else if (risk < 0.70) {
        text = 'Pause'; cls = 'risk-high';
    } else {
        text = 'Critical'; cls = 'risk-high';
    }

    if (label) label.textContent = text;
    verdict.className = 'governance-verdict' + (cls ? ' ' + cls : '');
}

function updateDataFreshness(timestamp) {
    const el = document.getElementById('data-freshness');
    if (!el || !timestamp) return;
    lastVitalsTimestamp = new Date(timestamp);
    updateFreshnessDisplay();
}

function updateFreshnessDisplay() {
    const el = document.getElementById('data-freshness');
    if (!el || !lastVitalsTimestamp) return;

    const ago = Math.floor((Date.now() - lastVitalsTimestamp.getTime()) / 1000);
    if (ago < 5) {
        el.textContent = 'just now';
        el.className = 'data-freshness fresh';
    } else if (ago < 60) {
        el.textContent = ago + 's ago';
        el.className = 'data-freshness fresh';
    } else if (ago < 300) {
        el.textContent = Math.floor(ago / 60) + 'm ago';
        el.className = 'data-freshness';
    } else {
        el.textContent = Math.floor(ago / 60) + 'm ago';
        el.className = 'data-freshness stale';
    }
}

setInterval(updateFreshnessDisplay, 5000);

// Event icons by type
const EVENT_ICONS = {
    verdict_change: '⚡',
    risk_threshold: '📊',
    trajectory_adjustment: '🎯',
    drift_alert: '🌊',
    agent_new: '✨',
    agent_idle: '💤'
};

// Severity to CSS class mapping
const SEVERITY_CLASSES = {
    info: 'event-info',
    warning: 'event-warning',
    critical: 'event-critical'
};

// ============================================
// Recent Decisions Log (coalesced check-ins)
// ============================================
const MAX_DECISIONS = 8;
const recentDecisions = []; // {agent_id, agent_name, verdict, risk, timestamp, count}

function getVerdictBadge(verdict, risk) {
    // Determine verdict from risk if not provided
    let v = verdict || 'safe';
    if (!verdict && risk != null) {
        if (risk < 0.35) v = 'approve';
        else if (risk < 0.60) v = 'proceed';
        else if (risk < 0.70) v = 'pause';
        else v = 'critical';
    }
    const badges = {
        'safe': { text: 'A', cls: 'verdict-approve', title: 'Approve' },
        'approve': { text: 'A', cls: 'verdict-approve', title: 'Approve' },
        'caution': { text: 'P', cls: 'verdict-proceed', title: 'Proceed' },
        'proceed': { text: 'P', cls: 'verdict-proceed', title: 'Proceed' },
        'elevated': { text: 'P', cls: 'verdict-proceed', title: 'Proceed with caution' },
        'pause': { text: '!', cls: 'verdict-pause', title: 'Pause' },
        'high-risk': { text: '!', cls: 'verdict-pause', title: 'High Risk' },
        'critical': { text: 'X', cls: 'verdict-critical', title: 'Critical' }
    };
    return badges[v] || badges['safe'];
}

function formatCompactTime(timestamp) {
    const now = Date.now();
    const ts = new Date(timestamp).getTime();
    const diff = Math.floor((now - ts) / 1000);
    if (diff < 5) return 'now';
    if (diff < 60) return diff + 's';
    if (diff < 3600) return Math.floor(diff / 60) + 'm';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h';
    return Math.floor(diff / 86400) + 'd';
}

function truncateAgentName(name, maxLen = 15) {
    if (!name) return 'unknown';
    if (name.length <= maxLen) return name;
    return name.substring(0, maxLen - 3) + '...';
}

function addDecision(data) {
    const agentId = data.agent_id || 'unknown';
    const agentName = data.agent_name || agentId;
    const verdict = data.metrics?.verdict || data.decision?.action || 'safe';
    const risk = data.risk != null ? data.risk : 0;
    const timestamp = data.timestamp || new Date().toISOString();
    const now = Date.now();

    // Check if we should coalesce with existing entry
    const existing = recentDecisions.find(d =>
        d.agent_id === agentId &&
        (now - new Date(d.timestamp).getTime()) < CONFIG.COALESCE_WINDOW_MS
    );

    if (existing) {
        // Coalesce: update values and increment count
        existing.verdict = verdict;
        existing.risk = risk;
        existing.timestamp = timestamp;
        existing.count++;
    } else {
        // Add new entry at start
        recentDecisions.unshift({
            agent_id: agentId,
            agent_name: agentName,
            verdict: verdict,
            risk: risk,
            timestamp: timestamp,
            count: 1
        });
        // Trim to max
        while (recentDecisions.length > MAX_DECISIONS) {
            recentDecisions.pop();
        }
    }

    renderDecisionsLog();
}

function renderDecisionsLog() {
    const container = document.getElementById('decisions-log-entries');
    if (!container) return;

    if (recentDecisions.length === 0) {
        container.innerHTML = '<div class="pulse-log-empty">No decisions yet</div>';
        return;
    }

    container.innerHTML = recentDecisions.map(d => {
        const badge = getVerdictBadge(d.verdict, d.risk);
        const countStr = d.count > 1 ? ` <span class="decision-count">×${d.count}</span>` : '';
        const nameDisplay = truncateAgentName(d.agent_name);
        const timeStr = formatCompactTime(d.timestamp);
        const riskStr = d.risk != null ? d.risk.toFixed(2) : '—';

        return `
            <div class="decision-entry" title="${escapeHtml(d.agent_name)} • Risk: ${riskStr} • ${badge.title}">
                <span class="decision-badge ${badge.cls}" title="${badge.title}">${badge.text}</span>
                <span class="decision-agent">${escapeHtml(nameDisplay)}${countStr}</span>
                <span class="decision-risk">(${riskStr})</span>
                <span class="decision-time">${timeStr}</span>
            </div>`;
    }).join('');
}

// Update decisions log timestamps every 5 seconds
setInterval(renderDecisionsLog, 5000);

function addEventEntry(event) {
    const container = document.getElementById('events-log-entries');
    if (!container) return;

    // Remove empty placeholder
    const empty = container.querySelector('.pulse-log-empty');
    if (empty) empty.remove();

    const ts = event.timestamp ? new Date(event.timestamp) : new Date();
    const icon = EVENT_ICONS[event.type] || '📌';
    const severityClass = SEVERITY_CLASSES[event.severity] || 'event-info';

    const entry = document.createElement('div');
    entry.className = `pulse-log-entry ${severityClass}`;
    entry.innerHTML =
        `<span class="event-icon">${icon}</span>` +
        `<span class="log-time">${ts.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}</span>` +
        `<span class="event-message">${escapeHtml(event.message || event.type)}</span>`;

    // Add tooltip with details
    if (event.reason) {
        entry.title = event.reason;
    }

    container.insertBefore(entry, container.firstChild);

    // Trim to max entries
    while (container.children.length > MAX_LOG_ENTRIES) {
        container.removeChild(container.lastChild);
    }
}

// Fetch initial events on page load
async function fetchInitialEvents() {
    try {
        const response = await fetch('/api/events?limit=20');
        const data = await response.json();
        if (data.success && data.events && data.events.length > 0) {
            // Add events in reverse order (oldest first) so newest end up on top
            data.events.slice().reverse().forEach(event => addEventEntry(event));
        }
    } catch (e) {
        console.debug('Could not fetch initial events:', e);
    }
}

// Animate value update with glow effect
function updateValueWithGlow(element, newValue) {
    if (!element) return;
    const oldValue = element.textContent;
    element.textContent = newValue;
    if (oldValue !== newValue) {
        element.classList.add('live-update');
        setTimeout(() => element.classList.remove('live-update'), 800);
    }
}

function updateGovernancePulse(data) {
    // Agent name display
    const agentNameEl = document.getElementById('pulse-agent-name');
    const agentName = data.agent_name || data.agent_id || 'unknown';
    if (agentNameEl) {
        // Truncate long names
        const displayName = agentName.length > 20 ? agentName.substring(0, 17) + '...' : agentName;
        agentNameEl.textContent = displayName;
        agentNameEl.title = agentName;
    }

    // Risk bar with adjustment info
    const risk = data.risk;
    if (risk != null) {
        const rBar = document.getElementById('v-risk');
        const rVal = document.getElementById('vv-risk');
        const rDetail = document.getElementById('vv-risk-detail');
        if (rBar) {
            rBar.style.width = (risk * 100).toFixed(0) + '%';
            // Dynamic color: green (<0.35) → yellow (0.35-0.6) → orange (0.6-0.7) → red (>0.7)
            const riskColor = risk < 0.35 ? '#22c55e' : risk < 0.6 ? '#eab308' : risk < 0.7 ? '#f97316' : '#ef4444';
            rBar.style.background = riskColor;
        }
        updateValueWithGlow(rVal, risk.toFixed(3));

        // Show risk adjustment if present
        if (rDetail) {
            const adjustment = data.risk_adjustment || 0;
            const rawRisk = data.risk_raw || risk;
            const reason = data.risk_reason || '';
            if (adjustment !== 0) {
                const sign = adjustment > 0 ? '+' : '';
                rDetail.textContent = `(${sign}${(adjustment * 100).toFixed(0)}%)`;
                rDetail.title = reason || `Base: ${(rawRisk * 100).toFixed(1)}%, Adjusted: ${(risk * 100).toFixed(1)}%`;
                rDetail.style.color = adjustment > 0 ? 'var(--risk-high, #ef4444)' : 'var(--risk-low, #22c55e)';
            } else {
                rDetail.textContent = '';
                rDetail.title = '';
            }
        }
    }

    // Governance input signals
    const inputs = data.inputs;
    if (inputs) {
        const cxBar = document.getElementById('v-complexity');
        const cxVal = document.getElementById('vv-complexity');
        if (cxBar && inputs.complexity != null) {
            cxBar.style.width = (inputs.complexity * 100).toFixed(0) + '%';
            // Complexity: low=cyan, medium=yellow, high=orange
            const cx = inputs.complexity;
            const cxColor = cx < 0.4 ? '#00f0ff' : cx < 0.7 ? '#eab308' : '#f97316';
            cxBar.style.background = cxColor;
        }
        if (inputs.complexity != null) updateValueWithGlow(cxVal, inputs.complexity.toFixed(2));

        const cfBar = document.getElementById('v-confidence');
        const cfVal = document.getElementById('vv-confidence');
        if (cfBar && inputs.confidence != null) {
            cfBar.style.width = (inputs.confidence * 100).toFixed(0) + '%';
            // Confidence: low=orange, medium=yellow, high=green
            const cf = inputs.confidence;
            const cfColor = cf < 0.5 ? '#f97316' : cf < 0.75 ? '#eab308' : '#22c55e';
            cfBar.style.background = cfColor;
        }
        if (inputs.confidence != null) updateValueWithGlow(cfVal, inputs.confidence.toFixed(2));

        const drift = inputs.ethical_drift;
        const driftTrends = data.drift_trends || {};
        if (drift && drift.length === 3) {
            for (let i = 0; i < 3; i++) {
                const axis = DRIFT_AXES[i];
                const trendInfo = driftTrends[axis] || null;
                updateDriftGauge(i, drift[i], trendInfo);
            }
        }
    }

    // Verdict badge
    updateGovernanceVerdict(data);

    // Events log - add any events from this update
    if (data.events && data.events.length > 0) {
        data.events.forEach(event => addEventEntry(event));
    }

    // Data freshness
    updateDataFreshness(data.timestamp);
}

function initWebSocket() {
    if (typeof EISVWebSocket === 'undefined') {
        console.warn('EISVWebSocket not available');
        return;
    }

    eisvWebSocket = new EISVWebSocket(
        // onUpdate
        function(data) {
            if (data.type === 'eisv_update') {
                addEISVDataPoint(data);

                // Also update agent card if visible
                updateAgentCardFromWS(data);
            }
        },
        // onStatusChange
        function(status) {
            const wsStatus = document.getElementById('ws-status');
            const wsDot = wsStatus ? wsStatus.querySelector('.ws-dot') : null;
            const wsLabel = wsStatus ? wsStatus.querySelector('.ws-label') : null;
            if (wsDot) {
                wsDot.className = 'ws-dot ' + status;
            }
            if (wsStatus) {
                const titles = {
                    connected: 'Live via WebSocket',
                    disconnected: 'WebSocket disconnected',
                    reconnecting: 'WebSocket reconnecting...',
                    polling: 'Live via HTTP polling (WebSocket unavailable)'
                };
                wsStatus.title = titles[status] || status;
            }
            if (wsLabel) {
                wsLabel.textContent = status === 'polling' ? 'Polling' : 'Live';
            }
            console.log('[WS] Status:', status);
        }
    );

    eisvWebSocket.connect();
}

function updateAgentCardFromWS(data) {
    // Find the agent card by agent_name or agent_id and flash it
    const agentCards = document.querySelectorAll('.agent-item');
    for (const card of agentCards) {
        const nameEl = card.querySelector('.agent-name');
        if (nameEl && (nameEl.textContent.includes(data.agent_name) || nameEl.textContent.includes(data.agent_id))) {
            card.style.borderLeftColor = '#10b981';
            card.style.boxShadow = '0 0 12px rgba(16,185,129,0.2)';
            setTimeout(() => {
                card.style.borderLeftColor = '';
                card.style.boxShadow = '';
            }, CONFIG.SCROLL_FEEDBACK_MS);
            break;
        }
    }
}

// Clear chart button
document.getElementById('eisv-chart-clear')?.addEventListener('click', () => {
    [eisvChartUpper, eisvChartLower].forEach(chart => {
        if (chart) {
            chart.data.datasets.forEach(ds => { ds.data = []; });
        }
    });
    requestAnimationFrame(() => {
        if (eisvChartUpper) eisvChartUpper.update();
        if (eisvChartLower) eisvChartLower.update();
    });
    const emptyMsg = document.getElementById('eisv-chart-empty');
    if (emptyMsg) emptyMsg.style.display = '';
    const info = document.getElementById('eisv-chart-info');
    if (info) info.innerHTML = '';
});

// Initialize chart — delay to ensure canvas has dimensions
requestAnimationFrame(() => {
    initEISVChart();
    initWebSocket();
});

// ============================================
// Skeleton loader initialization
// ============================================
function initSkeletons() {
    if (typeof LoadingSkeleton === 'undefined') return;
    const skeletonTargets = {
        'agents-skeleton': { type: 'listItem', count: 3 },
        'discoveries-skeleton': { type: 'card', count: 3 },
        'dialectic-skeleton': { type: 'card', count: 2 },
    };
    for (const [id, config] of Object.entries(skeletonTargets)) {
        const el = document.getElementById(id);
        if (el) {
            el.innerHTML = LoadingSkeleton.create(config.type, config.count);
        }
    }
}
initSkeletons();

// ============================================
// Agent Activity Timeline
// ============================================
function getVerdictClass(agent) {
    const verdict = (agent.metrics || {}).verdict || '';
    if (verdict === 'safe' || verdict === 'approve') return 'safe';
    if (verdict === 'caution' || verdict === 'proceed') return 'caution';
    if (verdict === 'high-risk' || verdict === 'pause') return 'high-risk';
    return 'unknown';
}

function getVerdictLabel(agent) {
    const verdict = (agent.metrics || {}).verdict;
    return verdict || getAgentStatus(agent);
}

function renderTimeline() {
    const container = document.getElementById('timeline-container');
    if (!container) return;

    const rangeSelect = document.getElementById('timeline-range');
    const range = rangeSelect ? rangeSelect.value : '24h';

    // Build timeline events from cached agents
    const now = Date.now();
    let cutoff = 0;
    if (range === '1h') cutoff = now - CONFIG.HOUR_MS;
    else if (range === '24h') cutoff = now - CONFIG.DAY_MS;
    else if (range === '7d') cutoff = now - CONFIG.WEEK_MS;

    const events = cachedAgents
        .filter(agent => {
            const t = new Date(agent.last_update || agent.created_at || 0).getTime();
            return t > cutoff && !isNaN(t);
        })
        .map(agent => {
            const t = new Date(agent.last_update || agent.created_at || 0);
            return {
                time: t,
                agent: agent,
                name: getAgentDisplayName(agent),
                verdictClass: getVerdictClass(agent),
                verdictLabel: getVerdictLabel(agent),
                status: getAgentStatus(agent),
                agentId: agent.agent_id,
            };
        })
        .sort((a, b) => b.time - a.time)
        .slice(0, 30);

    if (events.length === 0) {
        container.innerHTML = '<div class="timeline-empty">No activity in this time range</div>';
        return;
    }

    container.innerHTML = events.map((ev, idx) => {
        const relative = formatRelativeTime(ev.time.getTime()) || 'just now';
        const isLatest = idx === 0;
        return `
            <div class="timeline-item ${isLatest ? 'timeline-latest' : ''}" data-agent-uuid="${escapeHtml(ev.agentId)}" title="Click for details">
                <div class="timeline-dot ${ev.verdictClass}"></div>
                <div class="timeline-content">
                    <div class="timeline-row-primary">
                        <span class="timeline-agent">${escapeHtml(ev.name)}</span>
                        <span class="timeline-time">${escapeHtml(relative)}</span>
                    </div>
                    <div class="timeline-row-secondary">
                        <span class="timeline-action ${ev.verdictClass}">${escapeHtml(ev.verdictLabel)}</span>
                        <span class="timeline-status">${escapeHtml(ev.status)}</span>
                    </div>
                </div>
            </div>`;
    }).join('');
}

// Timeline range filter
const timelineRange = document.getElementById('timeline-range');
if (timelineRange) {
    timelineRange.addEventListener('change', renderTimeline);
}

// Timeline click → agent detail modal
const timelineContainer = document.getElementById('timeline-container');
if (timelineContainer) {
    timelineContainer.addEventListener('click', (event) => {
        const item = event.target.closest('.timeline-item');
        if (!item) return;
        const agentId = item.getAttribute('data-agent-uuid');
        if (!agentId) return;
        const agent = cachedAgents.find(a => (a.agent_id || '') === agentId);
        if (agent) showAgentDetail(agent);
    });
}

// Hook timeline into refresh cycle — update after agents load
const originalLoadAgents = loadAgents;
loadAgents = async function() {
    const result = await originalLoadAgents();
    renderTimeline();
    return result;
};

// ============================================
// WebSocket status label sync
// ============================================
function updateWSStatusLabel(status) {
    const dot = document.querySelector('#ws-status .ws-dot');
    const label = document.querySelector('#ws-status .ws-label');
    const container = document.getElementById('ws-status');
    if (!dot || !label || !container) return;

    dot.className = 'ws-dot ' + status;
    const labels = { connected: 'Live', polling: 'Polling', reconnecting: 'Reconnecting', disconnected: 'Offline' };
    label.textContent = labels[status] || 'Offline';
    const titles = { connected: 'Connected via WebSocket', polling: 'Polling (WebSocket unavailable)', reconnecting: 'Reconnecting...', disconnected: 'Offline' };
    container.title = titles[status] || 'Offline';
}

// Patch EISV WebSocket to update status label
if (typeof EISVWebSocket !== 'undefined') {
    const origInitWS = initWebSocket;
    initWebSocket = function() {
        origInitWS();
        // Monitor WS connection state changes
        const checkInterval = setInterval(() => {
            const wsEl = document.querySelector('#ws-status .ws-dot');
            if (!wsEl) return;
            const currentClass = wsEl.className;
            // The EISVWebSocket class updates dot classes — sync the label
            if (currentClass.includes('connected')) updateWSStatusLabel('connected');
            else if (currentClass.includes('polling')) updateWSStatusLabel('polling');
            else if (currentClass.includes('reconnecting')) updateWSStatusLabel('reconnecting');
            else updateWSStatusLabel('disconnected');
        }, CONFIG.SCROLL_FEEDBACK_MS);
    };
}

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
