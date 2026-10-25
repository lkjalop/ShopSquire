# Fictional market pilot and held-out comparison

Scope: a read-only, synthetic demonstration. No purchases, messages, live stock
updates, model-quality winner or real customer ROI is authorized or claimed.

## Reconciled data milestone (roadmap 2)

The existing SKU `LAP-01B48B57` is bound to `synthetic-market-pilot`, AUD, and a
versioned 180-day scenario ending September 30, 2026. The seed verifies the SKU
exists in the catalogue. Historical prices and demand are explicitly fictional.

The import persisted 436 canonical observations and 109 purchase facts; its
immutable snapshot supplies coverage for every day, including zero-sales days.
Rerunning inserted zero purchase facts and reused the snapshot identity.
Stock receipts and sales reconcile to the projected balance. The positive pilot
has zero returns/cancellations/transfers; their connected operational journeys
remain in roadmap 6. The original lifecycle-fault fixture is retained separately.

The decision uses observed sales, not latent demand. It reports four possibly
stockout-censored days, zero available units and 36 incoming units against a
19-unit replenishment target. The simple baseline advises monitoring the existing
inbound order. This is an inventory-position baseline, not proof of delivery-date
feasibility or a promise that current demand can be fulfilled.

Supplier terms are a new, explicit fictional quote; the previously expired offer
was not silently made current. The API rechecks quote and dataset freshness on
every read. Wrong tenant/SKU/currency, expiry, missing dates, invalid terms and
unreconciled stock block the decision. The dataset remains separate from live stock.

Evidence under `.artifacts/roadmap-execution-2026-10-01/`:

- `market-pilot.json`, `market-pilot-replay.json`: first import and idempotent replay.
- `market-persistence.xml`: ten passing focused tests at that checkpoint.
- `merchant-browser-scopes.json`: real-API clickthrough passed, including source
  evidence, stale-card removal on selection change, wrong scope and anonymous denial.
- `frontend-build.log`: successful production build.

Implementation: `synthetic_canonical_replay.py`, `merchant_decision_dataset.py`,
`merchant_intelligence.py`, `MerchantDecisionCard.tsx`; migration 20260887.
Configuration: `config/merchant_market_pilot.json`.
Runner: `scripts/seed_merchant_market_pilot.py --output <report.json>`.

## Initial challenger milestone (roadmap 4)

Frozen configuration: `config/heldout_inventory_benchmark.json`. Nine cases cover
three data-driven scenarios and three seeds. Each uses 240 training days and a
separate 60-day test period. Both forecast policies consume the same last 28
observed training days. Parameters are not tuned on the test outcomes.

The challenger is the existing EWMA model, compared with the simple mean-based
policy. A third arm adds a dated, scoped synthetic supplier-delay alert. This is
an intentionally informative synthetic signal, not evidence of live-news quality.
Future or expired signals cannot affect the frozen policy. Test-period latent
demand exists only inside the environment for measuring lost sales; changing it
cannot change the forecasts/policies.

Recorded outcomes include stockout days, filled/lost units, immediate fill rate,
average inventory, purchase spend, holding cost and shortage penalty. Cost
assumptions and the initial state are explicit. The benchmark starts with no
inbound orders; it does not reproduce the pilot's already-pending purchase order.

Results are mixed. For electronics seed 7, EWMA has five stockout days versus two
for the mean baseline. For perishable seed 7, EWMA has one versus six, with higher
cost. Signals sometimes reduce stockouts and sometimes add inventory/cost without
improving service. **There is no general winner.**

Evidence: `heldout-benchmark.json`, `heldout-tests.xml` (12 focused tests passed).
Runner: `scripts/run_heldout_inventory_benchmark.py --output <report.json>`.
Code: `src/app/services/heldout_inventory_benchmark.py`.

TimesFM/Chronos installation and comparison, noisy/misleading live-source signals,
independently reviewed relevance labels and broader deployment budgets remain
follow-on experiments under roadmap 13. This initial experiment establishes the
measurement path and supplies a valid reason not to replace the baseline blindly.
