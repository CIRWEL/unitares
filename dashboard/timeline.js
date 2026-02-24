/**
 * UNITARES Dashboard — Timeline Module
 *
 * Agent activity timeline, skeleton loaders, WS status label.
 * Extracted from dashboard.js to reduce monolith size.
 */
(function () {
    'use strict';

    if (typeof DashboardState === 'undefined') {
        console.warn('[TimelineModule] state.js not loaded, module disabled');
        return;
    }

    var escapeHtml = DataProcessor.escapeHtml;
    var formatRelativeTime = DataProcessor.formatRelativeTime;

    // Time constants (local to avoid cross-script CONFIG dependency)
    var HOUR_MS = 60 * 60 * 1000;
    var DAY_MS = 24 * 60 * 60 * 1000;
    var WEEK_MS = 7 * DAY_MS;

    // ========================================================================
    // Skeleton loader initialization
    // ========================================================================

    function initSkeletons() {
        if (typeof LoadingSkeleton === 'undefined') return;
        var targets = {
            'agents-skeleton': { type: 'listItem', count: 3 },
            'discoveries-skeleton': { type: 'card', count: 3 },
            'dialectic-skeleton': { type: 'card', count: 2 }
        };
        var ids = Object.keys(targets);
        for (var i = 0; i < ids.length; i++) {
            var el = document.getElementById(ids[i]);
            if (el) {
                el.innerHTML = LoadingSkeleton.create(targets[ids[i]].type, targets[ids[i]].count);
            }
        }
    }

    // Run immediately
    initSkeletons();

    // ========================================================================
    // Timeline utility functions
    // ========================================================================

    function getVerdictClass(agent) {
        var verdict = (agent.metrics || {}).verdict || '';
        if (verdict === 'safe' || verdict === 'approve') return 'safe';
        if (verdict === 'caution' || verdict === 'proceed') return 'caution';
        if (verdict === 'high-risk' || verdict === 'pause') return 'high-risk';
        return 'unknown';
    }

    function getVerdictLabel(agent) {
        var verdict = (agent.metrics || {}).verdict;
        if (verdict) return verdict;
        // Fall back to AgentsModule.getAgentStatus if available
        if (typeof AgentsModule !== 'undefined' && AgentsModule.getAgentStatus) {
            return AgentsModule.getAgentStatus(agent);
        }
        return 'unknown';
    }

    // ========================================================================
    // Timeline rendering
    // ========================================================================

    function renderTimeline() {
        var container = document.getElementById('timeline-container');
        if (!container) return;

        var rangeSelect = document.getElementById('timeline-range');
        var range = rangeSelect ? rangeSelect.value : '24h';
        var cachedAgents = state.get('cachedAgents');

        var now = Date.now();
        var cutoff = 0;
        if (range === '1h') cutoff = now - HOUR_MS;
        else if (range === '24h') cutoff = now - DAY_MS;
        else if (range === '7d') cutoff = now - WEEK_MS;

        var getDisplayName = (typeof AgentsModule !== 'undefined' && AgentsModule.getAgentDisplayName)
            ? AgentsModule.getAgentDisplayName
            : function (a) { return a.agent_name || a.display_name || a.agent_id || 'Unknown'; };

        var getStatus = (typeof AgentsModule !== 'undefined' && AgentsModule.getAgentStatus)
            ? AgentsModule.getAgentStatus
            : function () { return 'unknown'; };

        var events = cachedAgents
            .filter(function (agent) {
                var t = new Date(agent.last_update || agent.created_at || 0).getTime();
                return t > cutoff && !isNaN(t);
            })
            .map(function (agent) {
                var t = new Date(agent.last_update || agent.created_at || 0);
                return {
                    time: t,
                    agent: agent,
                    name: getDisplayName(agent),
                    verdictClass: getVerdictClass(agent),
                    verdictLabel: getVerdictLabel(agent),
                    status: getStatus(agent),
                    agentId: agent.agent_id
                };
            })
            .sort(function (a, b) { return b.time - a.time; })
            .slice(0, 30);

        if (events.length === 0) {
            container.innerHTML = '<div class="timeline-empty">No activity in this time range</div>';
            return;
        }

        container.innerHTML = events.map(function (ev, idx) {
            var relative = formatRelativeTime(ev.time.getTime()) || 'just now';
            var isLatest = idx === 0;
            return '<div class="timeline-item' + (isLatest ? ' timeline-latest' : '') + '" data-agent-uuid="' + escapeHtml(ev.agentId) + '" title="Click for details">' +
                '<div class="timeline-dot ' + ev.verdictClass + '"></div>' +
                '<div class="timeline-content">' +
                    '<div class="timeline-row-primary">' +
                        '<span class="timeline-agent">' + escapeHtml(ev.name) + '</span>' +
                        '<span class="timeline-time">' + escapeHtml(relative) + '</span>' +
                    '</div>' +
                    '<div class="timeline-row-secondary">' +
                        '<span class="timeline-action ' + ev.verdictClass + '">' + escapeHtml(ev.verdictLabel) + '</span>' +
                        '<span class="timeline-status">' + escapeHtml(ev.status) + '</span>' +
                    '</div>' +
                '</div>' +
            '</div>';
        }).join('');
    }

    // ========================================================================
    // WebSocket status label
    // ========================================================================

    function updateWSStatusLabel(status) {
        var dot = document.querySelector('#ws-status .ws-dot');
        var label = document.querySelector('#ws-status .ws-label');
        var container = document.getElementById('ws-status');
        if (!dot || !label || !container) return;

        dot.className = 'ws-dot ' + status;
        var labels = { connected: 'Live', polling: 'Polling', reconnecting: 'Reconnecting', disconnected: 'Offline' };
        label.textContent = labels[status] || 'Offline';
        var titles = { connected: 'Connected via WebSocket', polling: 'Polling (WebSocket unavailable)', reconnecting: 'Reconnecting...', disconnected: 'Offline' };
        container.title = titles[status] || 'Offline';
    }

    // ========================================================================
    // Self-initialization
    // ========================================================================

    function onDOMReady() {
        // Timeline range filter
        var rangeEl = document.getElementById('timeline-range');
        if (rangeEl) {
            rangeEl.addEventListener('change', renderTimeline);
        }

        // Timeline click → agent detail modal
        var timelineEl = document.getElementById('timeline-container');
        if (timelineEl) {
            timelineEl.addEventListener('click', function (event) {
                var item = event.target.closest('.timeline-item');
                if (!item) return;
                var agentId = item.getAttribute('data-agent-uuid');
                if (!agentId) return;
                var cachedAgents = state.get('cachedAgents');
                var agent = null;
                for (var i = 0; i < cachedAgents.length; i++) {
                    if ((cachedAgents[i].agent_id || '') === agentId) {
                        agent = cachedAgents[i];
                        break;
                    }
                }
                if (agent && typeof showAgentDetail === 'function') {
                    showAgentDetail(agent);
                }
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', onDOMReady);
    } else {
        onDOMReady();
    }

    // ========================================================================
    // Public API
    // ========================================================================

    window.TimelineModule = {
        initSkeletons: initSkeletons,
        getVerdictClass: getVerdictClass,
        getVerdictLabel: getVerdictLabel,
        renderTimeline: renderTimeline,
        updateWSStatusLabel: updateWSStatusLabel
    };
})();
