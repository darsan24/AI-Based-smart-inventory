/**
 * Smart Inventory AI — Centralized Dependent Filter Manager
 * Production-ready cascading dropdown engine used across all pages.
 *
 * Supports bidirectional filtering:
 *   Brand  → Product Type + Category
 *   Type   → Category + Brand
 *   Category → Type + Brand
 *   Product  → Type + Category + Brand  (direct lookup)
 *
 * Compatible with standard HTML <select> and jQuery Select2 components.
 * Uses jQuery EVENT DELEGATION so handlers survive Select2 destroy/recreate.
 */

class DependentFilterManager {

    /* ═══════════════════════════════════════════════
       CONSTRUCTOR
       ═══════════════════════════════════════════════ */
    constructor(options = {}) {
        this.typeEl     = this._resolveEl(options.typeEl);
        this.categoryEl = this._resolveEl(options.categoryEl);
        this.brandEl    = this._resolveEl(options.brandEl);
        this.productEl  = this._resolveEl(options.productEl);

        this.dataSource = options.dataSource || null;
        this.apiUrl     = options.apiUrl || '/api/filters/dependent';
        this.onChangeCallback = options.onChangeCallback || null;
        this.autoSelectSingle = options.autoSelectSingle !== false;

        this.placeholderType     = options.placeholderType     || 'All Types';
        this.placeholderCategory = options.placeholderCategory || 'All Categories';
        this.placeholderBrand    = options.placeholderBrand    || 'All Brands';
        this.placeholderProduct  = options.placeholderProduct  || 'All Products';

        // Centralized authoritative filter state
        this.filterState = {
            type:      options.initialType     || '',
            category:  options.initialCategory || '',
            brand:     options.initialBrand    || '',
            productId: options.initialProduct  || ''
        };

        // Internal flags
        this._updating     = false;
        this._initialized  = false;
        this._abortCtrl    = null;

        // Cache of the last option sets per dropdown (for skip-if-unchanged)
        this._prevOptions = { type: null, category: null, brand: null, product: null };

        this._init();
    }

    /* ═══════════════════════════════════════════════
       ELEMENT HELPERS
       ═══════════════════════════════════════════════ */
    _resolveEl(t) {
        if (!t) return null;
        if (typeof t === 'string') return document.getElementById(t);
        if (t.jquery) return t[0] || null;
        return t;
    }

    /** Read a <select> value, normalising "All …" placeholders to empty string. */
    _val(el) {
        if (!el) return '';
        const v = (el.value || '').trim();
        if (v === '' || v.toLowerCase() === 'all' ||
            /^all[\s_]/i.test(v)) return '';
        return v;
    }

    /* ═══════════════════════════════════════════════
       INITIALISATION
       ═══════════════════════════════════════════════ */
    _init() {
        const self = this;

        // ── SINGLE event path: jQuery delegated select2 events ──────────
        // Delegation binds to `document`, not the element itself, so it is
        // immune to Select2 destroy/recreate cycles.  No native
        // addEventListener is used, eliminating duplicate processing.
        if (window.jQuery) {
            const bind = (el, fn) => {
                if (!el || !el.id) return;
                window.jQuery(document).on(
                    'select2:select.dfm select2:clear.dfm',
                    '#' + el.id,
                    function () { if (!self._updating) fn.call(self); }
                );
            };
            bind(this.typeEl,     this._onTypeChange);
            bind(this.categoryEl, this._onCategoryChange);
            bind(this.brandEl,    this._onBrandChange);
            bind(this.productEl,  this._onProductChange);
        } else {
            // Fallback: native change events (for non-Select2 environments)
            const bindNative = (el, fn) => {
                if (!el) return;
                el.addEventListener('change', () => {
                    if (!self._updating) fn.call(self);
                });
            };
            bindNative(this.typeEl,     this._onTypeChange);
            bindNative(this.categoryEl, this._onCategoryChange);
            bindNative(this.brandEl,    this._onBrandChange);
            bindNative(this.productEl,  this._onProductChange);
        }

        // Seed filterState from DOM if no initial values were supplied
        if (!this.filterState.type)      this.filterState.type      = this._val(this.typeEl);
        if (!this.filterState.category)  this.filterState.category  = this._val(this.categoryEl);
        if (!this.filterState.brand)     this.filterState.brand     = this._val(this.brandEl);
        if (!this.filterState.productId) this.filterState.productId = this._val(this.productEl);

        this._process('init', true);
    }

