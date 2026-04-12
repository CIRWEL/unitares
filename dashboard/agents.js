/**
 * UNITARES Dashboard — Agents Module
 *
 * Agent rendering, filtering, detail modal, and export.
 * Extracted from dashboard.js to reduce monolith size.
 */
(function () {
    'use strict';

    if (typeof DashboardState === 'undefined') {
        console.warn('[AgentsModule] state.js not loaded, module disabled');
        return;
    }

    // Shorthand references (utils.js and visualizations.js load before this module)
    var escapeHtml = DataProcessor.escapeHtml;
    var highlightMatch = DataProcessor.highlightMatch;
    var formatRelativeTime = DataProcessor.formatRelativeTime;

    // Production filter & pagination state managed via state.js
    // VERDICT_ICONS is defined in utils.js and exported on window

    /**
     * Heuristic: returns true if agent looks like a test/experiment agent.
     */
    function isTestAgent(agent) {
        var name = (agent.label || agent.display_name || agent.name || '').toLowerCase();
        if (/^(exp_|val_|paper_|test_|test-|cli-pytest)/.test(name)) return true;
        if (/\bpytest\b/.test(name) || /\btest\b/.test(name)) return true;
        var tags = agent.tags || [];
        for (var i = 0; i < tags.length; i++) {
            var t = String(tags[i]).toLowerCase();
            if (t === 'test' || t === 'experimental') return true;
        }
        // Skip staleness heuristic for actively running agents
        if ((agent.lifecycle_status || '').toLowerCase() === 'active') return false;
        var totalUpdates = agent.total_updates || 0;
        if (totalUpdates < 200) {
            var staleness = getAgentStaleness(agent);
            if (staleness.ageMs > 72 * 60 * 60 * 1000) return true;
        }
        return false;
    }

    /**
     * Returns only production agents (filtered by isTestAgent heuristic).
     */
    function getProductionAgents(agents) {
        return agents.filter(function (a) { return !isTestAgent(a); });
    }

    // ========================================================================
    // Agent utility functions
    // ========================================================================

    function getAgentStaleness(agent) {
        if (!agent.last_update) return { level: 'unknown', label: '', ageMs: Infinity };
        var lastDt = new Date(agent.last_update);
        if (isNaN(lastDt.getTime())) return { level: 'unknown', label: '', ageMs: Infinity };
        var ageMs = Date.now() - lastDt.getTime();
        var ageMins = ageMs / 60000;
        var ageHours = ageMins / 60;
        var ageDays = ageHours / 24;

        if (ageMins < 10) return { level: 'fresh', label: '', ageMs: ageMs };
        if (ageMins < 60) return { level: 'recent', label: Math.round(ageMins) + 'm ago', ageMs: ageMs };
        if (ageHours < 24) return { level: 'stale', label: Math.round(ageHours) + 'h ago', ageMs: ageMs };
        return { level: 'dead', label: Math.round(ageDays) + 'd ago', ageMs: ageMs };
    }

    function getStaleBadgeHtml(agent) {
        var staleness = getAgentStaleness(agent);
        if (staleness.level === 'fresh' || staleness.level === 'unknown') return '';
        if (staleness.level === 'recent') {
            return '<span class="stale-badge stale-recent" title="Last check-in ' + staleness.label + '">' + staleness.label + '</span>';
        }
        if (staleness.level === 'stale') {
            return '<span class="stale-badge stale-warning" title="No check-in for ' + staleness.label + '">' + staleness.label + '</span>';
        }
        return '<span class="stale-badge stale-dead" title="Last check-in ' + staleness.label + '">Stale ' + staleness.label + '</span>';
    }

    function getInactiveBadgeHtml(agent) {
        if (agent._stuck) return '';  // already has stuck badge
        var staleness = getAgentStaleness(agent);
        if (staleness.ageMs > 3600000) {  // >1 hour
            return '<span class="inactive-badge" title="No check-in for over 1 hour">Inactive</span>';
        }
        return '';
    }

    function getAgentStatus(agent) {
        return agent.lifecycle_status || agent.status || 'unknown';
    }

    function getAgentDisplayName(agent) {
        return agent.label || agent.display_name || agent.name || agent.agent_id || 'Unknown';
    }

    function agentHasMetrics(agent) {
        var metrics = agent.metrics || {};
        return metrics && (metrics.E !== undefined || metrics.I !== undefined || metrics.S !== undefined);
    }

    function formatStatusLabel(status) {
        var normalized = String(status || 'unknown').toLowerCase();
        var labels = {
            active: 'Active',
            waiting_input: 'Waiting',
            paused: 'Paused',
            archived: 'Archived',
            deleted: 'Deleted',
            unknown: 'Unknown'
        };
        return labels[normalized] || normalized.replace(/_/g, ' ');
    }

    function formatAgentTimestamp(agent) {
        var lastUpdateDate = agent.last_update ? new Date(agent.last_update) : null;
        if (lastUpdateDate && !isNaN(lastUpdateDate.getTime())) {
            var lastUpdate = DataProcessor.formatTimestamp(agent.last_update);
            var relative = formatRelativeTime(lastUpdateDate.getTime());
            return relative ? 'Updated ' + lastUpdate + ' (' + relative + ')' : 'Updated ' + lastUpdate;
        }
        var createdDate = agent.created_at ? new Date(agent.created_at) : null;
        if (createdDate && !isNaN(createdDate.getTime())) {
            var created = DataProcessor.formatTimestamp(agent.created_at);
            var relative2 = formatRelativeTime(createdDate.getTime());
            return relative2 ? 'Created ' + created + ' (' + relative2 + ')' : 'Created ' + created;
        }
        return null;
    }

    // ========================================================================
    // Agent UI helpers
    // ========================================================================

    function updateStatusLegend(statusCounts) {
        var container = document.getElementById('agents-status-legend');
        if (!container) return;
        if (!statusCounts) {
            container.textContent = '';
            return;
        }
        var entries = [
            { key: 'active', label: 'Active', count: statusCounts.active || 0 },
            { key: 'waiting_input', label: 'Waiting', count: statusCounts.waiting_input || 0 },
            { key: 'paused', label: 'Paused', count: statusCounts.paused || 0 },
            { key: 'archived', label: 'Archived', count: statusCounts.archived || 0 },
            { key: 'deleted', label: 'Deleted', count: statusCounts.deleted || 0 },
            { key: 'unknown', label: 'Unknown', count: statusCounts.unknown || 0 }
        ];
        var chips = entries
            .filter(function (entry) { return entry.count > 0; })
            .map(function (entry) {
                return '<button class="status-chip ' + entry.key + '" data-status="' + entry.key + '" type="button">' + entry.label + ' ' + entry.count + '</button>';
            })
            .join(' ');
        container.innerHTML = chips || '';
    }

    function updateAgentFilterInfo(filteredCount) {
        var info = document.getElementById('agents-filter-info');
        if (!info) return;
        var total = state.get('cachedAgents').length;
        if (!total) {
            info.textContent = '';
            return;
        }
        if (filteredCount === 0) {
            info.textContent = 'No agents match filters (' + total + ' loaded)';
            return;
        }
        // Info text is now driven by pagination footer, keep this minimal
        info.textContent = '';
    }

    // ========================================================================
    // Agent list rendering
    // ========================================================================

    function renderAgentsList(agents, searchTerm) {
        searchTerm = searchTerm || '';
        var container = document.getElementById('agents-container');
        var cachedAgents = state.get('cachedAgents');

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
        var agentEISVHistory = state.get('agentEISVHistory') || {};
        var displayAgents = agents.slice(0, state.get('agentPageSize'));

        var cardsHtml = displayAgents.map(function (agent) {
            var status = getAgentStatus(agent);
            var statusClass = status === 'paused' ? 'paused' :
                status === 'archived' ? 'archived' :
                    status === 'deleted' ? 'archived' : '';
            var statusIndicator = '<span class="status-indicator ' + status + '"></span>';

            var metrics = agent.metrics || {};
            var eValue = metrics.E !== undefined && metrics.E !== null ? Number(metrics.E) : null;
            var iValue = metrics.I !== undefined && metrics.I !== null ? Number(metrics.I) : null;
            var sValue = metrics.S !== undefined && metrics.S !== null ? Number(metrics.S) : null;
            var vValue = metrics.V !== undefined && metrics.V !== null ? Number(metrics.V) : null;
            var cValue = metrics.coherence !== undefined && metrics.coherence !== null ? Number(metrics.coherence) : null;

            var e = eValue !== null && !Number.isNaN(eValue) ? eValue.toFixed(3) : '-';
            var i = iValue !== null && !Number.isNaN(iValue) ? iValue.toFixed(3) : '-';
            var s = sValue !== null && !Number.isNaN(sValue) ? sValue.toFixed(3) : '-';
            var v = vValue !== null && !Number.isNaN(vValue) ? vValue.toFixed(3) : '-';
            var coherence = cValue !== null && !Number.isNaN(cValue) ? cValue.toFixed(3) : '-';

            var clampPercent = function (value) {
                if (value === null || Number.isNaN(value)) return 0;
                return Math.max(0, Math.min(100, value * 100));
            };
            var ePct = clampPercent(eValue);
            var iPct = clampPercent(iValue);
            var sPct = clampPercent(sValue);
            var vPct = vValue !== null && !Number.isNaN(vValue)
                ? Math.max(0, Math.min(100, (Math.abs(vValue) / 0.3) * 100))
                : 0;
            var cPct = clampPercent(cValue);

            var displayName = getAgentDisplayName(agent);
            var agentId = agent.agent_id || '';
            var timestampLabel = formatAgentTimestamp(agent);
            var nameHtml = highlightMatch(displayName, searchTerm);

            var subtitleParts = [];
            if (timestampLabel) subtitleParts.push(escapeHtml(timestampLabel));
            var totalUpdates = agent.total_updates || 0;
            if (totalUpdates > 0) subtitleParts.push(totalUpdates + ' update' + (totalUpdates !== 1 ? 's' : ''));
            var subtitleHtml = subtitleParts.length
                ? '<div class="agent-subtitle">' + subtitleParts.join(' &bull; ') + '</div>' : '';

            var purpose = agent.purpose ? escapeHtml(agent.purpose) : '';
            var purposeHtml = purpose
                ? '<div class="agent-purpose" title="' + purpose + '">' + purpose + '</div>' : '';

            // Stuck badge
            var stuckBadgeHtml = '';
            if (agent._stuck && agent._stuckInfo) {
                var stuckReason = agent._stuckInfo.reason || 'timeout';
                var stuckReasonLabels = {
                    'critical_margin_timeout': 'Critical',
                    'tight_margin_timeout': 'Tight Margin',
                    'activity_timeout': 'Inactive'
                };
                var stuckLabel = stuckReasonLabels[stuckReason] || 'Stuck';
                stuckBadgeHtml = '<span class="stuck-badge" title="Stuck: ' + escapeHtml(agent._stuckInfo.details || stuckReason) + '">' + escapeHtml(stuckLabel) + '</span>';
            }

            // Trust tier badge
            var tierRaw = agent.trust_tier;
            var tierNameToNum = { unknown: 0, emerging: 1, established: 2, verified: 3 };
            var tierNames = { 0: 'unknown', 1: 'emerging', 2: 'established', 3: 'verified' };
            var tierNum = tierRaw !== undefined && tierRaw !== null
                ? (typeof tierRaw === 'number' ? tierRaw : (tierNameToNum[String(tierRaw).toLowerCase()] || 0))
                : 0;
            var tierDisplayNames = { 0: 'T0', 1: 'T1', 2: 'T2', 3: 'T3' };
            var trustTierHtml = '<span class="trust-tier tier-' + tierNum + '" title="Trust Tier ' + tierNum + ': ' + (tierNames[tierNum] || 'unknown') + '">' + tierDisplayNames[tierNum] + '</span>';

            var hasMetrics = agentHasMetrics(agent);
            var isPinned = state.get('pinnedAgentId') === agentId;
            var pinLabel = isPinned ? 'Pinned' : 'Pin';
            var pinClass = isPinned ? 'agent-action pinned' : 'agent-action';
            var actionsHtml = agentId
                ? '<div class="agent-actions">' +
                    '<button class="' + pinClass + '" type="button" data-action="pin" data-agent-id="' + escapeHtml(agentId) + '" data-agent-name="' + escapeHtml(displayName) + '">' + pinLabel + '</button>' +
                    '<button class="agent-action" type="button" data-action="copy-id" data-agent-id="' + escapeHtml(agentId) + '">Copy ID</button>' +
                  '</div>'
                : '';

            // Metric bar colors
            var eColor = MetricColors.forValue(eValue, false, 'css');
            var iColor = MetricColors.forValue(iValue, false, 'css');
            var sColor = MetricColors.forValue(sValue, true, 'css');
            var vColor = MetricColors.forValue(vValue, true, 'css');
            var cColor = MetricColors.forValue(cValue, false, 'css');

            // Health status badge
            var healthStatus = agent.health_status || '';
            var healthBadgeHtml = '';
            if (healthStatus && healthStatus !== 'unknown') {
                healthBadgeHtml = '<span class="health-badge-mini ' + healthStatus + '">' + escapeHtml(healthStatus) + '</span>';
            }

            // Verdict badge with icon
            var verdict = metrics.verdict || '';
            var verdictBadgeHtml = '';
            if (verdict && verdict !== '-') {
                var verdictClass = verdict === 'proceed' || verdict === 'approve' || verdict === 'safe' ? 'verdict-good' :
                    verdict === 'caution' || verdict === 'guide' ? 'verdict-caution' : 'verdict-bad';
                var verdictIcon = VERDICT_ICONS[verdict] || '';
                verdictBadgeHtml = '<span class="verdict-badge-mini ' + verdictClass + '">' + (verdictIcon ? verdictIcon + ' ' : '') + escapeHtml(verdict) + '</span>';
            }

            // Staleness & inactive badges
            var staleBadgeHtml = getStaleBadgeHtml(agent);
            var inactiveBadgeHtml = getInactiveBadgeHtml(agent);

            // Anomaly indicator
            var anomalyHtml = typeof getAnomalyIndicator === 'function' ? getAnomalyIndicator(metrics) : '';

            // Sparkline
            var history = agentEISVHistory[agentId] || [];
            var sparklineData = history.length >= 2 ? history.slice(-20).map(function (p) { return p.coherence; }) : null;
            var sparklineVal = sparklineData ? sparklineData[sparklineData.length - 1] : null;
            var sparklineHtml = sparklineData && typeof createSparklineSVG === 'function'
                ? '<div class="sparkline-container" title="Coherence trend (last ' + sparklineData.length + ' points)"><span class="sparkline-label">C ' + sparklineVal.toFixed(2) + '</span>' + createSparklineSVG(sparklineData, { color: '#06b6d4' }) + '</div>'
                : '';

            // Compact summary: verdict + coherence + risk (shown inline below title)
            var compactSummaryHtml = '';
            if (hasMetrics) {
                var riskScore = metrics.risk_score !== undefined && metrics.risk_score !== null
                    ? (Number(metrics.risk_score) * 100).toFixed(0) + '%' : '';
                compactSummaryHtml = '<div class="agent-compact-summary">' +
                    verdictBadgeHtml +
                    (coherence !== '-' ? '<span class="compact-coherence">C ' + coherence + '</span>' : '') +
                    (riskScore ? '<span class="compact-risk">R ' + riskScore + '</span>' : '') +
                '</div>';
            }

            // Metrics toggle
            var metricsToggleHtml = hasMetrics
                ? '<span class="agent-metrics-toggle" data-agent-uuid="' + escapeHtml(agentId) + '"><span class="toggle-arrow">\u25B8</span> Metrics</span>'
                : '';

            return '<div class="agent-item ' + statusClass + '" data-agent-uuid="' + escapeHtml(agentId) + '" title="Click to view details">' +
                '<div class="agent-meta">' +
                    '<div class="agent-title">' +
                        statusIndicator +
                        '<span class="agent-name">' + nameHtml + '</span>' +
                        stuckBadgeHtml + inactiveBadgeHtml +
                        healthBadgeHtml + staleBadgeHtml +
                        trustTierHtml + anomalyHtml +
                        sparklineHtml +
                        actionsHtml +
                    '</div>' +
                    subtitleHtml +
                    purposeHtml +
                    compactSummaryHtml +
                    metricsToggleHtml +
                '</div>' +
                (hasMetrics
                    ? '<div class="agent-metrics">' +
                        '<div class="metric e" title="Energy or presence">' +
                            '<div class="label">E</div>' +
                            '<div class="val">' + e + '</div>' +
                            '<div class="metric-bar"><div class="metric-bar-fill" style="width: ' + ePct + '%;' + (eColor ? ' background: ' + eColor : '') + '"></div></div>' +
                        '</div>' +
                        '<div class="metric i" title="Information Integrity">' +
                            '<div class="label">I</div>' +
                            '<div class="val">' + i + '</div>' +
                            '<div class="metric-bar"><div class="metric-bar-fill" style="width: ' + iPct + '%;' + (iColor ? ' background: ' + iColor : '') + '"></div></div>' +
                        '</div>' +
                        '<div class="metric s" title="Entropy (disorder/uncertainty)">' +
                            '<div class="label">S</div>' +
                            '<div class="val">' + s + '</div>' +
                            '<div class="metric-bar"><div class="metric-bar-fill" style="width: ' + sPct + '%;' + (sColor ? ' background: ' + sColor : '') + '"></div></div>' +
                        '</div>' +
                        '<div class="metric v" title="Void Integral (E-I imbalance)">' +
                            '<div class="label">V</div>' +
                            '<div class="val">' + v + '</div>' +
                            '<div class="metric-bar"><div class="metric-bar-fill" style="width: ' + vPct + '%;' + (vColor ? ' background: ' + vColor : '') + '"></div></div>' +
                        '</div>' +
                        '<div class="metric c" title="Coherence">' +
                            '<div class="label">C</div>' +
                            '<div class="val">' + coherence + '</div>' +
                            '<div class="metric-bar"><div class="metric-bar-fill" style="width: ' + cPct + '%;' + (cColor ? ' background: ' + cColor : '') + '"></div></div>' +
                        '</div>' +
                    '</div>'
                    : '<div class="agent-metrics"><span class="text-secondary-sm">No metrics yet</span></div>') +
                // Behavioral EISV overlay (shown when available from in-memory monitors)
                (function () {
                    var beh = agent.behavioral;
                    if (!beh) return '';
                    var bE = Number(beh.E).toFixed(3), bI = Number(beh.I).toFixed(3);
                    var bS = Number(beh.S).toFixed(3), bV = Number(beh.V).toFixed(3);
                    var bePct = clampPercent(beh.E), biPct = clampPercent(beh.I);
                    var bsPct = clampPercent(beh.S);
                    var bvPct = beh.V !== null ? Math.max(0, Math.min(100, (Math.abs(beh.V) / 0.3) * 100)) : 0;
                    var behVerdict = (agent.eisv || {}).behavioral_verdict || '';
                    var behVerdictHtml = behVerdict
                        ? '<span class="verdict-badge-mini ' + (behVerdict === 'proceed' ? 'verdict-good' : behVerdict === 'guide' ? 'verdict-caution' : 'verdict-bad') + '">' + escapeHtml(behVerdict) + '</span>'
                        : '';
                    return '<div class="agent-metrics behavioral-metrics" title="Behavioral EISV (per-agent signal)">' +
                        '<div class="behavioral-label">Behavioral' + (behVerdictHtml ? ' ' + behVerdictHtml : '') + '</div>' +
                        '<div class="metric e"><div class="label">E</div><div class="val">' + bE + '</div><div class="metric-bar behavioral"><div class="metric-bar-fill" style="width: ' + bePct + '%"></div></div></div>' +
                        '<div class="metric i"><div class="label">I</div><div class="val">' + bI + '</div><div class="metric-bar behavioral"><div class="metric-bar-fill" style="width: ' + biPct + '%"></div></div></div>' +
                        '<div class="metric s"><div class="label">S</div><div class="val">' + bS + '</div><div class="metric-bar behavioral"><div class="metric-bar-fill" style="width: ' + bsPct + '%"></div></div></div>' +
                        '<div class="metric v"><div class="label">V</div><div class="val">' + bV + '</div><div class="metric-bar behavioral"><div class="metric-bar-fill" style="width: ' + bvPct + '%"></div></div></div>' +
                    '</div>';
                })() +
            '</div>';
        }).join('');

        // Pagination footer
        var paginationHtml = '';
        if (agents.length > state.get('agentPageSize')) {
            paginationHtml = '<div class="agents-pagination">' +
                '<span class="pagination-info">Showing ' + displayAgents.length + ' of ' + agents.length + ' agents</span>' +
                '<button class="show-more-btn" type="button">Show more</button>' +
            '</div>';
        } else if (agents.length > 0) {
            paginationHtml = '<div class="agents-pagination">' +
                '<span class="pagination-info">Showing ' + agents.length + ' of ' + agents.length + ' agents</span>' +
            '</div>';
        }

        container.innerHTML = cardsHtml + paginationHtml;
    }

    // ========================================================================
    // Agent filtering
    // ========================================================================

    function applyAgentFilters() {
        var searchInput = document.getElementById('agent-search');
        var statusFilterInput = document.getElementById('agent-status-filter');
        var metricsOnlyInput = document.getElementById('agent-metrics-only');
        var sortInput = document.getElementById('agent-sort');

        var searchTerm = searchInput ? searchInput.value.trim().toLowerCase() : '';
        var statusFilter = statusFilterInput ? statusFilterInput.value : 'all';
        var metricsOnly = metricsOnlyInput ? metricsOnlyInput.checked : false;
        var sortBy = sortInput ? sortInput.value : 'recent';

        var cachedAgents = state.get('cachedAgents');
        var filteredAgents = cachedAgents.filter(function (agent) {
            // Production filter
            if (state.get('prodOnlyActive') && isTestAgent(agent)) return false;

            var agentStatus = getAgentStatus(agent);
            if (statusFilter !== 'all' && agentStatus !== statusFilter) return false;
            if (metricsOnly && !agentHasMetrics(agent)) return false;

            if (searchTerm) {
                var displayName = getAgentDisplayName(agent);
                var agentId = agent.agent_id || '';
                var purpose = agent.purpose || '';
                var tagStr = (agent.tags || []).join(' ');
                var haystack = (displayName + ' ' + agentId + ' ' + purpose + ' ' + tagStr).toLowerCase();
                if (haystack.indexOf(searchTerm) === -1) return false;
            }
            return true;
        });

        // Sort
        filteredAgents = filteredAgents.slice().sort(function (a, b) {
            switch (sortBy) {
                case 'name':
                    return getAgentDisplayName(a).localeCompare(getAgentDisplayName(b));
                case 'coherence': {
                    var aC = (a.metrics || {}).coherence;
                    var bC = (b.metrics || {}).coherence;
                    return (bC != null ? bC : -1) - (aC != null ? aC : -1);
                }
                case 'risk': {
                    var aR = (a.metrics || {}).risk_score;
                    var bR = (b.metrics || {}).risk_score;
                    return (bR != null ? bR : -1) - (aR != null ? aR : -1);
                }
                case 'updates':
                    return (b.total_updates || 0) - (a.total_updates || 0);
                case 'recent':
                default: {
                    var aTime = new Date(a.last_update || a.created_at || 0);
                    var bTime = new Date(b.last_update || b.created_at || 0);
                    return bTime - aTime;
                }
            }
        });

        renderAgentsList(filteredAgents, searchTerm);
    }

    function clearAgentFilters() {
        var searchInput = document.getElementById('agent-search');
        var statusFilterInput = document.getElementById('agent-status-filter');
        var metricsOnlyInput = document.getElementById('agent-metrics-only');
        var sortInput = document.getElementById('agent-sort');
        if (searchInput) searchInput.value = '';
        if (statusFilterInput) statusFilterInput.value = 'all';
        if (metricsOnlyInput) metricsOnlyInput.checked = false;
        if (sortInput) sortInput.value = 'recent';
        applyAgentFilters();
    }

    // ========================================================================
    // Agent detail modal
    // ========================================================================

    function showAgentDetail(agent) {
        var modal = document.getElementById('panel-modal');
        var modalTitle = document.getElementById('modal-title');
        var modalBody = document.getElementById('modal-body');
        if (!modal || !modalTitle || !modalBody) return;

        var displayName = getAgentDisplayName(agent);
        var status = getAgentStatus(agent);
        var agentId = agent.agent_id || 'Unknown';
        var metrics = agent.metrics || {};

        var tierNameToNum = { unknown: 0, emerging: 1, established: 2, verified: 3 };
        var tierRaw = agent.trust_tier;
        var trustTier = tierRaw !== undefined && tierRaw !== null
            ? (typeof tierRaw === 'number' ? tierRaw : (tierNameToNum[String(tierRaw).toLowerCase()] || 0))
            : 0;
        var tierNames = { 0: 'Unknown', 1: 'Emerging', 2: 'Established', 3: 'Verified' };
        var tierDescriptions = {
            0: 'New agent, no trajectory history. +5% risk adjustment.',
            1: 'Some history, building consistency. +5% risk adjustment.',
            2: 'Consistent behavioral trajectory. No risk adjustment.',
            3: 'Strong trajectory match + operator endorsement. -5% risk reduction.'
        };

        // EISV with interpretations using DataProcessor
        var eisvMetrics = ['E', 'I', 'S', 'V', 'C'];
        var metricValues = { E: metrics.E, I: metrics.I, S: metrics.S, V: metrics.V, C: metrics.coherence };
        var eisvHtml = eisvMetrics.map(function (name) {
            var val = metricValues[name];
            if (val === undefined || val === null) return '';
            var formatted = typeof DataProcessor !== 'undefined'
                ? DataProcessor.formatEISVMetric(Number(val), name)
                : { display: Number(val).toFixed(3), interpretation: '', color: 'var(--text-primary)' };
            return '<div class="eisv-metric-row">' +
                '<div>' +
                    '<strong style="color: ' + formatted.color + ';" class="text-mono">' + name + '</strong>' +
                    '<span class="text-secondary-xs" style="margin-left: 8px;">' + escapeHtml(formatted.interpretation) + '</span>' +
                '</div>' +
                '<span class="text-mono-bold" style="color: ' + formatted.color + ';">' + formatted.display + '</span>' +
            '</div>';
        }).filter(Boolean).join('');

        // Governance section
        var healthStatus = agent.health_status || 'unknown';
        var verdict = metrics.verdict || '-';
        var riskScore = metrics.risk_score !== undefined && metrics.risk_score !== null
            ? (Number(metrics.risk_score) * 100).toFixed(1) + '%' : '-';
        var phi = metrics.phi !== undefined && metrics.phi !== null
            ? Number(metrics.phi).toFixed(4) : '-';
        var meanRisk = metrics.mean_risk !== undefined && metrics.mean_risk !== null
            ? (Number(metrics.mean_risk) * 100).toFixed(1) + '%' : '-';

        // Tags
        var tags = agent.tags && agent.tags.length > 0
            ? agent.tags.map(function (t) {
                return '<span class="clickable-tag tag-chip" data-tag="' + escapeHtml(t) + '">' + escapeHtml(t) + '</span>';
            }).join(' ')
            : '<span class="text-secondary-sm">None</span>';
        var notes = agent.notes ? escapeHtml(agent.notes) : '';
        var purpose = agent.purpose ? escapeHtml(agent.purpose) : '';

        // filterInternalKeys defined in dashboard.js, available at call time
        var filterFn = typeof filterInternalKeys === 'function' ? filterInternalKeys : function (o) { return o; };

        var html = '<div class="agent-detail">' +
            '<div class="flex-row-wrap mb-md">' +
                '<span class="status-indicator ' + status + '"></span>' +
                '<span class="detail-box-value">' + escapeHtml(displayName) + '</span>' +
                '<span class="status-chip ' + status + '">' + escapeHtml(formatStatusLabel(status)) + '</span>' +
                (trustTier !== null ? '<span class="trust-tier tier-' + trustTier + '">Tier ' + trustTier + ': ' + (tierNames[trustTier] || 'Unknown') + '</span>' : '') +
            '</div>' +

            (purpose ? '<div class="text-secondary-sm mb-md agent-purpose">' + purpose + '</div>' : '') +

            '<div class="grid-2col mb-md">' +
                '<div>' +
                    '<strong class="text-secondary-sm">Agent ID:</strong><br>' +
                    '<code class="code-tertiary">' + escapeHtml(agentId) + '</code>' +
                '</div>' +
                '<div>' +
                    '<strong class="text-secondary-sm">Total Updates:</strong><br>' +
                    (agent.total_updates || 0) +
                '</div>' +
            '</div>' +

            '<div class="grid-2col mb-md">' +
                '<div>' +
                    '<strong class="text-secondary-sm">Created:</strong><br>' +
                    escapeHtml(agent.created_at || agent.created || '-') +
                '</div>' +
                '<div>' +
                    '<strong class="text-secondary-sm">Last Update:</strong><br>' +
                    escapeHtml(agent.last_update || '-') +
                '</div>' +
            '</div>' +

            (trustTier !== null
                ? '<div class="info-callout">' +
                    '<strong class="text-accent">Trust Tier ' + trustTier + ': ' + (tierNames[trustTier] || 'Unknown') + '</strong><br>' +
                    '<span class="text-secondary-sm">' + (tierDescriptions[trustTier] || '') + '</span>' +
                  '</div>'
                : '') +

            (eisvHtml
                ? '<div class="detail-section">' +
                    '<strong class="detail-section-title">EISV Metrics (ODE):</strong>' +
                    '<div class="mt-sm">' + eisvHtml + '</div>' +
                  '</div>' +
                  (typeof EISVRadarChart !== 'undefined'
                    ? '<div class="detail-section">' +
                        '<strong class="detail-section-title">EISV Profile:</strong>' +
                        '<div class="radar-chart-container mt-sm">' +
                            '<canvas id="agent-detail-radar"></canvas>' +
                        '</div>' +
                      '</div>'
                    : '')
                : '') +

            // Behavioral EISV section (per-agent signal, not ODE thermostat)
            (function () {
                var beh = agent.behavioral;
                if (!beh) return '';
                var behVerdict = (agent.eisv || {}).behavioral_verdict || '';
                var behMetrics = ['E', 'I', 'S', 'V'];
                var behHtml = behMetrics.map(function (name) {
                    var val = beh[name];
                    if (val === undefined || val === null) return '';
                    var formatted = typeof DataProcessor !== 'undefined'
                        ? DataProcessor.formatEISVMetric(Number(val), name)
                        : { display: Number(val).toFixed(3), interpretation: '', color: 'var(--text-primary)' };
                    return '<div class="eisv-metric-row">' +
                        '<div>' +
                            '<strong style="color: ' + formatted.color + ';" class="text-mono">' + name + '</strong>' +
                            '<span class="text-secondary-xs" style="margin-left: 8px;">' + escapeHtml(formatted.interpretation) + '</span>' +
                        '</div>' +
                        '<span class="text-mono-bold" style="color: ' + formatted.color + ';">' + formatted.display + '</span>' +
                    '</div>';
                }).filter(Boolean).join('');
                return '<div class="detail-section">' +
                    '<strong class="detail-section-title">Behavioral EISV' +
                        (behVerdict ? ' <span class="verdict-badge-mini ' + (behVerdict === 'proceed' ? 'verdict-good' : behVerdict === 'guide' ? 'verdict-caution' : 'verdict-bad') + '">' + escapeHtml(behVerdict) + '</span>' : '') +
                    ':</strong>' +
                    '<div class="mt-sm">' + behHtml + '</div>' +
                '</div>';
            })() +

            '<div class="detail-section">' +
                '<strong class="detail-section-title">Governance:</strong>' +
                '<div class="grid-auto-fit mt-sm">' +
                    '<div class="detail-box">' +
                        '<div class="detail-box-label">Health</div>' +
                        '<div class="health-badge ' + healthStatus + ' detail-box-value">' + escapeHtml(healthStatus) + '</div>' +
                    '</div>' +
                    '<div class="detail-box">' +
                        '<div class="detail-box-label">Verdict</div>' +
                        '<div class="detail-box-value"><span class="verdict-badge-mini ' +
                            (verdict === 'proceed' || verdict === 'approve' || verdict === 'safe' ? 'verdict-good' :
                             verdict === 'caution' || verdict === 'guide' ? 'verdict-caution' : 'verdict-bad') +
                        '">' + (VERDICT_ICONS[verdict] ? VERDICT_ICONS[verdict] + ' ' : '') + escapeHtml(verdict) + '</span></div>' +
                    '</div>' +
                    '<div class="detail-box">' +
                        '<div class="detail-box-label">Risk</div>' +
                        '<div class="detail-box-value">' + riskScore + '</div>' +
                    '</div>' +
                    '<div class="detail-box">' +
                        '<div class="detail-box-label">Phi</div>' +
                        '<div class="detail-box-value text-mono">' + phi + '</div>' +
                    '</div>' +
                    '<div class="detail-box">' +
                        '<div class="detail-box-label">Mean Risk</div>' +
                        '<div class="detail-box-value">' + meanRisk + '</div>' +
                    '</div>' +
                '</div>' +
            '</div>' +

            '<div class="detail-section">' +
                '<strong class="text-secondary-sm">Tags:</strong>' +
                '<div class="mt-sm">' + tags + '</div>' +
            '</div>' +

            // Recent Discoveries cross-link
            (function () {
                var cachedDisc = state.get('cachedDiscoveries') || [];
                var agentDisc = cachedDisc.filter(function (d) {
                    return (d.agent_id || d._agent_id || d.by || '') === agentId;
                }).slice(0, 5);
                if (agentDisc.length === 0) return '';
                var discItems = agentDisc.map(function (d) {
                    var dType = d.type || d.discovery_type || 'note';
                    var dSummary = d.summary || 'Untitled';
                    var dDate = d._displayDate || '';
                    return '<div class="discovery-mini-item" style="padding: 6px 0; border-bottom: 1px solid var(--border-color);">' +
                        '<span class="discovery-type ' + escapeHtml(dType) + '" style="font-size: 0.7em;">' + escapeHtml(dType) + '</span> ' +
                        '<span style="font-size: 0.85em;">' + escapeHtml(dSummary.length > 60 ? dSummary.substring(0, 57) + '...' : dSummary) + '</span>' +
                        (dDate ? ' <span class="text-secondary-xs">' + escapeHtml(dDate) + '</span>' : '') +
                    '</div>';
                }).join('');
                return '<div class="detail-section">' +
                    '<strong class="detail-section-title">Recent Discoveries:</strong>' +
                    '<div class="mt-sm">' + discItems + '</div>' +
                '</div>';
            })() +

            (notes
                ? '<div class="detail-section">' +
                    '<strong class="text-secondary-sm">Notes:</strong>' +
                    '<div class="content-box mt-sm">' + notes + '</div>' +
                  '</div>'
                : '') +

            '<div class="agent-detail-actions mt-md">' +
                '<button class="agent-detail-pin-btn panel-button" data-action="pin" data-agent-id="' + escapeHtml(agentId) + '" data-agent-name="' + escapeHtml(displayName) + '">' +
                    (state.get('pinnedAgentId') === agentId ? 'Unpin from Pulse' : 'Pin to Pulse') +
                '</button>' +
                (status === 'paused'
                    ? '<button class="agent-detail-resume-btn panel-button" data-agent-id="' + escapeHtml(agentId) + '">Resume Agent</button>'
                    : '') +
                (status !== 'archived' && status !== 'deleted'
                    ? '<button class="agent-detail-archive-btn panel-button danger" data-agent-id="' + escapeHtml(agentId) + '">Archive Agent</button>'
                    : '') +
            '</div>' +

            '<details class="mt-md">' +
                '<summary class="cursor-pointer text-secondary-sm">Raw data</summary>' +
                '<pre class="raw-data-pre">' + escapeHtml(JSON.stringify(filterFn(agent), null, 2)) + '</pre>' +
            '</details>' +
        '</div>';

        modalTitle.textContent = 'Agent: ' + displayName;
        modalBody.innerHTML = html;
        modal.classList.add('visible');
        document.body.style.overflow = 'hidden';

        // Initialize radar chart if metrics and visualizations available
        var hasMetrics = agentHasMetrics(agent);
        if (hasMetrics && typeof EISVRadarChart !== 'undefined') {
            requestAnimationFrame(function () {
                var radar = new EISVRadarChart('agent-detail-radar');
                var fleetAvg = typeof computeFleetAverageMetrics === 'function'
                    ? computeFleetAverageMetrics(state.get('cachedAgents'))
                    : null;
                radar.render(metrics, fleetAvg, displayName);
            });
        }
    }

    // ========================================================================
    // Export
    // ========================================================================

    function exportAgents(format) {
        var cachedAgents = state.get('cachedAgents');
        if (cachedAgents.length === 0) {
            if (typeof showError === 'function') showError('No agents to export');
            return;
        }

        var exportData = cachedAgents.map(function (agent) {
            var m = agent.metrics || {};
            return {
                agent_id: agent.agent_id || '',
                name: getAgentDisplayName(agent),
                status: getAgentStatus(agent),
                E: m.E || null,
                I: m.I || null,
                S: m.S || null,
                V: m.V || null,
                coherence: m.coherence || null,
                last_update: agent.last_update || '',
                created_at: agent.created_at || ''
            };
        });

        var filename = 'agents_' + new Date().toISOString().split('T')[0];

        if (format === 'csv') {
            if (typeof DataProcessor !== 'undefined' && DataProcessor.exportToCSV) {
                DataProcessor.exportToCSV(exportData, filename + '.csv');
            } else {
                var headers = Object.keys(exportData[0]);
                var csvLines = [headers.join(',')];
                exportData.forEach(function (row) {
                    csvLines.push(headers.map(function (h) {
                        var val = row[h];
                        return val === null || val === undefined ? '' : String(val).replace(/"/g, '""');
                    }).join(','));
                });
                var blob = new Blob([csvLines.join('\n')], { type: 'text/csv' });
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                a.download = filename + '.csv';
                a.click();
                URL.revokeObjectURL(url);
            }
        } else {
            if (typeof DataProcessor !== 'undefined' && DataProcessor.exportToJSON) {
                DataProcessor.exportToJSON(exportData, filename + '.json');
            } else {
                var json = JSON.stringify(exportData, null, 2);
                var blob2 = new Blob([json], { type: 'application/json' });
                var url2 = URL.createObjectURL(blob2);
                var a2 = document.createElement('a');
                a2.href = url2;
                a2.download = filename + '.json';
                a2.click();
                URL.revokeObjectURL(url2);
            }
        }
    }

    // ========================================================================
    // Event listeners: prod toggle, metrics toggle, show more
    // Deferred to DOMContentLoaded because agents.js loads in <head>
    // before the body elements exist.
    // ========================================================================

    function _bindAgentEvents() {
        // Production toggle button
        var prodToggleBtn = document.getElementById('prod-toggle');
        if (prodToggleBtn) {
            if (state.get('prodOnlyActive')) prodToggleBtn.classList.add('active');
            prodToggleBtn.addEventListener('click', function () {
                var newVal = !state.get('prodOnlyActive');
                state.set({ prodOnlyActive: newVal, agentPageSize: 20 });
                localStorage.setItem('unitares_prod_only', newVal ? 'true' : 'false');
                prodToggleBtn.classList.toggle('active', newVal);
                applyAgentFilters();
            });
        }

        // Delegated: metrics toggle + show more button
        var agentsContainer = document.getElementById('agents-container');
        if (agentsContainer) {
            agentsContainer.addEventListener('click', function (e) {
                // Metrics toggle
                var toggle = e.target.closest('.agent-metrics-toggle');
                if (toggle) {
                    e.stopPropagation();
                    var card = toggle.closest('.agent-item');
                    if (card) card.classList.toggle('metrics-expanded');
                    return;
                }

                // Show more pagination
                var showMore = e.target.closest('.show-more-btn');
                if (showMore) {
                    e.stopPropagation();
                    state.set({ agentPageSize: state.get('agentPageSize') + 20 });
                    applyAgentFilters();
                    return;
                }
            });
        }

        // Reset page size on filter/search/sort changes (NOT in applyAgentFilters since that's called on 30s refresh)
        var resetPageInputs = ['agent-search', 'agent-status-filter', 'agent-metrics-only', 'agent-sort'];
        resetPageInputs.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) {
                el.addEventListener(el.tagName === 'INPUT' && el.type === 'text' ? 'input' : 'change', function () {
                    state.set({ agentPageSize: 20 });
                });
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _bindAgentEvents);
    } else {
        _bindAgentEvents();
    }

    // ========================================================================
    // Public API
    // ========================================================================

    window.AgentsModule = {
        getAgentStatus: getAgentStatus,
        getAgentDisplayName: getAgentDisplayName,
        agentHasMetrics: agentHasMetrics,
        formatStatusLabel: formatStatusLabel,
        formatAgentTimestamp: formatAgentTimestamp,
        updateStatusLegend: updateStatusLegend,
        updateAgentFilterInfo: updateAgentFilterInfo,
        renderAgentsList: renderAgentsList,
        applyAgentFilters: applyAgentFilters,
        clearAgentFilters: clearAgentFilters,
        showAgentDetail: showAgentDetail,
        exportAgents: exportAgents,
        isTestAgent: isTestAgent,
        getProductionAgents: getProductionAgents,
        isProdOnlyActive: function () { return state.get('prodOnlyActive'); }
    };
})();
