/**
 * HorizontalScrollManager
 * Handles drag-to-scroll, wheel scroll, and arrow navigation for horizontally scrolling containers.
 */
class HorizontalScrollManager {
    /**
     * @param {Object} options 
     * @param {HTMLElement|string} options.wrapper - The outer wrapper element (used for fade classes)
     * @param {HTMLElement|string} options.container - The scrolling container element
     * @param {HTMLElement|string} [options.leftArrow] - The left navigation button
     * @param {HTMLElement|string} [options.rightArrow] - The right navigation button
     * @param {number} [options.scrollStep] - Amount to scroll on arrow click (default 200)
     */
    constructor(options) {
        this.wrapper = typeof options.wrapper === 'string' ? document.getElementById(options.wrapper) : options.wrapper;
        this.container = typeof options.container === 'string' ? document.getElementById(options.container) : options.container;
        this.leftArrow = typeof options.leftArrow === 'string' ? document.getElementById(options.leftArrow) : options.leftArrow;
        this.rightArrow = typeof options.rightArrow === 'string' ? document.getElementById(options.rightArrow) : options.rightArrow;
        this.scrollStep = options.scrollStep || 250;

        if (!this.wrapper || !this.container) return;

        this.isDown = false;
        this.startX = 0;
        this.scrollLeft = 0;

        this.init();
    }

    init() {
        // Drag to Scroll Events
        this.container.addEventListener('mousedown', (e) => {
            this.isDown = true;
            this.container.classList.add('dragging');
            this.startX = e.pageX - this.container.offsetLeft;
            this.scrollLeft = this.container.scrollLeft;
            // Prevent text selection while dragging
            e.preventDefault();
        });

        this.container.addEventListener('mouseleave', () => {
            this.isDown = false;
            this.container.classList.remove('dragging');
        });

        this.container.addEventListener('mouseup', () => {
            this.isDown = false;
            this.container.classList.remove('dragging');
        });

        this.container.addEventListener('mousemove', (e) => {
            if (!this.isDown) return;
            e.preventDefault();
            const x = e.pageX - this.container.offsetLeft;
            const walk = (x - this.startX) * 1.5; // Scroll-fast multiplier
            this.container.scrollLeft = this.scrollLeft - walk;
        });

        // Mouse Wheel Scroll (horizontal translation)
        this.container.addEventListener('wheel', (e) => {
            // Prevent default vertical scrolling to translate to horizontal
            if (e.deltaY !== 0) {
                e.preventDefault();
                this.container.scrollLeft += e.deltaY;
            }
        }, { passive: false });

        // Arrow Navigation
        if (this.leftArrow) {
            this.leftArrow.addEventListener('click', (e) => {
                e.preventDefault();
                this.container.scrollBy({ left: -this.scrollStep, behavior: 'smooth' });
            });
        }
        if (this.rightArrow) {
            this.rightArrow.addEventListener('click', (e) => {
                e.preventDefault();
                this.container.scrollBy({ left: this.scrollStep, behavior: 'smooth' });
            });
        }

        // Keyboard Navigation
        this.container.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                this.container.scrollBy({ left: -this.scrollStep, behavior: 'smooth' });
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                this.container.scrollBy({ left: this.scrollStep, behavior: 'smooth' });
            }
        });

        // Update Visibility on Scroll/Resize
        this.container.addEventListener('scroll', () => this.updateState());
        window.addEventListener('resize', () => this.updateState());

        // Initial state update
        this.updateState();
    }

    updateState() {
        if (!this.container || !this.wrapper) return;

        const maxScroll = Math.max(0, this.container.scrollWidth - this.container.clientWidth);
        const currentScroll = this.container.scrollLeft;
        
        // Use a tiny threshold to prevent rounding errors on high DPI screens
        const threshold = 1; 
        
        const canScrollLeft = currentScroll > threshold;
        const canScrollRight = currentScroll < (maxScroll - threshold);

        // Update wrapper fade classes
        if (canScrollLeft) {
            this.wrapper.classList.add('can-scroll-left');
        } else {
            this.wrapper.classList.remove('can-scroll-left');
        }

        if (canScrollRight) {
            this.wrapper.classList.add('can-scroll-right');
        } else {
            this.wrapper.classList.remove('can-scroll-right');
        }

        // Update arrow visibility
        if (this.leftArrow) {
            this.leftArrow.style.opacity = canScrollLeft ? '1' : '0';
            this.leftArrow.style.pointerEvents = canScrollLeft ? 'auto' : 'none';
        }
        
        if (this.rightArrow) {
            this.rightArrow.style.opacity = canScrollRight ? '1' : '0';
            this.rightArrow.style.pointerEvents = canScrollRight ? 'auto' : 'none';
        }
    }

    refresh() {
        // Force an update (e.g. after dynamic content changes)
        // Add a slight delay to allow DOM to render new children widths
        setTimeout(() => this.updateState(), 50);
    }
}
