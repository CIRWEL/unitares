/**
 * UNITARES Dashboard — Advanced Visualizations
 *
 * Radar charts, fleet heatmaps, sparklines, and anomaly indicators.
 * Depends on: Chart.js 4.x (already loaded), dashboard.js globals (cachedAgents, agentEISVHistory).
 */

// ============================================================================
// EISV RADAR CHART (Chart.js radar type)
// ============================================================================

class EISVRadarChart {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.chart = null;
    }

    /**
     * Render a 5-axis radar chart for one agent vs fleet average.
     * @param {Object} agentMetrics - {E, I, S, V, coherence}
     * @param {Object|null} fleetAvg - {E, I, S, V, coherence} or null
     * @param {string} agentName
     */
    render(agentMetrics, fleetAvg, agentName = 'Agent') {
        if (!this.canvas) return;
        if (this.chart) this.chart.destroy();

        const labels = ['Energy', 'Integrity', 'Entropy', '|Void|', 'Coherence'];

        // Normalize V to 0-1 range for radar display
        const normalizeV = v => Math.min(1, Math.abs(v || 0) / 0.3);

        const toRadarData = m => [
            m.E || 0,
            m.I || 0,
            m.S || 0,
            normalizeV(m.V),
            m.coherence || 0
        ];

        const datasets = [{
            label: agentName,
            data: toRadarData(agentMetrics),
            borderColor: '#00f0ff',
            backgroundColor: 'rgba(0, 240, 255, 0.12)',
            borderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBackgroundColor: '#00f0ff',
            pointBorderColor: '#00f0ff'
        }];

        if (fleetAvg) {
            datasets.push({
                label: 'Fleet Average',
                data: toRadarData(fleetAvg),
                borderColor: 'rgba(255, 255, 255, 0.3)',
                backgroundColor: 'rgba(255, 255, 255, 0.04)',
                borderWidth: 1.5,
                borderDash: [4, 4],
                pointRadius: 2,
                pointBackgroundColor: 'rgba(255, 255, 255, 0.3)'
            });
        }

        this.chart = new Chart(this.canvas, {
            type: 'radar',
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'bottom',
                        labels: {
                            color: '#9aa0af',
                            font: { size: 11, family: "'Outfit', sans-serif" },
                            padding: 12,
                            usePointStyle: true,
                            pointStyleWidth: 8
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(5, 5, 10, 0.9)',
                        borderColor: 'rgba(0, 240, 255, 0.3)',
                        borderWidth: 1,
                        titleFont: { family: "'Outfit', sans-serif" },
                        bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
                        callbacks: {
                            label: ctx => `${ctx.dataset.label}: ${ctx.raw.toFixed(4)}`
                        }
                    }
                },
                scales: {
                    r: {
                        min: 0,
                        max: 1,
                        grid: { color: 'rgba(255, 255, 255, 0.06)' },
                        angleLines: { color: 'rgba(255, 255, 255, 0.06)' },
                        pointLabels: {
                            color: '#9aa0af',
                            font: { size: 11, family: "'Outfit', sans-serif" }
                        },
                        ticks: { display: false, stepSize: 0.25 }
                    }
                },
                animation: { duration: 500, easing: 'easeOutCubic' }
            }
        });
    }

    destroy() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }
}

// ============================================================================
// FLEET HEATMAP (Canvas 2D)
// ============================================================================