    /* ═══════════════════════════════════════════════
       EVENT HANDLERS (one per dropdown)
       ═══════════════════════════════════════════════ */
    _onTypeChange() {
        this.filterState.type = this._val(this.typeEl);
        this.filterState.productId = '';
        this._process('type');
    }

    _onCategoryChange() {
        this.filterState.category = this._val(this.categoryEl);
        this.filterState.productId = '';
        this._process('category');
    }

    _onBrandChange() {
        this.filterState.brand = this._val(this.brandEl);
        this.filterState.productId = '';
        this._process('brand');
    }

    _onProductChange() {
        this.filterState.productId = this._val(this.productEl);
        this._process('product');
    }

    /* ═══════════════════════════════════════════════
       MAIN PROCESSING ROUTER
       ═══════════════════════════════════════════════ */
    _process(trigger, isInitial = false) {
        if (this.dataSource && Array.isArray(this.dataSource) && this.dataSource.length > 0) {
            const result = this._compute(this.filterState, trigger);
            this._apply(result, trigger, isInitial);
        } else {
            this._fetch(trigger, isInitial);
        }
    }

    /* ═══════════════════════════════════════════════
       LOCAL (client-side) COMPUTATION
       Builds valid option lists + inferences from
       the in-memory product dataset.
       ═══════════════════════════════════════════════ */
    _compute({ type, category, brand, productId }, trigger) {
        const products = this.dataSource;
        const norm = s => (s || '').trim().toLowerCase();

        const allTypes      = [...new Set(products.map(p => p.product_type).filter(Boolean))].sort();
        const allCategories = [...new Set(products.map(p => p.category).filter(Boolean))].sort();
        const allBrands     = [...new Set(products.map(p => p.brand).filter(Boolean))].sort();

        let at = type, ac = category, ab = brand;
        const inferred = {};

        // 1. Product ID direct lookup ─────────────────────────────────────
        if (productId) {
            const p = products.find(x =>
                String(x.id) === String(productId) ||
                x.product_id_str === String(productId) ||
                x.name === String(productId));
            if (p) {
                at = p.product_type; ac = p.category; ab = p.brand;
                inferred.product_type = at;
                inferred.category     = ac;
                inferred.brand        = ab;
            }
        }

        // 2. Category → infer Type ────────────────────────────────────────
        if (ac) {
            const catTypes = [...new Set(products
                .filter(p => norm(p.category) === norm(ac))
                .map(p => p.product_type).filter(Boolean))];
            if (catTypes.length === 1) {
                at = catTypes[0];
                inferred.product_type = at;
            } else if (at && !catTypes.map(norm).includes(norm(at))) {
                at = '';  // incompatible type → clear
            }
        }

        // 3. Brand → infer Type ───────────────────────────────────────────
        if (ab) {
            const brandTypes = [...new Set(products
                .filter(p => norm(p.brand) === norm(ab))
                .map(p => p.product_type).filter(Boolean))].sort();
            if (brandTypes.length === 1) {
                at = brandTypes[0];
                inferred.product_type = at;
            } else if (at && !brandTypes.map(norm).includes(norm(at))) {
                at = '';  // incompatible type → clear
            }
        }

        // 4. Valid Types (filtered by brand + category) ───────────────────
        let validTypes = allTypes;
        if (ab || ac) {
            validTypes = [...new Set(products.filter(p => {
                const mb = !ab || norm(p.brand) === norm(ab);
                const mc = !ac || norm(p.category) === norm(ac);
                return mb && mc;
            }).map(p => p.product_type).filter(Boolean))].sort();
        }

        // 5. Valid Categories (filtered by type + brand) ──────────────────
        let validCats = allCategories;
        if (at || ab) {
            validCats = [...new Set(products.filter(p => {
                const mt = !at || norm(p.product_type) === norm(at);
                const mb = !ab || norm(p.brand) === norm(ab);
                return mt && mb;
            }).map(p => p.category).filter(Boolean))].sort();
        }
        if (validCats.length === 1 && (ab || at)) {
            inferred.category = validCats[0];
        }

        // 6. Valid Brands (filtered by type + category) ───────────────────
        let validBrands = allBrands;
        if (at || ac) {
            validBrands = [...new Set(products.filter(p => {
                const mt = !at || norm(p.product_type) === norm(at);
                const mc = !ac || norm(p.category) === norm(ac);
                return mt && mc;
            }).map(p => p.brand).filter(Boolean))].sort();
        }
        if (validBrands.length === 1 && (at || ac)) {
            inferred.brand = validBrands[0];
        }

        // 7. Matched products ─────────────────────────────────────────────
        const matched = products.filter(p => {
            const mt = !at || norm(p.product_type) === norm(at);
            const mc = !ac || norm(p.category) === norm(ac);
            const mb = !ab || norm(p.brand) === norm(ab);
            return mt && mc && mb;
        });

        return {
            product_types:     validTypes,
            categories:        validCats,
            brands:            validBrands,
            products:          matched,
            product_names:     matched.map(p => p.name),
            all_product_types: allTypes,
            all_categories:    allCategories,
            all_brands:        allBrands,
            inferred,
            selected: { product_type: at, category: ac, brand: ab }
        };
    }

