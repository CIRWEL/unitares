// sentinel.js — Sentinel findings stream panel.
//
// Consumes:
//   GET /v1/sentinel/summary — counts by severity + violation class, recent stream
//
// Unlike Watcher, Sentinel findings are transient fleet-state signals with no
// open/closed lifecycle. This panel is a chronological log with a class
// breakdown — not an actionable queue.
//
// Auth + fetch go through `authFetch` from utils.js.

(function () {
    'use strict';

    async function fetchSummary() {
        try {
            var resp = await authFetch('/v1/sentinel/summary');
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();
            if (!data || data.success === false) {
                throw new Error((data && data.error) || 'unknown');
            }
            return data;
        } catch (e) {
            console.warn('[Sentinel] summary fetch failed:', e);
            return null;
        }
    }

    function setMetric(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function renderCounts(summary) {
        var bySev = summary.by_severity || {};
        setMetric('sentinel-count-total', summary.total || 0);
        setMetric('sentinel-count-critical', bySev.critical || 0);
        setMetric('sentinel-count-high', bySev.high || 0);
        setMetric('sentinel-count-medium', bySev.medium || 0);
    }

    function renderClassBreakdown(summary) {
        var container = document.getElementById('sentinel-class-breakdown');
        if (!container) return;
        container.innerHTML = '';
        var classes = summary.by_violation_class || [];
        if (classes.length === 0) {
            var empty = document.createElement('span');
            empty.className = 'sentinel-class-empty';
            empty.textContent = 'no findings in window';
            container.appendChild(empty);
            return;
        }
        for (var i = 0; i < classes.length; i++) {
            var c = classes[i];
            var pill = document.createElement('span');
            pill.className = 'sentinel-class-pill';
            var name = document.createElement('span');
            name.className = 'sentinel-class-name';
            name.textContent = c.violation_class;
            var count = document.createElement('span');
            count.className = 'sentinel-class-count';
            count.textContent = String(c.count);
            // Tooltip shows severity breakdown so hovering tells the full story
            var sevParts = [];
            var sev = c.by_severity || {};
            for (var k in sev) {
                if (Object.prototype.hasOwnProperty.call(sev, k)) {
                    sevParts.push(k + ':' + sev[k]);
                }
            }
            pill.title = sevParts.join(' · ');
            pill.appendChild(name);
            pill.appendChild(count);
            container.appendChild(pill);
        }
    }

    function formatRelative(isoStr) {
        if (!isoStr) return '';
        var then = new Date(isoStr);
        if (isNaN(then.getTime())) return isoStr;
        var secs = Math.floor((Date.now() - then.getTime()) / 1000);
        if (secs < 60) return 'just now';
        if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
        if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
        return Math.floor(secs / 86400) + 'd ago';
    }

    function renderStream(summary) {
        var container = document.getElementById('sentinel-stream');
        if (!container) return;
        container.innerHTML = '';
        var recent = summary.recent || [];
        if (recent.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'sentinel-stream-empty';
            empty.textContent = 'No Sentinel findings in the last ' + (summary.window_hours || 24) + ' hours.';
            container.appendChild(empty);
            return;
        }
        for (var i = 0; i < recent.length; i++) {
            var r = recent[i];
            var row = document.createElement('div');
            row.className = 'sentinel-row';

            var ts = document.createElement('span');
            ts.className = 'sentinel-row-time';
            ts.textContent = formatRelative(r.timestamp);
            ts.title = r.timestamp || '';

            var sev = document.createElement('span');
            var sevValue = (r.severity || '?').toLowerCase();
            sev.className = 'sentinel-row-sev sentinel-row-sev-' + sevValue;
            sev.textContent = sevValue;

            var vc = document.createElement('span');
            vc.className = 'sentinel-row-class';
            vc.textContent = r.violation_class || '?';

            var msg = document.createElement('span');
            msg.className = 'sentinel-row-msg';
            msg.textContent = r.message || '';

            row.appendChild(ts);
            row.appendChild(sev);
            row.appendChild(vc);
            row.appendChild(msg);
            container.appendChild(row);
        }
    }

    function setFooter(summary) {
        var el = document.getElementById('sentinel-meta');
        if (!el) return;
        el.textContent = 'window: ' + (summary.window_hours || 24) + 'h'
            + ' · ' + (summary.total || 0) + ' findings'
            + ' · refreshed ' + formatRelative(summary.generated_at);
    }

    async function refresh() {
        var summary = await fetchSummary();
        if (!summary) {
            setMetric('sentinel-count-total', '—');
            setMetric('sentinel-count-critical', '—');
            setMetric('sentinel-count-high', '—');
            setMetric('sentinel-count-medium', '—');
            return;
        }
        renderCounts(summary);
        renderClassBreakdown(summary);
        renderStream(summary);
        setFooter(summary);
    }

    function wire() {
        var btn = document.getElementById('sentinel-refresh');
        if (btn) btn.addEventListener('click', refresh);
        refresh();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wire);
    } else {
        wire();
    }

    window.SentinelPanel = { refresh: refresh };
})();
