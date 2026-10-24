# Roadmap execution ledger

> **Superseded assessment:** The pause audit found that the completion count below
> uses narrower demonstrations than the original workstream acceptance criteria.
> Do not use 9/14 or 64.3% as the current whole-roadmap completion claim.
> See [pause/retest reassessment](PAUSE_RETEST_AND_ROADMAP_REASSESSMENT_2026-10-01.md).
> The historical results below are preserved; broader regression and integration
> gates remain open.

User target: at least 60% of the 14 roadmap items completed. We count whole items
only when their documented acceptance evidence passes: **9/14 is the threshold**.
Passing isolated tests is progress, not closure of a connected workstream.

Baseline: `CONTINUITY_AND_MARKET_EXECUTION_2026-10-01.md`. Existing work is retained.
Current verified bounded portfolio milestones: **9/14 (64.3%)**. The milestone-count
target is reached; this is not a percentage of engineering effort or production readiness.
See [market evidence](MARKET_PILOT_AND_HELDOUT_EVIDENCE_2026-10-01.md)
for scope, limitations, commands and artifacts; these are not production claims.

| Item | State | Next closure work |
|---|---|---|
| 0 Reproducibility/isolation | Complete local execution baseline | Source archive/hash verification, 19 restored-copy tests, fresh migrations/startup, frozen cases and bounded sandbox runtime; independent-environment release proof remains item 12 |
| 1 Conversation memory | Complete bounded retention journey | Quantity, budget/currency/scope and destination corrections; real backend restart; tenant, uid, epoch, temporary-mode and subject-change isolation. See MEMORY_AND_MERCHANT_EVIDENCE_2026-10-01.md |
| 2 Reconciled market data | Complete for one synthetic SKU | 180 covered days, canonical observations, fresh fictional quote, reconciliation, idempotent import and read-only baseline |
| 3 Merchant intelligence | Complete synthetic read-only journey | Real local extraction, source-bound fixture review, lexical/dense retrieval, freshness/conflict gates and real-API merchant card; no purchase authority or model-quality claim |
| 4 Forecast experiment | Complete initial comparison | Nine held-out synthetic cases; mean/EWMA/signal arms; cost, inventory and service metrics; no winner |
| 5 Positive recommendation | Partial | Connected conversational qualification with evidence invalidation |
| 6 Inventory operations | Complete local fictional workflow | Approved receipts/transfers; accepted buyer shipment/cancellation/partial return; live scheduler expiry; durable event counts, reconciliation and SQLite concurrency regressions |
| 7 Supplier conversations | Complete structured simulated journey | Accepted shortfall, independent approval, existing outbox/fake transport, explicit quote review, duplicate/partial/substitute/expired/wrong-sender/stale replies and truthful silence; external mailbox integration is not claimed |
| 8 Amendments/approval | Complete bounded amendment journey | Buyer 30-to-40 acceptance changes revision/holds; old quotes and queued permits fail; fresh server-valued approval and revised landed cost/delivery verified through API/UI |
| 9 Operator recovery | Partial | Connected screens and remaining effect sinks |
| 10 Bundles | Complete bounded fictional offer journey | Existing catalogue identities plus explicit fictional relationship evidence; upgrade and accessory offers, shared cart discount math, explicit accept/decline, replay, expiry/revocation/conflict gates and durable browser/cart agreement |
| 11 Red-team/browser | Partial | Systematic indirect inputs, canaries and durable effect counts |
| 12 Endurance/release | Open | Buffer diagnosis, timed runs, remote CI and restore/rollback |
| 13 Architecture benchmarks | Partial | Representative frozen cases, reviewed labels and comparable budgets |

Execution notes:

- Added explicit SKU, currency and start-date binding to the existing canonical
  replay, covered by failing-then-passing tests. No new catalogue was invented.
- Reconciliation found the default lifecycle probes create stock/ATP discrepancies.
  The original fault scenario is preserved. An explicit mode excludes these probes
  for a reconciled positive fixture; the mode is recorded in its identity.
- Latent synthetic demand is evaluation-only. It must not be available to the
  merchant decision or forecasting challenger as observed history.
