/**
 * Dashboard Utilities
 * 
 * Core utilities for API calls, error handling, caching, and data processing.
 * Designed for quality, maintainability, and performance.
 */

class DashboardAPI {
    /**
     * Centralized API client with retry logic, error handling, and caching.
     */
    constructor(baseURL = window.location.origin) {
        this.baseURL = baseURL;
        this.cache = new Map();
        this.cacheTimeout = 5000; // 5 seconds default cache
        this.retryConfig = {
            maxRetries: 3,
            baseDelay: 500,
            maxDelay: 5000
        };
    }

    /**
     * Get API token from localStorage or URL params
     */
    getAuthToken() {
        return localStorage.getItem('unitares_api_token') || 
               new URLSearchParams(window.location.search).get('token');
    }

    /**
     * Get cache key for a tool call
     */
    getCacheKey(toolName, toolArguments) {
        return `${toolName}:${JSON.stringify(toolArguments)}`;
    }

    /**
     * Check if cached data is still valid
     */
    isCacheValid(cacheEntry) {
        if (!cacheEntry) return false;
        return Date.now() - cacheEntry.timestamp < this.cacheTimeout;
    }

    /**
     * Call a tool via the MCP API with retry logic and caching.
     * 
     * @param {string} toolName - Name of the tool to call
     * @param {object} toolArguments - Tool arguments
     * @param {object} options - Options: {useCache, cacheTimeout, retry}
     * @returns {Promise<object>} Tool result
     */
    async callTool(toolName, toolArguments = {}, options = {}) {
        const {
            useCache = true,
            cacheTimeout = this.cacheTimeout,
            retry = true
        } = options;

        // Ensure toolArguments is an object
        if (!toolArguments || typeof toolArguments !== 'object' || Array.isArray(toolArguments)) {
            toolArguments = {};
        }

        // Check cache
        if (useCache) {
            const cacheKey = this.getCacheKey(toolName, toolArguments);
            const cached = this.cache.get(cacheKey);
            if (this.isCacheValid(cached)) {
                return cached.data;
            }
        }

        // Make request with retry logic
        let lastError;
        const maxRetries = retry ? this.retryConfig.maxRetries : 1;
        
        for (let attempt = 0; attempt < maxRetries; attempt++) {
            try {
                const result = await this._makeRequest(toolName, toolArguments);
                
                // Cache successful result
                if (useCache) {
                    const cacheKey = this.getCacheKey(toolName, toolArguments);
                    this.cache.set(cacheKey, {
                        data: result,
                        timestamp: Date.now()
                    });
                }
                
                return result;
            } catch (error) {
                lastError = error;
                
                // Don't retry on certain errors
                if (error.status === 401 || error.status === 403 || error.status === 404) {
                    throw error;
                }
                
                // Exponential backoff
                if (attempt < maxRetries - 1) {
                    const delay = Math.min(
                        this.retryConfig.baseDelay * Math.pow(2, attempt),
                        this.retryConfig.maxDelay
                    );
                    await this._sleep(delay);
                }
            }
        }
        
        throw lastError;
    }

