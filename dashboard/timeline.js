/**
 * UNITARES Dashboard — Activity Timeline & Skeletons
 *
 * Global activity feed: check-ins, verdicts, discoveries, dialectic events.
 * Also handles skeleton loaders and WS status label.
 */
(function () {
    'use strict';

    if (typeof DashboardState === 'undefined') {
        console.warn('[TimelineModule] state.js not loaded, module disabled');
        return;
    }

    var escapeHtml = typeof DataProcessor !== 'undefined' ? DataProcessor.escapeHtml : function (s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
    var formatRelativeTime = typeof DataProcessor !== 'undefined' ? DataProcessor.formatRelativeTime : function () { return ''; };

    var MAX_TIMELINE_ITEMS = 100;
    var timelineEntries = []; // {ts, type, agent, message, verdict, className}
    var currentFilter = 'all';

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

    initSkeletons();

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
    // Activity timeline
    // ========================================================================

    var VERDICT_CLASSES = {
        approve: 'tl-good', proceed: 'tl-good',
        caution: 'tl-caution', guide: 'tl-caution',
        pause: 'tl-bad', reject: 'tl-bad'
    };

    function addTimelineEntry(entry) {
        // entry: {ts: Date, type: string, agent: string, message: string, verdict?: string}
        entry.ts = entry.ts || new Date();
        entry.className = entry.verdict ? (VERDICT_CLASSES[entry.verdict] || '') : '';

        timelineEntries.unshift(entry);
        if (timelineEntries.length > MAX_TIMELINE_ITEMS) {
            timelineEntries.length = MAX_TIMELINE_ITEMS;
        }

        renderTimeline();
    }

    function renderTimeline() {
        var container = document.getElementById('timeline-container');
        if (!container) return;

        var filtered = currentFilter === 'all'
            ? timelineEntries
            : timelineEntries.filter(function (e) { return e.type === currentFilter; });

        if (filtered.length === 0) {
            container.innerHTML = '<div class="timeline-empty">No events' + (currentFilter !== 'all' ? ' matching filter' : '') + '</div>';
            return;
        }

        var html = filtered.slice(0, 50).map(function (e) {
            var timeStr = e.ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            var relative = formatRelativeTime(e.ts.getTime());
            var relStr = relative ? ' (' + relative + ')' : '';
            var typeIcon = { checkin: '\u25CF', verdict: '\u25A0', discovery: '\u2605', dialectic: '\u25B6' }[e.type] || '\u25CB';
            var agentStr = e.agent ? '<span class="tl-agent">' + escapeHtml(e.agent) + '</span>' : '';
            var verdictBadge = e.verdict ? '<span class="tl-verdict ' + (VERDICT_CLASSES[e.verdict] || '') + '">' + escapeHtml(e.verdict) + '</span>' : '';

            return '<div class="tl-entry ' + (e.className || '') + '" data-type="' + (e.type || '') + '">' +
                '<span class="tl-icon">' + typeIcon + '</span>' +
                '<span class="tl-time" title="' + escapeHtml(e.ts.toLocaleString() + relStr) + '">' + timeStr + '</span>' +
                agentStr + verdictBadge +
                '<span class="tl-message">' + escapeHtml(e.message || '') + '</span>' +
            '</div>';
        }).join('');

        container.innerHTML = html;
    }

    // Called from WebSocket handler for each EISV update
    function onEISVUpdate(data) {
        if (!data || data.type !== 'eisv_update') return;

        var agentLabel = data.agent_label || data.agent_name || (data.agent_id ? data.agent_id.substring(0, 12) : 'unknown');
        var verdict = data.verdict;
        var risk = data.risk_score != null ? (data.risk_score * 100).toFixed(0) + '%' : null;
        var coherence = data.coherence != null ? data.coherence.toFixed(3) : null;

        // Check-in entry
        var parts = [];
        if (risk) parts.push('risk ' + risk);
        if (coherence) parts.push('C ' + coherence);
        var metricsStr = parts.length ? ' (' + parts.join(', ') + ')' : '';

        addTimelineEntry({
            ts: data.timestamp ? new Date(data.timestamp) : new Date(),
            type: 'checkin',
            agent: agentLabel,
            message: 'checked in' + metricsStr,
            verdict: verdict
        });

        // Events within the update
        if (data.events && data.events.length > 0) {
            data.events.forEach(function (event) {
                addTimelineEntry({
                    ts: event.timestamp ? new Date(event.timestamp) : new Date(),
                    type: 'verdict',
                    agent: agentLabel,
                    message: event.message || event.type,
                    verdict: event.severity === 'warning' ? 'caution' : event.severity === 'critical' ? 'pause' : null
                });
            });
        }
    }

    // Called from loadDiscoveries/loadDialecticSessions to seed recent items
    function addDiscoveryEvent(discovery) {
        var agent = discovery.by || discovery.agent_id || discovery._agent_id || 'unknown';
        var summary = discovery.summary || 'New discovery';
        var type = discovery.type || discovery.discovery_type || 'note';
        addTimelineEntry({
            ts: discovery._timestampMs ? new Date(discovery._timestampMs) : new Date(),
            type: 'discovery',
            agent: typeof agent === 'string' && agent.length > 20 ? agent.substring(0, 12) : agent,
            message: type + ': ' + (summary.length > 60 ? summary.substring(0, 57) + '...' : summary)
        });
    }

    function addDialecticEvent(session) {
        var phase = session.phase || session.status || 'unknown';
        var topic = session.topic || session.reason || 'session';
        addTimelineEntry({
            ts: session.created_at ? new Date(session.created_at) : new Date(),
            type: 'dialectic',
            agent: session.initiator_label || (session.initiator_id ? session.initiator_id.substring(0, 12) : ''),
            message: phase + ': ' + (topic.length > 50 ? topic.substring(0, 47) + '...' : topic)
        });
    }

    function clearTimeline() {
        timelineEntries.length = 0;
        renderTimeline();
    }

    // ========================================================================
    // Event listeners
    // ========================================================================

    var filterSelect = document.getElementById('timeline-filter');
    if (filterSelect) {
        filterSelect.addEventListener('change', function () {
            currentFilter = this.value;
            renderTimeline();
        });
    }

    var clearBtn = document.getElementById('timeline-clear');
    if (clearBtn) {
        clearBtn.addEventListener('click', clearTimeline);
    }

    // ========================================================================
    // Public API
    // ========================================================================

    window.TimelineModule = {
        initSkeletons: initSkeletons,
        updateWSStatusLabel: updateWSStatusLabel,
        addTimelineEntry: addTimelineEntry,
        onEISVUpdate: onEISVUpdate,
        addDiscoveryEvent: addDiscoveryEvent,
        addDialecticEvent: addDialecticEvent,
        clearTimeline: clearTimeline,
        renderTimeline: renderTimeline
    };
})();