    /* ═══════════════════════════════════════════════
       SERVER-SIDE (API) COMPUTATION
       Used when no local dataSource is available.
       ═══════════════════════════════════════════════ */
    async _fetch(trigger, isInitial) {
        if (this._abortCtrl) this._abortCtrl.abort();
        this._abortCtrl = new AbortController();

        try {
            const qs = new URLSearchParams();
            if (this.filterState.type)      qs.append('product_type', this.filterState.type);
            if (this.filterState.category)  qs.append('category',     this.filterState.category);
            if (this.filterState.brand)     qs.append('brand',        this.filterState.brand);
            if (this.filterState.productId) qs.append('product_id',   this.filterState.productId);
            if (trigger) qs.append('trigger', trigger);

            const res = await fetch(`${this.apiUrl}?${qs}`, { signal: this._abortCtrl.signal });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this._apply(data, trigger, isInitial);
        } catch (e) {
            if (e.name !== 'AbortError') {
                console.error('DependentFilterManager fetch error:', e);
            }
        }
    }

    /* ═══════════════════════════════════════════════
       APPLY RESULTS → Update filter state + DOM
       ═══════════════════════════════════════════════ */
    _apply(data, trigger, isInitial) {
        this._updating = true;

        const inferred = data.inferred || {};
        const selected = data.selected || {};

        // ── Determine target values ──────────────────────────────────────
        let tgtType  = selected.product_type !== undefined ? selected.product_type : this.filterState.type;
        let tgtCat   = selected.category     !== undefined ? selected.category     : this.filterState.category;
        let tgtBrand = selected.brand        !== undefined ? selected.brand        : this.filterState.brand;

        // Apply inferences
        if (inferred.product_type) tgtType  = inferred.product_type;
        if (inferred.category)     tgtCat   = inferred.category;
        if (inferred.brand)        tgtBrand = inferred.brand;

        // Auto-select when exactly 1 option exists and a constraining filter is active
        if (!tgtType && this.autoSelectSingle && data.product_types && data.product_types.length === 1
            && (this.filterState.brand || this.filterState.category)) {
            tgtType = data.product_types[0];
        }
        if (!tgtCat && this.autoSelectSingle && data.categories && data.categories.length === 1
            && (this.filterState.brand || tgtType)) {
            tgtCat = data.categories[0];
        }
        if (!tgtBrand && this.autoSelectSingle && data.brands && data.brands.length === 1
            && (tgtType || tgtCat)) {
            tgtBrand = data.brands[0];
        }

        // Validate selections against available options
        const includes = (arr, v) => arr && v && arr.map(x => x.toLowerCase()).includes(v.toLowerCase());
        if (tgtType  && data.product_types && !includes(data.product_types, tgtType))  tgtType  = '';
        if (tgtCat   && data.categories    && !includes(data.categories,    tgtCat))   tgtCat   = '';
        if (tgtBrand && data.brands        && !includes(data.brands,        tgtBrand)) tgtBrand = '';

        // ── Determine which options to show ──────────────────────────────
        const hasConstraint = !!(this.filterState.brand || this.filterState.category || tgtBrand || tgtCat);
        const typeOpts = hasConstraint && data.product_types && data.product_types.length > 0
            ? data.product_types
            : (data.all_product_types || data.product_types || []);

        const hasTBConstraint = !!(tgtType || this.filterState.brand || tgtBrand || this.filterState.type);
        const catOpts = hasTBConstraint && data.categories && data.categories.length > 0
            ? data.categories
            : (data.all_categories || data.categories || []);

        const hasTCConstraint = !!(tgtType || tgtCat || this.filterState.type || this.filterState.category);
        const brandOpts = hasTCConstraint && data.brands && data.brands.length > 0
            ? data.brands
            : (data.all_brands || data.brands || []);

        // ── Update centralized state ─────────────────────────────────────
        this.filterState.type     = tgtType;
        this.filterState.category = tgtCat;
        this.filterState.brand    = tgtBrand;

        // ── Sync dropdowns (skip if unchanged) ───────────────────────────
        this._syncDropdown(this.typeEl,     typeOpts,  tgtType,  this.placeholderType,     'type');
        this._syncDropdown(this.categoryEl, catOpts,   tgtCat,   this.placeholderCategory, 'category');
        this._syncDropdown(this.brandEl,    brandOpts, tgtBrand, this.placeholderBrand,    'brand');

        if (this.productEl) {
            const prodItems = data.products || data.product_names || [];
            this._syncProductDropdown(this.productEl, prodItems, this.filterState.productId);
        }

        this._updating    = false;
        this._initialized = true;

        // Fire callback AFTER _updating is cleared
        if (this.onChangeCallback) {
            try { this.onChangeCallback(this, trigger); } catch (_) { /* silent */ }
        }
    }