class FleetHeatmap {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
    }

    /**
     * Render agent x metric heatmap.
     * @param {Array<Object>} agents - Agent objects with .metrics and .label/.name/.agent_id
     */
    render(agents) {
        if (!this.canvas || !this.ctx) return;

        const metrics = ['E', 'I', 'S', 'V', 'coherence'];
        const metricLabels = ['E', 'I', 'S', '|V|', 'C'];
        const cellW = 56, cellH = 30, labelW = 130, headerH = 32;
        const width = labelW + metrics.length * cellW;
        const height = headerH + agents.length * cellH;

        // HiDPI scaling
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = width * dpr;
        this.canvas.height = height * dpr;
        this.canvas.style.width = width + 'px';
        this.canvas.style.height = height + 'px';
        this.ctx.scale(dpr, dpr);

        // Clear
        this.ctx.clearRect(0, 0, width, height);

        // Header labels
        this.ctx.font = '11px "JetBrains Mono", monospace';
        this.ctx.fillStyle = '#9aa0af';
        this.ctx.textAlign = 'center';
        metricLabels.forEach((label, i) => {
            this.ctx.fillText(label, labelW + i * cellW + cellW / 2, 20);
        });

        // Rows
        agents.forEach((agent, row) => {
            const y = headerH + row * cellH;
            const m = agent.metrics || {};

            // Agent name (truncated)
            this.ctx.textAlign = 'right';
            this.ctx.fillStyle = '#9aa0af';
            this.ctx.font = '10px "Outfit", sans-serif';
            const name = (agent.label || agent.name || agent.agent_id || '').substring(0, 16);
            this.ctx.fillText(name, labelW - 8, y + cellH / 2 + 4);

            // Metric cells
            metrics.forEach((metric, col) => {
                const x = labelW + col * cellW;
                let val = metric === 'V'
                    ? Math.min(1, Math.abs(m.V || 0) / 0.3)
                    : Math.max(0, Math.min(1, m[metric] || 0));

                // Color: for E/I/coherence, high=green; for S/V, low=green
                const isInverted = metric === 'S' || metric === 'V';
                const badness = isInverted ? val : (1 - val);

                // Interpolate: green → yellow → red (via MetricColors)
                this.ctx.fillStyle = (typeof MetricColors !== 'undefined')
                    ? MetricColors.heatmapRGBA(badness)
                    : 'rgba(128, 128, 60, 0.5)';
                this.ctx.fillRect(x + 2, y + 2, cellW - 4, cellH - 4);

                // Round corners (clip path for each cell)
                this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
                this.ctx.lineWidth = 0.5;
                this.ctx.strokeRect(x + 2, y + 2, cellW - 4, cellH - 4);

                // Value text
                this.ctx.fillStyle = '#f0f0f5';
                this.ctx.textAlign = 'center';
                this.ctx.font = '10px "JetBrains Mono", monospace';
                const displayVal = metric === 'V' ? m.V : m[metric];
                const text = displayVal !== undefined && displayVal !== null
                    ? Number(displayVal).toFixed(3)
                    : '-';
                this.ctx.fillText(text, x + cellW / 2, y + cellH / 2 + 4);
            });
        });
    }
}

// ============================================================================
// MINI SPARKLINES (inline SVG)
// ============================================================================

/**
 * Create a tiny SVG sparkline showing a metric trend.
 * @param {number[]} dataPoints - Array of numeric values
 * @param {Object} [options] - {width, height, color, strokeWidth}
 * @returns {string} SVG markup
 */
