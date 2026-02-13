# ShopSquire Frontend Implementation Plan (Mobile/Tablet-First)

Last updated: 2026-01-20
Owner: Frontend/UX

## Selected Direction
- Product surfaces: 
  - Customer: Floating Assistant (Option C) — non-intrusive FAB → fullscreen overlay on mobile, side panel on desktop.
  - Merchant: Unified Control Dashboard (Option A) — overview, decisions, security, analytics, approvals.
- Deployment model: Hybrid
  - Embeddable customer widget (script tag) for any storefront.
  - Standalone admin SPA at admin.shopsquire.dev.
- Form factors: Mobile and tablet first, then desktop.
- Stack:
  - Widget: Web Component (TypeScript + Shadow DOM). Bundle to `widget.js` (~50–80KB gzipped). No framework dependency on host page.
  - Admin: React 18 + TypeScript with Tailwind + shadcn/ui, Recharts, TanStack Table.

## UX Key Points (Customer Widget)
- States:
  - Collapsed FAB (60×60), thumb-reachable on mobile.
  - Expanded overlay: fullscreen on mobile/tablet; slide-up panel on desktop.
- Triggers (good): hover >3s on product, add-to-cart, search dwell, exit-intent; (avoid): random timers, on-load.
- Content: rich product cards, quick intents, comparison table, explainability (“why recommended”), human handoff always visible.
- Session: per-visit memory (budget, preferences) with clear reset.

## UX Key Points (Merchant Dashboard)
- Priority layout: critical alerts first, KPIs grid, live charts, approvals.
- Real-time: WebSocket updates, visible "last updated" tick, alert grouping to reduce fatigue.
- PowerBI: embedded reports + export endpoints.

## Initial API Contract (v1)
Customer-facing
- POST `/api/v1/chat/recommend` → { query, cart, prefs } → [{product, score, reasons, upsells}]
- POST `/api/v1/cart/items` → { product_id, qty }
- GET  `/api/v1/products/{id}` → product details
- WS  `/api/v1/ws/events` → live activity/recommendation nudges

Admin-facing
- GET `/api/v1/admin/decisions` (filters: time, agent, status, search)
- GET `/api/v1/admin/decisions/{id}` → full trace (context, reasoning, policy, audit)
- GET `/api/v1/admin/security/events` (filters: severity, technique, time)
- GET `/api/v1/metrics` → Prometheus metrics (already planned)
- GET `/api/v1/admin/powerbi/export` → JSON for scheduled refresh

Note: Use pagination, cursor-based where applicable; standardize timestamps to ISO8601 UTC.

## Accessibility & Performance Targets
- WCAG 2.1 AA+: tap targets ≥44px (mobile), focus visible, ARIA on icon buttons, live regions for alerts.
- Performance: LCP < 2.5s (mobile 3G), TTI < 3.5s, CLS < 0.1; lazy-load images; code-split admin routes; service worker caching.

## Packaging & Integration
- Widget deliverable: `https://cdn.shopsquire.dev/widget.js`
  ```html
  <script src="https://cdn.shopsquire.dev/widget.js" defer></script>
  <script>
    window.ShopSquire?.init({
      apiBase: "https://api.shopsquire.dev",
      tenantId: "{merchant_id}",
      theme: { primary: "#2563eb" },
      features: { recommendations: true, upsell: true, handoff: true }
    });
  </script>
  ```
- Admin deliverable: `admin.shopsquire.dev` (React SPA) with protected routes.

## Phased Delivery (Customer-first)
- Phase 1 — Widget MVP (1–2 weeks)
  - FAB + overlay, chat thread UI, product card rendering.
  - Intent triggers and basic telemetry.
  - Adapter with mock data → toggle to real API.
- Phase 2 — Widget Integration (1 week)
  - Wire to `/chat/recommend`, `/cart/items`, `/products/{id}`.
  - Session memory, explainability block, human handoff link.
- Phase 3 — Admin Essentials (2–3 weeks)
  - Overview KPIs, Decisions list + detail, Security events, Approval queue.
  - Charts (Recharts), tables (TanStack), real-time feed.
- Phase 4 — Observability & BI (1 week)
  - Prometheus metrics panel hook, PowerBI embed, exports.

## Component Inventory
Widget (Web Component)
- `shopsquire-fab`
- `shopsquire-overlay`
- `shopsquire-chat-thread`
- `shopsquire-product-card`
- `shopsquire-compare`

Admin (React)
- `KpiCard`, `LiveAlertList`, `DecisionTable`, `DecisionDetails`, `SecurityEvents`, `ApprovalQueue`, `Charts.*`

## Responsive Breakpoints
- Mobile: <768px (fullscreen chat, stacked cards)
- Tablet: 768–1023px (split chat/sidebar where feasible)
- Desktop: ≥1024px (panel chat, persistent sidebar optional)

## Risks & Mitigations
- Embed variability (host CSS conflicts) → Shadow DOM isolation, CSS variables for theming.
- Bundle size → no framework in widget; tree-shake, code-split admin.
- Real-time load → backoff and batching for WS; fall back to polling.

## Sign-offs Requested
- Confirm Hybrid model: Web Component widget + React admin.
- Confirm “customer-first” sequencing (Phases 1–2 before admin).
- Approve initial API endpoints and response shapes.
