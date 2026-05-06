/**
 * UNITARES Dashboard — Metric Color Utility
 *
 * Single source of truth for EISV metric colors, risk thresholds,
 * and heatmap gradients. Replaces 5 duplicated color computations.
 */
(function () {
    'use strict';

    var MetricColors = {};

    // Hex values for Chart.js / Canvas contexts (cannot use CSS vars)
    MetricColors.HEX = {
        energy:     '#9d4edd',
        integrity:  '#00e676',
        entropy:    '#ffea00',
        volatility: '#ff3d00',
        coherence:  '#00f0ff',
        // Chart.js series (slightly different shades for readability on dark bg)
        chartEnergy:    '#7c3aed',
        chartIntegrity: '#10b981',
        chartEntropy:   '#f59e0b',
        chartVoid:      '#ef4444',
        chartCoherence: '#06b6d4'
    };

    // Semantic status levels with both CSS var and hex representations
    MetricColors.STATUS = {
        good:     { css: 'var(--color-success)', hex: '#22c55e' },
        warning:  { css: 'var(--color-warning)', hex: '#eab308' },
        elevated: { css: 'var(--accent-orange)',  hex: '#f97316' },
        danger:   { css: 'var(--color-error)',    hex: '#ef4444' },
        info:     { css: 'var(--color-info)',     hex: '#3b82f6' },
        muted:    { css: 'var(--color-muted)',    hex: '#6b7280' }
    };

    // Trend state colors (for drift gauges)
    MetricColors.TREND = {
        stable:      { css: 'var(--drift-neutral)',  hex: '#6b7280' },
        oscillating: { css: 'var(--color-coherence)', hex: '#06b6d4' },
        drifting_up: { css: 'var(--drift-positive)',  hex: '#ef4444' },
        drifting_down: { css: 'var(--drift-negative)', hex: '#3b82f6' }
    };

    // Vivid accent colors for metric bars (match original dashboard style)
    MetricColors.ACCENT = {
        good:     { css: 'var(--accent-green)',  hex: '#00e676' },
        warning:  { css: 'var(--accent-yellow)', hex: '#ffea00' },
        elevated: { css: 'var(--accent-orange)', hex: '#ff3d00' }
    };

    /**
     * Color for a 0-1 metric value based on health thresholds.
     * Uses vivid accent colors for metric bars (DOM/Canvas).
     * @param {number} val - Metric value
     * @param {boolean} inverted - True for S/V (lower is better)
     * @param {string} [context='css'] - 'css' for DOM, 'hex' for Canvas/Chart.js
     * @returns {string} Color string or empty string if null
     */
    MetricColors.forValue = function (val, inverted, context) {
        if (val === null || val === undefined || Number.isNaN(val)) return '';
        context = context || 'css';
        var colors = MetricColors.ACCENT;
        if (inverted) {
            if (val < 0.3) return colors.good[context];
            if (val < 0.6) return colors.warning[context];
            return colors.elevated[context];
        }
        if (val > 0.6) return colors.good[context];
        if (val > 0.3) return colors.warning[context];
        return colors.elevated[context];
    };

    /**
     * Color for a 0-1 risk score (4-tier).
     * @param {number} risk
     * @param {string} [context='hex']
     * @returns {string}
     */
    MetricColors.forRisk = function (risk, context) {
        context = context || 'hex';
        if (risk < 0.35) return MetricColors.STATUS.good[context];
        if (risk < 0.6)  return MetricColors.STATUS.warning[context];
        if (risk < 0.7)  return MetricColors.STATUS.elevated[context];
        return MetricColors.STATUS.danger[context];
    };

    /**
     * RGBA string for Canvas heatmap cells (green → yellow → red).
     * @param {number} badness - 0 = healthy, 1 = unhealthy
     * @returns {string} rgba() string
     */
    MetricColors.heatmapRGBA = function (badness) {
        var r, g;
        if (badness < 0.5) {
            r = Math.round(badness * 2 * 230);
            g = 200;
        } else {
            r = 230;
            g = Math.round((1 - badness) * 2 * 200);
        }
        return 'rgba(' + r + ', ' + g + ', 60, 0.5)';
    };

    /**
     * Color for drift gauge fill based on drift value and percentage.
     * @param {number} clamped - Drift value (positive or negative)
     * @param {number} pct - Absolute percentage
     * @param {string} [context='hex']
     * @returns {string}
     */
    MetricColors.forDrift = function (clamped, pct, context) {
        context = context || 'hex';
        if (clamped >= 0) {
            if (pct > 20) return MetricColors.STATUS.danger[context];
            if (pct > 5) return MetricColors.STATUS.warning[context];
            return MetricColors.STATUS.muted[context];
        }
        if (pct > 20) return MetricColors.STATUS.info[context];
        if (pct > 5) return MetricColors.TREND.oscillating[context];
        return MetricColors.STATUS.muted[context];
    };

    if (typeof window !== 'undefined') {
        window.MetricColors = MetricColors;
    }
})();
