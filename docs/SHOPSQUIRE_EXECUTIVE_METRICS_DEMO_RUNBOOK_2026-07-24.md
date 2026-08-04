# ShopSquire Executive Metrics Demo Runbook

## Claim boundary

This recording proves that ShopSquire converts tenant-scoped commerce evidence into
read-only buyer, operator, and auditor projections, then applies deterministic
authorization gates to any proposed commercial action. It does not claim that the
synthetic replay is real traffic or that a dashboard can execute procurement.

## Before recording

1. Run `alembic upgrade head`.
2. Start the backend after the migration so `/api/v1/admin/bi/executive-metrics` is live.
3. Start shopper `:5173` and admin `:3001`.
4. Use `local-merchant-key` for the operator view and `local-owner-key` only for the
   audit drill-down.
5. Select **Live** in Market Intelligence. Use **Synthetic replay** only as a clearly
   labelled explanation of how a known seasonal scenario exercises the same pipeline.

## Act 1: Buyer-safe evidence

1. In the shopper, request a product and open Decision Trace > Market Intelligence.
2. Show demand, ATP position, WOS/turns status, source status, confidence, and `as_of`.
3. Point out that wholesale cost, margin, proposal controls, and catalogue actions are
   absent. The browser source has a ratchet test that fails if those controls return.

Proof: buyer evidence is scoped to the ordered slate and carries no operator action.

## Act 2: Operator projection

1. Open admin > Market Intelligence with the merchant key.
2. Select **Live**.
3. Show Executive metrics:
   - WOS and turns are `estimated` because they use current ATP rather than average
     inventory valuation.
   - RFM value and churn are explicitly heuristic estimates.
   - GMROI is `unavailable` until average landed-cost inventory exists.
4. Expand **Evidence** on a metric. Show definition version, timestamp, source count,
   confidence, reason, and provenance chain.

Proof: every figure has a typed status; absence of evidence does not become zero.

## Act 3: Auditor boundary

Call `/api/v1/admin/bi/executive-metrics/audit`:

- merchant key: `403`
- owner key: `200`

Show the tenant-scoped quarantine count. Explain that rejected or stale facts remain
auditable but cannot enter action policy.

## Act 4: Agentic, bounded replenishment

1. Show a model/detector proposal in Decision Trace.
2. Open its deterministic authorization evidence:
   - at least two independent demand sources,
   - fresh authoritative ATP deficit,
   - supplier lead time,
   - matched tenant/SKU/currency,
   - validated landed quote and margin floor.
3. Show forecast WAPE/coverage as `shadow`: it records whether the forecast-quality
   gate would pass but does not change an action yet.
4. Confirm that the result is `operator_advisory_only`; a dashboard cannot send an RFQ
   or place a PO.

This is the agentic proof: the model or detector proposes; typed deterministic policy
authorizes or blocks; the mature fulfillment workflow executes only after its human gate.

## Act 5: Closed-loop procurement

Run the existing bulk journey:

1. product recommendation,
2. cart quantity and local/network/RFQ split,
3. human confirmation,
4. fulfillment case,
5. supplier-channel-specific draft,
6. amendment,
7. redraft under the same trace/case lineage.

Then return to Market Intelligence and explain that committed order, return, marketing,
ATP, and validated supplier records enter the canonical fact adapters. Synthetic data
is retained only as a labelled regression fixture.

## Evidence captured on 2026-07-24

- SQLite demo migration reached `20260725_exec_metrics`.
- Empty PostgreSQL/pgvector migration reached `20260725_exec_metrics`.
- PostgreSQL contained `public.executive_metric_snapshot`,
  `public.supplier_score_audits`, and `oltp.product_embeddings`.
- Cross-tenant soak: 2 tenants x 10 concurrent users x 5 turns = 100 events.
- Data-quality rates: source identity 1.0, provenance/time 1.0, consent 1.0,
  monetary currency 1.0; no write errors; no cross-tenant bleed.
- No commercial insight was generated from the neutral soak, which is the expected
  fail-closed result.

## Do not claim yet

- GMROI without average landed-cost inventory valuation.
- PPV without one matched quote/PO/invoice identity.
- Forecast accuracy without sealed forecast/actual pairs.
- Production canary success from synthetic traffic.
- Real SAP, NetSuite, Power BI, Tableau, or Grafana integration until an adapter is
  connected and reconciled.
