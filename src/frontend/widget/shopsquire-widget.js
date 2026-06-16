class ShopSquireWidget extends HTMLElement {
  constructor() {
    super();
    this.shadow = this.attachShadow({ mode: 'open' });
    this.state = {
      open: false,
      stage: 'initial',
      results: [],
      cart: [],
      accessories: [
        { id: 'acc-usb-hub', sku: 'ACC-USB-HUB', name: 'USB-C Hub', price: 49 },
        { id: 'acc-sleeve', sku: 'ACC-SLEEVE', name: 'Laptop Sleeve', price: 29 },
        { id: 'acc-mouse', sku: 'ACC-MOUSE', name: 'Wireless Mouse', price: 39 },
      ],
      pendingDiscount: null,
      comparison: null,
      lastQuery: '',
      warnings: [],
      user: { name: 'Guest', tier: 'guest', signedIn: false },
      orders: [],
      orderHistoryOffset: 0,
      orderHistoryHasMore: false,
      orderHistoryLoading: false,
      traceEvents: [],
      decisionMeta: null,
      thinking: false,
      lastQueryAt: null,
      demoMode: false,
      speechSupported: false,
      speechListening: false,
      viewMode: 'grid',
      bannerMessage: ''
    };
    this.config = { apiBase: '', uid: 'demo-user', user: this.state.user, apiKey: '' };
    this.orderHistoryLimit = 5;
    this.demoRunning = false;
    this.speechRecog = null;
    this.tracePoller = null;
    this.traceEventSource = null;
    this.decisionModal = null;
    this.decisionModalBody = null;
    this.state.highlightRec = null;
  }

  connectedCallback() {
    try { this.style.display = 'block'; } catch (e) {}
    const apiBase = this.getAttribute('data-api-base');
    const uid = this.getAttribute('data-uid');
    const apiKey = this.getAttribute('data-api-key');
    const userName = this.getAttribute('data-user-name');
    const userTier = this.getAttribute('data-user-tier');
    const signedIn = this.getAttribute('data-signed-in');
    this.setConfig({
      apiBase: apiBase || '',
      uid: uid || this.config.uid,
      apiKey: apiKey || this.config.apiKey,
      user: {
        name: userName || 'Guest',
        tier: userTier || 'guest',
        signedIn: signedIn === 'true',
      },
    });
    try {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      this.state.speechSupported = Boolean(SR);
    } catch (e) {
      this.state.speechSupported = false;
    }
    this.render();
    this.fetchCart().then((cart) => {
      this.applyCartResponse(cart);
      this.render();
    }).catch(() => {});
    // Inject a global Decision Trace gear for tests and quick ops access
    try { this._injectDecisionGear(); } catch (e) {}
  }

  disconnectedCallback() {
    this.stopTraceStreaming();
  }

  _injectDecisionGear() {
    if (document.querySelector('[data-test="decision-gear"]')) return;
    const btn = document.createElement('button');
    btn.setAttribute('data-test', 'decision-gear');
    btn.id = 'decision-gear';
    btn.setAttribute('aria-label', 'Open decision trace');
    btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M11.3 1.046a1 1 0 00-2.6 0l-.233.511a1 1 0 01-.81.63l-.566.064a1 1 0 00-.67.402l-.4.545a1 1 0 01-.88.455l-.566.06a1 1 0 00-.62.31l-.426.426a1 1 0 00-.29.65l.03.57a1 1 0 01-.37.86l-.454.345a1 1 0 000 1.732l.454.345a1 1 0 01.37.86l-.03.57a1 1 0 00.29.65l.426.426c.18.18.4.3.62.31l.566.06a1 1 0 01.88.455l.4.545c.16.22.41.37.67.402l.566.064a1 1 0 01.81.63l.233.511a1 1 0 002 0l.233-.511a1 1 0 01.81-.63l.566-.064a1 1 0 00.67-.402l.4-.545a1 1 0 01.88-.455l.566-.06c.22-.02.44-.13.62-.31l.426-.426a1 1 0 00.29-.65l-.03-.57a1 1 0 01.37-.86l.454-.345a1 1 0 000-1.732l-.454-.345a1 1 0 01-.37-.86l.03-.57a1 1 0 00-.29-.65l-.426-.426a1 1 0 00-.62-.31l-.566-.06a1 1 0 01-.88-.455l-.4-.545a1 1 0 00-.67-.402l-.566-.064a1 1 0 01-.81-.63L11.3 1.046zM10 13a3 3 0 110-6 3 3 0 010 6z" clip-rule="evenodd"></path></svg>`;
    btn.style.position = 'fixed';
    btn.style.top = '12px';
    btn.style.left = '12px';
    btn.style.zIndex = '999999';
    btn.style.background = '#374151';
    btn.style.color = '#fff';
    btn.style.border = 'none';
    btn.style.padding = '8px 10px';
    btn.style.borderRadius = '10px';
    btn.style.cursor = 'pointer';
    const modal = document.createElement('div');
    modal.id = 'decision-modal';
    modal.style.display = 'none';
    modal.style.position = 'fixed';
    modal.style.inset = '0';
    modal.style.background = 'rgba(0,0,0,.4)';
    modal.style.zIndex = '999999';
    modal.innerHTML = `
      <div style="max-width:640px;margin:10% auto;background:#fff;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.25);">
        <div style="padding:14px 16px;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;justify-content:space-between;">
          <div style="font-weight:700;">Decision Trace</div>
          <button id="decision-close" style="border:none;background:#fff;padding:6px 10px;border:1px solid #e5e7eb;border-radius:8px;cursor:pointer;">Close</button>
        </div>
        <div style="padding:12px;border-bottom:1px solid #f3f4f6;display:flex;gap:8px;align-items:center;">
          <button id="decision-summary-btn" data-test="decision-summary-btn" style="padding:6px 10px;border-radius:8px;border:1px solid #e5e7eb;background:#fff;cursor:pointer;font-weight:600;">Summary</button>
          <button id="decision-trace-btn" data-test="decision-trace-btn" style="padding:6px 10px;border-radius:8px;border:1px solid #e5e7eb;background:transparent;cursor:pointer;">Live Trace</button>
        </div>
        <div id="decision-modal-body" style="padding:16px;">
          <div id="decision-summary" data-test="decision-summary" style="padding-bottom:12px;"></div>
          <div id="decision-trace" data-test="decision-trace" style="display:none;padding-top:8px;border-top:1px solid #f3f4f6;"></div>
        </div>
      </div>`;
    btn.addEventListener('click', () => { modal.style.display = 'block'; });
    modal.addEventListener('click', (e) => {
      const close = e.target.id === 'decision-close' || e.target === modal;
      if (close) modal.style.display = 'none';
    });
    document.body.appendChild(btn);
    document.body.appendChild(modal);
    this.decisionModal = modal;
    this.decisionModalBody = modal.querySelector('#decision-modal-body');
    // Wire simple tab behavior for tests and UX
    try {
      const sBtn = modal.querySelector('#decision-summary-btn');
      const tBtn = modal.querySelector('#decision-trace-btn');
      const sPanel = modal.querySelector('#decision-summary');
      const tPanel = modal.querySelector('#decision-trace');
      if (sBtn && tBtn && sPanel && tPanel) {
        sBtn.addEventListener('click', () => { sPanel.style.display = 'block'; tPanel.style.display = 'none'; sBtn.style.background = '#fff'; tBtn.style.background = 'transparent'; });
        tBtn.addEventListener('click', () => { sPanel.style.display = 'none'; tPanel.style.display = 'block'; tBtn.style.background = '#fff'; sBtn.style.background = 'transparent'; });
      }
    } catch (e) {}
  }

  startSpeech() {
    if (!this.state.speechSupported) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    try {
      if (this.speechRecog) {
        this.speechRecog.stop();
      }
    } catch (e) {}
    const recog = new SR();
    recog.lang = 'en-US';
    recog.interimResults = false;
    recog.maxAlternatives = 1;
    this.state.speechListening = true;
    this.render();
    recog.onresult = (event) => {
      const transcript = event.results && event.results[0] && event.results[0][0]
        ? event.results[0][0].transcript
        : '';
      const input = this.shadow.getElementById('query');
      if (input && transcript) input.value = transcript;
      this.state.speechListening = false;
      this.render();
      if (transcript) this.handleSubmit(transcript);
    };
    recog.onerror = () => {
      this.state.speechListening = false;
      this.render();
    };
    recog.onend = () => {
      this.state.speechListening = false;
      this.render();
    };
    this.speechRecog = recog;
    recog.start();
  }

  runDemoSequence() {
    if (this.demoRunning) return;
    this.demoRunning = true;
    const queries = [
      'Best 14 inch laptops under $1800 for video editing',
      'Show options with 2-day shipping and 16GB RAM',
    ];
    const run = (idx) => {
      if (!this.state.demoMode) {
        this.demoRunning = false;
        return;
      }
      const q = queries[idx];
      const input = this.shadow.getElementById('query');
      if (input) input.value = q;
      this.handleSubmit(q);
      if (idx < queries.length - 1) {
        setTimeout(() => run(idx + 1), 3500);
      } else {
        setTimeout(() => {
          window.open('/docs', '_blank');
          this.demoRunning = false;
        }, 3500);
      }
    };
    run(0);
  }

  normalizeInput(text) {
    const normalized = text.normalize('NFKC');
    const controlPattern = /[\u200B-\u200F\u202A-\u202E\u2066-\u2069\u00AD]/g;
    const found = normalized.match(controlPattern) || [];
    const warnings = [];
    if (found.length) warnings.push('Hidden characters removed for safety.');
    return { normalized: normalized.replace(controlPattern, ''), warnings };
  }

  isDiscountAttempt(text) {
    const t = text.toLowerCase();
    return /discount|\bapply\b|\bprice\b|\bpercent\b|%/.test(t);
  }

  parseConstraints(query) {
    const topNMatch = query.match(/top\s*(\d+)/i);
    const topN = topNMatch ? parseInt(topNMatch[1], 10) : 5;
    const rangeMatch = query.match(/(\$?\s*(\d{3,5}))\s*(to|-|and)\s*(\$?\s*(\d{3,5}))/i);
    const minPrice = rangeMatch ? parseInt(rangeMatch[2], 10) : 0;
    const maxPrice = rangeMatch ? parseInt(rangeMatch[5], 10) : 100000;
    const ramMatch = query.match(/(\d+)\s*gb\s*ram/i);
    const minRam = ramMatch ? parseInt(ramMatch[1], 10) : 0;
    return { topN, minPrice, maxPrice, minRam };
  }

  recommendProducts({ topN, minPrice, maxPrice, minRam }) {
    const all = [
      { id: 'thinkpad-x1', name: 'Lenovo ThinkPad X1 Carbon', price: 1899, rating: 4.9, ram: 16, storage: '1TB', battery: '18h', cpu: 'Intel Core i7', display: '14" OLED' },
      { id: 'dell-xps-13-plus', name: 'Dell XPS 13 Plus', price: 1299, rating: 4.4, ram: 16, storage: '512GB', battery: '12h', cpu: 'Intel Core i5', display: '13.4" FHD' },
      { id: 'macbook-pro-14', name: 'Apple MacBook Pro 14', price: 2099, rating: 4.6, ram: 16, storage: '512GB', battery: '17h', cpu: 'Apple M4', display: '14" Liquid Retina' },
      { id: 'hp-elitebook-840', name: 'HP EliteBook 840', price: 1499, rating: 4.3, ram: 16, storage: '512GB', battery: '14h', cpu: 'Intel Core i5', display: '14" FHD' },
      { id: 'asus-zenbook-14', name: 'ASUS ZenBook 14', price: 1249, rating: 4.2, ram: 16, storage: '512GB', battery: '13h', cpu: 'Intel Core i5', display: '14" FHD' },
      { id: 'acer-swift', name: 'Acer Swift 5', price: 1199, rating: 4.1, ram: 16, storage: '512GB', battery: '12h', cpu: 'Intel Core i5', display: '14" FHD' },
      { id: 'ms-surface', name: 'Microsoft Surface Laptop', price: 1599, rating: 4.0, ram: 16, storage: '512GB', battery: '13h', cpu: 'Intel Core i5', display: '13.5" PixelSense' },
    ];
    const filtered = all.filter(p => p.price >= minPrice && p.price <= maxPrice && p.ram >= minRam);
    const ranked = filtered.sort((a, b) => b.rating - a.rating || a.price - b.price);
    return ranked.slice(0, topN).map(p => ({
      ...p,
      reasons: this.buildReasons(p, { minRam, minPrice, maxPrice })
    }));
  }

  async fetchRecommend(query) {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/recommend/suggest?uid=${encodeURIComponent(this.config.uid)}&query=${encodeURIComponent(query)}`;
    const headers = {};
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    const resp = await fetch(url, { method: 'GET', headers, signal: controller.signal });
    clearTimeout(timer);
    if (!resp.ok) throw new Error(`Recommend failed ${resp.status}`);
    const data = await resp.json();
    return data;
  }

  async fetchCheckoutUpsell(skus) {
    const base = this.config.apiBase || window.location.origin;
    const cartSkus = (skus || []).filter(Boolean).join(',');
    const url = `${base.replace(/\/$/, '')}/api/v1/recommend/checkout_upsell?uid=${encodeURIComponent(this.config.uid)}&cart_skus=${encodeURIComponent(cartSkus)}&limit=3`;
    const headers = {};
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const resp = await fetch(url, { method: 'GET', headers });
    if (!resp.ok) throw new Error(`Checkout upsell failed ${resp.status}`);
    return resp.json();
  }

  async logRecommendInteraction({ sku, action, surface = 'checkout_upsell', context = {} }) {
    if (!sku || !action) return;
    try {
      const base = this.config.apiBase || window.location.origin;
      const url = `${base.replace(/\/$/, '')}/api/v1/recommend/interaction`;
      const headers = { 'Content-Type': 'application/json' };
      if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
      await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          uid: this.config.uid,
          sku,
          action,
          surface,
          trace_id: this.state.decisionMeta?.trace_id || null,
          context,
        }),
      });
    } catch (e) {
      // best-effort telemetry
    }
  }

  async fetchDecisionTrace(traceId) {
    if (!traceId) return null;
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/decisions/${encodeURIComponent(traceId)}`;
    const headers = {};
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    try {
      const resp = await fetch(url, { method: 'GET', headers });
      if (!resp.ok) return null;
      return resp.json();
    } catch (e) {
      return null;
    }
  }

  startTraceStreaming(traceId) {
    this.stopTraceStreaming();
    if (!traceId) return;
    // Use centralized TraceClient to manage EventSource + polling
    try {
      if (!window.ShopSquireTraceClient) {
        // Minimal in-page TraceClient
        class TraceClient {
          constructor() { this.es = null; this.poller = null; }
          start(url, onMessage, pollFn, pollInterval = 2000) {
            try { this.stop(); } catch (e) {}
            try {
              this.es = new EventSource(url);
              this.es.onmessage = (evt) => { try { onMessage(JSON.parse(evt.data || '[]')); } catch (e) {} };
            } catch (e) {}
            if (pollFn) this.poller = setInterval(async () => { try { await pollFn(); } catch (e) {} }, pollInterval);
          }
          stop() { try { if (this.es) this.es.close(); } catch (e) {} this.es = null; if (this.poller) clearInterval(this.poller); this.poller = null; }
        }
        window.ShopSquireTraceClient = new TraceClient();
      }
      const base = this.config.apiBase || window.location.origin;
      const apiKey = this.config.apiKey ? `?api_key=${encodeURIComponent(this.config.apiKey)}` : '';
      const url = `${base.replace(/\/$/, '')}/api/v1/decisions/${encodeURIComponent(traceId)}/events/stream${apiKey}`;
      const poll = async () => {
        const latest = await this.fetchDecisionTrace(traceId);
        if (latest) {
          this.state.decisionMeta = { ...(this.state.decisionMeta || {}), ...latest };
          this.updateDecisionModal();
        }
      };
      window.ShopSquireTraceClient.start(url, (items) => { if (Array.isArray(items)) this.mergeTraceEvents(items); }, poll, 2000);
    } catch (e) {}
  }

  stopTraceStreaming() {
    try { if (window.ShopSquireTraceClient) window.ShopSquireTraceClient.stop(); } catch (e) {}
  }

  mergeTraceEvents(items) {
    const existing = new Set((this.state.traceEvents || []).map(e => e.id));
    const mapped = items.map(i => ({
      id: i.id || `${i.event_type}-${i.created_at}`,
      time: i.created_at,
      event_type: i.event_type,
      source_id: i.source_id,
      target_id: i.target_id,
      payload: i.payload || {},
    }));
    const merged = [...mapped.filter(m => !existing.has(m.id)), ...(this.state.traceEvents || [])];
    this.state.traceEvents = merged.slice(0, 25);
    this.updateDecisionModal();
    this.render();
  }

  async fetchLatestDecision() {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/decisions/latest?uid=${encodeURIComponent(this.config.uid)}`;
    const headers = {};
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const resp = await fetch(url, { method: 'GET', headers });
    if (!resp.ok) return null;
    return resp.json();
  }
  async fetchCart() {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/cart?uid=${encodeURIComponent(this.config.uid)}`;
    const headers = {};
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const resp = await fetch(url, { method: 'GET', headers });
    if (!resp.ok) throw new Error(`Cart fetch failed ${resp.status}`);
    return resp.json();
  }

  async addCartItem(sku, quantity = 1) {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/cart/items`;
    const headers = { 'Content-Type': 'application/json' };
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const payload = { uid: this.config.uid, sku, quantity };
    const resp = await fetch(url, { method: 'POST', headers, body: JSON.stringify(payload) });
    if (!resp.ok) throw new Error(`Cart add failed ${resp.status}`);
    return resp.json();
  }

  async replaceCart(items) {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/cart/items`;
    const headers = { 'Content-Type': 'application/json' };
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const payload = { uid: this.config.uid, items };
    const resp = await fetch(url, { method: 'PUT', headers, body: JSON.stringify(payload) });
    if (!resp.ok) throw new Error(`Cart update failed ${resp.status}`);
    return resp.json();
  }

  async removeCartItem(sku) {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/cart/items/${encodeURIComponent(sku)}?uid=${encodeURIComponent(this.config.uid)}`;
    const headers = {};
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const resp = await fetch(url, { method: 'DELETE', headers });
    if (!resp.ok) throw new Error(`Cart remove failed ${resp.status}`);
    return resp.json();
  }

  async createOrder() {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/orders/create`;
    const payload = {
      uid: this.config.uid,
      items: this.state.cart.map((i) => ({ sku: i.sku || i.id, quantity: i.qty })),
    };
    const headers = { 'Content-Type': 'application/json' };
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const resp = await fetch(url, { method: 'POST', headers, body: JSON.stringify(payload) });
    if (!resp.ok) throw new Error(`Order failed ${resp.status}`);
    return resp.json();
  }

  async fetchOrderHistory(offset = 0, limit = 5) {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/api/v1/orders/history?uid=${encodeURIComponent(this.config.uid)}&limit=${limit}&offset=${offset}`;
    const headers = {};
    if (this.config.apiKey) headers['x-api-key'] = this.config.apiKey;
    const resp = await fetch(url, { method: 'GET', headers });
    if (!resp.ok) throw new Error(`History failed ${resp.status}`);
    return resp.json();
  }

  buildReasons(p, constraints) {
    const reasons = [];
    if (p.ram >= constraints.minRam) reasons.push('Meets RAM requirement');
    if (p.price >= constraints.minPrice && p.price <= constraints.maxPrice) reasons.push('Within budget range');
    if (parseInt(p.battery) >= 12) reasons.push('Battery 12h+');
    if (p.rating >= 4.5) reasons.push('High rating');
    return reasons;
  }

  applyCartResponse(cart) {
    const items = (cart.items || []).map(i => ({
      id: i.sku,
      sku: i.sku,
      name: i.name || i.sku,
      price: Math.round((i.price_cents || 0) / 100),
      qty: i.quantity || 1
    }));
    this.state.cart = items;
    const count = items.reduce((sum, i) => sum + (i.qty || 0), 0);
    try { localStorage.setItem('cart_count', String(count)); } catch (e) {}
  }

  addToCart(product) {
    const sku = product.sku || product.id;
    this.addCartItem(sku, 1).then((cart) => {
      this.applyCartResponse(cart);
      this.render();
    }).catch(() => {
      const existing = this.state.cart.find(i => i.id === product.id);
      if (existing) existing.qty += 1; else this.state.cart.push({ ...product, qty: 1 });
      this.render();
    });
  }

  removeFromCart(id) {
    this.removeCartItem(id).then((cart) => {
      this.applyCartResponse(cart);
      this.render();
    }).catch(() => {
      this.state.cart = this.state.cart.filter(i => i.id !== id);
      this.render();
    });
  }

  updateQty(id, qty) {
    const next = this.state.cart.map(i => (i.id === id ? { ...i, qty: Math.max(1, qty) } : i));
    const payload = next.map(i => ({ sku: i.sku || i.id, quantity: i.qty }));
    this.replaceCart(payload).then((cart) => {
      this.applyCartResponse(cart);
      this.render();
    }).catch(() => {
      const item = this.state.cart.find(i => i.id === id);
      if (item) { item.qty = Math.max(1, qty); this.render(); }
    });
  }

  subtotal() { return this.state.cart.reduce((sum, i) => sum + i.price * i.qty, 0); }
  tax() { return Math.round(this.subtotal() * 0.08); }
  total() { return this.subtotal() + this.tax(); }

  requestDiscount(percent) {
    this.state.pendingDiscount = { percent, status: 'pending', message: 'Awaiting approval' };
    this.render();
  }

  toggleOpen(open = !this.state.open) {
    this.state.open = open;
    if (open) {
      this.state.stage = 'initial';
      this.loadOrderHistory(true);
    }
    if (!open) {
      this.state.stage = 'initial';
    }
    this.render();
  }

  loadOrderHistory(reset = false) {
    if (this.state.orderHistoryLoading) return;
    if (reset) {
      this.state.orders = [];
      this.state.orderHistoryOffset = 0;
      this.state.orderHistoryHasMore = false;
    }
    this.state.orderHistoryLoading = true;
    this.fetchOrderHistory(this.state.orderHistoryOffset, this.orderHistoryLimit)
      .then((data) => {
        const nextOrders = data.orders || [];
        this.state.orders = reset ? nextOrders : this.state.orders.concat(nextOrders);
        this.state.orderHistoryHasMore = Boolean(data.has_more);
        this.state.orderHistoryOffset = Number.isFinite(data.next_offset)
          ? data.next_offset
          : this.state.orderHistoryOffset + nextOrders.length;
        this.state.orderHistoryLoading = false;
        this.render();
      })
      .catch(() => {
        this.state.orderHistoryLoading = false;
        this.render();
      });
  }

  setComparison(products) {
    this.state.comparison = products;
    this.render();
  }

  handleSubmit(queryRaw) {
    const { normalized, warnings } = this.normalizeInput(queryRaw);
    this.state.stage = 'split';
    this.state.warnings = warnings;
    this.state.lastQuery = normalized;
    this.state.lastQueryAt = new Date().toISOString();
    this.state.decisionMeta = null;
    this.state.thinking = true;
      this.state.trace = [
        { label: 'Parsing intent', status: 'done', ts: new Date().toLocaleTimeString() },
        { label: 'Safety checks', status: 'running', ts: '' },
        { label: 'Ranking candidates', status: 'queued', ts: '' },
        { label: 'Finalizing proposal', status: 'queued', ts: '' },
      ];

    if (this.isDiscountAttempt(normalized)) {
      this.state.results = [];
      this.state.thinking = false;
      this.shadow.getElementById('results').innerHTML = this.restrictedNotice();
      this.wireNoticeActions();
      this.renderCart();
      return;
    }

    this.setComparison(null);
    this.shadow.getElementById('results').innerHTML = '<div class="empty">Thinking...</div>';
    this.fetchRecommend(normalized).then(data => {
      this.state.thinking = false;
      if (data.status === 'budget_exceeded') {
        const remaining = typeof data.remaining === 'number' ? data.remaining : 0;
        this.shadow.getElementById('results').innerHTML = `
          <div class="notice">
            <div class="notice-title">Token budget reached</div>
            <div class="notice-body">Try a shorter request or wait for the budget window to reset. Remaining: ${remaining} tokens.</div>
            <div class="notice-actions">
              <button class="btn-secondary" id="continue-browse">Continue</button>
            </div>
          </div>
        `;
        this.wireNoticeActions();
        this.renderCart();
        return;
      }
      if (data.status === 'blocked') {
        this.shadow.getElementById('results').innerHTML = this.restrictedNotice();
        this.wireNoticeActions();
        return;
      }
      const ranked = (data.results || []).map(r => ({
        id: r.id,
        sku: r.sku,
        name: r.name,
        price: Math.round((r.price_cents || 0) / 100),
        rating: r.specs?.rating || 0,
        ram: 0,
        storage: r.specs?.storage || '',
        cpu: r.specs?.cpu || '',
        display: r.specs?.display || '',
        battery: '',
        stock: r.stock,
        shippingDays: r.specs?.shipping_days,
        reasons: this.buildReasons({ price: Math.round((r.price_cents || 0) / 100), ram: 0, battery: '0h', rating: 0 }, { minRam: 0, minPrice: 0, maxPrice: 999999 }),
        factors: r.factors || {},
        confidence: r.confidence,
        score: r.score,
        score_norm: r.score_norm,
        rank_delta: r.rank_delta,
        rerank_delta: r.rerank_delta,
        baseline_rank: r.baseline_rank,
        why_not: r.why_not
      }));
      this.state.results = ranked;
      // Surface the answer-first narration above the product cards (was invisible).
      this.state.answer = data.assistant_message || data.message || '';
      this.state.decisionMeta = {
        proposal: data.proposal || {},
        security: data.security || {},
        degraded: data.degraded,
        eligible: data.eligible,
        notice: data.notice,
        constraints: data.constraints_used || {},
        policy: data.policy_version || 'v1',
        riskScore: data.risk_score,
        whyNot: data.why_not || [],
        traceId: data.trace_id || null,
        timing: data.timing_breakdown || null,
        sourceStatuses: data.source_statuses || []
      };
      this.state.traceEvents = [];
      if (this.state.decisionMeta.traceId) {
        this.startTraceStreaming(this.state.decisionMeta.traceId);
      }
      this.fetchLatestDecision().then((latest) => {
        this.state.decisionMeta.latest = latest || null;
        this.render();
      }).catch(() => {});
      this.render();
    }).catch(() => {
      this.state.thinking = false;
      const constraints = this.parseConstraints(normalized);
      const products = this.recommendProducts(constraints);
      this.state.results = products;
      this.state.stage = 'split';
      this.state.decisionMeta = {
        proposal: { decision_mode: 'local_fallback', rationale: 'Local fallback ranking used.' },
        security: { severity: 'info', mitre: [], owasp: [] },
        degraded: true,
        eligible: false,
        notice: 'Local fallback used; backend unavailable.',
      };
      this.state.traceEvents = [{
        id: `error-${Date.now()}`,
        time: new Date().toISOString(),
        event_type: 'error',
        payload: { message: 'Backend unavailable; local fallback used.' }
      }];
      this.render();
    });
  }

  restrictedNotice() {
    return `
    <div class="notice">
      <div class="notice-title">Approval required</div>
      <div class="notice-body">Discount and price changes are reviewed by a human. Ask for recommendations or browse the catalog.</div>
      <div class="notice-actions">
        <button class="btn" id="continue-browse">Continue</button>
        <button class="btn-secondary" id="human-support">Talk to Support</button>
      </div>
    </div>`;
  }

  wireNoticeActions() {
    this.shadow.getElementById('continue-browse')?.addEventListener('click', () => {
      this.state.results = [];
      this.render();
    });
    this.shadow.getElementById('human-support')?.addEventListener('click', () => {
      window.open('mailto:support@shopsquire.local');
    });
  }

  openProductDetail(product) {
    const sku = product.sku || product.id;
    if (!sku) {
      alert('Product details unavailable.');
      return;
    }
    window.open(`/ui/product/${sku}`, '_blank');
  }

  renderResults() {
    const c = this.shadow.getElementById('results');
    if (!c) return;
    if (!this.state.results.length) {
      c.innerHTML = '<div class="empty">No results yet. Try a query.</div>';
      return;
    }
    const view = this.state.viewMode || 'grid';
    const meta = this.state.decisionMeta || {};
    const security = meta.security || {};
    const proposal = meta.proposal || {};
    const followups = (meta.proposal?.nlp?.followups || meta?.nlp?.followups || []);
    const constraints = meta.constraints || {};
    const whyNot = meta.whyNot || [];
    const latest = meta.latest || {};
    const weights = (this.state.results[0]?.factors?.weights || {});
    const wfRows = Object.keys(weights).slice(0, 6).map(k => {
      const val = weights[k] || 0;
      const width = Math.min(100, Math.max(5, Math.abs(val) * 10));
      return `<div class="wf-row"><div>${k}</div><div class="wf-bar"><div class="wf-fill" style="width:${width}%"></div></div><div>${val.toFixed(1)}</div></div>`;
    }).join('');
    const decisionPanel = `
      <div class="decision-panel">
        <div class="decision-title">Decision Trace</div>
        <div class="decision-meta">
          <span class="chip">Mode: ${proposal.decision_mode || 'rules'}</span>
          <span class="chip">Policy: ${meta.policy || 'v1'}</span>
          <span class="chip">Risk: ${security.severity || 'info'}</span>
          <span class="chip">Intent: ${(proposal?.nlp?.intent || 'recommend')} (${Math.round((proposal?.nlp?.intent_confidence || 0) * 100)}%)</span>
          <span class="chip">${meta.degraded ? 'Degraded' : 'Normal'}</span>
          <span class="chip">${meta.eligible === false ? 'Simulated' : 'Eligible'}</span>
        </div>
        <div class="decision-reason">Query: ${this.state.lastQuery || 'n/a'} ${this.state.lastQueryAt ? `(${new Date(this.state.lastQueryAt).toLocaleTimeString()})` : ''}</div>
        <div class="decision-reason">Inputs: budget ${constraints.budget_max || '?'}, specs ${(constraints.specs || []).join(', ') || '?'}, use case ${constraints.use_case || '?'}</div>
        <div class="decision-reason">Why: ${proposal.rationale || 'Ranked by constraints and availability.'}</div>
        <div class="decision-reason">Risk score: ${meta.riskScore ?? '?'}</div>
        <div class="decision-tags">
          ${(security.mitre || []).slice(0, 3).map(t => `<span class="tag">${t}</span>`).join('') || '<span class="tag">No MITRE flags</span>'}
          ${(security.owasp || []).slice(0, 3).map(t => `<span class="tag">${t}</span>`).join('') || ''}
        </div>
        ${followups.length ? `<div class="followup-chips">${followups.slice(0,4).map((q, i) => `<button class="chip followup" data-followup-index="${i}">${q}</button>`).join('')}</div>` : ''}
        ${meta.notice ? `<div class="decision-notice">${meta.notice}</div>` : ''}
        ${whyNot.length ? `<div class="decision-notice">Why not: ${whyNot.map(w => `${w.name} (${(w.reasons||[]).join(', ')})`).join(' | ')}</div>` : ''}
        ${wfRows ? `<div class="waterfall">${wfRows}</div>` : ''}
        ${latest && latest.id ? `<div class="decision-notice">Last log: ${latest.id} | ${latest.execution_status} | ${latest.valid_from}</div>` : ''}
        <div class="decision-links">
          <a href="/docs" target="_blank">API & decisions</a>
          ${meta.traceId ? ` | <a href="http://localhost:16686/trace/${meta.traceId}" target="_blank">View last trace</a>` : ''}
        </div>
      </div>
    `;
    // Answer-first banner: the buyer-facing narration, above the product cards.
    const _ans = String(this.state.answer || '').trim();
    const answerBanner = _ans
      ? `<div data-test="answer-banner" style="margin:0 0 12px;padding:12px 14px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;font-size:14px;line-height:1.5;color:#0c4a6e;">${_ans.replace(/</g, '&lt;')}</div>`
      : '';
    // render variants: grid, list, compact
    if (view === 'compact') {
      c.innerHTML = answerBanner + decisionPanel + `<div class="compact-list">${this.state.results.map((p, idx) => `
        <div class="card" style="padding:8px;display:flex;justify-content:space-between;align-items:center;">
          <div style="flex:1;min-width:0;">
            <div style="font-weight:600;">${idx + 1}. ${p.name}</div>
            <div style="font-size:11px;color:#6b7280;">$${p.price} • ${p.storage} • ${p.rating || 'n/a'}</div>
          </div>
          <div style="margin-left:8px;display:flex;gap:6px;align-items:center;">
            <button class="btn" data-add="${p.id}">Add</button>
            <button class="btn-tertiary" data-why="${p.id}">Why</button>
          </div>
        </div>
      `).join('')}</div>`;
    } else if (view === 'list') {
      c.innerHTML = answerBanner + decisionPanel + `<div class="list-view">${this.state.results.map((p, idx) => `
        <div class="card" style="display:flex;gap:12px;align-items:flex-start;">
          <div style="width:120px;height:80px;background:#f6f4f2;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#6b7280;">Img</div>
          <div style="flex:1;">
            <div class="card-title">${p.name} <span style="font-size:12px;color:#6b7280;">• $${p.price}</span></div>
            <div class="card-sub">${p.storage} • ${p.ram}GB • ${p.cpu || ''} • Rating: ${p.rating || 'n/a'}</div>
            <div style="margin-top:8px;font-size:12px;color:#374151;">${(p.reasons || []).slice(0,3).join(' • ')}</div>
            <div class="card-actions" style="margin-top:8px;">
              <button class="btn" data-add="${p.id}">Add to Cart</button>
              <button class="btn-secondary" data-details="${p.id}">Details</button>
              <button class="btn-tertiary" data-why="${p.id}">Why recommended</button>
            </div>
          </div>
        </div>
      `).join('')}</div>`;
    } else {
      // default grid
      c.innerHTML = answerBanner + decisionPanel + this.state.results.map((p, idx) => `
      <div class="card">
        <div class="card-title">${idx + 1}. ${p.name}</div>
        <div class="card-sub">$${p.price} | ${p.ram}GB | ${p.storage} | ${p.display || ''} ${p.cpu || ''} | Rating: ${p.rating || 'n/a'} | Stock: ${p.stock ?? 'n/a'} | Ship: ${p.shippingDays ?? 'n/a'}d</div>
        <div class="card-sub">
          ${(() => {
            const c = p.confidence || 0;
            const cls = c >= 0.75 ? 'badge-safe' : c >= 0.45 ? 'badge-warn' : 'badge-risk';
            const label = c >= 0.75 ? 'High confidence' : c >= 0.45 ? 'Medium confidence' : 'Low confidence';
            return `<span class="badge ${cls}">${label}</span>`;
          })()}
        </div>
        <div class="card-actions">
          <button class="btn" data-add="${p.id}">Add to Cart</button>
          <button class="btn-secondary" data-details="${p.id}">Details</button>
          <button class="btn-secondary" data-compare="${p.id}">Compare</button>
          <button class="btn-tertiary" data-why="${p.id}">Why recommended</button>
          ${idx === 0 ? `<button class="btn-tertiary" data-top-why="${p.id}">Why #1?</button>` : ''}
        </div>
        <div class="reasons" id="reasons-${p.id}" style="display:none">
          Why: ${p.reasons.map(r => '- ' + r).join(' | ')}<br/>
          Factors: ${(p.factors?.positive || []).join(', ')} ${(p.factors?.negative || []).join(', ')}<br/>
          Score: ${(p.score || 0).toFixed(2)} (Norm ${(p.score_norm || 0).toFixed(1)}) | Delta Rank: ${p.rank_delta ?? 'n/a'} | Baseline Delta: ${p.rerank_delta ?? 'n/a'} | Confidence: ${(p.confidence || 0).toFixed(2)}
          ${(() => {
            const weights = p.factors?.weights || {};
            const rows = Object.keys(weights).slice(0, 6).map(k => {
              const val = weights[k] || 0;
              const width = Math.min(100, Math.max(5, Math.abs(val) * 10));
              return `<div class="wf-row"><div>${k}</div><div class="wf-bar"><div class="wf-fill" style="width:${width}%"></div></div><div>${val.toFixed(1)}</div></div>`;
            }).join('');
            return rows ? `<div class="waterfall" style="margin-top:6px;">${rows}</div>` : '';
          })()}
          ${p.why_not ? `<div class="decision-notice">Why not this SKU: ${p.why_not.join(', ')}</div>` : ''}
          <div class="decision-notice">Policy checks: policy ${meta.policy || 'v1'} | risk ${meta.riskScore ?? 'n/a'} | severity ${security.severity || 'info'}</div>
        </div>
      </div>
    `).join('');
    }

    this.state.results.forEach(p => {
      const addBtn = c.querySelector(`[data-add="${p.id}"]`);
      const whyBtn = c.querySelector(`[data-why="${p.id}"]`);
      const topWhyBtn = c.querySelector(`[data-top-why="${p.id}"]`);
      const compareBtn = c.querySelector(`[data-compare="${p.id}"]`);
      const detailBtn = c.querySelector(`[data-details="${p.id}"]`);
      addBtn?.addEventListener('click', () => this.addToCart(p));
      whyBtn?.addEventListener('click', () => {
        const el = c.querySelector(`#reasons-${p.id}`);
        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
      });
      topWhyBtn?.addEventListener('click', () => {
        const el = c.querySelector(`#reasons-${p.id}`);
        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
      });
      compareBtn?.addEventListener('click', () => this.setComparison(this.state.results.slice(0, 3)));
      detailBtn?.addEventListener('click', () => this.openProductDetail(p));
    });
  }

  renderComparison() {
    const cmp = this.shadow.getElementById('comparison');
    if (!cmp) return;
    if (!this.state.comparison) { cmp.innerHTML = ''; return; }
    const rows = ['Price', 'RAM', 'Storage', 'Battery', 'Rating'];
    const cells = this.state.comparison.map(p => ({
      Price: `$${p.price}`, RAM: `${p.ram}GB`, Storage: p.storage, Battery: p.battery, Rating: p.rating.toFixed(1)
    }));
    cmp.innerHTML = `
      <div class="cmp-title">Comparison</div>
      <div class="cmp-grid">
        <div class="cmp-col cmp-head"></div>
        ${this.state.comparison.map(p => `<div class="cmp-col cmp-head">${p.name}</div>`).join('')}
        ${rows.map(r => `
          <div class="cmp-row">${r}</div>
          ${cells.map(c => `<div class="cmp-cell">${c[r]}</div>`).join('')}
        `).join('')}
      </div>
    `;
  }

  renderCart() {
    const cart = this.shadow.getElementById('cart');
    if (!cart) return;
    const items = this.state.cart.map(i => `
      <div class="cart-item">
        <div class="ci-name">${i.name}</div>
        <div class="ci-actions">
          <label>Qty <input type="number" min="1" value="${i.qty}" data-qty="${i.id}"/></label>
          <button class="btn-tertiary" data-remove="${i.id}">Remove</button>
        </div>
        <div class="ci-price">$${i.price} ea</div>
      </div>
    `).join('');

    const accessories = this.state.accessories.map(a => `
      <div class="acc-item">
        <div>${a.name} ($${a.price})</div>
        <button class="btn-secondary" data-add-acc="${a.id}">Add</button>
      </div>
    `).join('');

    const pending = this.state.pendingDiscount ? `
      <div class="discount">
        Discount ${this.state.pendingDiscount.percent}% | Status: ${this.state.pendingDiscount.status}
      </div>
    ` : '';

    const subtotal = this.subtotal();
    const tax = this.tax();
    const discountAmt = this.state.pendingDiscount?.status === 'approved' ? (this.state.pendingDiscount.amount || 0) : 0;
    const total = subtotal + tax - discountAmt;

    const orders = this.state.orders.map(o => `
      <div class="order-item">
        <div>Order ${o.order_id}</div>
        <div class="order-sub">$${Math.round((o.total_cents || 0) / 100)} | ${o.status || 'created'} | ${new Date(o.created_at).toLocaleString()}</div>
      </div>
    `).join('');
    const orderLoading = this.state.orderHistoryLoading ? '<div class="order-sub">Loading...</div>' : '';
    const loadMore = this.state.orderHistoryHasMore
      ? `<button class="btn-secondary" id="orders-more">Load more</button>`
      : '';

    cart.innerHTML = `
      <div class="cart-title">Your Cart</div>
      ${items || '<div class="empty">No items yet</div>'}
      <div class="acc-section">
        <div class="acc-title">Accessories</div>
        ${accessories}
      </div>
      <div id="checkout-upsell" class="upsell-wrap" style="display:none; margin-top:10px;"></div>
      ${pending}
      <div class="totals">
        <div>Subtotal: $${subtotal}</div>
        <div>Est. Tax: $${tax}</div>
        ${discountAmt ? `<div>Discount: -$${discountAmt}</div>` : ''}
        <div class="total">Total: $${total}</div>
      </div>
      <div class="cart-actions">
        <button class="btn" id="checkout">Go to Checkout</button>
        <button class="btn-secondary" id="proceed-checkout" style="display:none;">Proceed anyway</button>
        <button class="btn-secondary" id="req-10">Request 10% Discount</button>
      </div>
      <div class="order-history">
        <div class="cart-title">Recent Orders</div>
        ${orders || '<div class="empty">No orders yet</div>'}
        ${orderLoading}
        ${loadMore}
      </div>
      <div class="trust-note">Secure checkout. Decisions logged for transparency.</div>
    `;

    this.state.cart.forEach(i => {
      const qtyEl = cart.querySelector(`[data-qty="${i.id}"]`);
      qtyEl?.addEventListener('change', (e) => {
        const val = parseInt(e.target.value, 10) || 1;
        this.updateQty(i.id, val);
      });
      const remBtn = cart.querySelector(`[data-remove="${i.id}"]`);
      remBtn?.addEventListener('click', () => this.removeFromCart(i.id));
    });
    cart.querySelectorAll('[data-add-acc]').forEach(btn => {
      btn.addEventListener('click', () => {
        const aid = btn.getAttribute('data-add-acc');
        const acc = this.state.accessories.find(a => a.id === aid);
        if (!acc) return;
        this.addCartItem(acc.sku, 1).then((cart) => {
          this.applyCartResponse(cart);
          this.render();
        }).catch(() => {
          this.state.cart.push({ id: acc.sku, sku: acc.sku, name: acc.name, price: acc.price, qty: 1 });
          this.render();
        });
      });
    });
    cart.querySelector('#req-10')?.addEventListener('click', () => this.requestDiscount(10));
    cart.querySelector('#checkout')?.addEventListener('click', async () => {
      try { this.emitUiAction('checkout_click'); } catch (e) {}
      const ctn = cart.querySelector('#checkout-upsell');
      const proceedBtn = cart.querySelector('#proceed-checkout');
      if (!ctn || !proceedBtn) { window.location.href = '/ui/checkout'; return; }
      const cartItems = (this.state.cart || []);
      const skus = cartItems.map(i => i.sku || i.id).filter(Boolean).slice(0,3);
      if (!skus.length) { window.location.href = '/ui/checkout'; return; }
      ctn.style.display = 'block';
      ctn.innerHTML = `<div class="upsell-title">Before you go — recommended add‑ons <span class="badge" style="margin-left:8px;">Bundle: -5% at 2+</span></div><div class="upsell-row" id="chk-upsell-row"><div class="meta">Loading...</div></div>`;
      proceedBtn.style.display = 'inline-block';
      proceedBtn.onclick = () => { window.location.href = '/ui/checkout'; };
      try {
        const data = await this.fetchCheckoutUpsell(skus);
        let results = (data.results || []).slice(0,6).map(r => ({
          id: r.id || r.sku,
          sku: r.sku,
          name: r.name,
          price: Math.round((r.price_cents||0)/100),
          factors: r.factors || {},
          stock: r.stock,
          tags: r.tags || []
        }));
        try {
          results.forEach(p => this.logRecommendInteraction({
            sku: p.sku || p.id,
            action: 'view',
            context: { source: 'checkout', cart_skus: skus },
          }));
        } catch (e) {}
        results = results.slice(0,3);
        if (!results.length) { ctn.innerHTML = `<div class="upsell-title">Bundle & save</div><div class="meta">No add‑ons at this time.</div>`; return; }
        const row = results.map(p => `
          <div class="upsell-card" data-upsell-card="${p.sku||p.id}">
            <div class="upsell-img">Img</div>
            <div class="upsell-name" title="${p.name}">${p.name}</div>
            <div class="upsell-sub">$${p.price} ${p.stock>0?'• In stock':''}</div>
            <div class="upsell-tags">${(p.tags || []).slice(0,3).map(t => `<span class="tag">${t}</span>`).join('')}</div>
            <div style="display:flex;gap:6px;margin-top:6px;">
              <button class="btn-secondary" data-add-upsell="${p.sku||p.id}">Add</button>
            </div>
          </div>
        `).join('');
        ctn.innerHTML = `<div class="upsell-title">Before you go — recommended add‑ons <span class="badge" style="margin-left:8px;">Bundle: -5% at 2+</span></div><div class="upsell-row">${row}</div>`;
        ctn.querySelectorAll('[data-upsell-card]')?.forEach(card => {
          card.addEventListener('mouseenter', () => {
            const sku = card.getAttribute('data-upsell-card');
            this.logRecommendInteraction({ sku, action: 'hover', context: { source: 'checkout' } });
          });
        });
        ctn.querySelectorAll('[data-add-upsell]')?.forEach(btn => {
          btn.addEventListener('click', () => {
            const sku = btn.getAttribute('data-add-upsell');
            if (!sku) return;
            this.logRecommendInteraction({ sku, action: 'click', context: { source: 'checkout_add' } });
            this.logRecommendInteraction({ sku, action: 'add_to_cart', context: { source: 'checkout_add' } });
            this.addCartItem(sku, 1).then((next) => { this.applyCartResponse(next); this.render(); }).catch(() => {
              // best-effort fallback add
              this.state.cart.push({ id: sku, sku: sku, name: sku, price: 19, qty: 1 });
              this.render();
            });
          });
        });
      } catch (e) {
        ctn.innerHTML = `<div class="upsell-title">Bundle & save</div><div class="meta">Couldn’t load add‑ons. You can proceed to checkout.</div>`;
      }
    });
    cart.querySelector('#orders-more')?.addEventListener('click', () => this.loadOrderHistory(false));
  }

  template() {
    const user = this.config.user || this.state.user;
    const userLabel = user.signedIn ? `${user.name} (${user.tier})` : 'Guest';
    return `
      <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@600;700&family=Sora:wght@300;400;500;600;700&display=swap');
        :host { position: fixed; bottom: 22px; right: 22px; z-index: 999999; font-family: "Sora", system-ui, sans-serif; }
        .fab { width: 64px; height: 64px; border-radius: 20px; background: linear-gradient(135deg, #cc5b2c, #2a6d6b); color: #fff; display:flex; align-items:center; justify-content:center; box-shadow: 0 16px 30px rgba(0,0,0,.25); cursor:pointer; font-weight:600; letter-spacing: 1px; }
        .overlay { position: fixed; inset: 0; background: rgba(17, 19, 25, .4); display: ${this.state.open ? 'flex' : 'none'}; align-items:center; justify-content:center; }
        .panel { ${this.state.stage === 'initial' ? 'width: min(50vw, 640px); height: min(60vh, 520px);' : 'width: min(980px, 95vw); height: min(90vh, 760px);'} background: #fffaf4; border-radius: 20px; box-shadow: 0 20px 60px rgba(22, 18, 14, .3); display:flex; flex-direction:column; overflow:hidden; animation: ${this.state.open ? 'rise 0.3s ease' : 'none'}; }
        .header { display:flex; align-items:center; justify-content:space-between; padding: 14px 18px; border-bottom: 1px solid #eadfce; background: linear-gradient(90deg, #fff6ea, #eef6f4); }
        .title { font-weight: 700; font-family: "Fraunces", serif; }
        .meta { font-size: 12px; color:#5a5f6a; }
        .close { background:none; border:none; cursor:pointer; font-size:14px; color:#6b7280; }
        .body { display:grid; grid-template-columns: ${this.state.stage === 'split' ? '0.3fr 0.4fr' : '1fr'}; height: 100%; }
        .left { display:flex; flex-direction:column; border-right: ${this.state.stage === 'split' ? '1px solid #eadfce' : 'none'}; }
        .inputbar { padding: 10px 14px; border-top: 1px solid #f0e6d8; display:flex; gap:8px; }
        .inputbar input { flex:1; padding: 10px 12px; border:1px solid #e5d8c8; border-radius:12px; background:#fff; }
        .mic { min-width: 54px; }
        .mic.active { background:#2a6d6b; color:#fff; }
        .toggle { display:flex; align-items:center; gap:6px; font-size: 11px; color:#5a5f6a; }
        .btn, .btn-secondary, .btn-tertiary { padding: 8px 12px; border-radius: 10px; border:none; cursor:pointer; font-family: inherit; font-size: 12px; }
        .btn { background:#cc5b2c; color:#fff; }
        .btn-secondary { background:#fff; color:#1a1b1f; border:1px solid #eadfce; }
        .btn-tertiary { background:transparent; color:#6b7280; }
        .content { display:grid; gap: 10px; padding: 12px 14px; overflow:auto; }
        .card { border:1px solid #eadfce; border-radius:14px; padding:12px; background:#fff; }
        .badge { font-size: 10px; padding: 4px 8px; border-radius: 999px; border:1px solid #eadfce; background:#fff; display:inline-block; }
        .badge-safe { background:#e7f6f0; border-color:#b5e0cf; color:#145a45; }
        .badge-warn { background:#fff1e6; border-color:#f2c9a8; color:#7a371d; }
        .badge-risk { background:#ffe7e7; border-color:#f2b8b8; color:#7a1d1d; }
        .card-title { font-weight:600; margin-bottom:4px; }
        .card-sub { font-size: 12px; color:#6b7280; margin-bottom:8px; }
        .reasons { font-size:12px; color:#374151; margin-top:8px; }
        .decision-panel { border:1px solid #d9c7b3; background:#fff7ee; padding: 12px; border-radius: 14px; }
        .decision-title { font-weight: 700; margin-bottom: 6px; }
        .decision-meta { display:flex; flex-wrap: wrap; gap:6px; margin-bottom: 6px; }
        .chip { font-size: 11px; padding: 4px 8px; border-radius: 999px; border:1px solid #eadfce; background:#fff; }
        .decision-reason { font-size: 12px; color:#5a5f6a; margin-bottom: 6px; }
        .decision-tags { display:flex; gap:6px; flex-wrap: wrap; margin-bottom: 6px; }
        .waterfall { display:grid; gap:6px; margin-top: 8px; }
        .wf-row { display:grid; grid-template-columns: 120px 1fr 40px; gap:8px; align-items:center; font-size:11px; }
        .wf-bar { height: 8px; border-radius: 999px; background:#eef6f4; position: relative; overflow:hidden; }
        .wf-fill { height: 100%; background: linear-gradient(90deg, #2a6d6b, #cc5b2c); }
        .tag { font-size: 10px; padding: 4px 6px; border-radius: 6px; background:#eef6f4; border:1px solid #c6e6db; }
        .decision-notice { font-size: 12px; color:#7a371d; }
        .decision-links a { font-size: 12px; color:#2a6d6b; text-decoration:none; }
        .notice { padding: 12px; border:1px solid #d78b66; background:#fff1e6; border-radius: 12px; }
        .notice-title { font-weight:600; color:#7a371d; }
        .cmp-title { font-weight:600; margin: 8px 0; }
        .cmp-grid { display:grid; grid-template-columns: repeat(${(this.state.comparison?.length || 0) + 1}, 1fr); gap: 8px; }
        .cmp-head { font-weight:600; }
        .sidebar { padding: 12px; display:${this.state.stage === 'split' ? 'flex' : 'none'}; flex-direction:column; gap: 10px; }
        .rp-banner { border:1px dashed #eadfce; background:#fff; padding: 10px; border-radius: 12px; font-size:12px; color:#5a5f6a; }
        .range-grid { display:grid; grid-template-columns: repeat(3, 1fr); gap:8px; margin-top:8px; }
        .range-btn { padding:8px; border:1px solid #eadfce; border-radius:10px; background:#fff; font-size:12px; cursor:pointer; }
        .cart-title { font-weight:600; margin-bottom:8px; }
        .cart-item { display:flex; flex-direction:column; gap:6px; border-bottom:1px solid #f0e6d8; padding: 8px 0; }
        .ci-actions { display:flex; align-items:center; gap:8px; }
        .acc-section { margin-top: 10px; }
        .acc-title { font-weight:600; margin-bottom:6px; }
        .acc-item { display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; }
        .totals { border-top: 1px solid #f0e6d8; margin-top: 8px; padding-top: 8px; }
        .total { font-weight:700; }
        .cart-actions { display:flex; gap:8px; margin-top:8px; }
        .warnings { font-size:12px; color:#a14d2c; padding: 6px 10px; background:#fff1e6; border-radius: 10px; border:1px solid #eadfce; }
        .trust-note { font-size:11px; color:#5a5f6a; margin-top: 8px; }
        .quick-actions { display:flex; gap:8px; flex-wrap: wrap; }
        .qa { font-size:11px; padding:6px 10px; border-radius:999px; border:1px solid #eadfce; background:#fff; cursor:pointer; }
        .typing { display:flex; align-items:center; gap:6px; font-size:12px; color:#6b7280; }
        .dot { width:6px; height:6px; background:#cc5b2c; border-radius:50%; animation: pulse 1.2s infinite; }
        .dot:nth-child(2) { animation-delay: .2s; }
        .dot:nth-child(3) { animation-delay: .4s; }
        .guest { background:#fff1e6; border:1px dashed #d78b66; padding:10px 12px; border-radius: 12px; font-size: 12px; }
        .order-history { margin-top: 12px; }
        .order-item { padding: 8px; border: 1px solid #eadfce; border-radius: 10px; margin-bottom: 6px; background: #fff; }
        .order-sub { font-size: 11px; color: #5a5f6a; margin-top: 4px; }
        .trace { display:grid; gap:6px; margin-top: 8px; }
        .trace-item { display:flex; align-items:center; justify-content:space-between; font-size:11px; color:#5a5f6a; }
        .trace-status { font-weight:600; text-transform: uppercase; font-size: 10px; }
        .upsell-wrap { margin-top: 10px; border:1px solid #eadfce; background:#fff; border-radius:12px; padding:10px; }
        .upsell-title { font-weight:600; margin-bottom:6px; }
        .upsell-row { display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; }
        .upsell-card { min-width: 160px; border:1px solid #eadfce; border-radius:10px; padding:8px; background:#fffaf4; cursor:pointer; }
        .upsell-card:hover { background:#fff6ea; }
        .upsell-img { width:100%; height:72px; background:#f6f4f2; border-radius:8px; display:flex; align-items:center; justify-content:center; color:#6b7280; margin-bottom:6px; font-size:12px; }
        .upsell-name { font-size:12px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .upsell-sub { font-size:11px; color:#6b7280; margin:4px 0; }
        .upsell-tags { display:flex; gap:4px; flex-wrap:wrap; }
        @keyframes rise { from { transform: translateY(10px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        @keyframes pulse { 0%, 80%, 100% { opacity: .2; } 40% { opacity: 1; } }
        @media (max-width: 900px) {
          .panel { width: 100vw; height: 100vh; border-radius: 0; }
          .body { grid-template-columns: 1fr; }
          .left { border-right: none; border-bottom: 1px solid #eadfce; }
        }
      </style>
      <div class="fab" id="fab">SQ</div>
      <div class="overlay">
        <div class="panel">
          <div class="header">
            <div>
              <div class="title">ShopSquire Assistant</div>
              <div class="meta">User: ${userLabel}</div>
            </div>
            <label class="toggle">
              <input type="checkbox" id="demo-toggle" ${this.state.demoMode ? 'checked' : ''}/>
              Demo mode
            </label>
            <button class="close" id="close">Close</button>
          </div>
          <div class="body">
            <div class="left">
              <div class="content">
                ${!user.signedIn ? `<div class="guest">Guest mode: sign in for order history, VIP pricing, and saved carts.</div>` : ''}
                ${this.state.warnings.length ? `<div class="warnings">${this.state.warnings.join(' ')}</div>` : ''}
                ${this.state.thinking ? `<div class="typing"><span class="dot"></span><span class="dot"></span><span class="dot"></span>Thinking...</div>` : ''}
                ${(this.state.traceEvents || []).length ? `
                  <div class="card">
                    <div class="card-title">Agentic Trace</div>
                    <div class="trace">
                      ${this.state.traceEvents.slice(0, 6).map(t => `
                        <div class="trace-item">
                          <span>${t.event_type || 'event'} ${t.time ? `<span class="meta" style="margin-left:6px;">${new Date(t.time).toLocaleTimeString()}</span>` : ''}</span>
                          <span class="trace-status">${t.source_id || 'agent'}</span>
                        </div>
                      `).join('')}
                    </div>
                  </div>
                ` : ''}
                <div class="quick-actions">
                  <button class="qa" data-q="Show me laptops under $1000">Under $1000</button>
                  <button class="qa" data-q="Compare top 3 16GB RAM laptops">Compare 16GB</button>
                  <button class="qa" data-q="What is in stock with 2-day shipping?">Fast shipping</button>
                </div>
              </div>
              <div class="inputbar">
                <input id="query" placeholder="Ask: top 5 laptops between $1200 and $2100, 16GB RAM" />
                ${this.state.speechSupported ? `<button class="btn-tertiary mic ${this.state.speechListening ? 'active' : ''}" id="mic">${this.state.speechListening ? 'Listening' : 'Mic'}</button>` : ''}
                <button class="btn-tertiary" id="camera">Camera</button>
                <button class="btn" id="send">Send</button>
              </div>
            </div>
            <div class="sidebar">
              <div class="rp-banner">${this.state.bannerMessage || 'Recommended for you'}</div>
              <div class="range-grid">
                <button class="range-btn" data-range="$500-$800">$500–$800</button>
                <button class="range-btn" data-range="$800-$1200">$800–$1200</button>
                <button class="range-btn" data-range="$1200-$1600">$1200–$1600</button>
                <button class="range-btn" data-range="$1600-$2000">$1600–$2000</button>
                <button class="range-btn" data-range="$2000-$2500">$2000–$2500</button>
                <button class="range-btn" data-range="$2500-$3000">$2500–$3000</button>
              </div>
              <div class="grid" id="results"></div>
              <div id="upsell"></div>
              <div id="comparison"></div>
              <div id="cart"></div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  render() {
    this.shadow.innerHTML = this.template();
    this.shadow.getElementById('fab')?.addEventListener('click', () => this.toggleOpen(true));
    this.shadow.getElementById('close')?.addEventListener('click', () => this.toggleOpen(false));
    this.shadow.getElementById('send')?.addEventListener('click', () => {
      const q = this.shadow.getElementById('query').value;
      try { this.emitUiAction('send'); } catch (e) {}
      this.handleSubmit(q);
    });
    this.shadow.getElementById('camera')?.addEventListener('click', () => {
      this.state.bannerMessage = 'Image queued for analysis';
      try { this.emitUiAction('camera'); } catch (e) {}
      this.render();
    });
    this.shadow.getElementById('view-mode')?.addEventListener('change', (e) => {
      try {
        const v = e.target.value;
        this.state.viewMode = v || 'grid';
        this.render();
      } catch (err) {}
    });
    this.shadow.getElementById('mic')?.addEventListener('click', () => this.startSpeech());
    this.shadow.getElementById('demo-toggle')?.addEventListener('change', (e) => {
      const checked = Boolean(e.target.checked);
      this.state.demoMode = checked;
      this.render();
      if (checked) {
        this.runDemoSequence();
      }
    });
    this.shadow.getElementById('query')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.shadow.getElementById('send').click();
    });
    this.shadow.querySelectorAll('[data-q]').forEach(btn => {
      btn.addEventListener('click', () => {
        const q = btn.getAttribute('data-q');
        try { this.emitUiAction('quick_action'); } catch (e) {}
        this.shadow.getElementById('query').value = q || '';
        this.handleSubmit(q || '');
      });
    });
    this.shadow.querySelectorAll('[data-range]')?.forEach(btn => {
      btn.addEventListener('click', () => {
        const r = btn.getAttribute('data-range') || '';
        try { this.emitUiAction(`price_range:${r}`); } catch (e) {}
        const q = `Top 5 laptops between ${r}`;
        this.shadow.getElementById('query').value = q;
        this.handleSubmit(q);
      });
    });
    this.renderResults();
    this.renderUpsellCarousel();
    this.renderComparison();
    this.renderCart();
    this.updateDecisionModal();
    // Wire follow-up chip click handlers (accept -> resubmit query)
    try {
      const chips = this.shadow.querySelectorAll('.followup-chips .followup');
      chips.forEach(btn => {
        btn.addEventListener('click', (e) => {
          const idx = Number(btn.getAttribute('data-followup-index') || '0');
          const followups = (this.state.decisionMeta?.proposal?.nlp?.followups || this.state.decisionMeta?.nlp?.followups || []);
          const q = followups[idx] || btn.textContent || '';
          if (!q) return;
          const input = this.shadow.getElementById('query');
          if (input) input.value = q;
          try { this.emitUiAction('followup_accept'); } catch (err) {}
          this.handleSubmit(q);
        });
      });
    } catch (e) {}
  }

  renderUpsellCarousel() {
    const el = this.shadow.getElementById('upsell');
    if (!el) return;
    const products = (this.state.results || []).slice(0, 6);
    if (!products.length) { el.innerHTML = ''; return; }
    const cards = products.map(p => {
      const chips = [];
      const pos = (p.factors?.positive || []).slice(0, 2).map(s => s.replace(/^\+/, ''));
      if (p.stock > 0) chips.push('In stock');
      if (p.rerank_delta != null) chips.push(p.rerank_delta > 0 ? `↑${p.rerank_delta}` : p.rerank_delta < 0 ? `↓${Math.abs(p.rerank_delta)}` : '•');
      const reasons = (pos.concat(p.reasons || [])).slice(0, 3);
      return `
        <div class="upsell-card" data-upsell="${p.id}">
          <div class="upsell-img">Img</div>
          <div class="upsell-name" title="${p.name}">${p.name}</div>
          <div class="upsell-sub">$${p.price}${chips.length ? ` • ${chips.join(' ')}` : ''}</div>
          <div class="upsell-tags">${reasons.map(r => `<span class="tag">${r}</span>`).join('')}</div>
        </div>`;
    }).join('');
    el.innerHTML = `
      <div class="upsell-wrap">
        <div class="upsell-title">Recommended for you</div>
        <div class="upsell-row">${cards}</div>
      </div>`;
    // Wire clicks to open Decision Trace and highlight why
    el.querySelectorAll('[data-upsell]')?.forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-upsell');
        const p = (this.state.results || []).find(x => String(x.id) === String(id));
        if (!p) return;
        const reasons = (p.factors?.positive || []).slice(0, 5).map(s => s.replace(/^\+/, ''));
        const weights = p.factors?.weights || {};
        const topWeights = Object.entries(weights).sort((a,b)=>Math.abs(b[1]) - Math.abs(a[1])).slice(0,5);
        this.state.highlightRec = { sku: p.sku || p.id, name: p.name, reasons, weights: topWeights };
        if (this.decisionModal) this.decisionModal.style.display = 'block';
        this.updateDecisionModal();
      });
    });
  }

  updateDecisionModal() {
    if (!this.decisionModalBody) return;
    const meta = this.state.decisionMeta || {};
    const traceId = meta.traceId || meta.decision_id || meta.trace_id;
    const model = meta?.model_selection?.selected || meta?.llm_model || meta?.proposal?.decision_mode || 'unknown';
    const events = this.state.traceEvents || [];
    const filterSku = this.state.highlightRec?.sku || null;
    const filtered = filterSku ? events.filter(ev => {
      try {
        const p = ev.payload || {};
        return String(ev.target_id||'').includes(filterSku) || String(ev.source_id||'').includes(filterSku) || String(p.sku||'').includes(filterSku) || String(p.id||'').includes(filterSku);
      } catch (e) { return false; }
    }) : events;
    const eventList = filtered.slice(0, 12).map(ev => `
      <div style="font-size:12px; margin-bottom:6px;">
        <strong>${ev.event_type || 'event'}</strong>
        ${ev.time ? ` <span style="color:#6b7280">(${new Date(ev.time).toLocaleTimeString()})</span>` : ''}
        <div style="color:#6b7280;">${ev.source_id || 'agent'} ${ev.target_id ? `→ ${ev.target_id}` : ''}</div>
        <div style="color:#374151;font-size:12px;margin-top:4px;">${(ev.payload && typeof ev.payload === 'object') ? JSON.stringify(ev.payload) : (ev.payload || '')}</div>
      </div>`).join('') || '<div style="font-size:12px;color:#6b7280;">No trace events yet.</div>';
    const hl = this.state.highlightRec;
    const why = hl ? `
      <div style="margin-top:10px;">
        <div style="font-weight:600;">Why this recommendation</div>
        <div class="meta">${hl.name} (${hl.sku})</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">${(hl.reasons||[]).map(r => `<span class=tag>${r}</span>`).join('')}</div>
        ${hl.weights && hl.weights.length ? `<div style="margin-top:6px;">
          ${(hl.weights||[]).map(([k,v]) => `<div style="display:flex;justify-content:space-between;font-size:11px;color:#6b7280;"><span>${k}</span><span>${(v||0).toFixed(2)}</span></div>`).join('')}
        </div>` : ''}
        <div style="margin-top:8px;"><button id="filter-trace-item" class="btn-secondary" style="padding:6px 8px;border:1px solid #eadfce;border-radius:8px;background:#fff;cursor:pointer;">Filter for this item's events</button></div>
      </div>
    ` : '';

    // extract contract-nlp related events if present
    const contractEvent = events.find(e => (e.event_type || '').toLowerCase().includes('contract_nlp')) || null;
    const gateEvent = events.find(e => (e.event_type || '').toLowerCase().includes('nlp_quality_gate')) || null;
    const contractHtml = contractEvent ? `
      <div style="margin-top:8px;padding:8px;border:1px solid #eef2f7;border-radius:8px;background:#fff;">
        <div style="font-weight:600;">Contract NLP Analysis</div>
        <div class="meta" style="font-size:12px;color:#6b7280;margin-top:6px;">${contractEvent.source_id || ''} • ${contractEvent.time ? new Date(contractEvent.time).toLocaleString() : ''}</div>
        <pre style="white-space:pre-wrap;font-size:12px;color:#374151;margin-top:6px;">${JSON.stringify(contractEvent.payload || {}, null, 2)}</pre>
      </div>
    ` : '<div style="font-size:12px;color:#6b7280;">No Contract NLP analysis available.</div>';
    const gateHtml = gateEvent ? `
      <div style="margin-top:8px;padding:8px;border:1px solid #eef2f7;border-radius:8px;background:#fff;">
        <div style="font-weight:600;">NLP Quality Gate</div>
        <div class="meta" style="font-size:12px;color:#6b7280;margin-top:6px;">Decision: ${gateEvent.payload?.decision || 'n/a'} • Score: ${gateEvent.payload?.score ?? 'n/a'}</div>
        <pre style="white-space:pre-wrap;font-size:12px;color:#374151;margin-top:6px;">${JSON.stringify(gateEvent.payload || {}, null, 2)}</pre>
      </div>
    ` : '<div style="font-size:12px;color:#6b7280;">No NLP quality gate event yet.</div>';

    // Evidence Sources + latency (item 1) — turns retrieval/timing into on-screen
    // credibility. Null-safe; renders nothing extra when the fields are absent.
    const ss = meta.sourceStatuses || [];
    const tb = meta.timing || {};
    const _statusColor = (s) => s === 'full' ? '#059669' : (s === 'empty' ? '#9ca3af' : '#dc2626');
    const sourceRows = ss.length ? ss.map(s => `
      <div style="display:flex;justify-content:space-between;font-size:12px;color:#374151;">
        <span>${s.source}</span>
        <span style="color:${_statusColor(s.status)}">${s.status} · ${s.hit_count} hits · ${s.latency_ms}ms</span>
      </div>`).join('') : '<div style="font-size:12px;color:#6b7280;">No source status.</div>';
    const timingRows = Object.keys(tb).filter(k => k.endsWith('_ms')).map(k => `
      <div style="display:flex;justify-content:space-between;font-size:11px;color:#6b7280;"><span>${k.replace(/_ms$/, '')}</span><span>${tb[k]}ms</span></div>`).join('');
    const evidenceHtml = `
      <div data-test="evidence-sources" style="margin-top:8px;padding:8px;border:1px solid #eef2f7;border-radius:8px;background:#fff;">
        <div style="font-weight:600;">Evidence Sources</div>
        ${sourceRows}
        ${timingRows ? `<div style="font-weight:600;margin-top:8px;">Latency</div>${timingRows}` : ''}
      </div>`;

    const summaryHtml = `
      <div style="margin-bottom:10px;">
        <div style="font-weight:600;">Model Selection</div>
        <div class="meta">Selected model: ${model}</div>
      </div>
      <div style="margin-bottom:10px; font-size:12px; color:#6b7280;">Trace ID: ${traceId || 'n/a'}</div>
      ${evidenceHtml}
      <div style="font-weight:600; margin:10px 0 6px;">Contract & Quality</div>
      ${contractHtml}
      ${gateHtml}
      ${why}
    `;

    const traceHtml = `<div style="font-weight:600; margin-bottom:6px;">Live Trace</div>${eventList}`;

    try {
      const sPanel = this.decisionModalBody.querySelector('#decision-summary');
      const tPanel = this.decisionModalBody.querySelector('#decision-trace');
      if (sPanel) sPanel.innerHTML = summaryHtml;
      if (tPanel) tPanel.innerHTML = traceHtml;
      const btn = this.decisionModalBody.querySelector('#filter-trace-item');
      if (btn) btn.addEventListener('click', () => { this.updateDecisionModal(); });
    } catch (e) {}
  }

  setConfig(opts) {
    this.config = { ...this.config, ...(opts || {}) };
    if (opts && opts.user) {
      this.state.user = { ...this.state.user, ...opts.user };
    }
  }
}

customElements.define('shopsquire-widget', ShopSquireWidget);

window.ShopSquireWidget = window.ShopSquireWidget || {
  init(opts) {
    const el = document.querySelector('shopsquire-widget');
    if (el && typeof el.setConfig === 'function') el.setConfig(opts);
  }
};

// Lightweight metrics emission helper
ShopSquireWidget.prototype.emitUiAction = async function(action) {
  try {
    const base = this.config.apiBase || window.location.origin;
    const url = `${base.replace(/\/$/, '')}/observability/ui_action?action=${encodeURIComponent(action || 'unknown')}`;
    await fetch(url, { method: 'POST' });
  } catch (e) {
    // Swallow errors; metrics are best-effort
  }
};
