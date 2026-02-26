/**
 * UNITARES Dashboard — Discoveries Module
 *
 * Discovery rendering, filtering, detail modal, and export.
 * Extracted from dashboard.js to reduce monolith size.
 */
(function () {
    'use strict';

    if (typeof DashboardState === 'undefined') {
        console.warn('[DiscoveriesModule] state.js not loaded, module disabled');
        return;
    }

    var escapeHtml = DataProcessor.escapeHtml;
    var highlightMatch = DataProcessor.highlightMatch;

    // Time filter constants (avoids cross-script dependency on CONFIG)
    var DAY_MS = 24 * 60 * 60 * 1000;
    var WEEK_MS = 7 * DAY_MS;
    var MONTH_MS = 30 * DAY_MS;

    // ========================================================================
    // Discovery utility functions
    // ========================================================================

    function normalizeDiscoveryType(type) {
        if (!type) return 'note';
        return String(type).trim().toLowerCase();
    }

    function formatDiscoveryType(type) {
        var value = normalizeDiscoveryType(type);
        var labelMap = {
            bug_found: 'Bug',
            improvement: 'Improvement',
            insight: 'Insight',
            pattern: 'Pattern',
            question: 'Question',
            answer: 'Answer',
            note: 'Note',
            exploration: 'Exploration',
            analysis: 'Analysis'
        };
        return labelMap[value] || value.replace(/_/g, ' ');
    }

    // ========================================================================
    // Discovery UI helpers
    // ========================================================================

    function updateDiscoveryFilterInfo(filteredCount) {
        var info = document.getElementById('discoveries-filter-info');
        if (!info) return;
        var total = state.get('cachedDiscoveries').length;
        if (!total) {
            info.textContent = '';
            return;
        }
        if (filteredCount === 0) {
            info.textContent = 'No discoveries match filters (' + total + ' loaded)';
            return;
        }
        var showingCount = Math.min(filteredCount, 10);
        info.textContent = 'Showing ' + showingCount + ' of ' + filteredCount + ' filtered (' + total + ' loaded)';
    }

    function updateDiscoveryLegend(discoveries) {
        var container = document.getElementById('discoveries-type-legend');
        if (!container) return;
        if (!discoveries || discoveries.length === 0) {
            container.textContent = '';
            return;
        }

        var counts = {};
        discoveries.forEach(function (d) {
            var type = normalizeDiscoveryType(d.type || d.discovery_type || 'note');
            counts[type] = (counts[type] || 0) + 1;
        });

        var total = discoveries.length;
        var chips = [];
        chips.push('<button class="discovery-type" data-type="all" type="button">All ' + total + '</button>');

        var orderedTypes = ['insight', 'improvement', 'bug_found', 'pattern', 'question', 'answer', 'analysis', 'note', 'exploration'];
        orderedTypes.forEach(function (type) {
            if (!counts[type]) return;
            var label = escapeHtml(formatDiscoveryType(type));
            var count = counts[type];
            chips.push('<button class="discovery-type ' + type + '" data-type="' + type + '" type="button">' + label + ' ' + count + '</button>');
            delete counts[type];
        });

        Object.keys(counts).sort().forEach(function (type) {
            var label = escapeHtml(formatDiscoveryType(type));
            var count = counts[type];
            chips.push('<button class="discovery-type ' + type + '" data-type="' + type + '" type="button">' + label + ' ' + count + '</button>');
        });

        container.innerHTML = chips.join(' ');
    }

    // ========================================================================
    // Discovery list rendering
    // ========================================================================

    function renderDiscoveriesList(discoveries, searchTerm) {
        searchTerm = searchTerm || '';
        var container = document.getElementById('discoveries-container');
        var cachedDiscoveries = state.get('cachedDiscoveries') || [];
        if (!container) return;

        if (cachedDiscoveries.length === 0) {
            container.innerHTML = '<div class="loading">No discoveries yet. Agents add them via store_knowledge_graph().</div>';
            state.set({ filteredDiscoveries: [] });
            updateDiscoveryFilterInfo(0);
            return;
        }

        if (discoveries.length === 0) {
            container.innerHTML = '<div class="loading">No matches. Clear filters or change search.</div>';
            state.set({ filteredDiscoveries: [] });
            updateDiscoveryFilterInfo(0);
            return;
        }

        updateDiscoveryFilterInfo(discoveries.length);
        state.set({ filteredDiscoveries: discoveries });
        var displayDiscoveries = discoveries.slice(0, 10);
        container.innerHTML = displayDiscoveries.map(function (d, idx) {
            var type = normalizeDiscoveryType(d.type || d.discovery_type || 'note');
            var typeLabel = escapeHtml(formatDiscoveryType(type));
            var agent = escapeHtml(d.by || d.agent_id || d._agent_id || 'Unknown');
            var details = String(d.details || d.content || d.discovery || '');
            var summaryText = d.summary || 'Untitled';
            var summaryHtml = highlightMatch(summaryText, searchTerm);
            var relative = d._relativeTime ? ' (' + d._relativeTime + ')' : '';
            var displayDate = escapeHtml((d._displayDate || 'Unknown') + relative);
            var tags = (d.tags || []).slice(0, 5).map(function (t) {
                return '<span class="discovery-tag clickable-tag" data-tag="' + escapeHtml(t) + '">' + escapeHtml(t) + '</span>';
            }).join('');

            // Expandable details section (click to expand inline, or click card for modal)
            var detailsHtml = '';
            if (details && details.trim()) {
                detailsHtml = '<details class="discovery-expand" onclick="event.stopPropagation()">' +
                    '<summary>Show details</summary>' +
                    '<div class="discovery-details-preview">' + escapeHtml(details) + '</div>' +
                '</details>';
            }

            return '<div class="discovery-item" data-discovery-index="' + idx + '" style="cursor: pointer;" title="Click to view full details">' +
                '<div class="discoveries-meta-line">' +
                    '<span class="discovery-type ' + type + '">' + typeLabel + '</span>' +
                    '<span class="meta-item">By: ' + agent + '</span>' +
                    '<span class="meta-item">' + displayDate + '</span>' +
                '</div>' +
                '<div class="discovery-summary">' + summaryHtml + '</div>' +
                detailsHtml +
                (tags ? '<div class="discovery-tags">' + tags + '</div>' : '') +
            '</div>';
        }).join('');
    }

    // ========================================================================
    // Discovery filtering
    // ========================================================================

    function applyDiscoveryFilters() {
        var searchInput = document.getElementById('discovery-search');
        var typeFilterInput = document.getElementById('discovery-type-filter');
        var timeFilterInput = document.getElementById('discovery-time-filter');
        var searchTerm = searchInput ? searchInput.value.trim().toLowerCase() : '';
        var typeFilter = typeFilterInput ? typeFilterInput.value : 'all';
        var timeFilter = timeFilterInput ? timeFilterInput.value : 'all';

        var cutoff = null;
        if (timeFilter === '24h') cutoff = Date.now() - DAY_MS;
        else if (timeFilter === '7d') cutoff = Date.now() - WEEK_MS;
        else if (timeFilter === '30d') cutoff = Date.now() - MONTH_MS;

        var cachedDiscoveries = state.get('cachedDiscoveries');
        var filtered = cachedDiscoveries.filter(function (d) {
            var type = normalizeDiscoveryType(d.type || d.discovery_type || 'note');
            if (typeFilter !== 'all' && type !== typeFilter) return false;
            if (cutoff !== null && (!d._timestampMs || d._timestampMs < cutoff)) return false;
            if (searchTerm) {
                var tagStr = (d.tags || []).join(' ');
                var haystack = ((d.summary || '') + ' ' + (d.details || '') + ' ' + (d.content || '') + ' ' + (d.discovery || '') + ' ' + tagStr).toLowerCase();
                if (haystack.indexOf(searchTerm) === -1) return false;
            }
            return true;
        });

        renderDiscoveriesList(filtered, searchTerm);
    }

    function clearDiscoveryFilters() {
        var searchInput = document.getElementById('discovery-search');
        var typeFilterInput = document.getElementById('discovery-type-filter');
        var timeFilterInput = document.getElementById('discovery-time-filter');
        if (searchInput) searchInput.value = '';
        if (typeFilterInput) typeFilterInput.value = 'all';
        if (timeFilterInput) timeFilterInput.value = 'all';
        applyDiscoveryFilters();
    }

    // ========================================================================
    // Discovery detail modal
    // ========================================================================

    function showDiscoveryDetail(discovery) {
        var modal = document.getElementById('panel-modal');
        var modalTitle = document.getElementById('modal-title');
        var modalBody = document.getElementById('modal-body');
        if (!modal || !modalTitle || !modalBody) return;

        var type = normalizeDiscoveryType(discovery.type || discovery.discovery_type || 'note');
        var typeLabel = formatDiscoveryType(type);
        var agent = discovery.by || discovery.agent_id || discovery._agent_id || 'Unknown';
        var summary = discovery.summary || 'Untitled';
        var details = discovery.details || discovery.content || discovery.discovery || '';
        var displayDate = discovery._displayDate || 'Unknown';
        var relativeTime = discovery._relativeTime || '';

        var filterFn = typeof filterInternalKeys === 'function' ? filterInternalKeys : function (o) { return o; };

        // Tags
        var tagsHtml = (discovery.tags && discovery.tags.length > 0)
            ? discovery.tags.map(function (t) {
                return '<span class="discovery-tag clickable-tag tag-chip" data-tag="' + escapeHtml(t) + '">' + escapeHtml(t) + '</span>';
            }).join('')
            : '';

        var html = '<div class="discovery-detail">' +
            '<div class="flex-row mb-md">' +
                '<span class="discovery-type ' + type + '" style="font-size: 1em;">' + escapeHtml(typeLabel) + '</span>' +
                '<span class="text-secondary-sm">' + escapeHtml(displayDate) + (relativeTime ? ' (' + relativeTime + ')' : '') + '</span>' +
            '</div>' +

            '<div class="detail-section">' +
                '<strong class="text-secondary-sm">Summary:</strong><br>' +
                '<span style="font-size: 1.1em;">' + escapeHtml(summary) + '</span>' +
            '</div>' +

            (details
                ? '<div class="detail-section">' +
                    '<strong class="text-secondary-sm">Details:</strong>' +
                    '<div class="content-box">' + escapeHtml(details) + '</div>' +
                  '</div>'
                : '') +

            '<div class="grid-2col mb-md mt-md">' +
                '<div>' +
                    '<strong class="text-secondary-sm">Agent:</strong><br>' +
                    '<code style="font-size: 0.9em; word-break: break-all;">' + escapeHtml(agent) + '</code>' +
                '</div>' +
                (discovery.id
                    ? '<div>' +
                        '<strong class="text-secondary-sm">ID:</strong><br>' +
                        '<code style="font-size: 0.85em; word-break: break-all;">' + escapeHtml(discovery.id) + '</code>' +
                      '</div>'
                    : '') +
            '</div>' +

            (tagsHtml
                ? '<div class="mt-md">' +
                    '<strong class="text-secondary-sm">Tags:</strong>' +
                    '<div class="flex-row-wrap mt-sm" style="gap: 6px;">' + tagsHtml + '</div>' +
                  '</div>'
                : '') +

            ((discovery.severity || discovery.status)
                ? '<div class="flex-row mt-md">' +
                    (discovery.severity ? '<div><strong class="text-secondary-sm">Severity:</strong> ' + escapeHtml(discovery.severity) + '</div>' : '') +
                    (discovery.status ? '<div><strong class="text-secondary-sm">Status:</strong> ' + escapeHtml(discovery.status) + '</div>' : '') +
                  '</div>'
                : '') +

            '<details class="mt-md">' +
                '<summary class="cursor-pointer text-secondary-sm">Raw data</summary>' +
                '<pre class="raw-data-pre">' + escapeHtml(JSON.stringify(filterFn(discovery), null, 2)) + '</pre>' +
            '</details>' +
        '</div>';

        modalTitle.textContent = 'Discovery: ' + typeLabel;
        modalBody.innerHTML = html;
        modal.classList.add('visible');
        document.body.style.overflow = 'hidden';
    }

    // ========================================================================
    // Export
    // ========================================================================

    function exportDiscoveries(format) {
        var cachedDiscoveries = state.get('cachedDiscoveries');
        if (cachedDiscoveries.length === 0) {
            if (typeof showError === 'function') showError('No discoveries to export');
            return;
        }

        var exportData = cachedDiscoveries.map(function (d) {
            return {
                id: d.id || '',
                type: d.type || d.discovery_type || 'note',
                summary: d.summary || '',
                content: d.details || d.content || d.discovery || '',
                agent: d.by || d.agent_id || d._agent_id || '',
                timestamp: d._timestampMs ? new Date(d._timestampMs).toISOString() : ''
            };
        });

        var filename = 'discoveries_' + new Date().toISOString().split('T')[0];

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
    // Public API
    // ========================================================================

    window.DiscoveriesModule = {
        normalizeDiscoveryType: normalizeDiscoveryType,
        formatDiscoveryType: formatDiscoveryType,
        updateDiscoveryFilterInfo: updateDiscoveryFilterInfo,
        updateDiscoveryLegend: updateDiscoveryLegend,
        renderDiscoveriesList: renderDiscoveriesList,
        applyDiscoveryFilters: applyDiscoveryFilters,
        clearDiscoveryFilters: clearDiscoveryFilters,
        showDiscoveryDetail: showDiscoveryDetail,
        exportDiscoveries: exportDiscoveries
    };
})();
