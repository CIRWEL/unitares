// resident-progress.js — render Phase-1 resident-progress probe snapshots.
// Reads GET /v1/progress_flat/recent. Read-only; Phase 1 has no actions.
// Conforms to dashboard conventions: authFetch from utils.js, .panel layout.

(function () {
    'use strict';

    var REFRESH_INTERVAL_MS = 30000;
    var RESIDENT_LABELS = [
        "vigil", "sentinel", "watcher", "steward", "chronicler",
        "progress_flat_probe",
    ];
    var STATUS_CLASS = {
        "OK": "rp-status-ok",
        "flat-candidate": "rp-status-flat",
        "silent": "rp-status-silent",
        "source-error": "rp-status-error",
        "unresolved": "rp-status-unresolved",
        "startup-grace": "rp-status-init",
        "initializing": "rp-status-init",
    };

    async function fetchRecent(hours) {
        try {
            var resp = await authFetch(
                '/v1/progress_flat/recent?hours=' + (hours || 24)
            );
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();
            if (!data || data.success === false) {
                throw new Error((data && data.error) || 'unknown');
            }
            return data.rows || [];
        } catch (e) {
            console.warn('[ResidentProgress] fetch failed:', e);
            return [];
        }
    }

    function statusFor(row) {
        var s = row.status;
        if (!s && row.suppressed_reason === 'startup_unresolved_label') {
            return 'initializing';
        }
        return s || 'unresolved';
    }

    function renderRow(row) {
        var label = row.resident_label || '';
        var status = statusFor(row);
        var cls = STATUS_CLASS[status] || 'rp-status-unknown';
        var metric = (row.metric_value === null || row.metric_value === undefined)
            ? '—' : row.metric_value;
        var threshold = (row.threshold === null || row.threshold === undefined)
            ? '—' : row.threshold;
        var ticked = row.ticked_at
            ? new Date(row.ticked_at).toLocaleTimeString()
            : '—';
        var dim = label === 'progress_flat_probe' ? ' rp-dim' : '';
        return (
            '<div class="rp-row' + dim + '" data-label="' + label + '">' +
                '<span class="rp-label">' + label + '</span>' +
                '<span class="rp-badge ' + cls + '">' + status + '</span>' +
                '<span class="rp-metric">' + metric + ' / ' + threshold + '</span>' +
                '<span class="rp-window">' +
                    (row.window_seconds
                        ? Math.round(row.window_seconds / 60) + 'm'
                        : '—') +
                '</span>' +
                '<span class="rp-time">' + ticked + '</span>' +
            '</div>'
        );
    }

    function rowsByLabel(rows) {
        var out = {};
        rows.forEach(function (r) { out[r.resident_label] = r; });
        return out;
    }

    function applyOverlapFilter(rows, overlapOn) {
        if (!overlapOn) return rows;
        return rows.filter(function (r) {
            return r.candidate &&
                r.loop_detector_state &&
                r.loop_detector_state.loop_detected_at;
        });
    }

    async function refresh() {
        var rows = await fetchRecent(24);
        var overlapEl = document.getElementById('rp-overlap-toggle');
        var overlapOn = overlapEl ? overlapEl.checked : false;
        var filtered = applyOverlapFilter(rows, overlapOn);
        var byLabel = rowsByLabel(filtered);
        var html = RESIDENT_LABELS.map(function (label) {
            return renderRow(byLabel[label] || {
                resident_label: label, status: 'unresolved',
            });
        }).join('');
        var container = document.getElementById('rp-rows');
        if (container) container.innerHTML = html;
    }

    function wire() {
        var toggle = document.getElementById('rp-overlap-toggle');
        if (toggle) toggle.addEventListener('change', refresh);
        refresh();
        setInterval(refresh, REFRESH_INTERVAL_MS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wire);
    } else {
        wire();
    }
})();
