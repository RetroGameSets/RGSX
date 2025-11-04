/**
 * Accessibility Utilities Module
 * Handles keyboard navigation, focus management, and ARIA updates
 */

const A11y = {
    /**
     * Manage focus trap for modals (keep focus within modal)
     */
    trapFocus(element) {
        const focusableElements = element.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        element.addEventListener('keydown', (e) => {
            if (e.key !== 'Tab') return;

            if (e.shiftKey) {
                if (document.activeElement === firstElement) {
                    lastElement.focus();
                    e.preventDefault();
                }
            } else {
                if (document.activeElement === lastElement) {
                    firstElement.focus();
                    e.preventDefault();
                }
            }
        });

        // Set initial focus to first element
        firstElement?.focus();
    },

    /**
     * Restore focus to element after modal closes
     */
    savedFocusElement: null,

    saveFocus() {
        this.savedFocusElement = document.activeElement;
    },

    restoreFocus() {
        if (this.savedFocusElement && this.savedFocusElement.focus) {
            this.savedFocusElement.focus();
        }
    },

    /**
     * Announce changes to screen readers with live regions
     */
    announceToScreenReader(message, priority = 'polite') {
        let liveRegion = document.querySelector(`[role="status"][aria-live="${priority}"]`);
        
        if (!liveRegion) {
            liveRegion = document.createElement('div');
            liveRegion.setAttribute('role', 'status');
            liveRegion.setAttribute('aria-live', priority);
            liveRegion.className = 'sr-only';
            document.body.appendChild(liveRegion);
        }

        liveRegion.textContent = message;
        
        // Clear after announcement
        setTimeout(() => {
            liveRegion.textContent = '';
        }, 3000);
    },

    /**
     * Handle Enter/Space key on clickable elements
     */
    makeKeyboardClickable(element, callback) {
        element.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                callback();
            }
        });
    },

    /**
     * Arrow key navigation for grids
     */
    setupGridNavigation(gridSelector) {
        const grid = document.querySelector(gridSelector);
        if (!grid) return;

        const items = Array.from(grid.children);
        const colCount = Math.ceil(Math.sqrt(items.length));

        items.forEach((item, index) => {
            item.setAttribute('tabindex', index === 0 ? '0' : '-1');

            item.addEventListener('keydown', (e) => {
                let newIndex = index;

                switch (e.key) {
                    case 'ArrowLeft':
                        newIndex = index === 0 ? items.length - 1 : index - 1;
                        e.preventDefault();
                        break;
                    case 'ArrowRight':
                        newIndex = index === items.length - 1 ? 0 : index + 1;
                        e.preventDefault();
                        break;
                    case 'ArrowUp':
                        newIndex = Math.max(0, index - colCount);
                        e.preventDefault();
                        break;
                    case 'ArrowDown':
                        newIndex = Math.min(items.length - 1, index + colCount);
                        e.preventDefault();
                        break;
                    case 'Home':
                        newIndex = 0;
                        e.preventDefault();
                        break;
                    case 'End':
                        newIndex = items.length - 1;
                        e.preventDefault();
                        break;
                    default:
                        return;
                }

                items[index].setAttribute('tabindex', '-1');
                items[newIndex].setAttribute('tabindex', '0');
                items[newIndex].focus();
            });
        });
    },

    /**
     * Update ARIA attributes for dynamic content
     */
    updateAriaLabel(element, label) {
        element.setAttribute('aria-label', label);
    },

    updateAriaLive(element, region = 'polite') {
        element.setAttribute('aria-live', region);
        element.setAttribute('aria-atomic', 'true');
    },

    /**
     * Set loading state with ARIA
     */
    setLoadingState(element, isLoading) {
        if (isLoading) {
            element.setAttribute('aria-busy', 'true');
            element.setAttribute('disabled', 'true');
        } else {
            element.removeAttribute('aria-busy');
            element.removeAttribute('disabled');
        }
    },

    /**
     * Create accessible loading skeleton
     */
    createSkeletonLoader(containerId, itemCount = 6) {
        const container = document.getElementById(containerId);
        if (!container) return;

        container.innerHTML = '';
        for (let i = 0; i < itemCount; i++) {
            const skeleton = document.createElement('div');
            skeleton.className = 'skeleton-card';
            skeleton.setAttribute('aria-hidden', 'true');
            container.appendChild(skeleton);
        }
    },

    /**
     * Remove skeleton loader
     */
    removeSkeletonLoader(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const skeletons = container.querySelectorAll('.skeleton-card');
        skeletons.forEach(s => s.remove());
    }
};

// Export for use in app.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = A11y;
}
