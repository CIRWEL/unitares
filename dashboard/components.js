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

// Export for use in dashboard
if (typeof window !== 'undefined') {
    window.LoadingSkeleton = LoadingSkeleton;
}
