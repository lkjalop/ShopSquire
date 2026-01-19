# Medusa.js Integration (Mock E‑Commerce)

Goal: Provide a fast, portable storefront + backend you can copy and rejig. We use Medusa for catalog/cart/checkout and bridge events to ShopSquire.

## 1) Quick Start (Local)
- Prereqs: Node 18+, pnpm or yarn, PostgreSQL (for Medusa), Redis optional
- Scaffold Medusa:
  ```bash
  npx create-medusa-app@latest shopsquire-medusa -t starter
  cd shopsquire-medusa && pnpm i && pnpm dev
  ```
- Seed products (Medusa docs) and verify http://localhost:9000/store/products

## 2) Bridge to ShopSquire Orchestrator
- Configure ShopSquire API base and x-api-key in Medusa env:
  ```env
  SHOPSQUIRE_API_BASE=http://localhost:8080/api/v1
  SHOPSQUIRE_API_KEY=devkey123
  ```
- Webhooks from Medusa → ShopSquire:
  - order.placed → POST /orchestrator/events/order_placed
  - cart.updated → POST /orchestrator/events/cart_updated
  - refund.requested → POST /orchestrator/events/refund_requested
- ShopSquire adapters should:
  - Map Medusa IDs to internal `customer_id`, `draft_order_id`
  - Invoke CRAG classification, then Orchestrator 5‑stage pipeline

## 3) Using ShopSquire Decisions in Storefront
- Pricing suggestions: GET /pricing/suggest?cart_id=...
- Support responses: POST /support/answer {question, context}
- Guarded actions: POST /actions/execute {proposal_id} (policy gates)

## 4) Minimal Flows
- Browse → Draft cart → Pricing suggestion → Checkout intent → Order placed (webhook)
- Refund request → Observer + Firewall → Approval queue → Execute refund

## 5) Notes
- Keep Medusa app separate repo/folder for clarity
- Do not embed secrets; use .env and per‑tenant keys
- Add feature flags to gate agent paths (pricing/support/inventory)
