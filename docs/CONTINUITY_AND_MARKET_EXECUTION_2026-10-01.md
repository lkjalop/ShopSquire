# Continuity repairs and market-decision diagnosis — 1 October 2026

This is an implementation update, not completion of the whole roadmap. The earlier
platform audit remains historical evidence; it must not be overwritten with later passes.

## Implemented

- Restore a case from its most recent committed conversation turn, scoped by tenant,
  buyer, subject reference and session epoch. Tied latest cases require explicit selection.
  Temporary conversations do not use this restoration path.
  `src/app/services/chat_case_continuity.py:5`; `src/app/routers/chat.py:880`.
- Project retained quantity only from matching case/revision state. Unresolved product
  suitability no longer suppresses a known quantity. This grants no qualification or
  commerce authority. `src/app/services/chat_terminal_projection.py:66`.
- Reuse the shared quantity parser when model output omits literal buyer quantity, and
  reuse the existing material budget-scope gate. Preserve the question before clarification
  persistence. `src/app/services/chat_turn_projection.py:54`;
  `src/app/services/chat_case_continuity.py:38`; `src/app/routers/chat.py:4231`.
- Regression testing exposed a shared parser defect: “need 16 GB memory” could become
  16 items. The existing specification-unit guard now also applies to the broad quantity
  fallback. `src/app/services/bulk_intent.py:143`.
- API and terminal projections now publish the same ordered questions instead of
  replacing the budget question with a research question on one surface.

These are generic state, parsing and presentation repairs. No Blender/laptop-specific
core rules, vector database, graph infrastructure or new model were introduced.

## Evidence and limits

Task-delta checkpoint: `C:/AI/ShopSquire-checkpoints/20261001-173925-pre-continuity`.
This preserves selected baseline files and a database backup, not a clean full checkout.
Existing unrelated working-tree changes were retained.

Artifacts: `.artifacts/continuity-market-2026-10-01/`.
The new tests were observed failing before implementation, including the specification
quantity negative case and API/terminal question mismatch.
See `tests/services/test_chat_case_continuity.py` and
`frontend/e2e/platform-audit-memory.spec.ts`.

The initial continuity-only browser run passed four real-API tests. The subsequent
five-test run passed four and failed its first request with “Failed to fetch” during
server restart/startup; its trace is retained. That reload journey passed on explicit
rerun. These are bounded checks, not endurance certification. No new product was
qualified, and direct-injection authority assertions are not an all-sink security audit.

Final verification after all changes: **48 backend tests passed** (JUnit
`backend-final.xml`, zero failures/errors), and **all five real-API Playwright tests
passed in one run**, with retries disabled (`browser-verified.json`, 50.7 seconds).
They cover five messages plus reload with the same case, budget-scope clarification,
twenty turns with amended quantities, unavailable external research, and direct
authority injection. Browser traces, screenshots and videos are retained. The final
restart used `VLM_WARMUP_ON_START=0` and `CV_WARMUP_ON_START=0` and waited for HTTP
health before testing; earlier shorthand warm-up variables were ineffective.

## Existing-data market gap report

Run the read-only report:

```powershell
.venv/Scripts/python.exe scripts/report_market_decision_gaps.py --database .artifacts/connected-shop-2026-09-28/shop.sqlite3 --tenant synthetic-electronics --sku LAP-01B48B57 --as-of 2026-10-01T00:00:00+00:00 --output .artifacts/continuity-market-2026-10-01/market-gaps.json
```

For this scope, stock is 17 on hand, 2 reserved, 15 available across three locations.
Seven fixture events share one observation date. The forecasting source table has
zero active purchase facts for the scope. Its supplier offer expired September 27.
The larger database has 98 fixture histories and 98 offers, but catalogue breadth does
not establish a covered daily demand series.

Before a forecast experiment: create a versioned synthetic event timeline; reconcile
sales, returns, cancellations and stock; explicitly record reporting coverage and
stockout periods; bind current supplier capacity, lead times and costs; freeze a
decision-time cutoff. Keep known bulk commitments separate from uncertain demand.
Do not turn missing dates into fabricated zero-demand observations.

## Research application and remaining order

The [research assessment](AI_ML_MARKET_INTELLIGENCE_RESEARCH_AND_ROADMAP_2026-10-01.md)
contains primary-source citations and architectural tradeoffs. Memory research informs
tests of corrections and subsequent decisions; accepted facts remain in durable state.
Temporal retrieval informs quote validity and availability-time cutoffs. Hybrid retrieval
and one forecasting challenger come after the data diagnosis. Graph and recursive-context
experiments remain conditional on measured retrieval failures.

| Order | Remaining deliverable | Closure evidence |
|---|---|---|
| 0 | Complete checkpoint, frozen evaluation manifest and reproducible bounded startup | Clean checkout/restore; explicit runtime configuration; fake-effect isolation |
| 1 | Broaden restored-case and recall testing beyond quantity; verify all budget amendments and presentation | Restart, subject switch, ambiguous cases, totals/currency, temporary sessions; API/UI/trace agreement |
| 2 | One reconciled synthetic market dataset and baseline | Covered daily history, fresh terms, inventory reconciliation, reproducible reorder decision |
| 3 | Governed extraction, hybrid retrieval and read-only merchant decision card | Cited scoped observations; unknown/conflicting/expired data abstains; browser proof |
| 4 | One forecast challenger and external-signal ablation | Held-out time periods, no future leakage, equal budgets, stockouts/excess/cost/delivery metrics |
| 5 | Conversational research through positive qualification and shelf/trace | Changed, expired and revoked evidence invalidates fit; positive fixture and real-product claims separated |
| 6 | Scheduled expiry, receiving, transfers, shipment/return/cancellation journeys | Reconciled balances; no oversell or duplicate stock effects; browser and concurrency tests |
| 7 | Simulated supplier enquiry, response and reviewed quote | Partial/substituted/duplicate/stale/wrong-sender replies; gated fake dispatch; durable effect counts |
| 8 | Amendment economics and authenticated distinct-person approval | Revised costs/delivery; obsolete quotes/grants rejected; same person with two credentials rejected |
| 9 | Operator recovery and remaining effect boundaries | Review/revoke/renew/reconcile UI; uncertain outcomes and crashes cannot duplicate effects |
| 10 | Supported upgrades, accessories and bundles | Compatibility evidence, benefit, total price and explicit acceptance; unknowns abstain |
| 11 | Systematic red-team and connected-browser gaps | Direct/indirect pages, messages, OCR, memory; canary leakage, unnecessary refusals and all-sink counts |
| 12 | Buffer diagnosis, sustained reliability and release evidence | Measured cold starts/failures/restarts; successful 60-minute and eight-hour runs; observed CI/restore/rollback |
| 13 | Representative model/retrieval/graph comparisons | Frozen held-out cases and reviewed labels; comparable budgets and measured improvement |

No model quality winner, production readiness, real customer ROI or successful new
eight-hour run is established by this batch.