    /**
     * Make HTTP request to tool endpoint
     */
    async _makeRequest(toolName, toolArguments) {
        const headers = {
            'Content-Type': 'application/json',
        };
        
        const token = this.getAuthToken();
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        // Ensure toolArguments is a plain object
        if (!toolArguments || typeof toolArguments !== 'object' || Array.isArray(toolArguments)) {
            toolArguments = {};
        }
        
        const requestBody = {
            name: String(toolName || ''),
            arguments: toolArguments
        };
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout
        
        try {
            const requestBodyStr = JSON.stringify(requestBody);
            console.log(`[API] Calling ${toolName}:`, { 
                url: `${this.baseURL}/v1/tools/call`,
                body: requestBodyStr.substring(0, 200) + (requestBodyStr.length > 200 ? '...' : '')
            });
            
            const response = await fetch(`${this.baseURL}/v1/tools/call`, {
                method: 'POST',
                headers: headers,
                body: requestBodyStr,
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            const responseText = await response.text();
            console.log(`[API] Response status: ${response.status}`, responseText.substring(0, 200));
            
            if (!response.ok) {
                let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
                
                try {
                    const errorData = JSON.parse(responseText);
                    if (errorData.error) {
                        errorMessage = errorData.error;
                    }
                } catch {
                    // Not JSON, use text as-is
                    if (responseText) {
                        errorMessage = responseText.substring(0, 200);
                    }
                }
                
                const error = new Error(errorMessage);
                error.status = response.status;
                throw error;
            }
            
            let data;
            try {
                data = JSON.parse(responseText);
            } catch (parseError) {
                console.error('[API] Failed to parse response as JSON:', responseText.substring(0, 200));
                throw new Error(`Invalid JSON response from server: ${parseError.message}`);
            }
            
            // Check for error in response even if HTTP 200
            if (data.success === false || data.error) {
                const errorMsg = data.error || data.message || 'Tool call failed';
                const error = new Error(errorMsg);
                error.status = data.status || 500;
                throw error;
            }
            
            // Handle result - could be string JSON or already parsed
            if (typeof data.result === 'string') {
                try {
                    return JSON.parse(data.result);
                } catch (parseError) {
                    console.warn('[API] Result is string but not valid JSON, returning as-is');
                    return data.result;
                }
            }
            return data.result;
        } catch (error) {
            clearTimeout(timeoutId);
            
            if (error.name === 'AbortError' || error.name === 'TimeoutError') {
                const timeoutError = new Error(`Request timeout after 30s. The server may be overloaded.`);
                timeoutError.status = 504;
                throw timeoutError;
            }
            
            if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
                const networkError = new Error(`Network error: Cannot reach server at ${this.baseURL}. Is the server running?`);
                networkError.status = 0;
                throw networkError;
            }
            
            throw error;
        }
    }

    /**
     * Sleep utility for delays
     */
    _sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Clear cache
     */
    clearCache() {
        this.cache.clear();
    }

    /**
     * Clear cache for specific tool
     */
    clearCacheFor(toolName, toolArguments = {}) {
        const cacheKey = this.getCacheKey(toolName, toolArguments);
        this.cache.delete(cacheKey);
    }
}

class DataProcessor {
    /**
     * Utilities for processing and formatting dashboard data
     */
    
    /**
     * Calculate trend from current and previous values
     */
    static calculateTrend(current, previous) {
        if (previous === undefined || previous === null || previous === 0) {
            return null;
        }
        const diff = current - previous;
        const percentChange = ((diff / previous) * 100).toFixed(1);
        return {
            diff,
            percentChange: Math.abs(percentChange),
            direction: diff > 0 ? 'up' : diff < 0 ? 'down' : 'neutral',
            isSignificant: Math.abs(percentChange) > 5 // 5% threshold
        };
    }

    /**
     * Format EISV metric with context
     */
    static formatEISVMetric(value, metricName) {
        if (value === null || value === undefined || isNaN(value)) {
            return { display: '-', interpretation: 'No data', color: 'var(--text-secondary)' };
        }
        
        const clamped = Math.max(0, Math.min(1, value));
        const percent = (clamped * 100).toFixed(0);
        
        const interpretations = {
            E: {
                low: { text: 'Low energy - limited productive capacity', color: 'var(--accent-orange)' },
                medium: { text: 'Moderate energy - steady productivity', color: 'var(--accent-yellow)' },
                high: { text: 'High energy - strong productive capacity', color: 'var(--accent-green)' }
            },
            I: {
                low: { text: 'Low integrity - information quality concerns', color: 'var(--accent-orange)' },
                medium: { text: 'Moderate integrity - acceptable quality', color: 'var(--accent-yellow)' },
                high: { text: 'High integrity - excellent information quality', color: 'var(--accent-green)' }
            },
            S: {
                low: { text: 'Low entropy - highly ordered', color: 'var(--accent-green)' },
                medium: { text: 'Moderate entropy - balanced', color: 'var(--accent-yellow)' },
                high: { text: 'High entropy - high disorder/uncertainty', color: 'var(--accent-orange)' }
            },
            V: {
                low: { text: 'Low void - good E-I balance', color: 'var(--accent-green)' },
                medium: { text: 'Moderate void - some imbalance', color: 'var(--accent-yellow)' },
                high: { text: 'High void - significant E-I imbalance', color: 'var(--accent-orange)' }
            },
            C: {
                low: { text: 'Low coherence - fragmented state', color: 'var(--accent-orange)' },
                medium: { text: 'Moderate coherence - some alignment', color: 'var(--accent-yellow)' },
                high: { text: 'High coherence - well-aligned state', color: 'var(--accent-green)' }
            }
        };
        
        let interpretation;
        if (clamped < 0.33) {
            interpretation = interpretations[metricName]?.low || { text: 'Low', color: 'var(--text-secondary)' };
        } else if (clamped < 0.67) {
            interpretation = interpretations[metricName]?.medium || { text: 'Moderate', color: 'var(--text-secondary)' };
        } else {
            interpretation = interpretations[metricName]?.high || { text: 'High', color: 'var(--text-secondary)' };
        }
        
        return {
            display: clamped.toFixed(2),
            percent: percent,
            interpretation: interpretation.text,
            color: interpretation.color,
            value: clamped
        };
    }

