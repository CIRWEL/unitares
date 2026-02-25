/**
 * UNITARES Dashboard — Dialectic Module
 *
 * Dialectic session rendering, filtering, detail modal with transcript.
 * Extracted from dashboard.js to reduce monolith size.
 */
(function () {
    'use strict';

    if (typeof DashboardState === 'undefined') {
        console.warn('[DialecticModule] state.js not loaded, module disabled');
        return;
    }

    var escapeHtml = DataProcessor.escapeHtml;

    // ========================================================================
    // Dialectic utility functions
    // ========================================================================

    function getPhaseColor(phase) {
        var colors = {
            resolved: 'var(--accent-green)',
            failed: 'var(--accent-orange)',
            thesis: 'var(--accent-cyan)',
            antithesis: 'var(--accent-purple)',
            synthesis: 'var(--accent-yellow)'
        };
        return colors[phase] || 'var(--text-secondary)';
    }

    function formatDialecticPhase(phase) {
        var labels = {
            resolved: 'Resolved',
            failed: 'Failed',
            thesis: 'Thesis',
            antithesis: 'Antithesis',
            synthesis: 'Synthesis'
        };
        return labels[phase] || phase || 'Unknown';
    }

    // ========================================================================
    // Dialectic UI helpers
    // ========================================================================

    function updateDialecticDisplay(sessions, message) {
        var sessionsEl = document.getElementById('dialectic-sessions');
        var changeEl = document.getElementById('dialectic-change');
        if (sessionsEl) sessionsEl.textContent = sessions.length || '?';
        if (changeEl) changeEl.innerHTML = message || '';
    }

    function updateDialecticFilterInfo(count) {
        var filterInfo = document.getElementById('dialectic-filter-info');
        if (filterInfo) {
            filterInfo.textContent = 'Showing ' + count + ' session' + (count !== 1 ? 's' : '');
        }
    }

    /**
     * Resolve agent UUID to display label using cached agent data.
     * Returns label if found, otherwise truncated UUID, or fallback.
     */
    function resolveAgentLabel(uuid, fallback) {
        if (!uuid || uuid === 'Unknown' || uuid === 'unknown') return fallback || 'Unknown';
        var agents = state.get('cachedAgents') || [];
        for (var i = 0; i < agents.length; i++) {
            if (agents[i].agent_id === uuid) {
                return agents[i].label || agents[i].name || uuid.substring(0, 8);
            }
        }
        // Not in cache — return short UUID
        return uuid.substring(0, 8);
    }

    // ========================================================================
    // Dialectic list rendering
    // ========================================================================

    function renderDialecticList(sessions) {
        var container = document.getElementById('dialectic-container');
        if (!container) return;

        if (!sessions || sessions.length === 0) {
            container.innerHTML = '<div class="dialectic-empty">' +
                '<div class="dialectic-empty-icon">🔄</div>' +
                '<div>No active dialectic sessions</div>' +
                '<div style="font-size: 0.85em; margin-top: 5px; opacity: 0.7">' +
                    'Sessions appear when agents request recovery reviews' +
                '</div>' +
            '</div>';
            return;
        }

        var displaySessions = sessions.slice(0, 25);
        var hasMore = sessions.length > 25;

        container.innerHTML = displaySessions.map(function (session) {
            var phase = session.phase || session.status || 'unknown';
            var phaseColor = getPhaseColor(phase);
            var requestorUuid = session.paused_agent || session.requestor_id || session.agent_id || '';
            var reviewerUuid = session.reviewer || session.reviewer_id || '';
            var requestorLabel = resolveAgentLabel(requestorUuid, 'Unknown');
            var reviewerLabel = reviewerUuid ? resolveAgentLabel(reviewerUuid) : 'None';
            var sessionType = session.session_type || session.type || 'verification';
            var topic = session.topic || session.reason || (sessionType + ' session');
            var created = session.created || session.created_at || session.timestamp || '';

            // Format timestamp
            var timeAgo = '';
            if (created) {
                try {
                    var date = new Date(created);
                    var now = new Date();
                    var diffMs = now - date;
                    var diffMins = Math.floor(diffMs / 60000);
                    var diffHours = Math.floor(diffMins / 60);
                    var diffDays = Math.floor(diffHours / 24);

                    if (diffDays > 0) timeAgo = diffDays + 'd ago';
                    else if (diffHours > 0) timeAgo = diffHours + 'h ago';
                    else if (diffMins > 0) timeAgo = diffMins + 'm ago';
                    else timeAgo = 'Just now';
                } catch (e) {
                    timeAgo = created;
                }
            }

            // Resolution info
            var resolutionInfo = '';
            if (session.resolution) {
                var res = session.resolution;
                resolutionInfo = '<div class="dialectic-resolution">' +
                    'Resolution: ' + escapeHtml(res.action || res.type || 'Unknown') +
                    (res.confidence ? ' (' + (res.confidence * 100).toFixed(0) + '% conf)' : '') +
                '</div>';
            }

            return '<div class="dialectic-item ' + phase + '" data-session-id="' + (session.session_id || '') + '" style="cursor: pointer;" title="Click to view details">' +
                '<div class="dialectic-header">' +
                    '<span class="dialectic-type" style="border-color: ' + phaseColor + '; color: ' + phaseColor + '">' +
                        escapeHtml(formatDialecticPhase(phase)) +
                    '</span>' +
                    '<span class="dialectic-session-type">' + escapeHtml(sessionType) + '</span>' +
                    '<span class="dialectic-time">' + escapeHtml(timeAgo) + '</span>' +
                '</div>' +
                '<div class="dialectic-topic">' + escapeHtml(topic) + '</div>' +
                '<div class="dialectic-agents">' +
                    '<span class="agent-label">Requestor:</span> ' + escapeHtml(requestorLabel) + (requestorUuid ? ' <code style="font-size: 0.75em; color: var(--text-tertiary);">' + escapeHtml(requestorUuid.substring(0, 8)) + '</code>' : '') +
                    (reviewerLabel && reviewerLabel !== 'None'
                        ? '<span class="agent-label" style="margin-left: 10px;">Reviewer:</span> ' + escapeHtml(reviewerLabel) + (reviewerUuid ? ' <code style="font-size: 0.75em; color: var(--text-tertiary);">' + escapeHtml(reviewerUuid.substring(0, 8)) + '</code>' : '')
                        : '') +
                    '<span class="agent-label" style="margin-left: 10px; color: var(--accent-cyan);">📝 ' + (session.message_count || 0) + ' messages</span>' +
                '</div>' +
                resolutionInfo +
            '</div>';
        }).join('');

        if (hasMore) {
            container.innerHTML += '<div class="loading" style="text-align: center; padding: 10px;">' +
                '...and ' + (sessions.length - 25) + ' more sessions (use filter to narrow down)' +
            '</div>';
        }
    }

    // ========================================================================
    // Dialectic filtering
    // ========================================================================

    function applyDialecticFilters() {
        var statusFilter = document.getElementById('dialectic-status-filter');
        var filter = statusFilter ? statusFilter.value : 'all';

        var cachedDialecticSessions = state.get('cachedDialecticSessions');
        var filtered = cachedDialecticSessions;

        if (filter === 'substantive') {
            filtered = cachedDialecticSessions.filter(function (s) {
                return (s.message_count || 0) >= 3;
            });
        } else if (filter !== 'all') {
            filtered = cachedDialecticSessions.filter(function (s) {
                var phase = s.phase || s.status || '';
                if (filter === 'active') {
                    return ['thesis', 'antithesis', 'synthesis'].indexOf(phase) !== -1;
                }
                return phase === filter;
            });
        }

        updateDialecticFilterInfo(filtered.length);
        renderDialecticList(filtered);
    }

    // ========================================================================
    // Dialectic detail modal
    // ========================================================================

    function showDialecticDetail(session) {
        var modal = document.getElementById('panel-modal');
        var modalTitle = document.getElementById('modal-title');
        var modalBody = document.getElementById('modal-body');
        if (!modal || !modalTitle || !modalBody) return;

        var sessionId = session.session_id || 'Unknown';
        var phase = session.phase || session.status || 'unknown';

        // Show modal with loading state
        modalTitle.textContent = 'Dialectic Session: ' + formatDialecticPhase(phase);
        modalBody.innerHTML = '<div class="loading">Loading full session details...</div>';
        modal.classList.add('visible');
        document.body.style.overflow = 'hidden';

        // Try to fetch full session with transcript (callTool is in dashboard.js, available at call time)
        var fullSession = session;
        if (sessionId && sessionId !== 'Unknown' && typeof callTool === 'function') {
            callTool('dialectic', {
                action: 'get',
                session_id: sessionId
            }).then(function (result) {
                if (result && result.session) {
                    fullSession = result.session;
                } else if (result && !result.error) {
                    fullSession = result;
                }
                renderDialecticDetailContent(modalBody, fullSession);
            }).catch(function (e) {
                console.warn('Failed to fetch full session, using cached:', e);
                renderDialecticDetailContent(modalBody, fullSession);
            });
        } else {
            renderDialecticDetailContent(modalBody, fullSession);
        }
    }

    function renderDialecticDetailContent(container, session) {
        var phase = session.phase || session.status || 'unknown';
        var phaseColor = getPhaseColor(phase);
        var requestorUuid = session.paused_agent || session.requestor_id || session.agent_id || '';
        var reviewerUuid = session.reviewer || session.reviewer_id || '';
        var requestorLabel = resolveAgentLabel(requestorUuid, 'Unknown');
        var reviewerLabel = reviewerUuid ? resolveAgentLabel(reviewerUuid) : 'None';
        var sessionType = session.session_type || session.type || 'verification';
        var topic = session.topic || session.reason || (sessionType + ' session');
        var sessionId = session.session_id || 'Unknown';
        var created = session.created || session.created_at || session.timestamp || '';

        var filterFn = typeof filterInternalKeys === 'function' ? filterInternalKeys : function (o) { return o; };

        var html = '<div class="dialectic-detail">' +
            '<div class="dialectic-detail-header">' +
                '<span class="dialectic-type" style="border-color: ' + phaseColor + '; color: ' + phaseColor + '; font-size: 1.1em;">' +
                    escapeHtml(formatDialecticPhase(phase)) +
                '</span>' +
                '<span class="dialectic-session-type" style="font-size: 1em;">' + escapeHtml(sessionType) + '</span>' +
            '</div>' +

            '<div class="detail-section mt-md">' +
                '<strong class="text-secondary-sm">Topic:</strong><br>' +
                '<span style="font-size: 1.1em;">' + escapeHtml(topic) + '</span>' +
            '</div>' +

            '<div class="grid-2col mb-md mt-md">' +
                '<div>' +
                    '<strong class="text-secondary-sm">Session ID:</strong><br>' +
                    '<code style="font-size: 0.85em; word-break: break-all;">' + escapeHtml(sessionId) + '</code>' +
                '</div>' +
                '<div>' +
                    '<strong class="text-secondary-sm">Created:</strong><br>' +
                    escapeHtml(created) +
                '</div>' +
            '</div>' +

            '<div class="grid-2col mb-md">' +
                '<div>' +
                    '<strong class="text-secondary-sm">Requestor:</strong><br>' +
                    escapeHtml(requestorLabel) +
                    (requestorUuid ? '<br><code style="font-size: 0.75em; color: var(--text-tertiary); word-break: break-all;">' + escapeHtml(requestorUuid) + '</code>' : '') +
                '</div>' +
                '<div>' +
                    '<strong class="text-secondary-sm">Reviewer:</strong><br>' +
                    (reviewerLabel !== 'None'
                        ? escapeHtml(reviewerLabel) +
                          (reviewerUuid ? '<br><code style="font-size: 0.75em; color: var(--text-tertiary); word-break: break-all;">' + escapeHtml(reviewerUuid) + '</code>' : '')
                        : '<span class="text-secondary-sm">Not assigned</span>') +
                '</div>' +
            '</div>';

        // Resolution
        if (session.resolution) {
            var res = session.resolution;
            html += '<div class="resolution-callout">' +
                '<strong style="color: var(--accent-green);">Resolution:</strong><br>' +
                '<span>Action: ' + escapeHtml(res.action || res.type || 'Unknown') + '</span>' +
                (res.confidence ? '<br>Confidence: ' + (res.confidence * 100).toFixed(0) + '%' : '') +
                (res.reason ? '<br>Reason: ' + escapeHtml(res.reason) : '') +
            '</div>';
        }

        // Transcript
        var transcript = session.transcript || [];
        if (transcript.length > 0) {
            html += '<div class="detail-section mt-md">' +
                '<strong class="detail-section-title">Discussion Transcript (' + transcript.length + ' messages):</strong>' +
                '<div class="mt-sm" style="max-height: 350px; overflow-y: auto;">';

            transcript.forEach(function (entry) {
                var role = entry.role || entry.phase || 'system';
                var content = entry.content || entry.reasoning || entry.message || '';
                var timestamp = entry.timestamp || '';
                var authorUuid = entry.agent_id || '';
                var authorLabel = authorUuid ? resolveAgentLabel(authorUuid) : '';
                var roleColors = {
                    thesis: 'var(--accent-cyan)',
                    antithesis: 'var(--accent-purple)',
                    synthesis: 'var(--accent-yellow)',
                    system: 'var(--text-secondary)'
                };
                var roleColor = roleColors[role] || 'var(--accent-cyan)';

                html += '<div class="transcript-entry" style="border-left-color: ' + roleColor + ';">' +
                    '<div class="flex-between mb-sm">' +
                        '<span>' +
                            '<strong style="color: ' + roleColor + '; text-transform: uppercase; font-size: 0.8em;">' + escapeHtml(role) + '</strong>' +
                            (authorLabel ? '<span style="color: var(--text-secondary); font-size: 0.8em; margin-left: 8px;">' + escapeHtml(authorLabel) + '</span>' : '') +
                            (authorUuid ? '<code style="color: var(--text-tertiary); font-size: 0.7em; margin-left: 6px;">' + escapeHtml(authorUuid.substring(0, 8)) + '</code>' : '') +
                        '</span>' +
                        (timestamp ? '<span class="text-secondary-xxs">' + escapeHtml(timestamp) + '</span>' : '') +
                    '</div>' +
                    '<div style="color: var(--text-primary); white-space: pre-wrap; word-wrap: break-word; font-size: 0.9em; line-height: 1.5;">' + escapeHtml(content) + '</div>' +
                '</div>';
            });

            html += '</div></div>';
        } else {
            html += '<div class="empty-state-centered mt-md">' +
                '<div style="font-size: 1.5em; margin-bottom: 8px;">📭</div>' +
                'No transcript recorded for this session.<br>' +
                '<small>This may be an auto-resolved or system-generated session.</small>' +
            '</div>';
        }

        // Raw data
        html += '<details class="mt-md">' +
            '<summary class="cursor-pointer text-secondary-sm">Raw session data</summary>' +
            '<pre class="raw-data-pre">' + escapeHtml(JSON.stringify(filterFn(session), null, 2)) + '</pre>' +
        '</details></div>';

        container.innerHTML = html;
    }

    // ========================================================================
    // Public API
    // ========================================================================

    window.DialecticModule = {
        getPhaseColor: getPhaseColor,
        formatDialecticPhase: formatDialecticPhase,
        updateDialecticDisplay: updateDialecticDisplay,
        updateDialecticFilterInfo: updateDialecticFilterInfo,
        renderDialecticList: renderDialecticList,
        applyDialecticFilters: applyDialecticFilters,
        showDialecticDetail: showDialecticDetail,
        renderDialecticDetailContent: renderDialecticDetailContent
    };
})();
