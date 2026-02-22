/**
 * Dashboard Components
 * 
 * Reusable UI components for the dashboard.
 * Designed for quality, accessibility, and maintainability.
 */

class LoadingSkeleton {
    /**
     * Creates a loading skeleton placeholder
     */
    static create(type = 'card', count = 1) {
        const skeletons = [];
        for (let i = 0; i < count; i++) {
            skeletons.push(this._createSkeleton(type));
        }
        return skeletons.join('');
    }

    static _createSkeleton(type) {
        const baseClass = 'skeleton';
        const skeletons = {
            card: `
                <div class="${baseClass} ${baseClass}-card">
                    <div class="${baseClass}-line" style="width: 60%; height: 20px; margin-bottom: 10px;"></div>
                    <div class="${baseClass}-line" style="width: 100%; height: 16px; margin-bottom: 8px;"></div>
                    <div class="${baseClass}-line" style="width: 80%; height: 16px;"></div>
                </div>
            `,
            stat: `
                <div class="${baseClass} ${baseClass}-stat">
                    <div class="${baseClass}-line" style="width: 40%; height: 14px; margin-bottom: 8px;"></div>
                    <div class="${baseClass}-line" style="width: 60%; height: 32px;"></div>
                </div>
            `,
            listItem: `
                <div class="${baseClass} ${baseClass}-list-item">
                    <div class="${baseClass}-line" style="width: 30%; height: 18px; margin-bottom: 8px;"></div>
                    <div class="${baseClass}-line" style="width: 100%; height: 14px; margin-bottom: 6px;"></div>
                    <div class="${baseClass}-line" style="width: 70%; height: 14px;"></div>
                </div>
            `,
            metric: `
                <div class="${baseClass} ${baseClass}-metric">
                    <div class="${baseClass}-line" style="width: 20px; height: 14px; margin-bottom: 4px;"></div>
                    <div class="${baseClass}-line" style="width: 40px; height: 18px; margin-bottom: 4px;"></div>
                    <div class="${baseClass}-bar" style="width: 100%; height: 3px;"></div>
                </div>
            `
        };
        return skeletons[type] || skeletons.card;
    }
}

class MetricTooltip {
    /**
     * Creates a rich tooltip for EISV metrics
     */
    static create(metricName, value, trend = null) {
        const formatted = DataProcessor.formatEISVMetric(value, metricName);
        const trendHtml = trend ? this._formatTrend(trend) : '';

        return `
            <div class="metric-tooltip">
                <div class="metric-tooltip-header">
                    <strong>${metricName}</strong>
                    <span class="metric-tooltip-value" style="color: ${formatted.color}">
                        ${formatted.display}
                    </span>
                </div>
                <div class="metric-tooltip-interpretation">
                    ${DataProcessor.escapeHtml(formatted.interpretation)}
                </div>
                ${trendHtml}
                <div class="metric-tooltip-description">
                    ${this._getDescription(metricName)}
                </div>
            </div>
        `;
    }

    static _formatTrend(trend) {
        if (!trend || trend.direction === 'neutral') return '';
        const arrow = trend.direction === 'up' ? '↑' : '↓';
        const color = trend.direction === 'up' ? 'var(--accent-green)' : 'var(--accent-orange)';
        return `
            <div class="metric-tooltip-trend" style="color: ${color}">
                ${arrow} ${trend.percentChange}% vs previous
            </div>
        `;
    }

    static _getDescription(metricName) {
        const descriptions = {
            E: 'Energy represents productive capacity and divergence from baseline state.',
            I: 'Information Integrity measures the quality and reliability of information.',
            S: 'Entropy quantifies disorder and uncertainty in the system.',
            V: 'Void Integral measures the imbalance between Energy and Integrity.',
            C: 'Coherence measures how well-aligned the system state is.'
        };
        return descriptions[metricName] || '';
    }
}

class StatCard {
    /**
     * Creates a stat card with value, label, and optional trend
     */
    static create(id, label, value, trend = null, options = {}) {
        const {
            icon = '',
            color = 'var(--accent-cyan)',
            formatValue = (v) => v,
            showChange = true
        } = options;

        const trendHtml = trend && showChange ? this._formatChange(trend) : '';
        const formattedValue = formatValue(value);

        return `
            <div class="stat-card" id="${id}">
                ${icon ? `<div class="stat-card-icon">${icon}</div>` : ''}
                <h3>${DataProcessor.escapeHtml(label)}</h3>
                <div class="value" style="color: ${color}">${formattedValue}</div>
                <div class="change">${trendHtml}</div>
            </div>
        `;
    }

    static _formatChange(trend) {
        if (!trend || trend.direction === 'neutral') return '';
        const sign = trend.diff > 0 ? '+' : '';
        const color = trend.direction === 'up' ? 'var(--accent-green)' : 'var(--accent-orange)';
        return `<span style="color: ${color}">${sign}${trend.diff}</span>`;
    }
}

class AnimaGauge {
    /**
     * Creates a circular gauge for anima values
     */
    static create(value, label, color, size = 80) {
        const percent = Math.max(0, Math.min(100, value * 100));
        const circumference = 2 * Math.PI * (size / 2 - 5);
        const offset = circumference - (percent / 100) * circumference;

        return `
            <div class="anima-gauge" style="width: ${size}px; height: ${size}px;">
                <svg width="${size}" height="${size}">
                    <circle
                        cx="${size / 2}"
                        cy="${size / 2}"
                        r="${size / 2 - 5}"
                        fill="none"
                        stroke="var(--border-color)"
                        stroke-width="4"
                    />
                    <circle
                        cx="${size / 2}"
                        cy="${size / 2}"
                        r="${size / 2 - 5}"
                        fill="none"
                        stroke="${color}"
                        stroke-width="4"
                        stroke-dasharray="${circumference}"
                        stroke-dashoffset="${offset}"
                        stroke-linecap="round"
                        transform="rotate(-90 ${size / 2} ${size / 2})"
                        class="gauge-progress"
                    />
                </svg>
                <div class="gauge-value">${(value * 100).toFixed(0)}%</div>
                <div class="gauge-label">${DataProcessor.escapeHtml(label)}</div>
            </div>
        `;
    }
}

class EnvironmentalCard {
    /**
     * Creates a card for Pi sensor data (AHT20, VEML7700)
     */
    static create(data) {
        const { temp = 0, humidity = 0, lux = 0 } = data;

        return `
            <div class="stat-card environmental-card">
                <h3>Sensory Context</h3>
                <div class="env-grid">
                    <div class="env-item">
                        <span class="env-label">Temp</span>
                        <span class="env-value">${temp.toFixed(1)}°C</span>
                    </div>
                    <div class="env-item">
                        <span class="env-label">Humidity</span>
                        <span class="env-value">${humidity.toFixed(0)}%</span>
                    </div>
                    <div class="env-item">
                        <span class="env-label">Light</span>
                        <span class="env-value">${lux.toFixed(0)} lx</span>
                    </div>
                </div>
            </div>
        `;
    }
}

// Export for use in dashboard
if (typeof window !== 'undefined') {
    window.LoadingSkeleton = LoadingSkeleton;
    window.MetricTooltip = MetricTooltip;
    window.StatCard = StatCard;
    window.AnimaGauge = AnimaGauge;
    window.EnvironmentalCard = EnvironmentalCard;
}