    /**
     * Format relative time
     */
    static formatRelativeTime(timestampMs) {
        if (!timestampMs) return null;
        const diffMs = Date.now() - timestampMs;
        if (diffMs <= 0) return 'just now';
        
        const seconds = Math.floor(diffMs / 1000);
        if (seconds < 60) return `${seconds}s ago`;
        
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ago`;
        
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours}h ago`;
        
        const days = Math.floor(hours / 24);
        if (days < 7) return `${days}d ago`;
        
        const weeks = Math.floor(days / 7);
        if (weeks < 5) return `${weeks}w ago`;
        
        const months = Math.floor(days / 30);
        if (months < 12) return `${months}mo ago`;
        
        const years = Math.floor(days / 365);
        return `${years}y ago`;
    }

    /**
     * Format timestamp for display
     */
    static formatTimestamp(timestamp) {
        if (!timestamp) return null;
        const date = new Date(timestamp);
        if (isNaN(date.getTime())) return null;
        return date.toLocaleString();
    }

    /**
     * Escape HTML to prevent XSS
     */
    static escapeHtml(text) {
        if (text === null || text === undefined) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /**
     * Highlight search terms in text
     */
    static highlightMatch(text, term) {
        if (!term) return DataProcessor.escapeHtml(text);

        const safeText = String(text || '');
        const safeTerm = String(term || '').trim();
        if (!safeTerm) return DataProcessor.escapeHtml(safeText);

        const escapedTerm = safeTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(escapedTerm, 'ig');
        let result = '';
        let lastIndex = 0;
        let match;

        while ((match = regex.exec(safeText)) !== null) {
            result += DataProcessor.escapeHtml(safeText.slice(lastIndex, match.index));
            result += `<mark class="highlight">${DataProcessor.escapeHtml(match[0])}</mark>`;
            lastIndex = match.index + match[0].length;
        }
        result += DataProcessor.escapeHtml(safeText.slice(lastIndex));
        return result;
    }

    /**
     * Export data as CSV
     */
    static exportToCSV(data, filename) {
        if (!data || data.length === 0) return;
        
        const headers = Object.keys(data[0]);
        const csv = [
            headers.join(','),
            ...data.map(row => 
                headers.map(header => {
                    const value = row[header];
                    if (value === null || value === undefined) return '';
                    const stringValue = String(value);
                    // Escape quotes and wrap in quotes if contains comma, quote, or newline
                    if (stringValue.includes(',') || stringValue.includes('"') || stringValue.includes('\n')) {
                        return `"${stringValue.replace(/"/g, '""')}"`;
                    }
                    return stringValue;
                }).join(',')
            )
        ].join('\n');
        
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || 'export.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    /**
     * Export data as JSON
     */
    static exportToJSON(data, filename) {
        const json = JSON.stringify(data, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || 'export.json';
        a.click();
        URL.revokeObjectURL(url);
    }

    /**
     * Copy text to clipboard
     */
    static async copyToClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }
        
        // Fallback for older browsers
        return new Promise((resolve, reject) => {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            try {
                const success = document.execCommand('copy');
                document.body.removeChild(textarea);
                if (success) {
                    resolve();
                } else {
                    reject(new Error('Copy failed'));
                }
            } catch (error) {
                document.body.removeChild(textarea);
                reject(error);
            }
        });
    }
}

class ThemeManager {
    /**
     * Manages dark/light theme switching
     */
    constructor() {
        this.currentTheme = localStorage.getItem('dashboard_theme') || 'dark';
        this.applyTheme(this.currentTheme);
    }

    /**
     * Apply theme
     */
    applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('dashboard_theme', theme);
        this.currentTheme = theme;
    }

    /**
     * Toggle between dark and light themes
     */
    toggle() {
        const newTheme = this.currentTheme === 'dark' ? 'light' : 'dark';
        this.applyTheme(newTheme);
        return newTheme;
    }

    /**
     * Get current theme
     */
    getTheme() {
        return this.currentTheme;
    }
}

// Export for use in dashboard
if (typeof window !== 'undefined') {
    window.DashboardAPI = DashboardAPI;
    window.DataProcessor = DataProcessor;
    window.ThemeManager = ThemeManager;
}