function createSparklineSVG(dataPoints, options = {}) {
    const { width = 60, height = 20, color = '#00f0ff', strokeWidth = 1.5 } = options;

    if (!dataPoints || dataPoints.length < 2) {
        return `<svg width="${width}" height="${height}" class="sparkline"></svg>`;
    }

    const min = Math.min(...dataPoints);
    const max = Math.max(...dataPoints);
    const range = max - min || 0.001;
    const pad = 2;
    const plotW = width - pad * 2;
    const plotH = height - pad * 2;

    const points = dataPoints.map((val, i) => {
        const x = pad + (i / (dataPoints.length - 1)) * plotW;
        const y = pad + plotH - ((val - min) / range) * plotH;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const pathD = `M ${points.join(' L ')}`;

    // Trend detection: compare first third to last third
    const third = Math.max(1, Math.ceil(dataPoints.length / 3));
    const firstAvg = dataPoints.slice(0, third).reduce((a, b) => a + b, 0) / third;
    const lastAvg = dataPoints.slice(-third).reduce((a, b) => a + b, 0) / third;
    const trendColor = lastAvg > firstAvg * 1.02 ? '#22c55e'
        : lastAvg < firstAvg * 0.98 ? '#ef4444'
            : color;

    // Path length estimate for animation
    const pathLen = (dataPoints.length - 1) * (plotW / (dataPoints.length - 1)) * 1.2;

    const lastPt = points[points.length - 1].split(',');

    return `<svg width="${width}" height="${height}" class="sparkline" viewBox="0 0 ${width} ${height}">
        <path d="${pathD}" fill="none" stroke="${trendColor}" stroke-width="${strokeWidth}"
              stroke-linecap="round" stroke-linejoin="round"
              style="stroke-dasharray: ${pathLen}; stroke-dashoffset: ${pathLen}; animation: sparkline-draw 0.8s ease-out forwards;" />
        <circle cx="${lastPt[0]}" cy="${lastPt[1]}" r="2" fill="${trendColor}" opacity="0.8" />
    </svg>`;
}

// ============================================================================
// ANOMALY INDICATORS
// ============================================================================

/**
 * Generate anomaly indicator HTML for an agent's metrics.
 * @param {Object} metrics - {E, I, S, V, coherence, risk_score}
 * @returns {string} HTML string (empty if no anomalies)
 */
function getAnomalyIndicator(metrics) {
    if (!metrics) return '';

    const anomalies = [];

    if (metrics.coherence !== undefined && metrics.coherence < 0.3) {
        anomalies.push({ severity: 'warning', label: 'Low coherence' });
    }
    if (metrics.S !== undefined && metrics.S > 0.1) {
        anomalies.push({ severity: 'warning', label: 'High entropy' });
    }
    if (metrics.risk_score !== undefined && metrics.risk_score > 0.6) {
        anomalies.push({ severity: 'critical', label: 'High risk' });
    }
    if (metrics.V !== undefined && Math.abs(metrics.V) > 0.15) {
        anomalies.push({ severity: 'warning', label: 'E-I imbalance' });
    }

    if (anomalies.length === 0) return '';

    const maxSeverity = anomalies.some(a => a.severity === 'critical') ? 'critical' : 'warning';
    const titles = anomalies.map(a => a.label).join(', ');
    const icon = maxSeverity === 'critical' ? '!!' : '!';

    return `<span class="anomaly-indicator anomaly-${maxSeverity}" title="${titles}">${icon}</span>`;
}

// ============================================================================
// FLEET AVERAGE HELPER
// ============================================================================

/**
 * Compute fleet average EISV from an array of agents.
 * @param {Array<Object>} agents - Agent objects with .metrics
 * @returns {Object|null} {E, I, S, V, coherence} or null
 */
function computeFleetAverageMetrics(agents) {
    const withMetrics = agents.filter(a => {
        const m = a.metrics || {};
        return m.coherence !== undefined && m.coherence !== null;
    });
    if (withMetrics.length === 0) return null;

    const sum = { E: 0, I: 0, S: 0, V: 0, coherence: 0 };
    withMetrics.forEach(a => {
        const m = a.metrics;
        sum.E += Number(m.E || 0);
        sum.I += Number(m.I || 0);
        sum.S += Number(m.S || 0);
        sum.V += Number(m.V || 0);
        sum.coherence += Number(m.coherence || 0);
    });

    const n = withMetrics.length;
    return {
        E: sum.E / n,
        I: sum.I / n,
        S: sum.S / n,
        V: sum.V / n,
        coherence: sum.coherence / n
    };
}

// ============================================================================
// EXPORTS
// ============================================================================

if (typeof window !== 'undefined') {
    window.EISVRadarChart = EISVRadarChart;
    window.FleetHeatmap = FleetHeatmap;
    window.createSparklineSVG = createSparklineSVG;
    window.getAnomalyIndicator = getAnomalyIndicator;
    window.computeFleetAverageMetrics = computeFleetAverageMetrics;
}