    /* ═══════════════════════════════════════════════
       DROPDOWN SYNC  (optimised: skip if unchanged)
       ═══════════════════════════════════════════════ */
    _syncDropdown(el, items, selectedVal, placeholder, cacheKey) {
        if (!el) return;
        const newItems = (items || []).filter(Boolean);

        // Build a fingerprint of current <option> values (skip placeholder at [0])
        const curOpts = [];
        for (let i = 1; i < el.options.length; i++) curOpts.push(el.options[i].value);
        const curVal = el.value || '';

        const optsMatch = curOpts.length === newItems.length && curOpts.every((v, i) => v === newItems[i]);
        const valMatch  = (curVal === (selectedVal || ''));

        if (optsMatch && valMatch) return;  // nothing to do

        // ── Rebuild <option> elements ────────────────────────────────────
        el.innerHTML = '';
        const ph = document.createElement('option');
        ph.value = '';
        ph.textContent = placeholder;
        el.appendChild(ph);

        let matched = false;
        newItems.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item;
            opt.textContent = item;
            if (selectedVal && item.toLowerCase() === selectedVal.toLowerCase()) {
                opt.selected = true;
                matched = true;
            }
            el.appendChild(opt);
        });
        if (!matched) el.value = '';

        // ── Refresh Select2 visual ───────────────────────────────────────
        this._refreshSelect2(el);
    }

    /** Sync product dropdown (supports object items with rich metadata). */
    _syncProductDropdown(el, items, selectedVal) {
        if (!el) return;
        const placeholder = this.placeholderProduct;

        el.innerHTML = '';
        const ph = document.createElement('option');
        ph.value = '';
        ph.textContent = placeholder;
        el.appendChild(ph);

        let matched = false;
        (items || []).forEach(item => {
            if (!item) return;
            const opt = document.createElement('option');
            if (typeof item === 'object') {
                opt.value = item.id || item.product_id_str || '';
                opt.textContent = `${item.product_id_str || ''} - ${item.name || ''}`;
                opt.setAttribute('data-pid',      item.product_id_str || '');
                opt.setAttribute('data-name',     item.name     || '');
                opt.setAttribute('data-brand',    item.brand    || '');
                opt.setAttribute('data-category', item.category || '');
                opt.setAttribute('data-type',     item.product_type || '');
                opt.setAttribute('data-stock',    item.current_stock !== undefined ? item.current_stock : '');
                opt.setAttribute('data-price',    item.price !== undefined ? item.price : '');
                if (selectedVal && (String(item.id) === String(selectedVal) ||
                    item.product_id_str === selectedVal || item.name === selectedVal)) {
                    opt.selected = true; matched = true;
                }
            } else {
                opt.value = item;
                opt.textContent = item;
                if (selectedVal && String(item).toLowerCase() === String(selectedVal).toLowerCase()) {
                    opt.selected = true; matched = true;
                }
            }
            el.appendChild(opt);
        });
        if (!matched) el.value = '';

        this._refreshSelect2(el);
    }

    /* ═══════════════════════════════════════════════
       SELECT2 REFRESH
       Destroy + re-init ONLY when called (i.e. when
       options actually changed).
       ═══════════════════════════════════════════════ */
    _refreshSelect2(el) {
        if (!el || !window.jQuery) return;
        const $el = window.jQuery(el);
        const savedVal = el.value;

        // Destroy existing instance
        if ($el.data('select2') || $el.hasClass('select2-hidden-accessible')) {
            try { $el.select2('destroy'); } catch (_) {
                // Manual fallback cleanup
                $el.removeData('select2').removeClass('select2-hidden-accessible');
                const next = el.nextElementSibling;
                if (next && next.classList && next.classList.contains('select2-container')) next.remove();
            }
        }

        // Restore value (destroy can reset it)
        el.value = savedVal;

        // Re-initialise
        const cfg = { width: '100%', dropdownAutoWidth: true, dropdownPosition: 'below' };
        const modal = $el.closest('.modal');
        if (modal.length) cfg.dropdownParent = modal;
        if ($el.hasClass('select-product-rich') && typeof formatProductOption === 'function') {
            cfg.templateResult    = formatProductOption;
            cfg.templateSelection = formatProductSelection;
            cfg.escapeMarkup      = m => m;
        }

        try {
            $el.select2(cfg);
            // Force Select2 to sync its displayed text with the <select> value
            $el.val(savedVal).trigger('change.select2');
        } catch (_) { /* silent */ }
    }

    /* ═══════════════════════════════════════════════
       PUBLIC API
       ═══════════════════════════════════════════════ */

    /** Reset all filters to "All". */
    reset() {
        this.filterState = { type: '', category: '', brand: '', productId: '' };
        this._process('reset');
    }

    /** Read-only access to the current filter state. */
    getState() {
        return Object.assign({}, this.filterState);
    }

    /** Expose isInitialized flag. */
    get isInitialized() { return this._initialized; }
}

// Expose globally for cross-template access
window.DependentFilterManager = DependentFilterManager;
