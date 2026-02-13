# ShopSquire Expanded AI/ML Playbook

This playbook summarizes architecture patterns and implementation notes for decision tracing, model tiering, CV providers, and safe interleaving.

- Product detail JSON endpoint: /api/v1/products/{sku} (implemented in `src.app.routers.products_compare.get_product_detail`). Uses `CatalogRepository` for DB-backed products and falls back to docs seed.

- Product seeding: `scripts/seed_demo_data.seed_products` populates `products` + `inventory` and writes lightweight SVG images to `/static/images`.

- Tiered CV provider: `src.app.services.cv_tiered.TieredCVProvider` selects between `BasicCVTriage` and an enhanced Tier 2 path using `TierRouter` signals.

- WebSocket / SSE trace wiring: decision trace endpoints exist under `src.app.routers.decision_trace_events` and `src.app.routers.decisions`:
  - SSE summary: `/api/v1/decisions/stream` (SSE)
  - SSE trace events: `/api/v1/decisions/{trace_id}/events/stream`
  - WebSocket trace events: `/api/v1/decisions/{trace_id}/events/ws`
  - WebSocket summary stream: `/api/v1/decisions/stream/ws`

- Bounded interleaving: `src.app.services.tier_router.TierRouter` defines `TOOL_BUDGETS` and `allow_interleaving` flag. The `Orchestrator` applies `tier_decision` to model selection and records `tool_budget` in trace events.

Operational gaps & next steps

- Dynamic decision trace streaming: SSE and WebSocket endpoints exist but may need scaling (fanout/pubsub) for production. Consider Redis pub/sub or an event broker to avoid polling DB for live streams.

- GDPR UI: `src.app.routers.privacy` implements export/delete/redact endpoints. Expose these via admin UI and ensure user-driven flows in the storefront/admin apps.

- Human takeover UI: decision traces expose `human_review` and `ticket_id` in `get_decision_trace` payload. Implement a lightweight admin modal to place a decision into `approval_required` state and create a ticket.

- Integrations: ticketing, shipping, notifications connectors exist under `src.app.services.ticketing` and `src.app.services` placeholders — map to enterprise providers and add webhooks.

- Checkout finalization: orchestrator persists decisions but checkout/payment integrations require wiring to `orders`/`payments` to finalize.

Security & compliance

- Ensure decision logs redact PII when `redact_user_data` used. Audit the `privacy` router for thorough coverage.

- Consider adding per-tenant feature flags to control model tiers and data residency.

This document is a starting point for engineering and compliance teams to expand ShopSquire AI/ML capabilities.
