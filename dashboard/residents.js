/**
 * UNITARES Dashboard — Resident Fleet Panel
 *
 * Renders a card per "always-on" agent (residents) at the top of the dashboard.
 * Residents are operator-configurable via UNITARES_RESIDENT_AGENTS (env) or
 * agent_metadata.resident=True; this module is user-agnostic and renders
 * whatever /v1/residents returns.
 *
 * Each card shows:
 *   - Status dot (healthy / silent / paused / unknown) — pulses when live
 *   - Verdict pill
 *   - Coherence sparkline (SVG, last hour) with risk shading
 *   - Current EISV vector
 *   - Silence indicator (elapsed since last check-in)
 *   - Last 3 KG writes the agent authored
 *
 * Live update: subscribes to broadcaster events. eisv_update events for the
 * agent push a new sparkline point; knowledge_write events refresh the
 * recent-writes strip; lifecycle_paused/resumed flip the status.
 */

(function () {
    'use strict';

    var REFRESH_INTERVAL_MS = 60 * 1000; // periodic re-fetch fallback (covers broadcaster restarts)
    var SPARKLINE_WIDTH = 220;
    var SPARKLINE_HEIGHT = 44;
    var SPARKLINE_PADDING = 4;
    var MAX_HISTORY_POINTS = 60;

    // residents indexed by agent_id (filled by /v1/residents response).
    // Agents without an agent_id (haven't checked in yet) are keyed by label.
    var residentsByAgentId = {};
    var residentsByLabel = {};
    var orderedLabels = [];
    var sourceLabel = '';

    // ---------------------------------------------------------------------
    // Pure helpers
    // ---------------------------------------------------------------------

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function fmtSilence(seconds) {
        if (seconds == null) return '—';
        if (seconds < 60) return Math.round(seconds) + 's';
        if (seconds < 3600) return Math.round(seconds / 60) + 'm';
        if (seconds < 86400) return (seconds / 3600).toFixed(1) + 'h';
        return Math.round(seconds / 86400) + 'd';
    }

    function statusForCard(resident, nowMs) {
        // Recompute status client-side so the "silent" flip happens between
        // server fetches without waiting for a re-poll.
        if (resident.status === 'paused' || resident.status === 'archived') {
            return resident.status;
        }
        if (!resident.last_checkin_at) return 'unknown';
        try {
            var lastMs = new Date(resident.last_checkin_at).getTime();
            var elapsed = (nowMs - lastMs) / 1000;
            if (elapsed > resident.silence_threshold_seconds) return 'silent';
            return 'healthy';
        } catch (e) {
            return 'unknown';
        }
    }

    function verdictColour(v) {
        if (v === 'proceed' || v === 'approve') return 'verdict-good';
        if (v === 'guide' || v === 'caution') return 'verdict-caution';
        if (v === 'pause' || v === 'reject') return 'verdict-bad';
        return 'verdict-neutral';
    }

    // ---------------------------------------------------------------------
    // SVG sparkline
    // ---------------------------------------------------------------------

    function renderSparkline(history) {
        var w = SPARKLINE_WIDTH, h = SPARKLINE_HEIGHT, pad = SPARKLINE_PADDING;
        var innerW = w - pad * 2;
        var innerH = h - pad * 2;

        if (!history || history.length === 0) {
            return '<svg class="resident-sparkline" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">' +
                '<line x1="' + pad + '" y1="' + (h / 2) + '" x2="' + (w - pad) + '" y2="' + (h / 2) + '" class="spark-axis-empty" stroke-dasharray="3 3"/>' +
                '<text x="' + (w / 2) + '" y="' + (h / 2 + 4) + '" class="spark-empty-label" text-anchor="middle">no data</text>' +
                '</svg>';
        }

        // Time-normalize over the visible window (last 60 min).
        var lastTs = history[history.length - 1].ts;
        var firstTs = history[0].ts;
        var tsRange = Math.max(1, lastTs - firstTs);

        // Coherence is in [0, 1]; stretch a tiny floor so very-flat lines aren't invisible.
        var minY = 0;
        var maxY = 1;

        function px(point) {
            var x = pad + ((point.ts - firstTs) / tsRange) * innerW;
            var y = pad + (1 - (point.coherence - minY) / (maxY - minY)) * innerH;
            return [x, y];
        }

        // Build the line path.
        var pathD = '';
        var areaD = '';
        for (var i = 0; i < history.length; i++) {
            var p = px(history[i]);
            if (i === 0) {
                pathD = 'M ' + p[0] + ' ' + p[1];
                areaD = 'M ' + p[0] + ' ' + (h - pad);
                areaD += ' L ' + p[0] + ' ' + p[1];
            } else {
                pathD += ' L ' + p[0] + ' ' + p[1];
                areaD += ' L ' + p[0] + ' ' + p[1];
            }
        }
        var lastP = px(history[history.length - 1]);
        areaD += ' L ' + lastP[0] + ' ' + (h - pad) + ' Z';

        // Risk-shaded background bands (light tint where risk > 0.5).
        var riskBands = '';
        var inHotBand = false;
        var hotStart = null;
        for (var j = 0; j < history.length; j++) {
            var hot = (history[j].risk != null && history[j].risk > 0.5);
            if (hot && !inHotBand) {
                hotStart = px(history[j])[0];
                inHotBand = true;
            } else if (!hot && inHotBand) {
                var hotEnd = px(history[j])[0];
                riskBands += '<rect x="' + hotStart + '" y="' + pad + '" width="' + (hotEnd - hotStart) + '" height="' + innerH + '" class="spark-risk-band"/>';
                inHotBand = false;
            }
        }
        if (inHotBand) {
            var endP = px(history[history.length - 1]);
            riskBands += '<rect x="' + hotStart + '" y="' + pad + '" width="' + (endP[0] - hotStart) + '" height="' + innerH + '" class="spark-risk-band"/>';
        }

        // Last-point dot, with verdict color.
        var lastVerdict = history[history.length - 1].verdict;
        var dotClass = verdictColour(lastVerdict);

        return '<svg class="resident-sparkline" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">' +
            riskBands +
            '<path d="' + areaD + '" class="spark-area"/>' +
            '<path d="' + pathD + '" class="spark-line"/>' +
            '<circle cx="' + lastP[0] + '" cy="' + lastP[1] + '" r="3" class="spark-dot ' + dotClass + '"/>' +
            '</svg>';
    }

    // ---------------------------------------------------------------------
    // Card rendering
    // ---------------------------------------------------------------------

    function renderCard(resident, nowMs) {
        var status = statusForCard(resident, nowMs);
        var verdictPill = resident.verdict
            ? '<span class="resident-verdict ' + verdictColour(resident.verdict) + '">' + escapeHtml(resident.verdict) + '</span>'
            : '<span class="resident-verdict verdict-neutral">no verdict</span>';

        // Compute live silence (since cards may render between server polls).
        var liveSilence = resident.silence_seconds;
        if (resident.last_checkin_at) {
            try {
                liveSilence = (nowMs - new Date(resident.last_checkin_at).getTime()) / 1000;
            } catch (e) { /* keep server value */ }
        }

        var eisvHtml = '';
        if (resident.eisv) {
            var fmt = function (v) { return v == null ? '—' : Number(v).toFixed(2); };
            eisvHtml =
                '<div class="resident-eisv">' +
                '<span title="Energy">E ' + fmt(resident.eisv.E) + '</span>' +
                '<span title="Information Integrity">I ' + fmt(resident.eisv.I) + '</span>' +
                '<span title="Entropy">S ' + fmt(resident.eisv.S) + '</span>' +
                '<span title="Void">V ' + fmt(resident.eisv.V) + '</span>' +
                '</div>';
        } else {
            eisvHtml = '<div class="resident-eisv resident-eisv-empty">no EISV yet</div>';
        }

        var coherenceVal = resident.coherence != null
            ? '<span class="resident-coherence">C ' + Number(resident.coherence).toFixed(3) + '</span>'
            : '';

        var writesHtml = '';
        var writes = (resident.recent_writes || []).slice(0, 3);
        if (writes.length === 0) {
            writesHtml = '<div class="resident-writes-empty">no recent writes</div>';
        } else {
            writesHtml = '<ul class="resident-writes">' + writes.map(function (w) {
                var summary = (w.summary || '').slice(0, 80);
                if ((w.summary || '').length > 80) summary += '…';
                var sevClass = w.severity === 'critical' ? 'sev-critical'
                    : w.severity === 'high' ? 'sev-high'
                    : w.severity === 'medium' ? 'sev-medium'
                    : 'sev-low';
                return '<li class="' + sevClass + '" title="' + escapeHtml(w.summary || '') + '">' +
                    '<span class="resident-write-type">' + escapeHtml(w.type || 'note') + '</span>' +
                    '<span class="resident-write-summary">' + escapeHtml(summary) + '</span>' +
                    '</li>';
            }).join('') + '</ul>';
        }

        return '<article class="resident-card status-' + status + '" data-agent="' + escapeHtml(resident.label) + '">' +
            '<header class="resident-header">' +
                '<span class="resident-dot status-' + status + '" title="' + status + '"></span>' +
                '<h3 class="resident-name">' + escapeHtml(resident.label) + '</h3>' +
                verdictPill +
            '</header>' +
            '<div class="resident-meta">' +
                '<span class="resident-silence" title="time since last check-in">' +
                    '<span class="resident-silence-label">silence</span> ' +
                    '<span class="resident-silence-value">' + escapeHtml(fmtSilence(liveSilence)) + '</span>' +
                '</span>' +
                coherenceVal +
                '<span class="resident-updates" title="total check-ins">' +
                    escapeHtml(String(resident.total_updates || 0)) + ' upd' +
                '</span>' +
            '</div>' +
            '<div class="resident-spark-row">' + renderSparkline(resident.history) + '</div>' +
            eisvHtml +
            writesHtml +
        '</article>';
    }

    function renderAll() {
        var grid = document.getElementById('residents-grid');
        if (!grid) return;
        var src = document.getElementById('residents-source-label');
        if (src) {
            src.textContent = sourceLabel
                ? 'source: ' + sourceLabel
                : '';
        }
        if (orderedLabels.length === 0) {
            grid.innerHTML = '<div class="residents-empty">' +
                'No residents configured. Set <code>UNITARES_RESIDENT_AGENTS</code> ' +
                'in your governance plist or mark agents with <code>resident=True</code> in metadata.' +
                '</div>';
            return;
        }
        var nowMs = Date.now();
        var cards = orderedLabels.map(function (label) {
            var r = residentsByLabel[label];
            return r ? renderCard(r, nowMs) : '';
        });
        grid.innerHTML = cards.join('');
    }

    // ---------------------------------------------------------------------
    // Data fetch
    // ---------------------------------------------------------------------

    function getAuthToken() {
        try {
            return localStorage.getItem('unitares_api_token') ||
                new URLSearchParams(window.location.search).get('token');
        } catch (e) {
            return null;
        }
    }

    async function fetchResidents() {
        try {
            // Attach the bearer token if present — bare fetch() returns 401
            // when the dashboard server is configured with UNITARES_HTTP_API_TOKEN.
            // Trusted-network bypass kicks in for curl from localhost but not
            // for browser fetches because the request reaches the server with
            // a hostname/origin that doesn't match the trusted set.
            var token = getAuthToken();
            var headers = {};
            if (token) headers['Authorization'] = 'Bearer ' + token;
            var resp = await fetch('/v1/residents', {
                credentials: 'same-origin',
                headers: headers,
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();
            if (!data || data.success === false) throw new Error(data && data.error || 'unknown');
            sourceLabel = data.source || '';
            orderedLabels = (data.configured || []).slice();
            residentsByAgentId = {};
            residentsByLabel = {};
            for (var i = 0; i < (data.residents || []).length; i++) {
                var r = data.residents[i];
                residentsByLabel[r.label] = r;
                if (r.agent_id) residentsByAgentId[r.agent_id] = r;
            }
            renderAll();
        } catch (e) {
            console.warn('[Residents] fetch failed:', e);
            var grid = document.getElementById('residents-grid');
            if (grid) grid.innerHTML = '<div class="residents-empty">Residents unavailable: ' + escapeHtml(String(e.message || e)) + '</div>';
        }
    }

    // ---------------------------------------------------------------------
    // Live WS update — feed eisv_update / knowledge_write to the right card
    // ---------------------------------------------------------------------

    // Broadcaster eisv_update payloads are nested: { eisv: {E,I,S,V}, coherence,
    // metrics: {risk_score, verdict}, decision: {action} }. Surface them flat.
    function flattenEisv(data) {
        var eisv = data.eisv || {};
        var metrics = data.metrics || {};
        var decision = data.decision || {};
        return {
            E: eisv.E,
            I: eisv.I,
            S: eisv.S,
            V: eisv.V,
            coherence: data.coherence != null ? data.coherence : metrics.coherence,
            risk: metrics.risk_score != null ? metrics.risk_score : data.risk,
            verdict: decision.action || metrics.verdict,
        };
    }

    function onEISVUpdate(data) {
        if (!data || data.type !== 'eisv_update') return;
        var aid = data.agent_id;
        if (!aid) return;
        var resident = residentsByAgentId[aid];
        if (!resident) {
            // Maybe a resident's first check-in since the last fetch — refetch.
            fetchResidents();
            return;
        }
        var f = flattenEisv(data);
        // Append to history (cap MAX_HISTORY_POINTS).
        var now = Date.now() / 1000;
        if (f.coherence != null) {
            resident.history = (resident.history || []).concat([{
                ts: now,
                coherence: Number(f.coherence),
                risk: f.risk != null ? Number(f.risk) : null,
                verdict: f.verdict,
            }]);
            if (resident.history.length > MAX_HISTORY_POINTS) {
                resident.history = resident.history.slice(-MAX_HISTORY_POINTS);
            }
        }
        if (f.coherence != null) resident.coherence = Number(f.coherence);
        if (f.risk != null) resident.risk_score = Number(f.risk);
        if (f.verdict) resident.verdict = f.verdict;
        if (f.E != null) resident.eisv = { E: f.E, I: f.I, S: f.S, V: f.V };
        resident.last_checkin_at = data.timestamp || new Date().toISOString();
        resident.total_updates = (resident.total_updates || 0) + 1;
        renderAll();
    }

    function onGovernanceEvent(data) {
        if (!data || !data.type) return;
        if (data.type === 'eisv_update') return; // handled separately
        var aid = data.agent_id;
        if (!aid) return;
        var resident = residentsByAgentId[aid];
        if (!resident) return;

        if (data.type === 'knowledge_write') {
            var write = {
                id: data.discovery_id,
                type: data.discovery_type || 'note',
                severity: data.severity || 'low',
                summary: data.summary || '',
                tags: data.tags || [],
                timestamp: data.timestamp,
            };
            resident.recent_writes = [write].concat(resident.recent_writes || []).slice(0, 5);
            renderAll();
        } else if (data.type === 'lifecycle_paused' || data.type === 'lifecycle_archived') {
            resident.status = data.type.replace('lifecycle_', '');
            renderAll();
        } else if (data.type === 'lifecycle_resumed') {
            resident.status = 'healthy';
            renderAll();
        }
    }

    // ---------------------------------------------------------------------
    // Tick: re-render once per second so silence indicators stay live.
    // ---------------------------------------------------------------------
    function startSilenceTicker() {
        setInterval(function () {
            // Cheap re-render of just the silence + status dot — full renderAll is fine.
            if (orderedLabels.length > 0) renderAll();
        }, 1000);
    }

    // ---------------------------------------------------------------------
    // Init
    // ---------------------------------------------------------------------

    function init() {
        fetchResidents();
        setInterval(fetchResidents, REFRESH_INTERVAL_MS);
        startSilenceTicker();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.ResidentsModule = {
        fetchResidents: fetchResidents,
        onEISVUpdate: onEISVUpdate,
        onGovernanceEvent: onGovernanceEvent,
    };
})();
