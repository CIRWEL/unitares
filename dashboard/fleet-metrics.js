// fleet-metrics.js — render `metrics.series` time-series on the dashboard.
//
// Consumes:
//   GET /v1/metrics/catalog       — list of available series names
//   GET /v1/metrics/series?name=X — points for the selected series
//
// Deliberately small surface: one line chart, a dropdown of series, a
// refresh button. No WS subscription (these metrics move on daily cadence,
// so polling-on-demand is right-sized). Extends naturally as the catalog
// grows — no code change needed to see new series, just pick them from
// the dropdown.

(function () {
    'use strict';

    var chart = null;          // Chart.js instance
    var currentName = null;    // selected series name

    function getAuthToken() {
        try {
            return localStorage.getItem('UNITARES_HTTP_API_TOKEN') || null;
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

    function renderEmpty(message) {
        var empty = document.getElementById('fleet-metrics-empty');
        var canvas = document.getElementById('fleet-metrics-chart');
        if (!empty || !canvas) return;
        empty.textContent = message;
        empty.style.display = '';
        canvas.style.display = 'none';
        if (chart) {
            chart.destroy();
            chart = null;
        }
    }

    function renderChart(metric, points) {
        var empty = document.getElementById('fleet-metrics-empty');
        var canvas = document.getElementById('fleet-metrics-chart');
        if (!canvas) return;

        if (points.length === 0) {
            renderEmpty('No data yet for "' + metric.name + '" — wait for the next Chronicler cycle.');
            return;
        }

        empty.style.display = 'none';
        canvas.style.display = '';

        var data = points.map(function (p) {
            return { x: new Date(p.ts), y: p.value };
        });

        if (chart) {
            chart.destroy();
        }

        // eslint-disable-next-line no-undef
        chart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                datasets: [{
                    label: metric.name + (metric.unit ? ' (' + metric.unit + ')' : ''),
                    data: data,
                    borderColor: '#4a9eff',
                    backgroundColor: 'rgba(74, 158, 255, 0.1)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true, position: 'top' },
                    tooltip: { mode: 'index', intersect: false },
                },
                scales: {
                    x: {
                        type: 'time',
                        time: { tooltipFormat: 'yyyy-MM-dd HH:mm' },
                        title: { display: false },
                    },
                    y: {
                        beginAtZero: false,
                        title: { display: !!metric.unit, text: metric.unit },
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
            o.textContent = m.name + (m.description ? '  —  ' + m.description : '');
            select.appendChild(o);
        }
        if (!currentName || !metrics.some(function (m) { return m.name === currentName; })) {
            currentName = metrics[0].name;
            select.value = currentName;
        }
    }

    async function refresh() {
        var metrics = await fetchCatalog();
        populateDropdown(metrics);
        if (metrics.length === 0) {
            renderEmpty('No metrics registered yet.');
            return;
        }
        var metric = metrics.find(function (m) { return m.name === currentName; }) || metrics[0];
        currentName = metric.name;
        var points = await fetchSeries(metric.name);
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

    // Expose for console debugging / tests
    window.FleetMetricsPanel = {
        refresh: refresh,
        _fetchCatalog: fetchCatalog,
        _fetchSeries: fetchSeries,
    };
})();
