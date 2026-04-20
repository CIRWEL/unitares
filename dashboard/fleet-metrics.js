// fleet-metrics.js — render `metrics.series` time-series on the dashboard.
//
// Consumes:
//   GET /v1/metrics/catalog       — available series (name, description, unit)
//   GET /v1/metrics/series?name=X — points for the selected series
//
// Surfaces Chronicler's scrape effect via a "Last scrape" subtitle so the
// scraper is visible even though it isn't a resident agent with its own
// identity/check-ins.

(function () {
    'use strict';

    var chart = null;          // Chart.js instance
    var currentName = null;    // selected series name
    var catalogCache = [];     // last-seen catalog

    function getAuthToken() {
        try {
            return localStorage.getItem('UNITARES_HTTP_API_TOKEN')
                || localStorage.getItem('unitares_api_token')
                || null;
        } catch (_e) {
            return null;
        }
    }

    function authHeaders() {
        var token = getAuthToken();
        return token ? { 'Authorization': 'Bearer ' + token } : {};
    }

    async function fetchCatalog() {
        try {
            var resp = await fetch('/v1/metrics/catalog', {
                credentials: 'same-origin',
                headers: authHeaders(),
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();
            if (!data || data.success === false) {
                throw new Error((data && data.error) || 'unknown');
            }
            return data.metrics || [];
        } catch (e) {
            console.warn('[FleetMetrics] catalog fetch failed:', e);
            return [];
        }
    }

    async function fetchSeries(name) {
        try {
            var url = '/v1/metrics/series?name=' + encodeURIComponent(name);
            var resp = await fetch(url, {
                credentials: 'same-origin',
                headers: authHeaders(),
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();
            if (!data || data.success === false) {
                throw new Error((data && data.error) || 'unknown');
            }
            return data.points || [];
        } catch (e) {
            console.warn('[FleetMetrics] series fetch failed:', e);
            return [];
        }
    }

    function formatRelative(isoStr) {
        if (!isoStr) return '';
        var then = new Date(isoStr);
        var secs = Math.floor((Date.now() - then.getTime()) / 1000);
        if (secs < 60) return 'just now';
        if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
        if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
        return Math.floor(secs / 86400) + 'd ago';
    }

    function setDescription(text) {
        var el = document.getElementById('fleet-metrics-description');
        if (el) el.textContent = text || '';
    }

    function setScrapeStatus(points) {
        var el = document.getElementById('fleet-metrics-scrape-status');
        if (!el) return;
        if (!points || points.length === 0) {
            el.textContent = 'no data — awaiting first scrape';
            el.title = '';
            return;
        }
        var newest = points[points.length - 1];
        el.textContent = 'last scrape: ' + formatRelative(newest.ts)
            + ' (' + points.length + ' point' + (points.length === 1 ? '' : 's') + ')';
        el.title = newest.ts;
    }

    function showChart(show) {
        var canvas = document.getElementById('fleet-metrics-chart');
        var empty = document.getElementById('fleet-metrics-empty');
        if (canvas) canvas.style.display = show ? '' : 'none';
        if (empty) empty.style.display = show ? 'none' : '';
    }

    function renderEmpty(message) {
        var empty = document.getElementById('fleet-metrics-empty');
        if (empty) empty.textContent = message;
        showChart(false);
        if (chart) { chart.destroy(); chart = null; }
    }

    function renderChart(metric, points) {
        var canvas = document.getElementById('fleet-metrics-chart');
        if (!canvas) return;

        if (points.length === 0) {
            renderEmpty('No data for "' + metric.name + '" yet. Chronicler runs daily — try Refresh after the next cycle.');
            return;
        }

        showChart(true);
        var data = points.map(function (p) {
            return { x: new Date(p.ts), y: p.value };
        });

        if (chart) chart.destroy();
        // eslint-disable-next-line no-undef
        chart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                datasets: [{
                    label: metric.name + (metric.unit ? ' (' + metric.unit + ')' : ''),
                    data: data,
                    borderColor: '#4a9eff',
                    backgroundColor: 'rgba(74, 158, 255, 0.12)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { mode: 'index', intersect: false },
                },
                scales: {
                    x: {
                        type: 'time',
                        time: { tooltipFormat: 'yyyy-MM-dd HH:mm' },
                    },
                    y: {
                        beginAtZero: false,
                        title: { display: !!metric.unit, text: metric.unit || '' },
                    },
                },
            },
        });
    }

    function populateDropdown(metrics) {
        var select = document.getElementById('fleet-metrics-select');
        if (!select) return;
        select.innerHTML = '';
        if (metrics.length === 0) {
            var opt = document.createElement('option');
            opt.value = '';
            opt.textContent = '(no metrics registered)';
            select.appendChild(opt);
            return;
        }
        for (var i = 0; i < metrics.length; i++) {
            var m = metrics[i];
            var o = document.createElement('option');
            o.value = m.name;
            o.textContent = m.name;          // terse — description goes in subtitle
            if (m.description) o.title = m.description;
            select.appendChild(o);
        }
        if (!currentName || !metrics.some(function (m) { return m.name === currentName; })) {
            currentName = metrics[0].name;
        }
        select.value = currentName;
    }

    async function refresh() {
        catalogCache = await fetchCatalog();
        populateDropdown(catalogCache);
        if (catalogCache.length === 0) {
            setDescription('');
            setScrapeStatus(null);
            renderEmpty('No metrics registered yet.');
            return;
        }
        var metric = catalogCache.find(function (m) { return m.name === currentName; }) || catalogCache[0];
        currentName = metric.name;
        setDescription(metric.description || '');
        var points = await fetchSeries(metric.name);
        setScrapeStatus(points);
        renderChart(metric, points);
    }

    function wire() {
        var select = document.getElementById('fleet-metrics-select');
        var refreshBtn = document.getElementById('fleet-metrics-refresh');
        if (select) {
            select.addEventListener('change', function () {
                currentName = select.value;
                refresh();
            });
        }
        if (refreshBtn) {
            refreshBtn.addEventListener('click', refresh);
        }
        refresh();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wire);
    } else {
        wire();
    }

    window.FleetMetricsPanel = {
        refresh: refresh,
        _fetchCatalog: fetchCatalog,
        _fetchSeries: fetchSeries,
    };
})();
